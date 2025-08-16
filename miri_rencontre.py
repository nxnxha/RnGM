# miri_rencontre.py — Profil via bouton (serveur) → formulaire en DM → ajout photo → rôle auto
# Prêt pour discord.py 2.x

import os
import re
import json
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List

import discord
from discord import app_commands
from discord.ext import commands

# -------------------- CONFIG (IDs par défaut, override possibles via variables d'env) --------------------
def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")                               # ← mets ton token dans Railway → Variables
GUILD_ID      = env_int("GUILD_ID",      1382730341944397967)            # serveur Miri
ROLE_ACCESS   = env_int("ROLE_ACCESS",   1401403405729267762)            # rôle Accès Rencontre
CH_GIRLS      = env_int("CH_GIRLS",      1400520391793053841)            # salon profils filles
CH_BOYS       = env_int("CH_BOYS",       1400520396557521058)            # salon profils hommes
CH_SPEED      = env_int("CH_SPEED",      1402665906546413679)            # salon speed dating
CH_LOGS       = env_int("CH_LOGS",       1403154919913033728)            # salon logs
CH_WELCOME    = env_int("CH_WELCOME",    0)                              # salon d’accueil (0 = désactivé)
FIRST_MSG_LIMIT = env_int("FIRST_MSG_LIMIT", 1)                          # anti-spam 1er message
DATA_FILE     = os.getenv("DATA_FILE", "rencontre_data.json")            # stockage JSON

# -------------------- Intents --------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

# -------------------- Storage JSON --------------------
class Storage:
    def __init__(self, path: str):
        self.path = path
        self.data: Dict[str, Any] = {
            "profiles": {},          # user_id -> profile dict
            "profile_msgs": {},      # user_id -> {channel_id, message_id}
            "first_msg_counts": {}   # "author:target" -> int
        }
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.data.update(json.load(f))
            except Exception:
                pass

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_profile(self, uid: int) -> Optional[Dict[str, Any]]:
        return self.data["profiles"].get(str(uid))

    def set_profile(self, uid: int, prof: Dict[str, Any]):
        self.data["profiles"][str(uid)] = prof
        self.save()

    def delete_profile(self, uid: int):
        self.data["profiles"].pop(str(uid), None)
        self.data["profile_msgs"].pop(str(uid), None)
        self.save()

    def set_profile_msg(self, uid: int, channel_id: int, message_id: int):
        self.data["profile_msgs"][str(uid)] = {"channel_id": channel_id, "message_id": message_id}
        self.save()

    def get_profile_msg(self, uid: int) -> Optional[Dict[str, int]]:
        return self.data["profile_msgs"].get(str(uid))

    def inc_first_msg(self, author_id: int, target_id: int) -> int:
        key = f"{author_id}:{target_id}"
        val = self.data["first_msg_counts"].get(key, 0) + 1
        self.data["first_msg_counts"][key] = val
        self.save()
        return val

storage = Storage(DATA_FILE)

# -------------------- États temporaires (DM photo après modal) --------------------
awaiting_photo: Dict[int, Dict[str, Any]] = {}  # uid -> partial_profile

# -------------------- Vues & Modals --------------------
class StartFormView(discord.ui.View):
    """Bouton sur l'embed d'accueil du serveur → envoie un DM avec un bouton qui ouvre le modal."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Créer mon profil", style=discord.ButtonStyle.success, custom_id="start_profile_btn")
    async def start_profile_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            dm = await interaction.user.create_dm()
            await dm.send(
                embed=discord.Embed(
                    title="Création de ton profil — DM",
                    description=(
                        "On va remplir le formulaire en **privé**.\n\n"
                        "1) Clique sur **Démarrer** pour ouvrir le formulaire (modal)\n"
                        "2) À la fin, **envoie une photo** (image **uploadée** ou **lien**) dans ce DM\n"
                        "3) Je publierai ton profil et je te donnerai le rôle **Accès Rencontre** ✅"
                    ),
                    color=discord.Color.purple()
                ),
                view=OpenModalView()
            )
            await interaction.response.send_message("📩 Je t'ai envoyé un DM pour créer ton profil.", ephemeral=True)
        except Exception:
            await interaction.response.send_message("⚠️ Je ne peux pas t'écrire en DM (DM fermés ?).", ephemeral=True)

class OpenModalView(discord.ui.View):
    """Bouton dans le DM pour ouvrir la Modal."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Démarrer", style=discord.ButtonStyle.primary, custom_id="open_modal_btn")
    async def open_modal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ProfilModal())

class ProfilModal(discord.ui.Modal, title="Créer/Mettre à jour mon profil"):
    age = discord.ui.TextInput(label="Âge (>=18)", min_length=1, max_length=3, placeholder="18")
    genre = discord.ui.TextInput(label="Genre (Fille/Homme)", min_length=1, max_length=10, placeholder="Fille")
    orientation = discord.ui.TextInput(label="Attirance", required=False, max_length=50, placeholder="Hétéro, Bi, etc.")
    passions = discord.ui.TextInput(label="Passions", required=False, style=discord.TextStyle.paragraph, max_length=300)
    activite = discord.ui.TextInput(label="Activité (ce que tu fais)", required=False, max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
        # Le modal doit être soumis en DM
        if not isinstance(interaction.channel, discord.DMChannel):
            await interaction.response.send_message("Ouvre d’abord le **DM** depuis le serveur (bouton *Créer mon profil*).", ephemeral=True)
            return
        try:
            age_val = int(str(self.age.value).strip())
        except Exception:
            await interaction.response.send_message("Âge invalide.", ephemeral=True)
            return
        if age_val < 18:
            await interaction.response.send_message("❌ Réservé aux 18 ans et plus.", ephemeral=True)
            return

        profile = {
            "age": age_val,
            "genre": str(self.genre.value).strip(),
            "orientation": str(self.orientation.value).strip(),
            "passions": str(self.passions.value).strip(),
            "activite": str(self.activite.value).strip(),
            "photo_url": "",  # rempli après
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        awaiting_photo[interaction.user.id] = profile
        await interaction.response.send_message(
            "✔️ Formulaire reçu ! Maintenant, **envoie une photo** dans ce DM (upload **ou** **lien**). "
            "Écris `skip` pour ignorer la photo.",
            ephemeral=True
        )

class ContactModal(discord.ui.Modal, title="Premier message"):
    def __init__(self, target_id: int, logs_ch: Optional[discord.TextChannel], anti_spam_limit: int):
        super().__init__(timeout=300)
        self.target_id = target_id
        self.logs_ch = logs_ch
        self.anti_spam_limit = anti_spam_limit
        self.msg = discord.ui.TextInput(
            label="Ton message (1er contact)",
            style=discord.TextStyle.paragraph,
            min_length=5,
            max_length=600,
            placeholder="Présente-toi vite fait et sois respectueux(se) 😉"
        )
        self.add_item(self.msg)

    async def on_submit(self, interaction: discord.Interaction):
        author = interaction.user
        guild = discord.utils.get(interaction.client.guilds, id=GUILD_ID)
        target = guild.get_member(self.target_id) if guild else None
        if not target:
            await interaction.response.send_message("❌ Utilisateur introuvable.", ephemeral=True)
            return

        count = storage.inc_first_msg(author.id, target.id)
        if count > FIRST_MSG_LIMIT:
            await interaction.response.send_message(
                f"❌ Tu as déjà envoyé {FIRST_MSG_LIMIT} premier message à cette personne. Attends une réponse.",
                ephemeral=True
            )
            return

        txt = f"**{author.display_name}** souhaite te contacter :\n> {self.msg.value}\n\n(Tu peux répondre directement à ce message pour poursuivre.)"
        ok = True
        try:
            dm = await target.create_dm()
            await dm.send(txt)
        except Exception:
            ok = False

        if ok:
            await interaction.response.send_message("✅ Message envoyé en DM à la personne.", ephemeral=True)
            if self.logs_ch:
                await self.logs_ch.send(f"📨 **Contact** {author.mention} → {target.mention} : {self.msg.value}")
        else:
            await interaction.response.send_message("⚠️ Impossible d’envoyer le DM (DM fermés ?).", ephemeral=True)
            if self.logs_ch:
                await self.logs_ch.send(f"⚠️ **Contact raté (DM fermés)** {author.mention} → {target.mention}")

class ContactView(discord.ui.View):
    def __init__(self, target_id: int, logs_ch: Optional[discord.TextChannel], anti_spam_limit: int):
        super().__init__(timeout=None)
        self.target_id = target_id
        self.logs_ch = logs_ch
        self.anti_spam_limit = anti_spam_limit

    @discord.ui.button(label="Contacter", style=discord.ButtonStyle.primary, custom_id="contact_btn")
    async def contact_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ContactModal(self.target_id, self.logs_ch, self.anti_spam_limit))

# -------------------- Cog --------------------
class Rencontre(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _logs_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        return guild.get_channel(CH_LOGS) if CH_LOGS else None

    def _target_channel(self, gender: str, guild: discord.Guild) -> Optional[discord.TextChannel]:
        gender = (gender or "").strip().lower()
        if gender.startswith("f"):
            return guild.get_channel(CH_GIRLS)
        return guild.get_channel(CH_BOYS)

    def _profile_embed(self, member: discord.Member, prof: Dict[str, Any]) -> discord.Embed:
        e = discord.Embed(
            title=f"Profil de {member.display_name}",
            description="Espace Rencontre — Miri",
            color=discord.Color.purple()
        )
        e.set_author(name=str(member), icon_url=member.display_avatar.url if member.display_avatar else None)
        fields = [
            ("Âge", f"{prof.get('age', '—')}", True),
            ("Genre", prof.get('genre', '—') or "—", True),
            ("Attirance", prof.get('orientation', '—') or "—", True),
            ("Passions", prof.get('passions', '—') or "—", False),
            ("Activité", prof.get('activite', '—') or "—", False),
        ]
        for n, v, inline in fields:
            e.add_field(name=n, value=v, inline=inline)
        if prof.get("photo_url"):
            e.set_image(url=prof["photo_url"])
        e.set_footer(text="Clique sur « Contacter » pour envoyer un premier message (modal).")
        return e

    async def _publish(self, member: discord.Member, prof: Dict[str, Any]) -> Optional[discord.Message]:
        guild = member.guild
        target_ch = self._target_channel(prof.get("genre", ""), guild)
        if not target_ch:
            return None
        logs_ch = self._logs_channel(guild)
        view = ContactView(target_id=member.id, logs_ch=logs_ch, anti_spam_limit=FIRST_MSG_LIMIT)
        embed = self._profile_embed(member, prof)

        existing = storage.get_profile_msg(member.id)
        try:
            if existing:
                ch = guild.get_channel(existing["channel_id"])
                if isinstance(ch, discord.TextChannel):
                    msg = await ch.fetch_message(existing["message_id"])
                    await msg.edit(embed=embed, view=view, content=None)
                    return msg
        except Exception:
            pass

        msg = await target_ch.send(embed=embed, view=view)
        storage.set_profile_msg(member.id, target_ch.id, msg.id)
        return msg

    @app_commands.command(name="profil_delete", description="Supprimer ton profil")
    async def profil_delete(self, interaction: discord.Interaction):
        prof = storage.get_profile(interaction.user.id)
        storage.delete_profile(interaction.user.id)
        if prof:
            await interaction.response.send_message("✅ Profil supprimé.", ephemeral=True)
        else:
            await interaction.response.send_message("Rien à supprimer.", ephemeral=True)

    @app_commands.command(name="profil_show", description="Voir ton profil (DM)")
    async def profil_show(self, interaction: discord.Interaction):
        prof = storage.get_profile(interaction.user.id)
        if not prof:
            await interaction.response.send_message("Tu n’as pas encore de profil. Clique sur **Créer mon profil** dans le serveur.", ephemeral=True)
            return
        try:
            dm = await interaction.user.create_dm()
            await dm.send(embed=self._profile_embed(interaction.user, prof))
            await interaction.response.send_message("📩 Je t’ai envoyé ton profil en DM.", ephemeral=True)
        except Exception:
            await interaction.response.send_message("Impossible d’envoyer un DM.", ephemeral=True)

# -------------------- Bot --------------------
class RencontreBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.synced = False
        self.cog_inst = Rencontre(self)

    async def setup_hook(self):
        # Vues persistantes (boutons)
        self.add_view(StartFormView())
        self.add_view(OpenModalView())
        self.add_view(ContactView(target_id=0, logs_ch=None, anti_spam_limit=FIRST_MSG_LIMIT))

    async def on_ready(self):
        try:
            if not self.synced:
                guild = discord.Object(id=GUILD_ID) if GUILD_ID else None
                if guild:
                    await self.tree.sync(guild=guild)
                else:
                    await self.tree.sync()
                self.synced = True
        except Exception as e:
            print("[Sync error]", e)

        print(f"✅ Connecté en tant que {self.user} ({self.user.id})")

        # Embed d’accueil avec bouton (si CH_WELCOME défini)
        if CH_WELCOME:
            ch = self.get_channel(CH_WELCOME)
            if isinstance(ch, discord.TextChannel):
                try:
                    await ch.send(
                        embed=discord.Embed(
                            title="**Bienvenue dans l’Espace Rencontre de Miri !**",
                            description=(
                                "Ici, tu peux créer ton profil et découvrir ceux des autres membres.\n"
                                "Likes, matchs, MP privés, des soirées speed dating… tout est fait pour favoriser de vraies connexions.\n\n"
                                "⚠️ Système réservé aux **18 ans et plus**.\n\n"
                                "Clique ci-dessous pour commencer :"
                            ),
                            color=discord.Color.purple()
                        ),
                        view=StartFormView()
                    )
                except Exception:
                    pass

    async def on_message(self, message: discord.Message):
        # Capture de la photo en DM après le modal
        if message.author.bot:
            return
        if isinstance(message.channel, discord.DMChannel):
            uid = message.author.id
            if uid in awaiting_photo:
                photo_url = ""
                # Pièce jointe image
                if message.attachments:
                    att = message.attachments[0]
                    if (att.content_type and att.content_type.startswith("image")) or att.filename.lower().endswith((".png",".jpg",".jpeg",".webp",".gif")):
                        photo_url = att.url
                # URL dans le texte
                if not photo_url:
                    m = re.search(r'https?://\S+', message.content)
                    if m:
                        photo_url = m.group(0)
                # Skip
                if message.content.strip().lower() in {"skip", "aucune", "non", "ignore"}:
                    photo_url = ""

                prof = awaiting_photo.pop(uid)
                prof["photo_url"] = photo_url

                # Publier + donner le rôle
                guild = discord.utils.get(self.guilds, id=GUILD_ID)
                if not guild:
                    await message.channel.send("⚠️ Je ne trouve pas le serveur. Réessaie plus tard.")
                    return
                member = guild.get_member(uid)
                if not member:
                    await message.channel.send("⚠️ Je ne te trouve pas sur le serveur.")
                    return

                storage.set_profile(uid, prof)
                _ = await self.cog_inst._publish(member, prof)

                if ROLE_ACCESS:
                    role = guild.get_role(ROLE_ACCESS)
                    if role:
                        try:
                            await member.add_roles(role, reason="Création du profil Rencontre")
                        except Exception:
                            pass

                logs_ch = guild.get_channel(CH_LOGS) if CH_LOGS else None
                if isinstance(logs_ch, discord.TextChannel):
                    await logs_ch.send(f"✅ **Profil créé** : {member.mention} — rôle Accès Rencontre attribué.")

                await message.channel.send("✅ Profil créé. Bienvenue dans l’Espace Rencontre !")

# -------------------- Entrée --------------------
bot = RencontreBot()
bot.tree.add_command(bot.cog_inst.profil_delete, guild=discord.Object(id=GUILD_ID) if GUILD_ID else None)
bot.tree.add_command(bot.cog_inst.profil_show,   guild=discord.Object(id=GUILD_ID) if GUILD_ID else None)

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN est requis (mets-le en variable d’environnement).")
    bot.run(DISCORD_TOKEN)
