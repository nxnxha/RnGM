# ================================================================
# 💞 Miri Rencontre — Bot Discord (Luxury Edition)
# ================================================================
import os, re, json, asyncio, time, tempfile, shutil, random
from datetime import datetime, timedelta, timezone
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
GUILD_ID      = env_int("GUILD_ID",      1382730341944397967)
ROLE_ACCESS   = env_int("ROLE_ACCESS",   1401403405729267762)
CH_GIRLS      = env_int("CH_GIRLS",      1400520391793053841)
CH_BOYS       = env_int("CH_BOYS",       1400520396557521058)
CH_SPEED      = env_int("CH_SPEED",      1402665906546413679)
CH_LOGS       = env_int("CH_LOGS",       1403154919913033728)
CH_WELCOME    = env_int("CH_WELCOME",    1400808431941849178)
DATA_FILE     = os.getenv("DATA_FILE", "rencontre_data.json")
BACKUPS_TO_KEEP = env_int("BACKUPS_TO_KEEP", 3)
BRAND_COLOR   = 0x5C1A1A
TZ = ZoneInfo("Europe/Paris")

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
        self.data: Dict[str, Any] = {
            "profiles": {}, "profile_msgs": {}, "first_msg_counts": {},
            "likes": {}, "passes": {}, "matches": [],
            "speed_perms": {"roles": [], "users": []},
            "welcome_panel": None, "banned_users": [],
            "speed_last_run": 0.0, "speed_signups": [],
            "speed_panel": None, "owners": [],
            "delete_threads_after_hours": 0
        }
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path,"r",encoding="utf-8") as f:
                    d=json.load(f)
                    self.data.update(d)
            except Exception:
                pass

    async def save(self):
        async with self._lock:
            tmp_fd, tmp_path = tempfile.mkstemp(prefix="rencontre_", suffix=".json")
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.path)

    def get_profile(self, uid:int): return self.data["profiles"].get(str(uid))
    async def set_profile(self, uid:int, prof:Dict[str,Any]):
        self.data["profiles"][str(uid)] = prof; await self.save()

    def get_profile_msg(self, uid:int): return self.data["profile_msgs"].get(str(uid))
    def set_profile_msg(self, uid:int, cid:int, mid:int):
        self.data["profile_msgs"][str(uid)] = {"channel_id": cid, "message_id": mid}
        try: open(self.path,"w").write(json.dumps(self.data, indent=2))
        except: pass

    async def delete_profile_everywhere(self, uid:int):
        self.data["profiles"].pop(str(uid), None)
        self.data["likes"].pop(str(uid), None)
        self.data["passes"].pop(str(uid), None)
        self.data["profile_msgs"].pop(str(uid), None)
        await self.save()

storage = Storage(DATA_FILE)

# -------------------- UTILS --------------------
def now_ts(): return datetime.now(TZ).strftime("[%d/%m/%Y %H:%M]")
def _clean(v, fallback="—"): return (v or "").strip() or fallback

def log_embed(title:str, desc:str):
    return discord.Embed(title=title, description=desc, color=BRAND_COLOR, timestamp=datetime.now(timezone.utc))

def log_line(guild: Optional[discord.Guild], text:str):
    if not guild or not CH_LOGS: return
    ch = guild.get_channel(CH_LOGS)
    if isinstance(ch, discord.TextChannel):
        asyncio.create_task(ch.send(embed=log_embed("📜 Log Rencontre", f"{now_ts()} {text}")))

async def _remove_access_role(guild: discord.Guild, member: Optional[discord.Member]):
    if not (guild and member and ROLE_ACCESS): return
    role = guild.get_role(ROLE_ACCESS)
    if role and role in member.roles:
        try: await member.remove_roles(role, reason="Reset profil Rencontre")
        except: pass

async def full_profile_reset(guild: discord.Guild, user_id: int, reason="Reset profil"):
    ref = storage.get_profile_msg(user_id)
    await storage.delete_profile_everywhere(user_id)
    if ref:
        ch = guild.get_channel(ref["channel_id"])
        if isinstance(ch, discord.TextChannel):
            try:
                msg = await ch.fetch_message(ref["message_id"])
                await msg.delete()
            except: pass
    member = guild.get_member(user_id)
    await _remove_access_role(guild, member)
    log_line(guild, f"🧹 Profil supprimé pour {user_id} — {reason}")

# -------------------- EMBEDS --------------------
def build_profile_embed(member: discord.Member, prof: Dict[str, Any]) -> discord.Embed:
    e = discord.Embed(
        title=f"{member.display_name}",
        description="Une rencontre qui mêle élégance et passion 💫",
        color=BRAND_COLOR
    )
    if _clean(prof.get("photo_url"), ""):
        e.set_thumbnail(url=prof["photo_url"])
    e.set_author(name=str(member), icon_url=member.display_avatar.url)
    e.add_field(name="Âge", value=f"{prof.get('age', '—')} ans", inline=True)
    e.add_field(name="Genre", value=_clean(prof.get("genre")), inline=True)
    e.add_field(name="Attirance", value=_clean(prof.get("orientation")), inline=True)
    e.add_field(name="Passions", value=f"_{_clean(prof.get('passions'))}_", inline=False)
    e.add_field(name="Activité", value=f"_{_clean(prof.get('activite'))}_", inline=False)
    e.set_footer(text="Miri Rencontre • Laissez la magie opérer ✨")
    e.timestamp = datetime.now(timezone.utc)
    return e

def build_speed_panel_embed(guild: Optional[discord.Guild]) -> discord.Embed:
    count = len(storage.data.get("speed_signups", []))
    e = discord.Embed(
        title="💞 Inscription Soirée Speed Dating",
        description=(
            "Bienvenue dans l’univers **Miri Rencontre**.\n"
            "Cliquez sur **Je participe** pour rejoindre la prochaine soirée.\n\n"
            "💬 Des rencontres vraies, des échanges sincères, et peut-être plus...\n"
            f"✨ **Inscriptions actuelles :** {count}"
        ),
        color=BRAND_COLOR
    )
    if guild and guild.icon:
        e.set_author(name=guild.name, icon_url=guild.icon.url)
    e.set_footer(text="Miri Rencontre • Laissez la magie opérer ✨")
    e.timestamp = datetime.now(timezone.utc)
    return e

# -------------------- THREAD CLEAN --------------------
async def delete_threads_later(threads: List[discord.Thread], delay_hours: int = 24):
    await asyncio.sleep(delay_hours * 3600)
    for th in threads:
        try: await th.delete(reason=f"Suppression automatique après {delay_hours} h")
        except: pass

# -------------------- EMBED EVENTS --------------------
async def send_event_announcement(guild: discord.Guild, author: discord.Member, duration_str: str, couples: int):
    ch = guild.get_channel(CH_SPEED)
    if not isinstance(ch, discord.TextChannel): return
    e = discord.Embed(
        title="🌹 Soirée Speed Dating • C’est parti !",
        description=(
            f"✨ L'événement commence !\n\n"
            f"⏰ **Durée :** {duration_str}\n"
            f"👥 **Participants :** {couples * 2 if couples > 0 else '—'}\n\n"
            "Faites des rencontres sincères et laissez parler le feeling 💞"
        ),
        color=BRAND_COLOR
    )
    e.set_footer(text=f"Lancé par {author.display_name} • Bonne soirée ✨")
    e.timestamp = datetime.now(timezone.utc)
    await ch.send(embed=e)

async def send_event_closure(guild: discord.Guild, threads_count: int):
    ch = guild.get_channel(CH_SPEED)
    if not isinstance(ch, discord.TextChannel): return
    e = discord.Embed(
        title="🎆 Fin de soirée",
        description=(
            f"Merci à toutes et tous d’avoir participé 💖\n\n"
            f"✨ **{threads_count}** conversations ont eu lieu ce soir.\n"
            "Rendez-vous bientôt pour une nouvelle édition de **Miri Rencontre** 💫"
        ),
        color=0x3B0A0A
    )
    e.set_footer(text="Miri Rencontre • La soirée s’achève, mais les liens restent 💞")
    e.timestamp = datetime.now(timezone.utc)
    await ch.send(embed=e)
# ================================================================
# 💼 COMMANDES ET COGS
# ================================================================

# -------------------- VIEWS --------------------
class ProfileView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=None)
        self.owner_id = owner_id

    @discord.ui.button(emoji="❤️", style=discord.ButtonStyle.success, custom_id="pf_like")
    async def like_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.owner_id:
            await interaction.response.send_message("🤨 Tu ne peux pas te liker toi-même.", ephemeral=True)
            return

        anim = discord.Embed(
            description="💞 Une connexion se crée... peut-être un match ?",
            color=BRAND_COLOR
        )
        await interaction.response.send_message(embed=anim, ephemeral=True)

        # gestion du like
        is_match = False
        storage.data.setdefault("likes", {})
        user_likes = storage.data["likes"].setdefault(str(interaction.user.id), [])
        if str(self.owner_id) not in user_likes:
            user_likes.append(str(self.owner_id))
        else:
            await interaction.edit_original_response(content="❤️ Déjà liké !")
            return
        target_likes = storage.data["likes"].get(str(self.owner_id), [])
        if str(interaction.user.id) in target_likes:
            is_match = True
            storage.data.setdefault("matches", []).append([str(interaction.user.id), str(self.owner_id)])
        await storage.save()
        log_line(interaction.guild, f"❤️ Like : {interaction.user} → {self.owner_id}")

        # match
        if is_match:
            a = interaction.guild.get_member(interaction.user.id)
            b = interaction.guild.get_member(self.owner_id)
            for m1, m2 in [(a, b), (b, a)]:
                try:
                    dm = await m1.create_dm()
                    await dm.send(embed=discord.Embed(
                        title="💘 C’est un match !",
                        description=f"Toi et **{m2.display_name}** avez liké vos profils mutuellement 💞\n\n"
                                    "Commencez à discuter et laissez la magie opérer ✨",
                        color=BRAND_COLOR
                    ))
                except Exception:
                    pass
            log_line(interaction.guild, f"🔥 Match : {a} ❤️ {b}")

    @discord.ui.button(emoji="❌", style=discord.ButtonStyle.secondary, custom_id="pf_pass")
    async def pass_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("👌 C’est noté.", ephemeral=True)
        storage.data.setdefault("passes", {})
        storage.data["passes"].setdefault(str(interaction.user.id), []).append(str(self.owner_id))
        await storage.save()
        log_line(interaction.guild, f"❌ Pass : {interaction.user} → {self.owner_id}")

    @discord.ui.button(emoji="📩", style=discord.ButtonStyle.primary, custom_id="pf_contact")
    async def contact_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        class ContactModal(discord.ui.Modal, title="Premier message"):
            def __init__(self, target_id: int):
                super().__init__(timeout=300)
                self.target_id = target_id
                self.msg = discord.ui.TextInput(
                    label="Ton message (premier contact)",
                    style=discord.TextStyle.paragraph,
                    min_length=5,
                    max_length=500
                )
                self.add_item(self.msg)

            async def on_submit(self, inter: discord.Interaction):
                author = inter.user
                target = inter.guild.get_member(self.target_id)
                if not target:
                    await inter.response.send_message("❌ Utilisateur introuvable.", ephemeral=True)
                    return
                try:
                    dm = await target.create_dm()
                    await dm.send(f"**{author.display_name}** souhaite te contacter 💌 :\n> {self.msg.value}")
                    await inter.response.send_message("✅ Message envoyé !", ephemeral=True)
                    log_line(inter.guild, f"📨 Contact : {author} → {target}")
                except Exception:
                    await inter.response.send_message("⚠️ Impossible d’envoyer le message (DM fermés ?)", ephemeral=True)

        await interaction.response.send_modal(ContactModal(target_id=self.owner_id))

    @discord.ui.button(emoji="🗑️", style=discord.ButtonStyle.danger, custom_id="pf_delete")
    async def del_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator and interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Tu ne peux pas supprimer ce profil.", ephemeral=True)
            return
        await interaction.response.send_message("🗑️ Suppression du profil...", ephemeral=True)
        await full_profile_reset(interaction.guild, self.owner_id, reason="Suppression via bouton")
        await interaction.edit_original_response(content="✅ Profil supprimé et rôle retiré.")

# -------------------- COGS --------------------
class OwnersCog(commands.Cog):
    def __init__(self, bot): self.bot = bot
    group = app_commands.Group(name="owners", description="Gérer les owners du bot", guild_ids=[GUILD_ID])

    @group.command(name="add")
    @app_commands.checks.has_permissions(administrator=True)
    async def add(self, interaction, user: discord.Member):
        storage.data["owners"].append(user.id)
        await storage.save()
        await interaction.response.send_message(f"✅ {user.display_name} ajouté comme owner.", ephemeral=True)

    @group.command(name="remove")
    @app_commands.checks.has_permissions(administrator=True)
    async def remove(self, interaction, user: discord.Member):
        if user.id in storage.data["owners"]:
            storage.data["owners"].remove(user.id)
            await storage.save()
        await interaction.response.send_message(f"🗑️ {user.display_name} retiré des owners.", ephemeral=True)

    @group.command(name="list")
    async def list(self, interaction):
        owners = storage.data.get("owners", [])
        if not owners:
            await interaction.response.send_message("Aucun owner défini.", ephemeral=True)
            return
        mentions = [interaction.guild.get_member(i).mention if interaction.guild.get_member(i) else f"`{i}`" for i in owners]
        await interaction.response.send_message("**Owners :** " + ", ".join(mentions), ephemeral=True)

# -------------------- SETTINGS --------------------
class RencontreSettingsCog(commands.Cog):
    def __init__(self, bot): self.bot = bot
    settings_group = app_commands.Group(
        name="rencontresettings",
        description="Configurer les paramètres du bot Miri Rencontre",
        guild_ids=[GUILD_ID]
    )

    @settings_group.command(name="delaythreads", description="Changer le délai avant suppression des threads (0 = immédiat)")
    @app_commands.describe(heures="Nombre d'heures avant suppression auto (0 = immédiat)")
    @app_commands.checks.has_permissions(administrator=True)
    async def delaythreads(self, interaction: discord.Interaction, heures: int):
        if heures < 0:
            await interaction.response.send_message("❌ Le délai ne peut pas être négatif.", ephemeral=True)
            return
        storage.data["delete_threads_after_hours"] = heures
        await storage.save()
        msg = f"🕓 Les threads seront supprimés **après {heures} h**." if heures > 0 else "💨 Suppression **immédiate** activée."
        await interaction.response.send_message(msg, ephemeral=True)
        log_line(interaction.guild, f"⚙️ Paramètre modifié : delaythreads = {heures} h")
# ================================================================
# 💖 DM, EVENTS & BOT PRINCIPAL
# ================================================================

async def publish_or_update_profile(guild: discord.Guild, member: discord.Member, prof: Dict[str, Any]):
    view = ProfileView(owner_id=member.id)
    embed = build_profile_embed(member, prof)
    ref = storage.get_profile_msg(member.id)
    ch = guild.get_channel(CH_GIRLS) if (prof.get("genre", "").lower().startswith("f")) else guild.get_channel(CH_BOYS)

    if ref:
        try:
            msg = await guild.get_channel(ref["channel_id"]).fetch_message(ref["message_id"])
            await msg.edit(embed=embed, view=view)
            return
        except Exception:
            pass
    if isinstance(ch, discord.TextChannel):
        msg = await ch.send(embed=embed, view=view)
        storage.set_profile_msg(member.id, ch.id, msg.id)

# ================================================================
# 🎉 SPEED DATING
# ================================================================
class SpeedCog(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="speeddating", description="Organiser une soirée speed dating")
    @app_commands.guilds(GUILD_OBJ)
    @app_commands.describe(couples="Nombre de couples", duree="Durée totale (ex: 15m, 30m, 1h)")
    async def speeddating(self, interaction: discord.Interaction, couples: int = 5, duree: str = "15m"):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ Tu n’es pas autorisé(e) à lancer une soirée.", ephemeral=True)
            return

        if not CH_SPEED:
            await interaction.response.send_message("⚠️ Salon speed introuvable.", ephemeral=True)
            return

        speed_ch = interaction.guild.get_channel(CH_SPEED)
        if not isinstance(speed_ch, discord.TextChannel):
            await interaction.response.send_message("⚠️ Salon speed invalide.", ephemeral=True)
            return

        signups = storage.data.get("speed_signups", [])
        if len(signups) < 2:
            await interaction.response.send_message("👥 Pas assez d'inscrits pour lancer une soirée.", ephemeral=True)
            return

        total_seconds = 60 * int(re.sub(r"[^0-9]", "", duree) or "10")
        nice_duration = duree
        random.shuffle(signups)
        pairs = [signups[i:i+2] for i in range(0, min(len(signups), couples * 2), 2)]
        created_threads = []

        await send_event_announcement(interaction.guild, interaction.user, nice_duration, len(pairs))

        for duo in pairs:
            if len(duo) < 2: continue
            a = interaction.guild.get_member(int(duo[0]))
            b = interaction.guild.get_member(int(duo[1]))
            if not a or not b: continue
            try:
                thread = await speed_ch.create_thread(
                    name=f"💬 {a.display_name} × {b.display_name}",
                    type=discord.ChannelType.private_thread,
                    invitable=False
                )
                await thread.add_user(a)
                await thread.add_user(b)
                await thread.send(f"Bienvenue {a.mention} et {b.mention} 💞\nVous avez **{nice_duration}** ⏳\nSoyez vous-même !")
                created_threads.append(thread)
            except Exception:
                pass

        await interaction.response.send_message(f"✅ **{len(created_threads)}** conversations lancées pour {nice_duration}.", ephemeral=True)
        await asyncio.sleep(total_seconds)

        # gestion de la suppression / archivage
        delay_hours = storage.data.get("delete_threads_after_hours", 0)
        if delay_hours > 0:
            asyncio.create_task(delete_threads_later(created_threads, delay_hours=delay_hours))
        else:
            for th in created_threads:
                try:
                    await th.delete(reason="Fin du Speed Dating - suppression auto")
                except Exception:
                    pass

        await send_event_closure(interaction.guild, len(created_threads))

# ================================================================
# 📬 BOT PRINCIPAL
# ================================================================
class RencontreBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.synced = False

    async def setup_hook(self):
        await self.add_cog(OwnersCog(self))
        await self.add_cog(RencontreSettingsCog(self))
        await self.add_cog(SpeedCog(self))
        self.add_view(ProfileView(owner_id=0))

    async def on_ready(self):
        if not self.synced:
            try:
                await self.tree.sync(guild=GUILD_OBJ)
                self.synced = True
                print(f"[SYNC] Commandes synchronisées sur {GUILD_ID}")
            except Exception as e:
                print(f"[SYNC FAIL] {e}")

        print(f"✅ Connecté en tant que {self.user} (id={self.user.id})")
        await self.change_presence(status=discord.Status.online, activity=discord.Game("Miri Rencontre 💞"))

    async def on_message(self, message: discord.Message):
        await self.process_commands(message)
        if message.author.bot or message.guild: return

        uid = message.author.id
        sess = storage.data.get("dm_sessions", {}).get(str(uid))
        if not sess:
            return

# ================================================================
# 🚀 LANCEMENT
# ================================================================
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN manquant dans l'environnement.")
bot = RencontreBot()
bot.run(DISCORD_TOKEN)
