# ================================================================
# 🌹 MIRI RENCONTRE — VERSION LUXURY
# ================================================================
import os, re, json, asyncio, time, tempfile, shutil
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

# -------------------- CONFIG --------------------
def env_int(name: str, default: int) -> int:
    try: return int(os.getenv(name, str(default)))
    except Exception: return default

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID      = env_int("GUILD_ID", 1382730341944397967)
ROLE_ACCESS   = env_int("ROLE_ACCESS", 1401403405729267762)
CH_GIRLS      = env_int("CH_GIRLS", 1400520391793053841)
CH_BOYS       = env_int("CH_BOYS", 1400520396557521058)
CH_SPEED      = env_int("CH_SPEED", 1402665906546413679)
CH_LOGS       = env_int("CH_LOGS", 1403154919913033728)
CH_WELCOME    = env_int("CH_WELCOME", 1400808431941849178)

DATA_FILE     = os.getenv("DATA_FILE", "rencontre_data.json")
BRAND_COLOR   = 0x7C3AED
TZ = ZoneInfo("Europe/Paris")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

GUILD_OBJ = discord.Object(id=GUILD_ID)

# ================================================================
# 🌹 STOCKAGE
# ================================================================
class Storage:
    def __init__(self, path: str):
        self.path = path
        self._lock = asyncio.Lock()
        self.data: Dict[str, Any] = {
            "profiles": {},
            "profile_msgs": {},
            "banned_users": [],
            "owners": [],
        }
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    self.data.update(d)
            except Exception:
                pass

    async def save(self):
        async with self._lock:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get_profile(self, uid: int) -> Optional[Dict[str, Any]]:
        return self.data["profiles"].get(str(uid))

    async def set_profile(self, uid: int, prof: Dict[str, Any]):
        self.data["profiles"][str(uid)] = prof
        await self.save()

    async def delete_profile(self, uid: int):
        self.data["profiles"].pop(str(uid), None)
        self.data["profile_msgs"].pop(str(uid), None)
        await self.save()

    def set_profile_msg(self, uid: int, ch_id: int, msg_id: int):
        self.data["profile_msgs"][str(uid)] = {"channel_id": ch_id, "message_id": msg_id}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get_profile_msg(self, uid: int) -> Optional[Dict[str, int]]:
        return self.data["profile_msgs"].get(str(uid))

    def list_bans(self) -> List[int]:
        return list(map(int, self.data.get("banned_users", [])))

    def is_banned(self, uid: int) -> bool:
        return uid in self.list_bans()

    async def ban_user(self, uid: int):
        b = self.data.setdefault("banned_users", [])
        if uid not in b:
            b.append(uid)
            await self.save()

    async def unban_user(self, uid: int):
        b = self.data.setdefault("banned_users", [])
        if uid in b:
            b.remove(uid)
            await self.save()

storage = Storage(DATA_FILE)

# ================================================================
# 🌹 LOGS ÉLÉGANTS
# ================================================================
async def send_log_embed(
    guild: discord.Guild,
    title: str,
    description: str,
    user: Optional[discord.Member | discord.User] = None,
    color: int = 0x7C3AED
):
    if not guild or not CH_LOGS:
        return
    ch = guild.get_channel(CH_LOGS)
    if not isinstance(ch, discord.TextChannel):
        return

    embed = discord.Embed(
        title=f"🕊️ {title}",
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text="Miri Rencontre • Journal des actions")
    if user:
        embed.set_author(name=str(user), icon_url=user.display_avatar.url)

    try:
        await ch.send(embed=embed)
    except Exception:
        pass


async def log_profile_created(guild: discord.Guild, member: discord.Member):
    profile = storage.get_profile(member.id)
    if not profile:
        return
    desc = (
        f"**Profil créé** par {member.mention}\n\n"
        f"**Âge :** {profile.get('age', '—')}\n"
        f"**Genre :** {profile.get('genre', '—')}\n"
        f"**Orientation :** {profile.get('orientation', '—')}\n"
        f"**Activité :** {profile.get('activite', '—')}\n"
        f"**Date :** {datetime.now(TZ).strftime('%d/%m/%Y %H:%M')}"
    )
    await send_log_embed(guild, "Nouveau profil créé", desc, user=member, color=0x4ADE80)


async def log_profile_deleted(guild: discord.Guild, member: Optional[discord.Member], reason: str = "—"):
    user_text = member.mention if member else "Utilisateur inconnu"
    desc = (
        f"{user_text}\n"
        f"**Raison :** {reason}\n"
        f"**Date :** {datetime.now(TZ).strftime('%d/%m/%Y %H:%M')}"
    )
    await send_log_embed(guild, "Profil supprimé", desc, user=member, color=0xF87171)
# ================================================================
# 🌹 ACCUEIL & CRÉATION DE PROFIL
# ================================================================

dm_sessions: Dict[int, Dict[str, Any]] = {}

# ---------- utilitaires ----------
async def remove_access_role(guild: discord.Guild, member: Optional[discord.Member]):
    if not (guild and member and ROLE_ACCESS):
        return
    role = guild.get_role(ROLE_ACCESS)
    if role and role in member.roles:
        try:
            await member.remove_roles(role, reason="Reset profil Rencontre")
        except Exception:
            pass


async def full_profile_reset(guild: discord.Guild, user_id: int, reason: str = "—"):
    ref = storage.get_profile_msg(user_id)
    await storage.delete_profile(user_id)

    if ref:
        ch = guild.get_channel(ref["channel_id"])
        if isinstance(ch, discord.TextChannel):
            try:
                msg = await ch.fetch_message(ref["message_id"])
                await msg.delete()
            except Exception:
                pass

    member = guild.get_member(user_id)
    await remove_access_role(guild, member)
    await log_profile_deleted(guild, member, reason)


# ================================================================
# 🌹 EMBEDS DE PROFIL — STYLE LUXURY
# ================================================================
def build_profile_embed(member: discord.Member, prof: Dict[str, Any]) -> discord.Embed:
    e = discord.Embed(
        title=f"Profil de {member.display_name}",
        description="💞 Rencontre • Miri",
        color=BRAND_COLOR
    )
    e.set_author(name=str(member), icon_url=member.display_avatar.url)
    if prof.get("photo_url"):
        e.set_thumbnail(url=prof["photo_url"])

    e.add_field(name="Âge", value=str(prof.get("age", "—")), inline=True)
    e.add_field(name="Genre", value=prof.get("genre", "—"), inline=True)
    e.add_field(name="Attirance", value=prof.get("orientation", "—"), inline=True)
    e.add_field(name="Passions", value=prof.get("passions", "—"), inline=False)
    e.add_field(name="Activité", value=prof.get("activite", "—"), inline=False)

    e.set_footer(text="Miri Rencontre • Profil membre")
    e.timestamp = datetime.now(timezone.utc)
    return e


def target_channel_for(guild: discord.Guild, prof: Dict[str, Any]) -> Optional[discord.TextChannel]:
    gender = (prof.get("genre") or "").lower()
    return guild.get_channel(CH_GIRLS) if gender.startswith("f") else guild.get_channel(CH_BOYS)


async def publish_or_update_profile(guild: discord.Guild, member: discord.Member, prof: Dict[str, Any]):
    embed = build_profile_embed(member, prof)
    ref = storage.get_profile_msg(member.id)
    view = discord.ui.View()
    view.add_item(discord.ui.Button(emoji="❤️", style=discord.ButtonStyle.success, custom_id="pf_like"))
    view.add_item(discord.ui.Button(emoji="❌", style=discord.ButtonStyle.secondary, custom_id="pf_pass"))
    view.add_item(discord.ui.Button(emoji="📩", style=discord.ButtonStyle.primary, custom_id="pf_contact"))
    view.add_item(discord.ui.Button(emoji="🗑️", style=discord.ButtonStyle.danger, custom_id="pf_delete"))

    if ref:
        ch = guild.get_channel(ref["channel_id"])
        if isinstance(ch, discord.TextChannel):
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
    await log_profile_created(guild, member)


# ================================================================
# 🌹 PANNEAU D’ACCUEIL
# ================================================================
class StartFormView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✨ Créer mon profil", style=discord.ButtonStyle.success, custom_id="start_profile_btn")
    async def start_profile_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if storage.is_banned(interaction.user.id):
            await interaction.response.send_message("🚫 Tu n’as pas accès à l’Espace Rencontre.", ephemeral=True)
            return
        await interaction.response.send_message("📩 Regarde tes DM pour créer ton profil 💞", ephemeral=True)
        try:
            dm = await interaction.user.create_dm()
            await dm.send(
                embed=discord.Embed(
                    title="Création de ton profil 💫",
                    description="Réponds à ces quelques questions en privé 👇\nTu peux écrire `stop` à tout moment.",
                    color=BRAND_COLOR
                )
            )
            dm_sessions[interaction.user.id] = {"step": 0, "answers": {}}
            await dm.send("1️⃣ Quel est **ton âge** ? (nombre ≥ 18)")
        except Exception:
            await interaction.followup.send("⚠️ Impossible de t’écrire en DM (DM fermés ?)", ephemeral=True)


async def ensure_welcome_panel(bot: commands.Bot):
    if not CH_WELCOME:
        print("[WARN] Aucun salon d'accueil configuré.")
        return
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    ch = guild.get_channel(CH_WELCOME)
    if not isinstance(ch, discord.TextChannel):
        return

    ref = storage.data.get("welcome_panel")
    if isinstance(ref, dict) and "message_id" in ref:
        try:
            await ch.fetch_message(ref["message_id"])
            return
        except Exception:
            pass

    embed = discord.Embed(
        title="🌹 Bienvenue dans l’Espace Rencontre • Miri",
        description=(
            "Un lieu pour créer de vraies connexions 💞\n\n"
            "✨ Ici, tu peux :\n"
            "• Créer ton profil et découvrir les autres membres\n"
            "• Participer à des soirées **Speed Dating** exclusives\n"
            "• Tisser des liens sincères et élégants\n\n"
            "⚠️ Réservé aux **18 ans et plus**.\n\n"
            "Clique ci-dessous pour **commencer ton aventure** ⤵️"
        ),
        color=BRAND_COLOR
    )
    if guild.icon:
        embed.set_author(name=guild.name, icon_url=guild.icon.url)
    embed.set_footer(text="Miri Rencontre • Laissez la magie opérer ✨")
    embed.timestamp = datetime.now(timezone.utc)

    try:
        msg = await ch.send(embed=embed, view=StartFormView())
        storage.data["welcome_panel"] = {"channel_id": ch.id, "message_id": msg.id}
        await storage.save()
        print("[OK] Panneau d'accueil envoyé.")
    except Exception as e:
        print(f"[ERREUR] Panneau accueil : {e}")


# ================================================================
# 🌹 CRÉATION DE PROFIL PAR DM
# ================================================================
async def handle_dm_message(bot: commands.Bot, message: discord.Message):
    uid = message.author.id
    if uid not in dm_sessions:
        return
    sess = dm_sessions[uid]
    dm_ch: discord.DMChannel = message.channel  # type: ignore
    content = (message.content or "").strip()

    if content.lower() == "stop":
        await dm_ch.send("🚫 Création annulée.")
        dm_sessions.pop(uid, None)
        return

    # Étape 0 — Âge
    if sess["step"] == 0:
        try:
            age = int(re.sub(r"[^0-9]", "", content))
            if age < 18:
                await dm_ch.send("❌ Réservé aux **18 ans et plus**.")
                dm_sessions.pop(uid, None)
                return
            sess["answers"]["age"] = age
            sess["step"] = 1
            await dm_ch.send("2️⃣ Ton **genre** ? (Homme / Femme)")
        except Exception:
            await dm_ch.send("⚠️ Entre un nombre valide (ex: 23).")
        return

    # Étape 1 — Genre
    if sess["step"] == 1:
        g = content.lower()
        if g.startswith("h"):
            sess["answers"]["genre"] = "Homme"
        elif g.startswith("f"):
            sess["answers"]["genre"] = "Femme"
        else:
            await dm_ch.send("⚠️ Réponds par **Homme** ou **Femme**.")
            return
        sess["step"] = 2
        await dm_ch.send("3️⃣ Quelle est ton **attirance** ? (ex: hétéro, bi, pan...)")
        return

    # Étape 2 — Orientation
    if sess["step"] == 2:
        sess["answers"]["orientation"] = content[:100]
        sess["step"] = 3
        await dm_ch.send("4️⃣ Parle-nous un peu de tes **passions** ✨")
        return

    # Étape 3 — Passions
    if sess["step"] == 3:
        sess["answers"]["passions"] = content[:200]
        sess["step"] = 4
        await dm_ch.send("5️⃣ Que fais-tu dans la vie ? (ton **activité**)")
        return

    # Étape 4 — Activité
    if sess["step"] == 4:
        sess["answers"]["activite"] = content[:150]
        sess["step"] = 5
        await dm_ch.send("📸 Envoie maintenant une **photo** (upload ou lien .jpg/.png/.webp)")
        return

    # Étape 5 — Photo
    if sess["step"] == 5:
        photo_url = None
        if message.attachments:
            att = message.attachments[0]
            if att.content_type and att.content_type.startswith("image/"):
                photo_url = att.url
        if not photo_url and content.startswith("http") and re.search(r"\.(png|jpe?g|webp)", content):
            photo_url = content
        if not photo_url:
            await dm_ch.send("⚠️ Envoie une image ou un lien direct d’image.")
            return

        sess["answers"]["photo_url"] = photo_url
        profile = sess["answers"]

        await storage.set_profile(uid, profile)
        guild = bot.get_guild(GUILD_ID)
        if guild:
            member = guild.get_member(uid)
            if member:
                await publish_or_update_profile(guild, member, profile)
                role = guild.get_role(ROLE_ACCESS)
                if role and role not in member.roles:
                    try:
                        await member.add_roles(role, reason="Profil Rencontre validé")
                    except Exception:
                        pass

        dm_sessions.pop(uid, None)
        await dm_ch.send("✅ **Profil enregistré !** Il est maintenant visible sur le serveur 💞")
# ================================================================
# 🌹 COMMANDES SLASH & BOT
# ================================================================

class AdminCog(commands.Cog, name="Admin"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="resetprofil", description="🗑️ Supprime ton profil et retire ton accès Rencontre.")
    @app_commands.guilds(GUILD_OBJ)
    async def reset_profil(self, interaction: discord.Interaction):
        uid = interaction.user.id
        had = storage.get_profile(uid)
        await full_profile_reset(interaction.guild, uid, reason="Reset via /resetprofil")
        if had:
            await interaction.response.send_message(
                "🗑️ Ton profil a été supprimé et ton rôle **Accès Rencontre** retiré.", ephemeral=True
            )
        else:
            await interaction.response.send_message("ℹ️ Aucun profil enregistré.", ephemeral=True)


    @app_commands.command(name="resetrencontre", description="⚠️ Réinitialise toutes les données Rencontre (admin).")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guilds(GUILD_OBJ)
    async def reset_rencontre(self, interaction: discord.Interaction):
        storage.data = {"profiles": {}, "profile_msgs": {}, "banned_users": [], "owners": []}
        await storage.save()
        await interaction.response.send_message("🧹 Données Rencontre réinitialisées.", ephemeral=True)


    # --- gestion des bans Rencontre
    ban_group = app_commands.Group(name="rencontreban", description="Gérer les bannis de l'Espace Rencontre")

    @ban_group.command(name="add", description="🚫 Bannir un membre de l'Espace Rencontre")
    @app_commands.checks.has_permissions(administrator=True)
    async def ban_add(self, interaction: discord.Interaction, user: discord.Member, raison: Optional[str] = None):
        await storage.ban_user(user.id)
        await full_profile_reset(interaction.guild, user.id, reason="Ban Rencontre")
        await send_log_embed(
            interaction.guild,
            "Rencontre — Membre banni",
            f"{user.mention} a été banni de la Rencontre.\n**Raison :** {raison or '—'}",
            user=user,
            color=0xF87171,
        )
        await interaction.response.send_message(f"🚫 {user.display_name} banni de la Rencontre.", ephemeral=True)

    @ban_group.command(name="remove", description="✅ Débannir un membre de la Rencontre")
    @app_commands.checks.has_permissions(administrator=True)
    async def ban_remove(self, interaction: discord.Interaction, user: discord.Member):
        await storage.unban_user(user.id)
        await send_log_embed(
            interaction.guild,
            "Rencontre — Membre débanni",
            f"{user.mention} peut à nouveau accéder à la Rencontre.",
            user=user,
            color=0x4ADE80,
        )
        await interaction.response.send_message(f"✅ {user.display_name} débanni.", ephemeral=True)

    @ban_group.command(name="list", description="Voir les bannis actuels")
    async def ban_list(self, interaction: discord.Interaction):
        ids = storage.list_bans()
        if not ids:
            await interaction.response.send_message("Aucun membre banni.", ephemeral=True)
            return
        mentions = [interaction.guild.get_member(i).mention if interaction.guild.get_member(i) else f"`{i}`" for i in ids]
        await interaction.response.send_message("**Bannis Rencontre :** " + ", ".join(mentions), ephemeral=True)


# ================================================================
# 🌹 COG HELP — /rencontre_help
# ================================================================
class HelpCog(commands.Cog, name="AideRencontre"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="rencontre_help", description="Affiche la liste des commandes du bot Rencontre")
    @app_commands.guilds(GUILD_OBJ)
    async def rencontre_help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🌹 Aide — Miri Rencontre",
            description=(
                "Bienvenue dans **Miri Rencontre** 💞\n"
                "Voici les commandes disponibles selon ton rôle.\n\n"
                "📘 *Toutes les commandes fonctionnent uniquement sur le serveur Miri.*"
            ),
            color=BRAND_COLOR,
        )
        if interaction.guild and interaction.guild.icon:
            embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url)
        embed.set_footer(text="Miri Rencontre • Laissez la magie opérer ✨")

        embed.add_field(
            name="💬 Membres",
            value=(
                "• `/resetprofil` — Supprime ton profil et retire le rôle\n"
                "• Bouton `✨ Créer mon profil` — Commence ton profil en DM\n"
                "• Réagis aux profils avec ❤️ / ❌ / 📩"
            ),
            inline=False,
        )
        embed.add_field(
            name="⚙️ Admins",
            value=(
                "• `/resetrencontre` — Réinitialise toutes les données\n"
                "• `/rencontreban add/remove/list` — Gère les bannis\n"
                "• `/owners add/remove/list` — Gère les propriétaires"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ================================================================
# 🌹 BOT FINAL
# ================================================================
class RencontreBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.synced = False

    async def setup_hook(self):
        await self.add_cog(AdminCog(self))
        await self.add_cog(HelpCog(self))
        self.add_view(StartFormView())

    async def on_ready(self):
        if not self.synced:
            try:
                await self.tree.sync(guild=GUILD_OBJ)
                self.synced = True
                print(f"[SYNC] Commandes synchronisées sur {GUILD_ID}")
            except Exception as e:
                print(f"[SYNC FAIL] {e}")

        print(f"✅ Connecté en tant que {self.user} (id={self.user.id})")
        await self.change_presence(
            status=discord.Status.online,
            activity=discord.Game("💞 Miri Rencontre")
        )
        await ensure_welcome_panel(self)

    async def on_message(self, message: discord.Message):
        await self.process_commands(message)
        if message.author.bot:
            return
        if isinstance(message.channel, discord.DMChannel):
            await handle_dm_message(self, message)

    async def on_member_remove(self, member: discord.Member):
        # Nettoyage quand quelqu’un quitte
        await full_profile_reset(member.guild, member.id, reason="Départ du serveur")


# ================================================================
# 🌹 LANCEMENT DU BOT
# ================================================================
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN manquant.")
bot = RencontreBot()
bot.run(DISCORD_TOKEN)
