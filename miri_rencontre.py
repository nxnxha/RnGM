
# ================================================================
# 🌹 MIRI RENCONTRE — BOT DISCORD COMPLET (Final Downloadable)
# ================================================================
# Caractéristiques principales :
# - Panneau d’accueil automatique (sombre & épuré) avec bouton "Créer mon profil"
# - Création de profil en DM (âge, genre, attirance, passions, activité, photo)
# - Affichage de profils avec embed stylé + boutons emoji-only persistants (❤️ ❌ 📩 🗑️)
# - Animation douce sur le like
# - Bouton 📩 via MODAL pour envoyer un premier message (DM) + logs détaillés (qui → qui + extrait)
# - Suppression de profil retire aussi le rôle d’accès
# - Logs élégants (embeds colorés) pour toutes les interactions
# - Speed Dating : création de threads privés par paires, alerte -1 min, suppression/archivage fin, rapport embed
# - Commandes claires : /rencontre_help /rencontre_info /rencontre_stats /setcooldown /owners /rencontreban /speeddating
# - Aucune pollution de logs lors des leaves (nettoyage silencieux)
#
# Dépendances : discord.py 2.4+ (pip install -U discord.py)
# Variables d’environnement requises : DISCORD_TOKEN, GUILD_ID, ROLE_ACCESS, CH_GIRLS, CH_BOYS, CH_SPEED, CH_LOGS, CH_WELCOME
# ================================================================

import os, re, json, asyncio, time, random
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
GUILD_ID      = env_int("GUILD_ID",      1382730341944397967)
ROLE_ACCESS   = env_int("ROLE_ACCESS",   1401403405729267762)
CH_GIRLS      = env_int("CH_GIRLS",      1400520391793053841)
CH_BOYS       = env_int("CH_BOYS",       1400520396557521058)
CH_SPEED      = env_int("CH_SPEED",      1402665906546413679)
CH_LOGS       = env_int("CH_LOGS",       1403154919913033728)
CH_WELCOME    = env_int("CH_WELCOME",    1400808431941849178)

DATA_FILE     = os.getenv("DATA_FILE", "rencontre_data.json")
BRAND_COLOR   = 0x7C3AED
TZ = ZoneInfo("Europe/Paris")

# Cooldowns par défaut (secondes) — modifiables par /setcooldown
LIKE_COOLDOWN_DEFAULT    = 600
CONTACT_COOLDOWN_DEFAULT = 600

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

GUILD_OBJ = discord.Object(id=GUILD_ID)

# ================================================================
# STORAGE
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
            "welcome_panel": None,
            "like_cooldown": LIKE_COOLDOWN_DEFAULT,
            "contact_cooldown": CONTACT_COOLDOWN_DEFAULT,
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

    # Profils
    def get_profile(self, uid: int) -> Optional[Dict[str, Any]]:
        return self.data["profiles"].get(str(uid))

    async def set_profile(self, uid: int, profile: Dict[str, Any]):
        self.data["profiles"][str(uid)] = profile
        await self.save()

    def get_profile_msg(self, uid: int) -> Optional[Dict[str, int]]:
        return self.data["profile_msgs"].get(str(uid))

    def set_profile_msg(self, uid: int, ch_id: int, msg_id: int):
        self.data["profile_msgs"][str(uid)] = {"channel_id": ch_id, "message_id": msg_id}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    async def delete_profile_data(self, uid: int):
        self.data["profiles"].pop(str(uid), None)
        self.data["profile_msgs"].pop(str(uid), None)
        await self.save()

    # Bans / Owners
    def is_banned(self, uid: int) -> bool:
        return uid in self.data.get("banned_users", [])

    async def ban(self, uid: int):
        if uid not in self.data["banned_users"]:
            self.data["banned_users"].append(uid)
            await self.save()

    async def unban(self, uid: int):
        if uid in self.data["banned_users"]:
            self.data["banned_users"].remove(uid)
            await self.save()

    def list_bans(self) -> List[int]:
        return self.data.get("banned_users", [])

    def is_owner(self, uid: int) -> bool:
        return uid in self.data.get("owners", [])

    async def add_owner(self, uid: int):
        if uid not in self.data["owners"]:
            self.data["owners"].append(uid)
            await self.save()

    async def remove_owner(self, uid: int):
        if uid in self.data["owners"]:
            self.data["owners"].remove(uid)
            await self.save()

storage = Storage(DATA_FILE)
LIKE_COOLDOWN    = int(storage.data.get("like_cooldown", LIKE_COOLDOWN_DEFAULT))
CONTACT_COOLDOWN = int(storage.data.get("contact_cooldown", CONTACT_COOLDOWN_DEFAULT))

# ================================================================
# UTILS & LOGS
# ================================================================
def now_str() -> str:
    return datetime.now(TZ).strftime("%d/%m/%Y %H:%M")

async def send_log_embed(
    guild: discord.Guild,
    action: str,
    details: str,
    user: Optional[discord.Member | discord.User] = None,
    color: Optional[int] = None
):
    if not guild or not CH_LOGS:
        return
    ch = guild.get_channel(CH_LOGS)
    if not isinstance(ch, discord.TextChannel):
        return
    e = discord.Embed(
        title=f"📘 {action}",
        description=details,
        color=color or BRAND_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    e.set_footer(text="Miri Rencontre • Journal des événements")
    if user:
        e.set_author(name=str(user), icon_url=user.display_avatar.url)
    try:
        await ch.send(embed=e)
    except Exception:
        pass

async def _remove_access_role(guild: discord.Guild, member: Optional[discord.Member]):
    if not (guild and member and ROLE_ACCESS):
        return
    role = guild.get_role(ROLE_ACCESS)
    if role and role in member.roles:
        try:
            await member.remove_roles(role, reason="Suppression du profil Rencontre")
        except Exception:
            pass

async def full_profile_reset(
    guild: discord.Guild,
    uid: int,
    reason: str = "Suppression profil",
    do_log: bool = True
):
    ref = storage.get_profile_msg(uid)
    await storage.delete_profile_data(uid)
    if ref:
        ch = guild.get_channel(ref["channel_id"])
        if isinstance(ch, discord.TextChannel):
            try:
                msg = await ch.fetch_message(ref["message_id"])
                await msg.delete()
            except Exception:
                pass
    member = guild.get_member(uid)
    await _remove_access_role(guild, member)
    if do_log:
        await send_log_embed(guild, "Profil supprimé", f"Profil supprimé ({reason})", member, 0xF43F5E)

def parse_duration_to_seconds(s: str) -> int:
    s = (s or "").strip().lower().replace(" ", "")
    if not s: return 5*60
    if re.fullmatch(r"\d+", s): return max(60, int(s)*60)
    m = re.fullmatch(r"(\d+)h(\d+)?m?$", s)
    if m: return max(60, int(m.group(1))*3600 + int(m.group(2) or 0)*60)
    m2 = re.fullmatch(r"(\d+)m(in)?$", s)
    if m2: return max(60, int(m2.group(1))*60)
    return 5*60

# ================================================================
# EMBEDS / VIEWS
# ================================================================
def build_profile_embed(member: discord.Member, prof: Dict[str, Any]) -> discord.Embed:
    e = discord.Embed(
        title=f"{member.display_name}",
        description="💞 Profil Rencontre — Miri",
        color=BRAND_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    e.add_field(name="Âge",        value=str(prof.get("age", "—")), inline=True)
    e.add_field(name="Genre",      value=prof.get("genre", "—"), inline=True)
    e.add_field(name="Attirance",  value=prof.get("orientation", "—"), inline=True)
    e.add_field(name="Passions",   value=prof.get("passions", "—"), inline=False)
    e.add_field(name="Activité",   value=prof.get("activite", "—"), inline=False)
    if prof.get("photo_url"):
        e.set_thumbnail(url=prof["photo_url"])
    e.set_footer(text="Miri Rencontre • Connecte-toi 🌹")
    return e

def target_channel_for(guild: discord.Guild, prof: Dict[str, Any]) -> Optional[discord.TextChannel]:
    gender = (prof.get("genre") or "").strip().lower()
    return guild.get_channel(CH_GIRLS) if gender.startswith("f") else guild.get_channel(CH_BOYS)

async def publish_or_update_profile(guild: discord.Guild, member: discord.Member, prof: Dict[str, Any]):
    embed = build_profile_embed(member, prof)
    view = ProfileView(owner_id=member.id)
    ref = storage.get_profile_msg(member.id)
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

# Cooldowns mémoire
like_cooldowns: Dict[Tuple[int, int], float]    = {}
contact_cooldowns: Dict[Tuple[int, int], float] = {}

# --------- Modal de contact ---------
class ContactModal(discord.ui.Modal, title="💌 Premier message"):
    def __init__(self, target_id: int):
        super().__init__(timeout=300)
        self.target_id = target_id
        self.message = discord.ui.TextInput(
            label="Ton message (max 300 caractères)",
            style=discord.TextStyle.paragraph,
            max_length=300,
            required=True,
            placeholder="Dis quelque chose de sympa et respectueux 💞"
        )
        self.add_item(self.message)

    async def on_submit(self, inter: discord.Interaction):
        author = inter.user
        guild: Optional[discord.Guild] = inter.guild
        if not guild:
            await inter.response.send_message("⚠️ Utilisable sur le serveur.", ephemeral=True)
            return
        target = guild.get_member(self.target_id)
        if not target:
            await inter.response.send_message("⚠️ Membre introuvable.", ephemeral=True)
            return

        content = self.message.value.strip()
        if not content:
            await inter.response.send_message("⚠️ Message vide.", ephemeral=True)
            return

        # Envoi DM
        sent_ok = False
        try:
            dm = await target.create_dm()
            txt = (
                f"💌 **{author.display_name}** souhaite te parler !\n"
                f"🗨️ “{content}”\n\n"
                f"❤️ Tu peux répondre directement à ce message."
            )
            await dm.send(txt)
            sent_ok = True
        except Exception:
            sent_ok = False

        if sent_ok:
            await inter.response.send_message("📨 Message envoyé avec succès 💞", ephemeral=True)
            excerpt = (content[:180] + "…") if len(content) > 180 else content
            await send_log_embed(
                guild,
                "Contact envoyé",
                f"👤 {author.mention} → <@{self.target_id}>\n✉️ “{excerpt}”",
                user=author,
                color=0x3B82F6
            )
        else:
            await inter.response.send_message("⚠️ Impossible d’envoyer le DM (DM fermés ?).", ephemeral=True)

class ProfileView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=None)
        self.owner_id = owner_id

    def _check_cd(self, store: Dict[Tuple[int,int], float], user_id: int, cooldown: int) -> bool:
        key = (user_id, self.owner_id)
        now = time.time()
        if key in store and now - store[key] < cooldown:
            return False
        store[key] = now
        return True

    @discord.ui.button(emoji="❤️", style=discord.ButtonStyle.success, custom_id="profile_like")
    async def like(self, inter: discord.Interaction, btn: discord.ui.Button):
        if inter.user.id == self.owner_id:
            await inter.response.send_message("💡 Tu ne peux pas te liker toi-même.", ephemeral=True); return
        if not self._check_cd(like_cooldowns, inter.user.id, int(storage.data.get("like_cooldown", LIKE_COOLDOWN))):
            await inter.response.send_message("⏳ Attends un peu avant de reliker ❤️", ephemeral=True); return

        # Animation
        await inter.response.defer(ephemeral=True)
        try:
            msg = await inter.followup.send("💞 Une connexion se crée...", ephemeral=True)
            await asyncio.sleep(1.2)
            await msg.edit(content="🌹 Sentiment partagé ou simple curiosité ? Le temps nous le dira.")
            await asyncio.sleep(1.2)
            await msg.edit(content="❤️ Like enregistré.")
        except Exception:
            await inter.followup.send("❤️ Like enregistré.", ephemeral=True)

        await send_log_embed(inter.guild, "Like", f"{inter.user.mention} a liké <@{self.owner_id}>", inter.user, 0xF472B6)

    @discord.ui.button(emoji="❌", style=discord.ButtonStyle.secondary, custom_id="profile_pass")
    async def _pass(self, inter: discord.Interaction, btn: discord.ui.Button):
        if inter.user.id == self.owner_id:
            await inter.response.send_message("🙃 Tu ne peux pas passer sur toi-même.", ephemeral=True); return
        await inter.response.send_message("👌 C’est noté.", ephemeral=True)
        await send_log_embed(inter.guild, "Pass", f"{inter.user.mention} a passé <@{self.owner_id}>", inter.user, 0x9CA3AF)

    @discord.ui.button(emoji="📩", style=discord.ButtonStyle.primary, custom_id="profile_contact")
    async def contact(self, inter: discord.Interaction, btn: discord.ui.Button):
        if inter.user.id == self.owner_id:
            await inter.response.send_message("🙃 Pas toi-même.", ephemeral=True); return
        # Cooldown contact
        if not self._check_cd(contact_cooldowns, inter.user.id, int(storage.data.get("contact_cooldown", CONTACT_COOLDOWN))):
            await inter.response.send_message("⏳ Attends un peu avant d’envoyer un nouveau message 💌", ephemeral=True); return
        # Ouvre le modal
        await inter.response.send_modal(ContactModal(target_id=self.owner_id))

    @discord.ui.button(emoji="🗑️", style=discord.ButtonStyle.danger, custom_id="profile_delete")
    async def delete(self, inter: discord.Interaction, btn: discord.ui.Button):
        if inter.user.id != self.owner_id and not inter.user.guild_permissions.administrator and not storage.is_owner(inter.user.id):
            await inter.response.send_message("❌ Tu ne peux pas supprimer ce profil.", ephemeral=True); return
        await full_profile_reset(inter.guild, self.owner_id, "Suppression via bouton", do_log=True)
        await inter.response.send_message("✅ Profil supprimé avec succès.", ephemeral=True)

# Accueil
dm_sessions: Dict[int, Dict[str, Any]] = {}

async def _send_next_step(dm_ch: discord.DMChannel, uid: int):
    step = dm_sessions[uid]["step"]
    prompts = [
        "Quel est **ton âge** ? (nombre ≥ 18)",
        "Ton **genre** ? (Femme / Homme)",
        "Ton **attirance** (orientation) ? (ex : hétéro, bi, pan…)",
        "Tes **passions** ? (quelques mots)",
        "Ton **activité** (ce que tu fais dans la vie) ?",
        "📸 Envoie une **photo** (fichier image) **ou** un **lien direct** (.png/.jpg/.webp).",
    ]
    if 0 <= step < len(prompts):
        await dm_ch.send(f"{step+1}/6 — {prompts[step]}")

class StartView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="✨ Créer mon profil", emoji="🌹", style=discord.ButtonStyle.success, custom_id="start_profile")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if storage.is_banned(interaction.user.id):
            await interaction.response.send_message("🚫 Tu n’as pas accès à l’espace Rencontre.", ephemeral=True); return
        await interaction.response.send_message("📩 Regarde tes **DM** pour commencer la création 💞", ephemeral=True)
        try:
            dm = await interaction.user.create_dm()
            await dm.send(
                embed=discord.Embed(
                    title="💞 Création de ton profil",
                    description="Réponds aux questions pas à pas. Tu peux écrire `stop` pour annuler.",
                    color=BRAND_COLOR
                )
            )
            dm_sessions[interaction.user.id] = {"step": 0, "answers": {}}
            await _send_next_step(dm, interaction.user.id)
        except Exception:
            await interaction.followup.send("⚠️ Impossible de t’écrire en DM (DM fermés ?).", ephemeral=True)

async def ensure_welcome_panel(bot: commands.Bot):
    if not CH_WELCOME: return
    guild = bot.get_guild(GUILD_ID)
    if not guild: return
    ch = guild.get_channel(CH_WELCOME)
    if not isinstance(ch, discord.TextChannel): return

    ref = storage.data.get("welcome_panel")
    if isinstance(ref, dict) and "message_id" in ref:
        try:
            await ch.fetch_message(ref["message_id"])
            return
        except Exception:
            pass

    embed = discord.Embed(
        title="🌙 Bienvenue dans **Miri Rencontre**",
        description=(
            "✨ **Découvre, partage, connecte.**\n\n"
            "Crée ton profil pour rencontrer de nouvelles personnes, liker, échanger et participer aux **soirées rencontre** 🥂\n\n"
            "⚠️ Réservé aux **18 ans et plus**.\n\n"
            "> 🌹 Clique sur le bouton ci-dessous pour commencer."
        ),
        color=discord.Color.dark_purple()
    )
    if guild.icon:
        embed.set_author(name=guild.name, icon_url=guild.icon.url)
    embed.set_footer(text="Miri Rencontre • Ensemble, ça matche 💞")
    msg = await ch.send(embed=embed, view=StartView())
    storage.data["welcome_panel"] = {"channel_id": ch.id, "message_id": msg.id}
    await storage.save()

# ================================================================
# SPEED DATING — Rapport embed
# ================================================================
async def send_speed_report_embed(
    guild: discord.Guild,
    organizer: discord.Member,
    couples: int,
    duration_str: str,
    created_threads: List[discord.Thread],
    started_at: datetime,
    closed_at: datetime,
):
    if not guild or not CH_LOGS: return
    ch = guild.get_channel(CH_LOGS)
    if not isinstance(ch, discord.TextChannel): return
    e = discord.Embed(
        title="🕊️ Rapport — Soirée Speed Dating",
        description=f"**Organisateur :** {organizer.mention}\n"
                    f"**Durée :** {duration_str}\n"
                    f"**Threads créés :** {len(created_threads)}",
        color=discord.Color.purple(),
        timestamp=datetime.now(timezone.utc),
    )
    e.add_field(name="🕒 Horaires", value=f"Début : {started_at.strftime('%d/%m/%Y %H:%M')}\nFin : {closed_at.strftime('%d/%m/%Y %H:%M')}", inline=False)
    if created_threads:
        lines = [f"• [{th.name}](https://discord.com/channels/{guild.id}/{th.id})" for th in created_threads[:10]]
        e.add_field(name="💬 Conversations", value="\n".join(lines), inline=False)
        if len(created_threads) > 10:
            e.add_field(name="…", value=f"+{len(created_threads)-10} threads supplémentaires", inline=False)
    e.set_footer(text="Miri Rencontre • Journal des événements")
    try: await ch.send(embed=e)
    except Exception: pass

# ================================================================
# COGS & COMMANDES
# ================================================================
class AdminCog(commands.Cog, name="Admin"):
    def __init__(self, bot: commands.Bot): self.bot = bot

    # Cooldowns
    @app_commands.command(name="setcooldown", description="Modifier le cooldown des interactions (admin)")
    @app_commands.describe(type="like ou contact", minutes="durée en minutes (min 1)")
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
            await inter.response.send_message("⚠️ Type invalide. Utilise `like` ou `contact`.", ephemeral=True); return
        await storage.save()
        await inter.response.send_message(f"✅ Cooldown `{type}` mis à **{minutes} min**.", ephemeral=True)
        await send_log_embed(inter.guild, "Configuration modifiée", f"{inter.user.mention} a mis `{type}` à **{minutes} min**.", inter.user, 0x7DD3FC)

    # Stats admin
    @app_commands.command(name="rencontre_stats", description="📊 Statistiques de l’Espace Rencontre (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def rencontre_stats(self, inter: discord.Interaction):
        total = len(storage.data.get("profiles", {}))
        published = len(storage.data.get("profile_msgs", {}))
        bans = len(storage.data.get("banned_users", []))
        e = discord.Embed(title="📊 Statistiques — Miri Rencontre", description="Aperçu global 💞", color=BRAND_COLOR, timestamp=datetime.now(timezone.utc))
        e.add_field(name="👥 Profils", value=f"• Total : **{total}**\n• Publiés : **{published}**\n• Bannis : **{bans}**", inline=False)
        e.add_field(name="⚙️ Paramètres", value=f"• ❤️ Like : **{storage.data.get('like_cooldown', LIKE_COOLDOWN)//60} min**\n• 💌 Contact : **{storage.data.get('contact_cooldown', CONTACT_COOLDOWN)//60} min**", inline=False)
        e.set_footer(text="Miri Rencontre • Dashboard Admin")
        await inter.response.send_message(embed=e, ephemeral=True)

    # Ban / Unban
    ban_group = app_commands.Group(name="rencontreban", description="Gérer l'accès Rencontre (admin)")

    @ban_group.command(name="add", description="🚫 Bannir un membre de la Rencontre")
    @app_commands.checks.has_permissions(administrator=True)
    async def ban_add(self, inter: discord.Interaction, user: discord.Member, raison: Optional[str] = None):
        await storage.ban(user.id)
        await full_profile_reset(inter.guild, user.id, reason="Ban rencontre", do_log=True)
        await inter.response.send_message(f"🚫 **{user.display_name}** banni de la Rencontre.", ephemeral=True)

    @ban_group.command(name="remove", description="✅ Débannir un membre")
    @app_commands.checks.has_permissions(administrator=True)
    async def ban_remove(self, inter: discord.Interaction, user: discord.Member):
        await storage.unban(user.id)
        await inter.response.send_message(f"✅ **{user.display_name}** débanni.", ephemeral=True)

    @ban_group.command(name="list", description="Voir la liste des bannis")
    async def ban_list(self, inter: discord.Interaction):
        ids = storage.list_bans()
        if not ids:
            await inter.response.send_message("Aucun membre banni.", ephemeral=True); return
        names = []
        for i in ids:
            m = inter.guild.get_member(i)
            names.append(m.mention if m else f"`{i}`")
        await inter.response.send_message("**Bannis Rencontre :** " + ", ".join(names), ephemeral=True)

    # Owners
    owners_group = app_commands.Group(name="owners", description="Gérer les propriétaires du bot")

    @owners_group.command(name="add", description="Ajouter un owner (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def owners_add(self, inter: discord.Interaction, user: discord.Member):
        await storage.add_owner(user.id)
        await inter.response.send_message(f"✅ **{user.display_name}** ajouté comme owner.", ephemeral=True)

    @owners_group.command(name="remove", description="Retirer un owner (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def owners_remove(self, inter: discord.Interaction, user: discord.Member):
        await storage.remove_owner(user.id)
        await inter.response.send_message(f"🗑️ **{user.display_name}** retiré des owners.", ephemeral=True)

    @owners_group.command(name="list", description="Lister les owners")
    async def owners_list(self, inter: discord.Interaction):
        ids = storage.data.get("owners", [])
        if not ids:
            await inter.response.send_message("Aucun owner défini.", ephemeral=True); return
        mentions = []
        for i in ids:
            m = inter.guild.get_member(i)
            mentions.append(m.mention if m else f"`{i}`")
        await inter.response.send_message("**Owners :** " + ", ".join(mentions), ephemeral=True)

    # SpeedDating
    @app_commands.command(
        name="speeddating",
        description="Créer des threads privés pour une soirée (participants via mentions)."
    )
    @app_commands.describe(
        participants="Mentionne les participants dans un texte (ex: @a @b @c …)",
        couples="Nombre maximum de couples (paires) à créer",
        duree="Durée : ex 20m, 30m, 1h, 1h30…",
        nom="Nom d’événement (préfixe des threads)",
        delete_after="Supprimer les threads à la fin (True/False)"
    )
    async def speeddating(
        self,
        inter: discord.Interaction,
        participants: str,
        couples: int = 5,
        duree: str = "20m",
        nom: Optional[str] = "Speed ⏳",
        delete_after: bool = True,
    ):
        u = inter.user
        if not (u.guild_permissions.administrator or u.guild_permissions.manage_channels or storage.is_owner(u.id)):
            await inter.response.send_message("❌ Tu n’es pas autorisé(e) à lancer une soirée.", ephemeral=True); return

        ch_speed = inter.guild.get_channel(CH_SPEED)
        if not isinstance(ch_speed, discord.TextChannel):
            await inter.response.send_message("❌ Salon Speed Dating introuvable (CH_SPEED).", ephemeral=True); return

        ids = [int(m) for m in re.findall(r"<@!?(\d+)>", participants)]
        uniq_ids = []
        for i in ids:
            if i not in uniq_ids: uniq_ids.append(i)
        members: List[discord.Member] = []
        for i in uniq_ids:
            m = inter.guild.get_member(i)
            if m and not storage.is_banned(m.id):
                members.append(m)

        if len(members) < 2:
            await inter.response.send_message("⚠️ Il faut au moins 2 participants éligibles.", ephemeral=True); return

        total_seconds = parse_duration_to_seconds(duree)
        mins = total_seconds // 60
        h, mn = mins // 60, mins % 60
        nice_duration = f"{h}h{mn:02d}" if h else f"{mn}m"

        random.shuffle(members)
        pairs: List[Tuple[discord.Member, discord.Member]] = []
        pool = members[:]
        while len(pairs) < couples and len(pool) >= 2:
            a = pool.pop()
            b = pool.pop()
            pairs.append((a, b))

        created_threads: List[discord.Thread] = []
        started_at = datetime.now(TZ)

        for a, b in pairs:
            name = f"{(nom or 'Speed ⏳').strip()} {a.display_name} × {b.display_name}"
            try:
                th = await ch_speed.create_thread(
                    name=name,
                    type=discord.ChannelType.private_thread,
                    invitable=False,
                    auto_archive_duration=60
                )
                await th.add_user(a); await th.add_user(b)
                await th.send(
                    f"Bienvenue {a.mention} et {b.mention} — vous avez **{nice_duration}** ⏳.\n"
                    f"Soyez respectueux·ses. Le fil sera **clôturé** à la fin."
                )
                created_threads.append(th)
            except Exception:
                continue

        await inter.response.send_message(f"✅ **{len(created_threads)}** threads créés pour **{nice_duration}**.", ephemeral=True)

        if total_seconds >= 120:
            try:
                await asyncio.sleep(total_seconds - 60)
                for th in created_threads:
                    try: await th.send("⏰ **Plus qu’1 minute** ! Échangez vos contacts si ça matche 💞")
                    except Exception: pass
                await asyncio.sleep(60)
            except Exception: pass
        else:
            await asyncio.sleep(total_seconds)

        closed_at = datetime.now(TZ)

        for th in created_threads:
            try:
                if delete_after:
                    await th.delete()
                else:
                    await th.edit(archived=True, locked=True)
            except Exception:
                pass

        await send_speed_report_embed(inter.guild, inter.user, couples, nice_duration, created_threads, started_at, closed_at)

class HelpCog(commands.Cog, name="Aide"):
    def __init__(self, bot: commands.Bot): self.bot = bot

    @app_commands.command(name="rencontre_help", description="Affiche l’aide du bot Rencontre")
    async def rencontre_help(self, inter: discord.Interaction):
        e = discord.Embed(
            title="🌹 Aide — Miri Rencontre",
            description="Commandes principales et rôles requis.",
            color=BRAND_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        e.add_field(
            name="👤 Utilisateurs",
            value="• Bouton **✨ Créer mon profil** dans le panneau d’accueil\n• Interagir avec les profils via ❤️ / ❌ / 📩 / 🗑️\n• `/rencontre_info` — infos publiques",
            inline=False
        )
        e.add_field(
            name="🛠️ Admins",
            value=(
                "• `/speeddating participants:<mentions> couples:<n> duree:<ex 30m> nom:<txt> delete_after:<bool>`\n"
                "• `/setcooldown like|contact <minutes>`\n"
                "• `/rencontre_stats`\n"
                "• `/rencontreban add/remove/list`\n"
                "• `/owners add/remove/list`"
            ),
            inline=False
        )
        e.set_footer(text="Miri Rencontre • Laissez la magie opérer ✨")
        await inter.response.send_message(embed=e, ephemeral=True)

class PublicInfoCog(commands.Cog, name="Infos"):
    def __init__(self, bot: commands.Bot): self.bot = bot

    @app_commands.command(name="rencontre_info", description="📖 Infos publiques de l’Espace Rencontre")
    async def rencontre_info(self, inter: discord.Interaction):
        total = len(storage.data.get("profiles", {}))
        published = len(storage.data.get("profile_msgs", {}))
        percent = round((published / total) * 100, 1) if total else 0
        e = discord.Embed(
            title="🌹 Miri Rencontre — Informations",
            description="✨ L’Espace Rencontre est ouvert à ceux qui cherchent de vraies connexions 💞",
            color=BRAND_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        e.add_field(name="💬 Activité", value=f"• Profils enregistrés : **{total}**\n• Profils publiés : **{published}**\n• Taux d’activité : **{percent}%**", inline=False)
        e.add_field(name="🕊️ Modération", value="Respect & bienveillance 🛡️", inline=False)
        e.set_footer(text="Miri Rencontre • Ensemble, ça matche ✨")
        await inter.response.send_message(embed=e, ephemeral=False)

# ================================================================
# BOT PRINCIPAL
# ================================================================
class RencontreBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.synced = False

    async def setup_hook(self):
        await self.add_cog(AdminCog(self))
        await self.add_cog(HelpCog(self))
        await self.add_cog(PublicInfoCog(self))
        # Views persistantes
        self.add_view(ProfileView(owner_id=0))
        self.add_view(StartView())

    async def on_ready(self):
        if not self.synced:
            try:
                await self.tree.sync(guild=GUILD_OBJ)
                self.synced = True
                print(f"[SYNC] Commandes guild synchronisées ({GUILD_ID})")
            except Exception as e:
                print(f"[SYNC FAIL] {e}")
        print(f"✅ Connecté comme {self.user} (id={self.user.id})")
        await self.change_presence(status=discord.Status.online, activity=discord.Game("Miri Rencontre 🌹"))
        await ensure_welcome_panel(self)

    async def on_message(self, message: discord.Message):
        await self.process_commands(message)
        if message.author.bot or message.guild is not None: return
        uid = message.author.id
        if uid not in dm_sessions: return
        sess = dm_sessions[uid]
        dm_ch: discord.DMChannel = message.channel
        content = (message.content or "").strip()

        if content.lower() == "stop":
            await dm_ch.send("🚫 Création annulée."); dm_sessions.pop(uid, None); return

        # Étapes DM
        if sess["step"] == 0:
            try:
                age = int(re.sub(r"\D+", "", content))
                if age < 18:
                    await dm_ch.send("🚫 Désolé, réservé aux **18+**."); dm_sessions.pop(uid, None); return
                sess["answers"]["age"] = age; sess["step"] = 1; await _send_next_step(dm_ch, uid)
            except Exception:
                await dm_ch.send("⚠️ Entre un nombre valide (ex: 22).")
            return

        if sess["step"] == 1:
            g = content.lower()
            if g.startswith("f"): sess["answers"]["genre"] = "Femme"
            elif g.startswith("h"): sess["answers"]["genre"] = "Homme"
            else: await dm_ch.send("⚠️ Réponds par **Femme** ou **Homme**."); return
            sess["step"] = 2; await _send_next_step(dm_ch, uid); return

        if sess["step"] == 2:
            sess["answers"]["orientation"] = content[:100] if content else "—"
            sess["step"] = 3; await _send_next_step(dm_ch, uid); return

        if sess["step"] == 3:
            sess["answers"]["passions"] = content[:200] if content else "—"
            sess["step"] = 4; await _send_next_step(dm_ch, uid); return

        if sess["step"] == 4:
            sess["answers"]["activite"] = content[:150] if content else "—"
            sess["step"] = 5; await _send_next_step(dm_ch, uid); return

        if sess["step"] == 5:
            photo_url = None
            if message.attachments:
                att = message.attachments[0]
                if att.content_type and att.content_type.startswith("image/"):
                    photo_url = att.url
            if not photo_url and content.startswith("http") and re.search(r"\.(png|jpe?g|gif|webp)(\?|$)", content, re.I):
                photo_url = content
            if not photo_url:
                await dm_ch.send("⚠️ Envoie une **image** ou un **lien direct** (.png/.jpg/.webp)."); return

            sess["answers"]["photo_url"] = photo_url
            profile = sess["answers"]
            await storage.set_profile(uid, profile)

            guild = self.get_guild(GUILD_ID)
            if guild:
                member = guild.get_member(uid)
                if member:
                    await publish_or_update_profile(guild, member, profile)
                    await send_log_embed(guild, "Création de profil", f"{member.mention} a créé son profil 💞", member, 0xA855F7)
                    if ROLE_ACCESS:
                        role = guild.get_role(ROLE_ACCESS)
                        if role and role not in member.roles:
                            try: await member.add_roles(role, reason="Profil Rencontre validé")
                            except Exception: pass

            dm_sessions.pop(uid, None)
            await dm_ch.send("✅ **Profil enregistré !** Il est maintenant visible sur le serveur 💞")
            return

    async def on_member_remove(self, member: discord.Member):
        # Nettoyage silencieux (aucun log de leave)
        try:
            await full_profile_reset(member.guild, member.id, reason="Départ du serveur", do_log=False)
        except Exception:
            pass

# ------------------------------------------------
# LANCEMENT
# ------------------------------------------------
if not DISCORD_TOKEN:
    raise RuntimeError("❌ DISCORD_TOKEN manquant dans l'environnement.")
bot = RencontreBot()
bot.run(DISCORD_TOKEN)
