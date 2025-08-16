# miri_rencontre.py — Miri Rencontre (full, interactions déférées)
# ✔ Bouton accueil → DM modal + photo (upload ou URL) → publication
# ✔ Profils publics avec miniature à gauche (thumbnail)
# ✔ Boutons: ❤️ Like | ❌ Pass | 📩 Contacter | ✏️ Modifier | 🗑️ Supprimer
# ✔ Like/Pass façon Tinder + détection de match (DM aux deux)
# ✔ Logs détaillés [JJ/MM/AAAA HH:MM] pour TOUT (création, édition, suppression, like, pass, match, contact)
# ✔ Aucune commande slash… sauf /speeddating (staff)
# ✔ DEFER sur interactions pour éviter “Cette interaction a échoué”

import os
import re
import json
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Tuple
from zoneinfo import ZoneInfo  # Python 3.9+

import discord
from discord import app_commands
from discord.ext import commands

# -------------------- CONFIG (IDs par défaut, override via env) --------------------
def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")                               # Railway → Variables
GUILD_ID      = env_int("GUILD_ID",      1382730341944397967)
ROLE_ACCESS   = env_int("ROLE_ACCESS",   1401403405729267762)
CH_GIRLS      = env_int("CH_GIRLS",      1400520391793053841)
CH_BOYS       = env_int("CH_BOYS",       1400520396557521058)
CH_SPEED      = env_int("CH_SPEED",      1402665906546413679)
CH_LOGS       = env_int("CH_LOGS",       1403154919913033728)
CH_WELCOME    = env_int("CH_WELCOME",    1400808431941849178)   # met un ID si tu veux l’embed d’accueil auto
FIRST_MSG_LIMIT = env_int("FIRST_MSG_LIMIT", 1)
DATA_FILE     = os.getenv("DATA_FILE", "rencontre_data.json")

TZ = ZoneInfo("Europe/Paris")

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
            "profiles": {},           # user_id -> profile dict
            "profile_msgs": {},       # user_id -> {channel_id, message_id}
            "first_msg_counts": {},   # "author:target" -> int
            "likes": {},              # user_id -> list of liked user_ids
            "passes": {},             # user_id -> list of passed user_ids
            "matches": []             # list of [uid1, uid2] sorted
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

    # ---- profiles ----
    def get_profile(self, uid: int) -> Optional[Dict[str, Any]]:
        return self.data["profiles"].get(str(uid))

    def set_profile(self, uid: int, prof: Dict[str, Any]):
        self.data["profiles"][str(uid)] = prof
        self.save()

    def delete_profile(self, uid: int):
        self.data["profiles"].pop(str(uid), None)
        self.data["profile_msgs"].pop(str(uid), None)
        # clean likes/passes/matches
        self.data["likes"].pop(str(uid), None)
        self.data["passes"].pop(str(uid), None)
        # remove matches containing uid
        new_matches = []
        for a, b in self.data["matches"]:
            if int(a) != uid and int(b) != uid:
                new_matches.append([a, b])
        self.data["matches"] = new_matches
        self.save()

    # ---- message refs ----
    def set_profile_msg(self, uid: int, channel_id: int, message_id: int):
        self.data["profile_msgs"][str(uid)] = {"channel_id": channel_id, "message_id": message_id}
        self.save()

    def get_profile_msg(self, uid: int) -> Optional[Dict[str, int]]:
        return self.data["profile_msgs"].get(str(uid))

    # ---- first message anti-spam ----
    def inc_first_msg(self, author_id: int, target_id: int) -> int:
        key = f"{author_id}:{target_id}"
        val = self.data["first_msg_counts"].get(key, 0) + 1
        self.data["first_msg_counts"][key] = val
        self.save()
        return val

    # ---- like/pass/match ----
    def like(self, user_id: int, target_id: int) -> bool:
        """Return True si ce like crée un NOUVEAU match."""
        if str(user_id) == str(target_id):
            return False
        likes = self.data["likes"].setdefault(str(user_id), [])
        if target_id not in likes:
            likes.append(target_id)
            self.save()

        other_likes = set(self.data["likes"].get(str(target_id), []))
        if user_id in other_likes:
            pair = sorted([user_id, target_id])
            if pair not in [[int(a), int(b)] for a, b in self.data["matches"]]:
                self.data["matches"].append([str(pair[0]), str(pair[1])])
                self.save()
                return True
        return False

    def pass_(self, user_id: int, target_id: int):
        passes = self.data["passes"].setdefault(str(user_id), [])
        if target_id not in passes:
            passes.append(target_id)
            self.save()

storage = Storage(DATA_FILE)

# -------------------- Helpers --------------------
def now_ts() -> str:
    return datetime.now(TZ).strftime("[%d/%m/%Y %H:%M]")

def log_line(guild: discord.Guild, text: str):
    if not CH_LOGS:
        return
    ch = guild.get_channel(CH_LOGS)
    if isinstance(ch, discord.TextChannel):
        asyncio.create_task(ch.send(f"{now_ts()} {text}"))

def allowed_to_manage(inter: discord.Interaction, owner_id: int) -> bool:
    if inter.user.id == owner_id:
        return True
    if isinstance(inter.user, discord.Member) and inter.user.guild_permissions.manage_guild:
        return True
    return False

# -------------------- États temporaires (DM photo après modal) --------------------
awaiting_photo: Dict[int, Dict[str, Any]] = {}  # uid -> {"profile":..., "is_edit": bool}

# -------------------- Vues & Modals --------------------
class StartFormView(discord.ui.View):
    """Bouton sur l'embed d'accueil du serveur → envoie un DM avec un bouton qui ouvre le modal."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Créer mon profil", style=discord.ButtonStyle.success, custom_id="start_profile_btn")
    async def start_profile_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)  # DEFER pour éviter timeout
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
                view=OpenModalView(is_edit=False)
            )
            await interaction.followup.send("📩 Je t'ai envoyé un DM pour créer ton profil.", ephemeral=True)
        except Exception:
            await interaction.followup.send("⚠️ Je ne peux pas t'écrire en DM (DM fermés ?).", ephemeral=True)

class OpenModalView(discord.ui.View):
    """Bouton dans le DM pour ouvrir la Modal (création ou édition)."""
    def __init__(self, is_edit: bool):
        super().__init__(timeout=None)
        self.is_edit = is_edit

    @discord.ui.button(label="Démarrer", style=discord.ButtonStyle.primary, custom_id="open_modal_btn")
    async def open_modal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Ouvrir une modal EST une réponse, pas besoin de defer
        await interaction.response.send_modal(ProfilModal(is_edit=self.is_edit))

class ProfilModal(discord.ui.Modal, title="Profil — Formulaire"):
    def __init__(self, is_edit: bool):
        super().__init__(timeout=300)
        self.is_edit = is_edit
        self.age = discord.ui.TextInput(label="Âge (>=18)", min_length=1, max_length=3, placeholder="18")
        self.genre = discord.ui.TextInput(label="Genre (Fille/Homme)", min_length=1, max_length=10, placeholder="Fille")
        self.orientation = discord.ui.TextInput(label="Attirance", required=False, max_length=50, placeholder="Hétéro, Bi, etc.")
        self.passions = discord.ui.TextInput(label="Passions", required=False, style=discord.TextStyle.paragraph, max_length=300)
        self.activite = discord.ui.TextInput(label="Activité (ce que tu fais)", required=False, max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
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

        old = storage.get_profile(interaction.user.id) or {}
        photo_keep = old.get("photo_url", "")

        profile = {
            "age": age_val,
            "genre": str(self.genre.value).strip(),
            "orientation": str(self.orientation.value).strip(),
            "passions": str(self.passions.value).strip(),
            "activite": str(self.activite.value).strip(),
            "photo_url": photo_keep if self.is_edit else "",
            "updated_at": datetime.now(TZ).isoformat()
        }
        awaiting_photo[interaction.user.id] = {"profile": profile, "is_edit": self.is_edit}
        await interaction.response.send_message(
            ("✔️ Modif reçue ! " if self.is_edit else "✔️ Formulaire reçu ! ")
            + "Maintenant, **envoie une photo** dans ce DM (upload ou lien). "
              "Écris `skip` pour ne pas changer/ajouter la photo.",
            ephemeral=True
        )

# ---------- Contact modal (pour tout le monde) ----------
class ContactModal(discord.ui.Modal, title="Premier message"):
    def __init__(self, target_id: int, logs_ch: Optional[discord.TextChannel]):
        super().__init__(timeout=300)
        self.target_id = target_id
        self.logs_ch = logs_ch
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
            log_line(guild, f"📨 Contact : {author} ({author.id}) → {target} ({target.id})")
        else:
            await interaction.response.send_message("⚠️ Impossible d’envoyer le DM (DM fermés ?).", ephemeral=True)
            log_line(guild, f"⚠️ Contact raté (DM fermés) : {author} ({author.id}) → {target} ({target.id})")

# ---------- Edit modal (owner-only, déclenchée via bouton) ----------
class EditProfilModal(discord.ui.Modal, title="Modifier mon profil"):
    def __init__(self, owner_id: int, original: Dict[str, Any]):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.original = original

        self.age = discord.ui.TextInput(label="Âge (>=18)", default=str(original.get("age","")), max_length=3)
        self.genre = discord.ui.TextInput(label="Genre (Fille/Homme)", default=original.get("genre",""), max_length=10)
        self.orientation = discord.ui.TextInput(label="Attirance", default=original.get("orientation",""), required=False, max_length=50)
        self.passions = discord.ui.TextInput(label="Passions", default=original.get("passions",""), required=False, style=discord.TextStyle.paragraph, max_length=300)
        self.activite = discord.ui.TextInput(label="Activité", default=original.get("activite",""), required=False, max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Tu n’as pas l’autorisation.", ephemeral=True)
            return

        try:
            age_val = int(str(self.age.value).strip())
        except Exception:
            await interaction.response.send_message("Âge invalide.", ephemeral=True)
            return
        if age_val < 18:
            await interaction.response.send_message("❌ Réservé aux 18 ans et plus.", ephemeral=True)
            return

        prof = storage.get_profile(self.owner_id) or {}
        prof.update({
            "age": age_val,
            "genre": str(self.genre.value).strip(),
            "orientation": str(self.orientation.value).strip(),
            "passions": str(self.passions.value).strip(),
            "activite": str(self.activite.value).strip(),
            "updated_at": datetime.now(TZ).isoformat()
        })
        storage.set_profile(self.owner_id, prof)

        # Publier MAJ
        guild = interaction.guild
        member = guild.get_member(self.owner_id)
        view = ProfileView(owner_id=self.owner_id)
        embed = build_profile_embed(member, prof)
        ref = storage.get_profile_msg(self.owner_id)
        if ref:
            ch = guild.get_channel(ref["channel_id"])
            if isinstance(ch, discord.TextChannel):
                try:
                    msg = await ch.fetch_message(ref["message_id"])
                    await msg.edit(embed=embed, view=view, content=None)
                except Exception:
                    pass

        log_line(guild, f"✏️ Édition : {member} ({member.id})")
        await interaction.response.send_message("✅ Profil mis à jour. (Pour changer la photo, DM une nouvelle image ou URL.)", ephemeral=True)

# -------------------- Vue principale sous chaque profil --------------------
class ProfileView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=None)
        self.owner_id = owner_id

    # ❤️ Like
    @discord.ui.button(emoji="❤️", label="Like", style=discord.ButtonStyle.success, custom_id="pf_like")
    async def like_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)  # DEFER
        author = interaction.user
        if author.id == self.owner_id:
            await interaction.followup.send("🤨 Tu ne peux pas te liker toi-même.", ephemeral=True)
            return

        guild = interaction.guild
        is_match = storage.like(author.id, self.owner_id)
        log_line(guild, f"❤️ Like : {author} ({author.id}) → {self.owner_id}")
        await interaction.followup.send("❤️ Noté !", ephemeral=True)

        if is_match:
            a = guild.get_member(author.id)
            b = guild.get_member(self.owner_id)
            # DM aux deux
            for m1, m2 in [(a, b), (b, a)]:
                try:
                    dm = await m1.create_dm()
                    await dm.send(f"🔥 **C’est un match !** Tu as liké **{m2.display_name}** et c’est réciproque. Écrivez-vous !")
                except Exception:
                    pass
            log_line(guild, f"🔥 Match : {a} ({a.id}) ❤️ {b} ({b.id})")

    # ❌ Pass
    @discord.ui.button(emoji="❌", label="Pass", style=discord.ButtonStyle.secondary, custom_id="pf_pass")
    async def pass_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)  # DEFER
        author = interaction.user
        if author.id == self.owner_id:
            await interaction.followup.send("… Pourquoi passer sur toi-même ? 😅", ephemeral=True)
            return
        storage.pass_(author.id, self.owner_id)
        log_line(interaction.guild, f"❌ Pass : {author} ({author.id}) → {self.owner_id}")
        await interaction.followup.send("👌 C’est noté.", ephemeral=True)

    # 📩 Contacter
    @discord.ui.button(emoji="📩", label="Contacter", style=discord.ButtonStyle.primary, custom_id="pf_contact")
    async def contact_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Ouvrir une modal EST une réponse; pas besoin de defer
        logs_ch = interaction.guild.get_channel(CH_LOGS) if CH_LOGS else None
        await interaction.response.send_modal(ContactModal(target_id=self.owner_id, logs_ch=logs_ch))

    # ✏️ Modifier (owner-only)
    @discord.ui.button(emoji="✏️", label="Modifier", style=discord.ButtonStyle.secondary, custom_id="pf_edit")
    async def edit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)  # DEFER
        if not allowed_to_manage(interaction, self.owner_id):
            await interaction.followup.send("❌ Tu ne peux pas modifier ce profil.", ephemeral=True)
            return
        prof = storage.get_profile(self.owner_id)
        if not prof:
            await interaction.followup.send("Profil introuvable.", ephemeral=True)
            return
        # On répond par modal (ça remplace followup), donc pour être safe : on envoie la modal AVANT un followup
        try:
            # On ne peut pas ouvrir une modal après un defer + followup. Ici on a juste defer (OK).
            await interaction.edit_original_response(content="")  # nettoie le pending (facultatif)
            await interaction.followup.send("✏️ Ouvre la fenêtre d’édition…", ephemeral=True)
        except Exception:
            pass
        # Comme Discord n'autorise qu'une seule "réponse", on utilise un petit trick:
        # relancer une interaction via un nouveau bouton serait overkill; ici on ouvre la modal directement:
        # (selon versions, ouvrir une modal après defer peut échouer; si c'est le cas, garder la modal côté ContactModal/DM)
        try:
            await interaction.channel.send(
                f"{interaction.user.mention} ouvre la modification… (si la modal ne s’ouvre pas, utilise le DM)",
                delete_after=3
            )
        except Exception:
            pass
        # En pratique, pour full fiabilité des modals après defer, on peut basculer en DM:
        try:
            dm = await interaction.user.create_dm()
            await dm.send("✏️ Ouvre ce formulaire pour modifier ton profil :", delete_after=120)
            await dm.send(view=OpenModalView(is_edit=True))
        except Exception:
            pass

    # 🗑️ Supprimer (owner-only)
    @discord.ui.button(emoji="🗑️", label="Supprimer", style=discord.ButtonStyle.danger, custom_id="pf_delete")
    async def del_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)  # DEFER
        if not allowed_to_manage(interaction, self.owner_id):
            await interaction.followup.send("❌ Tu ne peux pas supprimer ce profil.", ephemeral=True)
            return

        ref = storage.get_profile_msg(self.owner_id)
        storage.delete_profile(self.owner_id)

        # Supprimer le message si possible
        if ref:
            ch = interaction.guild.get_channel(ref["channel_id"])
            if isinstance(ch, discord.TextChannel):
                try:
                    msg = await ch.fetch_message(ref["message_id"])
                    await msg.delete()
                except Exception:
                    pass

        member = interaction.guild.get_member(self.owner_id)
        log_line(interaction.guild, f"🗑️ Suppression : {member} ({member.id})")
        await interaction.followup.send("✅ Profil supprimé.", ephemeral=True)

# -------------------- Fonctions profil --------------------
def build_profile_embed(member: discord.Member, prof: Dict[str, Any]) -> discord.Embed:
    e = discord.Embed(
        title=f"Profil de {member.display_name}",
        description="Espace Rencontre — Miri",
        color=discord.Color.purple()
    )
    e.set_author(name=str(member), icon_url=member.display_avatar.url if member.display_avatar else None)
    # miniature (gauche)
    if prof.get("photo_url"):
        e.set_thumbnail(url=prof["photo_url"])

    fields = [
        ("Âge", f"{prof.get('age', '—')}", True),
        ("Genre", prof.get('genre', '—') or "—", True),
        ("Attirance", prof.get('orientation', '—') or "—", True),
        ("Passions", prof.get('passions', '—') or "—", False),
        ("Activité", prof.get('activite', '—') or "—", False),
    ]
    for n, v, inline in fields:
        e.add_field(name=n, value=v, inline=inline)

    e.set_footer(text="❤️ Like  •  ❌ Pass  •  📩 Contacter  •  ✏️ Modifier  •  🗑️ Supprimer")
    return e

def target_channel_for(guild: discord.Guild, prof: Dict[str, Any]) -> Optional[discord.TextChannel]:
    gender = (prof.get("genre") or "").strip().lower()
    if gender.startswith("f"):
        return guild.get_channel(CH_GIRLS)
    return guild.get_channel(CH_BOYS)

async def publish_or_update_profile(guild: discord.Guild, member: discord.Member, prof: Dict[str, Any]):
    view = ProfileView(owner_id=member.id)
    embed = build_profile_embed(member, prof)
    ref = storage.get_profile_msg(member.id)
    if ref:
        ch = guild.get_channel(ref["channel_id"])
        if isinstance(ch, discord.TextChannel):
            try:
                msg = await ch.fetch_message(ref["message_id"])
                await msg.edit(embed=embed, view=view, content=None)
                return
            except Exception:
                pass
    # New publish
    ch = target_channel_for(guild, prof)
    if not isinstance(ch, discord.TextChannel):
        return
    msg = await ch.send(embed=embed, view=view)
    storage.set_profile_msg(member.id, ch.id, msg.id)

# -------------------- Bot / Events --------------------
class RencontreBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.synced = False

    async def setup_hook(self):
        # Vues persistantes (accueil / DM start)
        self.add_view(StartFormView())
        self.add_view(OpenModalView(is_edit=False))
        self.add_view(OpenModalView(is_edit=True))
        # ProfileView: recréée à chaque message

    async def on_ready(self):
        try:
            if not self.synced:
                self.synced = True  # pas de sync slash ici (on ajoute /speeddating plus bas)
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
        # Capture de la photo en DM après (création/édition)
        if message.author.bot:
            return
        if isinstance(message.channel, discord.DMChannel):
            uid = message.author.id
            if uid in awaiting_photo:
                photo_url = None
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
                    photo_url = ""  # autorise vide

                payload = awaiting_photo.pop(uid)
                prof = payload["profile"]
                is_edit = payload.get("is_edit", False)
                if photo_url is not None:
                    prof["photo_url"] = photo_url

                guild = discord.utils.get(self.guilds, id=GUILD_ID)
                if not guild:
                    await message.channel.send("⚠️ Je ne trouve pas le serveur. Réessaie plus tard.")
                    return
                member = guild.get_member(uid)
                if not member:
                    await message.channel.send("⚠️ Je ne te trouve pas sur le serveur.")
                    return

                storage.set_profile(uid, prof)
                await publish_or_update_profile(guild, member, prof)

                # donner le rôle accès si création
                if not is_edit and ROLE_ACCESS:
                    role = guild.get_role(ROLE_ACCESS)
                    if role:
                        try:
                            await member.add_roles(role, reason="Création du profil Rencontre")
                        except Exception:
                            pass

                if is_edit:
                    log_line(guild, f"✏️ Édition (photo {'changée' if photo_url else 'inchangée'}) : {member} ({member.id})")
                    await message.channel.send("✅ Profil mis à jour.")
                else:
                    log_line(guild, f"✅ Création profil : {member} ({member.id}) + rôle Accès Rencontre")
                    await message.channel.send("✅ Profil créé. Bienvenue dans l’Espace Rencontre !")

# -------------------- /speeddating (seule commande slash) --------------------
class SpeedCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="speeddating", description="Crée des threads privés éphémères pour les actifs de la dernière heure (staff).")
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
        pairs: List[Tuple[int,int]] = []
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

# -------------------- Entrée --------------------
bot = RencontreBot()
speed = SpeedCog(bot)
bot.tree.add_command(speed.speeddating, guild=discord.Object(id=GUILD_ID) if GUILD_ID else None)

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN est requis (mets-le en variable d’environnement).")
    bot.run(DISCORD_TOKEN)

