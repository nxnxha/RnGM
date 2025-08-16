# miri_rencontre.py — version prêtes avec IDs pré-remplis
import os
import json
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List

import discord
from discord import app_commands
from discord.ext import commands

# --------- CONFIG PAR DÉFAUT (pré-remplie) ----------
DEFAULTS = {
    "GUILD_ID": 1382730341944397967,
    "ROLE_ACCESS": 1401403405729267762,
    "CH_GIRLS": 1400520391793053841,
    "CH_BOYS": 1400520396557521058,
    "CH_SPEED": 1402665906546413679,
    "CH_LOGS": 1403154919913033728,
    "CH_WELCOME": 1400808431941849178,
    "FIRST_MSG_LIMIT": 1,
    "DATA_FILE": "rencontre_data.json"
}

def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

# --------- LECTURE CONFIG ----------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")  # ← mets ton token ici via variable d'env sur Railway
GUILD_ID      = env_int("GUILD_ID",      DEFAULTS["GUILD_ID"])
ROLE_ACCESS   = env_int("ROLE_ACCESS",   DEFAULTS["ROLE_ACCESS"])
CH_GIRLS      = env_int("CH_GIRLS",      DEFAULTS["CH_GIRLS"])
CH_BOYS       = env_int("CH_BOYS",       DEFAULTS["CH_BOYS"])
CH_SPEED      = env_int("CH_SPEED",      DEFAULTS["CH_SPEED"])
CH_LOGS       = env_int("CH_LOGS",       DEFAULTS["CH_LOGS"])
CH_WELCOME    = env_int("CH_WELCOME",    DEFAULTS["CH_WELCOME"])
FIRST_MSG_LIMIT = env_int("FIRST_MSG_LIMIT", DEFAULTS["FIRST_MSG_LIMIT"])
DATA_FILE     = os.getenv("DATA_FILE", DEFAULTS["DATA_FILE"])

# --------- Intents ----------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

# --------- Storage JSON ----------
class Storage:
    def __init__(self, path: str):
        self.path = path
        self.data: Dict[str, Any] = {
            "profiles": {},         # user_id -> profile dict
            "profile_msgs": {},     # user_id -> {channel_id, message_id}
            "first_msg_counts": {}  # "author:target" -> int
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

# --------- UI ----------
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
        target = interaction.guild.get_member(self.target_id)
        if not target:
            await interaction.response.send_message("❌ Utilisateur introuvable.", ephemeral=True)
            return
        count = storage.inc_first_msg(author.id, target.id)
        if count > self.anti_spam_limit:
            await interaction.response.send_message(
                f"❌ Tu as déjà envoyé {self.anti_spam_limit} premier message à cette personne. Attends une réponse.",
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

# --------- Cog ----------
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

    def _has_access_role(self, member: discord.Member) -> bool:
        if not ROLE_ACCESS:
            return True
        return any(r.id == ROLE_ACCESS for r in member.roles)

    def _profile_embed(self, member: discord.Member, prof: Dict[str, Any]) -> discord.Embed:
        e = discord.Embed(
            title=f"Profil de {member.display_name}",
            description="Espace Rencontre — Miri",
            color=discord.Color.purple()
        )
        e.set_author(name=str(member), icon_url=member.display_avatar.url if member.display_avatar else None)
        fields = [
            ("Âge", f"{prof.get('age', '—')}", True),
            ("Genre", prof.get('genre', '—'), True),
            ("Attirance", prof.get('orientation', '—'), True),
            ("Passions", prof.get('passions', '—'), False),
            ("Activité", prof.get('activite', '—'), False)
        ]
        for n, v, inline in fields:
            e.add_field(name=n, value=v or "—", inline=inline)
        photo = prof.get("photo_url")
        if photo:
            e.set_image(url=photo)
        e.set_footer(text="Clique sur « Contacter » pour envoyer un premier message (modal).")
        return e

    async def _publish_or_update(self, member: discord.Member, prof: Dict[str, Any]) -> Optional[discord.Message]:
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

    @app_commands.command(name="profil_create", description="Créer ton profil Rencontre (formulaire)")
    async def profil_create(self, interaction: discord.Interaction):
        if not self._has_access_role(interaction.user):
            await interaction.response.send_message("❌ Tu n’as pas le rôle d’accès.", ephemeral=True)
            return

        class ProfilModal(discord.ui.Modal, title="Créer/Mettre à jour mon profil"):
            age = discord.ui.TextInput(label="Âge (>=18)", min_length=1, max_length=3, placeholder="18")
            genre = discord.ui.TextInput(label="Genre (Fille/Homme)", min_length=1, max_length=10, placeholder="Fille")
            orientation = discord.ui.TextInput(label="Attirance", required=False, max_length=50, placeholder="Hétéro, Bi, etc.")
            passions = discord.ui.TextInput(label="Passions", required=False, style=discord.TextStyle.paragraph, max_length=300)
            activite = discord.ui.TextInput(label="Activité (ce que tu fais)", required=False, max_length=100)
            photo_url = discord.ui.TextInput(label="Photo (URL, optionnel)", required=False, max_length=200)

            async def on_submit(self, inter: discord.Interaction):
                try:
                    age_val = int(str(self.age.value).strip())
                except Exception:
                    await inter.response.send_message("Âge invalide.", ephemeral=True)
                    return
                if age_val < 18:
                    await inter.response.send_message("❌ Réservé aux 18 ans et plus.", ephemeral=True)
                    return

                profile = {
                    "age": age_val,
                    "genre": str(self.genre.value).strip(),
                    "orientation": str(self.orientation.value).strip(),
                    "passions": str(self.passions.value).strip(),
                    "activite": str(self.activite.value).strip(),
                    "photo_url": str(self.photo_url.value).strip(),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }
                storage.set_profile(inter.user.id, profile)

                cog: "Rencontre" = inter.client.get_cog("Rencontre")  # type: ignore
                msg = await cog._publish_or_update(inter.user, profile)

                if msg is None:
                    await inter.response.send_message("Profil enregistré, mais salon cible introuvable. Vérifie CH_GIRLS/CH_BOYS.", ephemeral=True)
                    return
                await inter.response.send_message("✅ Profil enregistré et publié/MAJ.", ephemeral=True)

        await interaction.response.send_modal(ProfilModal())

    @app_commands.command(name="profil_delete", description="Supprimer ton profil (et la publication)")
    async def profil_delete(self, interaction: discord.Interaction):
        prof = storage.get_profile(interaction.user.id)
        storage.delete_profile(interaction.user.id)
        if prof:
            await interaction.response.send_message("✅ Profil supprimé.", ephemeral=True)
        else:
            await interaction.response.send_message("Rien à supprimer.", ephemeral=True)

    @app_commands.command(name="profil_show", description="T’afficher le profil enregistré (en DM).")
    async def profil_show(self, interaction: discord.Interaction):
        prof = storage.get_profile(interaction.user.id)
        if not prof:
            await interaction.response.send_message("Tu n’as pas encore de profil. Utilise /profil_create.", ephemeral=True)
            return
        try:
            dm = await interaction.user.create_dm()
            await dm.send(embed=self._profile_embed(interaction.user, prof))
            await interaction.response.send_message("📩 Je t’ai envoyé ton profil en DM.", ephemeral=True)
        except Exception:
            await interaction.response.send_message("Impossible d’envoyer un DM.", ephemeral=True)

    @app_commands.command(name="speeddating", description="Lance des threads privés éphémères (admin).")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def speeddating(self, interaction: discord.Interaction, couples: int = 5):
        if not CH_SPEED:
            await interaction.response.send_message("❌ CH_SPEED non défini.", ephemeral=True)
            return
        speed_ch = interaction.guild.get_channel(CH_SPEED)
        if not isinstance(speed_ch, discord.TextChannel):
            await interaction.response.send_message("❌ Salon speed introuvable.", ephemeral=True)
            return

        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        authors: List[int] = []
        try:
            async for m in speed_ch.history(limit=500, oldest_first=False, after=cutoff):
                if m.author.bot:
                    continue
                if m.author.id not in authors:
                    authors.append(m.author.id)
        except Exception:
            pass

        if len(authors) < 2:
            await interaction.response.send_message("Pas assez de personnes actives dans l’heure.", ephemeral=True)
            return

        import random
        random.shuffle(authors)
        pairs = []
        while len(authors) >= 2 and len(pairs) < couples:
            a = authors.pop()
            b = authors.pop()
            if a == b:
                continue
            pairs.append((a, b))

        created_threads = []
        for a, b in pairs:
            ma = interaction.guild.get_member(a)
            mb = interaction.guild.get_member(b)
            if not ma or not mb:
                continue
            name = f"Speed ⏳ {ma.display_name} × {mb.display_name}"
            try:
                thread = await speed_ch.create_thread(
                    name=name,
                    type=discord.ChannelType.private_thread,
                    invitable=False
                )
                await thread.add_user(ma)
                await thread.add_user(mb)
                await thread.send(f"Bienvenue {ma.mention} et {mb.mention} — vous avez **5 minutes** ⏳. Soyez respectueux/sses.")
                created_threads.append(thread)
            except Exception:
                continue

        await interaction.response.send_message(f"✅ Créé {len(created_threads)} threads éphémères.", ephemeral=True)

        await asyncio.sleep(5 * 60)
        for t in created_threads:
            try:
                await t.edit(archived=True, locked=True)
            except Exception:
                pass

# --------- Bot ----------
class RencontreBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.synced = False

    async def setup_hook(self):
        logs_ch = None
        guild = self.get_guild(GUILD_ID)
        if guild and CH_LOGS:
            logs_ch = guild.get_channel(CH_LOGS)
        self.add_view(ContactView(target_id=0, logs_ch=logs_ch if isinstance(logs_ch, discord.TextChannel) else None,
                                  anti_spam_limit=FIRST_MSG_LIMIT))

    async def on_ready(self):
        try:
            if not self.synced:
                if GUILD_ID:
                    guild = discord.Object(id=GUILD_ID)
                    await self.tree.sync(guild=guild)
                else:
                    await self.tree.sync()
                self.synced = True
        except Exception as e:
            print("[Sync error]", e)

        print(f"✅ Connecté en tant que {self.user} ({self.user.id})")

        if CH_WELCOME:
            ch = self.get_channel(CH_WELCOME)
            if isinstance(ch, discord.TextChannel):
                try:
                    await ch.send(embed=discord.Embed(
                        title="**Bienvenue dans l’Espace Rencontre de Miri !**",
                        description=(
                            "Ici, tu peux créer ton profil et découvrir ceux des autres membres.\n"
                            "Likes, matchs, MP privés, des soirées speed dating… tout est fait pour favoriser de vraies connexions.\n\n"
                            "⚠️ Système réservé aux **18 ans et plus**.\n\n"
                            "Clique ci-dessous pour commencer : /profil_create"
                        ),
                        color=discord.Color.purple()
                    ))
                except Exception:
                    pass

bot = RencontreBot()
cog = Rencontre(bot)
bot.tree.add_command(cog.profil_create, guild=discord.Object(id=GUILD_ID) if GUILD_ID else None)
bot.tree.add_command(cog.profil_delete, guild=discord.Object(id=GUILD_ID) if GUILD_ID else None)
bot.tree.add_command(cog.profil_show,   guild=discord.Object(id=GUILD_ID) if GUILD_ID else None)
bot.tree.add_command(cog.speeddating,   guild=discord.Object(id=GUILD_ID) if GUILD_ID else None)

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN est requis (mets-le en variable d\'environnement).")
    bot.run(DISCORD_TOKEN)
