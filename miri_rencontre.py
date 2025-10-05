# ================================================================
# 🌹 MIRI RENCONTRE — BOT DISCORD COMPLET
# ================================================================
import os, re, json, asyncio, time, tempfile, shutil, random
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

# -------------------- CONFIG --------------------
def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = env_int("GUILD_ID", 1382730341944397967)
ROLE_ACCESS = env_int("ROLE_ACCESS", 1401403405729267762)
CH_GIRLS = env_int("CH_GIRLS", 1400520391793053841)
CH_BOYS = env_int("CH_BOYS", 1400520396557521058)
CH_SPEED = env_int("CH_SPEED", 1402665906546413679)
CH_LOGS = env_int("CH_LOGS", 1403154919913033728)
CH_WELCOME = env_int("CH_WELCOME", 1400808431941849178)
DATA_FILE = os.getenv("DATA_FILE", "rencontre_data.json")
BRAND_COLOR = 0x7C3AED
TZ = ZoneInfo("Europe/Paris")

LIKE_COOLDOWN = 600
CONTACT_COOLDOWN = 600

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True
GUILD_OBJ = discord.Object(id=GUILD_ID)

# -------------------- STORAGE --------------------
class Storage:
    def __init__(self, path: str):
        self.path = path
        self._lock = asyncio.Lock()
        self.data = {
            "profiles": {},
            "profile_msgs": {},
            "banned_users": [],
            "owners": [],
            "welcome_panel": None,
        }
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.data.update(json.load(f))
            except Exception:
                pass

    async def save(self):
        async with self._lock:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get_profile(self, uid: int): return self.data["profiles"].get(str(uid))
    async def set_profile(self, uid: int, profile: Dict[str, Any]):
        self.data["profiles"][str(uid)] = profile
        await self.save()

    def get_profile_msg(self, uid: int): return self.data["profile_msgs"].get(str(uid))
    def set_profile_msg(self, uid: int, ch: int, msg: int):
        self.data["profile_msgs"][str(uid)] = {"channel_id": ch, "message_id": msg}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    async def delete_profile(self, uid: int):
        self.data["profiles"].pop(str(uid), None)
        self.data["profile_msgs"].pop(str(uid), None)
        await self.save()

    def is_banned(self, uid: int) -> bool: return uid in self.data.get("banned_users", [])
    async def ban(self, uid: int):
        if uid not in self.data["banned_users"]:
            self.data["banned_users"].append(uid)
            await self.save()
    async def unban(self, uid: int):
        if uid in self.data["banned_users"]:
            self.data["banned_users"].remove(uid)
            await self.save()
    def list_bans(self): return self.data["banned_users"]

storage = Storage(DATA_FILE)
LIKE_COOLDOWN = storage.data.get("like_cooldown", LIKE_COOLDOWN)
CONTACT_COOLDOWN = storage.data.get("contact_cooldown", CONTACT_COOLDOWN)

# -------------------- UTILS --------------------
async def send_log_embed(guild, title: str, desc: str, user=None, color=0x7C3AED):
    if not CH_LOGS or not guild:
        return
    ch = guild.get_channel(CH_LOGS)
    if not isinstance(ch, discord.TextChannel):
        return
    e = discord.Embed(title=f"📋 {title}", description=desc, color=color)
    e.timestamp = datetime.now(timezone.utc)
    if user:
        e.set_footer(text=f"{user} ({user.id})")
    try:
        await ch.send(embed=e)
    except Exception:
        pass

def now_str() -> str:
    return datetime.now(TZ).strftime("%d/%m/%Y %H:%M")

async def _remove_access_role(guild, member):
    if not guild or not member or not ROLE_ACCESS:
        return
    role = guild.get_role(ROLE_ACCESS)
    if role and role in member.roles:
        try:
            await member.remove_roles(role, reason="Suppression du profil Rencontre")
        except Exception:
            pass

async def full_profile_reset(guild, uid: int, reason="Suppression profil"):
    await storage.delete_profile(uid)
    ref = storage.get_profile_msg(uid)
    if ref:
        ch = guild.get_channel(ref["channel_id"])
        if ch:
            try:
                msg = await ch.fetch_message(ref["message_id"])
                await msg.delete()
            except Exception:
                pass
    member = guild.get_member(uid)
    await _remove_access_role(guild, member)
    await send_log_embed(guild, "Profil supprimé", f"Profil supprimé ({reason})", member, 0xEF4444)
# -------------------- EMBEDS PROFIL --------------------
def build_profile_embed(member: discord.Member, prof: Dict[str, Any]) -> discord.Embed:
    e = discord.Embed(
        title=f"{member.display_name}",
        description="💞 Profil Rencontre — Miri",
        color=BRAND_COLOR,
    )
    e.add_field(name="Âge", value=str(prof.get("age", "—")), inline=True)
    e.add_field(name="Genre", value=prof.get("genre", "—"), inline=True)
    e.add_field(name="Attirance", value=prof.get("orientation", "—"), inline=True)
    e.add_field(name="Passions", value=prof.get("passions", "—"), inline=False)
    e.add_field(name="Activité", value=prof.get("activite", "—"), inline=False)
    if prof.get("photo_url"):
        e.set_thumbnail(url=prof["photo_url"])
    e.set_footer(text="Miri Rencontre • Connecte-toi 🌹")
    e.timestamp = datetime.now(timezone.utc)
    return e

# -------------------- PUBLICATION PROFIL --------------------
def target_channel_for(guild: discord.Guild, prof: Dict[str, Any]) -> Optional[discord.TextChannel]:
    gender = (prof.get("genre") or "").lower()
    if gender.startswith("f"):
        return guild.get_channel(CH_GIRLS)
    return guild.get_channel(CH_BOYS)

async def publish_or_update_profile(guild: discord.Guild, member: discord.Member, prof: Dict[str, Any]):
    embed = build_profile_embed(member, prof)
    view = ProfileView(owner_id=member.id)
    ref = storage.get_profile_msg(member.id)
    if ref:
        ch = guild.get_channel(ref["channel_id"])
        if ch:
            try:
                msg = await ch.fetch_message(ref["message_id"])
                await msg.edit(embed=embed, view=view)
                return
            except Exception:
                pass
    ch = target_channel_for(guild, prof)
    if not isinstance(ch, discord.TextChannel):
        return
    msg = await ch.send(embed=embed, view=view)
    storage.set_profile_msg(member.id, ch.id, msg.id)

# -------------------- PROFILE VIEW --------------------
like_cooldowns: Dict[Tuple[int, int], float] = {}
contact_cooldowns: Dict[Tuple[int, int], float] = {}

class ProfileView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=None)
        self.owner_id = owner_id

    def _check_cd(self, store: Dict, user_id: int, cooldown: int):
        key = (user_id, self.owner_id)
        now = time.time()
        if key in store and now - store[key] < cooldown:
            return False
        store[key] = now
        return True

    @discord.ui.button(emoji="❤️", style=discord.ButtonStyle.success)
    async def like(self, inter: discord.Interaction, btn: discord.ui.Button):
        if inter.user.id == self.owner_id:
            await inter.response.send_message("💡 Tu ne peux pas te liker toi-même.", ephemeral=True)
            return
        if not self._check_cd(like_cooldowns, inter.user.id, LIKE_COOLDOWN):
            await inter.response.send_message("⏳ Attends avant de reliker ❤️", ephemeral=True)
            return
        await inter.response.send_message("❤️ Like enregistré.", ephemeral=True)
        await send_log_embed(inter.guild, "Like", f"{inter.user.mention} a liké <@{self.owner_id}>", inter.user, 0xF472B6)

    @discord.ui.button(emoji="📩", style=discord.ButtonStyle.primary)
    async def contact(self, inter: discord.Interaction, btn: discord.ui.Button):
        if inter.user.id == self.owner_id:
            await inter.response.send_message("🙃 Pas toi-même.", ephemeral=True)
            return
        if not self._check_cd(contact_cooldowns, inter.user.id, CONTACT_COOLDOWN):
            await inter.response.send_message("⏳ Attends avant de recontacter 💌", ephemeral=True)
            return
        target = inter.guild.get_member(self.owner_id)
        if not target:
            await inter.response.send_message("⚠️ Membre introuvable.", ephemeral=True)
            return
        try:
            dm = await target.create_dm()
            await dm.send(f"💌 **{inter.user.display_name}** souhaite te parler !")
            await inter.response.send_message("📨 Message envoyé.", ephemeral=True)
        except Exception:
            await inter.response.send_message("⚠️ DM impossible.", ephemeral=True)

    @discord.ui.button(emoji="🗑️", style=discord.ButtonStyle.danger)
    async def delete(self, inter: discord.Interaction, btn: discord.ui.Button):
        if inter.user.id != self.owner_id and not inter.user.guild_permissions.administrator:
            await inter.response.send_message("❌ Tu ne peux pas supprimer ce profil.", ephemeral=True)
            return
        await full_profile_reset(inter.guild, self.owner_id, "Suppression via bouton")
        await inter.response.send_message("✅ Profil supprimé.", ephemeral=True)

# -------------------- FORMULAIRE DM --------------------
dm_sessions: Dict[int, Dict[str, Any]] = {}

async def _send_next_step(dm_ch: discord.DMChannel, uid: int):
    step = dm_sessions[uid]["step"]
    questions = [
        "Quel est **ton âge** ? (nombre ≥ 18)",
        "Ton **genre** ? (Fille / Homme)",
        "Ton **attirance** (orientation) ? (ex : hétéro, bi, pan…)",
        "Tes **passions** ? (quelques mots)",
        "Ton **activité** (ce que tu fais dans la vie) ?",
        "📸 Envoie une **photo** (fichier ou lien URL d’image).",
    ]
    if step < len(questions):
        await dm_ch.send(f"{step+1}/6 — {questions[step]}")

# -------------------- PANEL D’ACCUEIL --------------------
class StartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✨ Créer mon profil maintenant", style=discord.ButtonStyle.success, custom_id="start_profile")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if storage.is_banned(interaction.user.id):
            await interaction.response.send_message("🚫 Tu n’as pas accès à la section Rencontre.", ephemeral=True)
            return
        await interaction.response.send_message("📩 Regarde tes messages privés pour commencer 💌", ephemeral=True)
        try:
            dm = await interaction.user.create_dm()
            await dm.send("💞 Bienvenue dans la création de ton profil ! Réponds à mes questions ⤵️")
            dm_sessions[interaction.user.id] = {"step": 0, "answers": {}}
            await _send_next_step(dm, interaction.user.id)
        except Exception:
            await interaction.followup.send("⚠️ Impossible de t’écrire en DM.", ephemeral=True)

async def ensure_welcome_panel(bot: commands.Bot):
    if not CH_WELCOME:
        return
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    ch = guild.get_channel(CH_WELCOME)
    if not isinstance(ch, discord.TextChannel):
        return

    ref = storage.data.get("welcome_panel")
    if ref and "message_id" in ref:
        try:
            await ch.fetch_message(ref["message_id"])
            return
        except Exception:
            pass

    embed = discord.Embed(
        title="🌹 Bienvenue dans l’Espace Rencontre",
        description=(
            "✨ Crée ton profil pour découvrir les autres membres et participer aux **Soirées Rencontre** 💞\n\n"
            "⚠️ Réservé aux **18 ans et plus**."
        ),
        color=BRAND_COLOR
    )
    if guild.icon:
        embed.set_author(name=guild.name, icon_url=guild.icon.url)
    embed.set_footer(text="Miri Rencontre • Ensemble, ça matche 💞")

    msg = await ch.send(embed=embed, view=StartView())
    storage.data["welcome_panel"] = {"channel_id": ch.id, "message_id": msg.id}
    await storage.save()
# -------------------- BOT PRINCIPAL --------------------
class RencontreBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.add_cog(AdminCog(self))
        await self.add_cog(PublicInfoCog(self))
        self.add_view(ProfileView(owner_id=0))
        self.add_view(StartView())

    async def on_ready(self):
        print(f"✅ Connecté comme {self.user}")
        await ensure_welcome_panel(self)
        await self.change_presence(status=discord.Status.online, activity=discord.Game("Miri Rencontre 🌹"))

    async def on_message(self, message: discord.Message):
        await self.process_commands(message)
        if message.author.bot or message.guild is not None:
            return
        uid = message.author.id
        if uid not in dm_sessions:
            return
        sess = dm_sessions[uid]
        dm_ch: discord.DMChannel = message.channel
        content = (message.content or "").strip()

        # Étape 1 : âge
        if sess["step"] == 0:
            try:
                age = int(re.sub(r"\D+", "", content))
                if age < 18:
                    await dm_ch.send("🚫 Désolé, c’est réservé aux **18 ans et plus.**")
                    dm_sessions.pop(uid, None)
                    return
                sess["answers"]["age"] = age
                sess["step"] = 1
                await _send_next_step(dm_ch, uid)
            except Exception:
                await dm_ch.send("⚠️ Entre un **nombre valide** (ex: 22).")
            return

        # Étape 2 : genre
        if sess["step"] == 1:
            g = content.lower()
            if g.startswith("f"):
                sess["answers"]["genre"] = "Femme"
            elif g.startswith("h"):
                sess["answers"]["genre"] = "Homme"
            else:
                await dm_ch.send("⚠️ Réponds par **Femme** ou **Homme.**")
                return
            sess["step"] = 2
            await _send_next_step(dm_ch, uid)
            return

        # Étape 3 : attirance
        if sess["step"] == 2:
            sess["answers"]["orientation"] = content[:100] if content else "—"
            sess["step"] = 3
            await _send_next_step(dm_ch, uid)
            return

        # Étape 4 : passions
        if sess["step"] == 3:
            sess["answers"]["passions"] = content[:200] if content else "—"
            sess["step"] = 4
            await _send_next_step(dm_ch, uid)
            return

        # Étape 5 : activité
        if sess["step"] == 4:
            sess["answers"]["activite"] = content[:150] if content else "—"
            sess["step"] = 5
            await _send_next_step(dm_ch, uid)
            return

        # Étape 6 : photo
        if sess["step"] == 5:
            photo_url = None
            if message.attachments:
                att = message.attachments[0]
                if att.content_type and att.content_type.startswith("image/"):
                    photo_url = att.url
            if not photo_url and content.startswith("http"):
                if re.search(r"\.(png|jpe?g|gif|webp)(\?|$)", content, re.I):
                    photo_url = content
            if not photo_url:
                await dm_ch.send("⚠️ Envoie une **image** (fichier ou lien direct .jpg/.png/.webp).")
                return

            sess["answers"]["photo_url"] = photo_url
            profile = sess["answers"]

            # Sauvegarde profil
            await storage.set_profile(uid, profile)
            guild = self.get_guild(GUILD_ID)
            if guild:
                member = guild.get_member(uid)
                if member:
                    try:
                        await publish_or_update_profile(guild, member, profile)
                        await send_log_embed(guild, "Nouveau profil", f"{member.mention} a créé son profil.", member)
                    except Exception:
                        pass
                    if ROLE_ACCESS:
                        role = guild.get_role(ROLE_ACCESS)
                        if role and role not in member.roles:
                            try:
                                await member.add_roles(role, reason="Profil Rencontre validé")
                            except Exception:
                                pass

            dm_sessions.pop(uid, None)
            await dm_ch.send("✅ **Profil enregistré !** Il a été publié sur le serveur 💞")
            return

# -------------------- COMMANDES --------------------
class AdminCog(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="setcooldown", description="Modifier le cooldown (admin)")
    @app_commands.describe(type="like/contact", minutes="Durée en minutes")
    @app_commands.checks.has_permissions(administrator=True)
    async def setcooldown(self, inter: discord.Interaction, type: str, minutes: int):
        global LIKE_COOLDOWN, CONTACT_COOLDOWN
        seconds = max(60, minutes * 60)
        if type.lower() == "like":
            LIKE_COOLDOWN = seconds
            storage.data["like_cooldown"] = seconds
        elif type.lower() == "contact":
            CONTACT_COOLDOWN = seconds
            storage.data["contact_cooldown"] = seconds
        else:
            await inter.response.send_message("⚠️ Type invalide.", ephemeral=True)
            return
        await storage.save()
        await inter.response.send_message(f"✅ Cooldown `{type}` mis à {minutes} min.", ephemeral=True)
        await send_log_embed(inter.guild, "Cooldown modifié", f"{type} → {minutes} min", inter.user)

    @app_commands.command(name="rencontre_stats", description="📊 Statistiques Rencontre")
    @app_commands.checks.has_permissions(administrator=True)
    async def stats(self, inter: discord.Interaction):
        total = len(storage.data.get("profiles", {}))
        published = len(storage.data.get("profile_msgs", {}))
        bans = len(storage.data.get("banned_users", []))
        e = discord.Embed(title="📊 Statistiques Rencontre", color=BRAND_COLOR)
        e.add_field(name="👥 Profils", value=f"{total} enregistrés\n{published} publiés", inline=False)
        e.add_field(name="🚫 Bannis", value=str(bans), inline=True)
        e.add_field(name="⚙️ Cooldowns", value=f"❤️ {LIKE_COOLDOWN//60}m\n💌 {CONTACT_COOLDOWN//60}m", inline=True)
        e.timestamp = datetime.now(timezone.utc)
        await inter.response.send_message(embed=e, ephemeral=True)

class PublicInfoCog(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="rencontre_info", description="📖 Infos publiques de l’Espace Rencontre")
    async def info(self, inter: discord.Interaction):
        total = len(storage.data.get("profiles", {}))
        published = len(storage.data.get("profile_msgs", {}))
        percent = round((published / total) * 100, 1) if total else 0
        e = discord.Embed(
            title="🌹 Miri Rencontre",
            description="✨ Crée de vraies connexions humaines 💞",
            color=BRAND_COLOR,
        )
        e.add_field(name="👥 Profils", value=f"{published}/{total} publiés ({percent}%)", inline=False)
        e.add_field(name="🕊️ Règles", value="Respect, authenticité et bienveillance 🛡️", inline=False)
        e.set_footer(text="Miri Rencontre • Ensemble, ça matche ✨")
        await inter.response.send_message(embed=e, ephemeral=False)

# -------------------- LANCEMENT --------------------
if not DISCORD_TOKEN:
    raise RuntimeError("❌ DISCORD_TOKEN manquant dans l'environnement.")
bot = RencontreBot()
bot.run(DISCORD_TOKEN)
