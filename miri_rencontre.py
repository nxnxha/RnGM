# miri_rencontre.py — Miri Rencontre (DM pas-à-pas, stable, reset admin)
# ✔ Formulaire en DM pas-à-pas (pas de Modal en DM → fini “Échec de l’interaction”)
# ✔ ACK immédiat + edit (évite timeouts)
# ✔ Vues persistantes restaurées au boot
# ✔ /resetrencontre (admin), /resetprofil (user), /speeddating (staff)
# ✔ /creerprofil (user), /sync (admin)
# ✔ Tinder: Like / Pass / Match (+ DM)
# ✔ Logs horodatés [JJ/MM/AAAA HH:MM]
# ✔ Rôle Accès Rencontre ajouté en sécurité
# ✔ Slash commands scope serveur + sync agressive

import os
import re
import json
import asyncio
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
GUILD_ID      = env_int("GUILD_ID",      1382730341944397967)  # ton serveur
ROLE_ACCESS   = env_int("ROLE_ACCESS",   1401403405729267762)
CH_GIRLS      = env_int("CH_GIRLS",      1400520391793053841)
CH_BOYS       = env_int("CH_BOYS",       1400520396557521058)
CH_SPEED      = env_int("CH_SPEED",      1402665906546413679)
CH_LOGS       = env_int("CH_LOGS",       1403154919913033728)
CH_WELCOME    = env_int("CH_WELCOME",    1400808431941849178)
FIRST_MSG_LIMIT = env_int("FIRST_MSG_LIMIT", 1)
DATA_FILE     = os.getenv("DATA_FILE", "rencontre_data.json")
TZ = ZoneInfo("Europe/Paris")

# intents
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True  # lire les DM (photo/lien)

# -------------------- Storage --------------------
class Storage:
    def __init__(self, path: str):
        self.path = path
        self.data: Dict[str, Any] = {
            "profiles": {},
            "profile_msgs": {},
            "first_msg_counts": {},
            "likes": {},
            "passes": {},
            "matches": []
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

    # profiles
    def get_profile(self, uid: int) -> Optional[Dict[str, Any]]:
        return self.data["profiles"].get(str(uid))

    def set_profile(self, uid: int, prof: Dict[str, Any]):
        self.data["profiles"][str(uid)] = prof
        self.save()

    def delete_profile_everywhere(self, uid: int):
        # Profil et références
        self.data["profiles"].pop(str(uid), None)
        self.data["profile_msgs"].pop(str(uid), None)
        # Likes/Passes émis par l'utilisateur
        self.data["likes"].pop(str(uid), None)
        self.data["passes"].pop(str(uid), None)

        # Nettoyer les compteurs de 1er message (émetteur ou cible)
        fmc = self.data.get("first_msg_counts", {})
        to_del = [k for k in list(fmc.keys()) if k.startswith(f"{uid}:") or k.endswith(f":{uid}")]
        for k in to_del:
            fmc.pop(k, None)

        # Matches
        new_matches = []
        for a, b in self.data["matches"]:
            if int(a) != uid and int(b) != uid:
                new_matches.append([a, b])
        self.data["matches"] = new_matches
        self.save()

    # message refs
    def set_profile_msg(self, uid: int, channel_id: int, message_id: int):
        self.data["profile_msgs"][str(uid)] = {"channel_id": channel_id, "message_id": message_id}
        self.save()

    def get_profile_msg(self, uid: int) -> Optional[Dict[str, int]]:
        return self.data["profile_msgs"].get(str(uid))

    # anti-spam contact
    def inc_first_msg(self, author_id: int, target_id: int) -> int:
        key = f"{author_id}:{target_id}"
        val = self.data["first_msg_counts"].get(key, 0) + 1
        self.data["first_msg_counts"][key] = val
        self.save()
        return val

    # tinder
    def like(self, user_id: int, target_id: int) -> bool:
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

def log_line(guild: Optional[discord.Guild], text: str):
    if not guild or not CH_LOGS:
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

# -------------------- States --------------------
awaiting_photo: Dict[int, Dict[str, Any]] = {}   # uid -> {"profile":..., "is_edit": bool}
dm_sessions: Dict[int, Dict[str, Any]] = {}      # uid -> {step:int, is_edit:bool, answers:dict}

# -------------------- Views & Modals --------------------
class StartFormView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Créer mon profil", style=discord.ButtonStyle.success, custom_id="start_profile_btn")
    async def start_profile_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("⏳ J’ouvre un DM avec toi…", ephemeral=True)
        ok = True
        try:
            dm = await interaction.user.create_dm()
            await dm.send(
                embed=discord.Embed(
                    title="Création de ton profil — DM",
                    description=(
                        "On va remplir le formulaire en **privé**.\n\n"
                        "👉 Clique sur **Démarrer** ci-dessous, puis réponds aux questions.\n"
                        "Ensuite, **envoie une photo** (upload ou lien) dans ce DM.\n"
                        "Je publierai ton profil et je te donnerai le **rôle Accès Rencontre** ✅"
                    ),
                    color=discord.Color.purple()
                ),
                view=StartDMFormView(is_edit=False)
            )
        except Exception:
            ok = False

        try:
            await interaction.edit_original_response(
                content=("📩 C’est bon ! Regarde tes DM pour créer ton profil." if ok
                         else "⚠️ Impossible de t’écrire en DM (DM fermés ?).")
            )
        except Exception:
            pass

class StartDMFormView(discord.ui.View):
    def __init__(self, is_edit: bool):
        super().__init__(timeout=None)
        self.is_edit = is_edit

    @discord.ui.button(label="Démarrer", style=discord.ButtonStyle.primary, custom_id="start_dm_form")
    async def start_dm_form(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("✅ OK, on fait ça ici en DM. Réponds à mes questions ⤵️", ephemeral=True)
        uid = interaction.user.id
        dm_sessions[uid] = {"step": 0, "is_edit": self.is_edit, "answers": {}}
        await interaction.channel.send("1/5 — Quel est **ton âge** ? (nombre ≥ 18)")

# -------------------- Profile View (sous chaque profil) --------------------
class ProfileView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=None)
        self.owner_id = owner_id

    @discord.ui.button(emoji="❤️", label="Like", style=discord.ButtonStyle.success, custom_id="pf_like")
    async def like_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("⏳ Je note ton like…", ephemeral=True)
        author = interaction.user
        if author.id == self.owner_id:
            await interaction.edit_original_response(content="🤨 Tu ne peux pas te liker toi-même.")
            return
        is_match = storage.like(author.id, self.owner_id)
        log_line(interaction.guild, f"❤️ Like : {author} ({author.id}) → {self.owner_id}")
        await interaction.edit_original_response(content="❤️ Like enregistré.")
        if is_match:
            a = interaction.guild.get_member(author.id)
            b = interaction.guild.get_member(self.owner_id)
            for m1, m2 in [(a, b), (b, a)]:
                try:
                    dm = await m1.create_dm()
                    await dm.send(f"🔥 **C’est un match !** Tu as liké **{m2.display_name}** et c’est réciproque. Écrivez-vous !")
                except Exception:
                    pass
            log_line(interaction.guild, f"🔥 Match : {a} ({a.id}) ❤️ {b} ({b.id})")

    @discord.ui.button(emoji="❌", label="Pass", style=discord.ButtonStyle.secondary, custom_id="pf_pass")
    async def pass_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("⏳ Je note ton pass…", ephemeral=True)
        author = interaction.user
        if author.id == self.owner_id:
            await interaction.edit_original_response(content="… Pourquoi passer sur toi-même ? 😅")
            return
        storage.pass_(author.id, self.owner_id)
        log_line(interaction.guild, f"❌ Pass : {author} ({author.id}) → {self.owner_id}")
        await interaction.edit_original_response(content="👌 C’est noté.")

    @discord.ui.button(emoji="📩", label="Contacter", style=discord.ButtonStyle.primary, custom_id="pf_contact")
    async def contact_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        class ContactModal(discord.ui.Modal, title="Premier message"):
            def __init__(self, target_id: int):
                super().__init__(timeout=300)
                self.target_id = target_id
                self.msg = discord.ui.TextInput(
                    label="Ton message (1er contact)",
                    style=discord.TextStyle.paragraph,
                    min_length=5, max_length=600
                )
                self.add_item(self.msg)

            async def on_submit(self, inter: discord.Interaction):
                author = inter.user
                guild = inter.guild
                target = guild.get_member(self.target_id) if guild else None
                if not target:
                    await inter.response.send_message("❌ Utilisateur introuvable.", ephemeral=True)
                    return
                count = storage.inc_first_msg(author.id, target.id)
                if count > FIRST_MSG_LIMIT:
                    await inter.response.send_message(
                        f"❌ Tu as déjà envoyé {FIRST_MSG_LIMIT} premier message à cette personne.",
                        ephemeral=True
                    )
                    return
                txt = f"**{author.display_name}** souhaite te contacter :\n> {self.msg.value}\n\n(Tu peux répondre directement à ce message.)"
                try:
                    dm = await target.create_dm()
                    await dm.send(txt)
                    await inter.response.send_message("✅ Message envoyé en DM à la personne.", ephemeral=True)
                    log_line(guild, f"📨 Contact : {author} ({author.id}) → {target} ({target.id})")
                except Exception:
                    await inter.response.send_message("⚠️ Impossible d’envoyer le DM (DM fermés ?).", ephemeral=True)
                    log_line(guild, f"⚠️ Contact raté (DM fermés) : {author} ({author.id}) → {target} ({target.id})")

        await interaction.response.send_modal(ContactModal(target_id=self.owner_id))

    @discord.ui.button(emoji="✏️", label="Modifier", style=discord.ButtonStyle.secondary, custom_id="pf_edit")
    async def edit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("⏳ J’ouvre un DM pour modifier ton profil…", ephemeral=True)
        if not allowed_to_manage(interaction, self.owner_id):
            await interaction.edit_original_response(content="❌ Tu ne peux pas modifier ce profil.")
            return
        ok = True
        try:
            dm = await interaction.user.create_dm()
            await dm.send("✏️ On modifie ton profil ici. Clique **Démarrer** :", view=StartDMFormView(is_edit=True))
        except Exception:
            ok = False
        await interaction.edit_original_response(
            content="📩 DM envoyé, ouvre le formulaire." if ok else "⚠️ Impossible d’ouvrir un DM pour l’édition."
        )

    @discord.ui.button(emoji="🗑️", label="Supprimer", style=discord.ButtonStyle.danger, custom_id="pf_delete")
    async def del_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("⏳ Je supprime ton profil…", ephemeral=True)
        if not allowed_to_manage(interaction, self.owner_id):
            await interaction.edit_original_response(content="❌ Tu ne peux pas supprimer ce profil.")
            return
        ref = storage.get_profile_msg(self.owner_id)
        storage.delete_profile_everywhere(self.owner_id)
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
        await interaction.edit_original_response(content="✅ Profil supprimé.")

# -------------------- Helpers profils --------------------
def build_profile_embed(member: discord.Member, prof: Dict[str, Any]) -> discord.Embed:
    e = discord.Embed(
        title=f"Profil de {member.display_name}",
        description="Espace Rencontre — Miri",
        color=discord.Color.purple()
    )
    e.set_author(name=str(member), icon_url=member.display_avatar.url if member.display_avatar else None)
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
    ch = target_channel_for(guild, prof)
    if not isinstance(ch, discord.TextChannel):
        return
    msg = await ch.send(embed=embed, view=view)
    storage.set_profile_msg(member.id, ch.id, msg.id)

# -------------------- COGS: Admin, User & Staff --------------------
class AdminCog(commands.Cog, name="Admin"):
    """Slash admin/user: resetrencontre, resetprofil, sync"""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="resetrencontre", description="⚠️ Réinitialise complètement tous les profils Rencontre (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def reset_rencontre(self, interaction: discord.Interaction):
        try:
            if os.path.exists(DATA_FILE):
                os.remove(DATA_FILE)
            # reset en mémoire
            storage.data = {
                "profiles": {},
                "profile_msgs": {},
                "first_msg_counts": {},
                "likes": {},
                "passes": {},
                "matches": []
            }
            storage.save()
            await interaction.response.send_message(
                "✅ Données Rencontre **réinitialisées**.\n"
                "• Les anciens messages de profils n’ont plus de boutons valides (supprime-les si besoin).\n"
                "• Les membres peuvent recréer via le bouton ou `/creerprofil`.",
                ephemeral=True
            )
            log_line(interaction.guild, f"🗑️ Reset Rencontre (complet) par {interaction.user} ({interaction.user.id})")
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Erreur pendant le reset : {e}", ephemeral=True)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="resetprofil", description="🗑️ Supprime ton propre profil Rencontre")
    async def reset_profil(self, interaction: discord.Interaction):
        uid = interaction.user.id
        had = storage.get_profile(uid) is not None
        storage.delete_profile_everywhere(uid)
        if had:
            await interaction.response.send_message(
                "🗑️ Ton profil a été supprimé. Utilise le bouton **Créer mon profil** ou `/creerprofil` pour recommencer.",
                ephemeral=True
            )
            log_line(interaction.guild, f"🗑️ Profil reset par {interaction.user} ({interaction.user.id})")
        else:
            await interaction.response.send_message("ℹ️ Tu n’avais pas encore de profil enregistré.", ephemeral=True)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="sync", description="Force la synchronisation des commandes slash (admin).")
    @app_commands.checks.has_permissions(administrator=True)
    async def sync_cmds(self, interaction: discord.Interaction):
        try:
            cmds = await self.bot.tree.sync(guild=discord.Object(id=GUILD_ID))
            await interaction.response.send_message(f"🔁 Sync OK : **{len(cmds)}** commandes.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Sync fail : {e}", ephemeral=True)

class UserCog(commands.Cog, name="User"):
    """Slash user: creerprofil"""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="creerprofil", description="Ouvre un DM pour créer ton profil.")
    async def creer_profil(self, interaction: discord.Interaction):
        try:
            await interaction.response.send_message("⏳ J’ouvre un DM avec toi…", ephemeral=True)
            dm = await interaction.user.create_dm()
            await dm.send(
                embed=discord.Embed(
                    title="Création de ton profil — DM",
                    description=(
                        "On remplit en **privé**.\n\n"
                        "👉 Clique **Démarrer**, réponds aux questions puis **envoie une photo** (upload ou lien).\n"
                        "Je publierai ton profil et te donnerai le **rôle Accès Rencontre** ✅"
                    ),
                    color=discord.Color.purple()
                ),
                view=StartDMFormView(is_edit=False)
            )
            await interaction.edit_original_response(content="📩 DM envoyé !")
        except Exception:
            await interaction.edit_original_response(content="⚠️ Impossible d’écrire en DM (DM fermés ?).")

class SpeedCog(commands.Cog, name="SpeedDating"):
    """Slash staff: speeddating"""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="speeddating", description="Crée des threads privés éphémères (staff).")
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

# -------------------- BOT --------------------
class RencontreBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.synced = False

    async def setup_hook(self):
        # Vues persistantes globales
        self.add_view(StartFormView())
        self.add_view(StartDMFormView(is_edit=False))
        self.add_view(StartDMFormView(is_edit=True))

        # 🔁 Restaurer les vues des profils publiés (après reboot)
        try:
            for uid_str, ref in storage.data.get("profile_msgs", {}).items():
                owner_id = int(uid_str)
                message_id = int(ref.get("message_id", 0))
                if message_id:
                    self.add_view(ProfileView(owner_id=owner_id), message_id=message_id)
        except Exception as e:
            print("[Persistent views restore error]", e)

        # Cogs (slash commands)
        self.add_cog(AdminCog(self))
        self.add_cog(UserCog(self))
        self.add_cog(SpeedCog(self))

        # (On ne sync pas ici définitivement : certains hosts chargent avant que le guild soit prêt)

    async def on_ready(self):
        print(f"✅ Connecté en tant que {self.user} ({self.user.id})")
        # Sync agressive dès que possible
        try:
            if GUILD_ID:
                guild = self.get_guild(GUILD_ID)
                if guild:
                    cmds = await self.tree.sync(guild=discord.Object(id=GUILD_ID))
                    print(f"[SYNC] {len(cmds)} commandes sync sur {guild.name}")
                    self.synced = True
        except Exception as e:
            print("[Slash sync on_ready error]", e)

        if CH_WELCOME:
            ch = self.get_channel(CH_WELCOME)
            if isinstance(ch, discord.TextChannel):
                try:
                    await ch.send(
                        embed=discord.Embed(
                            title="**Bienvenue dans l’Espace Rencontre de Miri !**",
                            description=(
                                "Crée ton profil et découvre ceux des autres.\n"
                                "Likes, matchs, MP privés, speed dating…\n\n"
                                "⚠️ Réservé aux **18+**.\n\n"
                                "Clique ci-dessous pour commencer :"
                            ),
                            color=discord.Color.purple()
                        ),
                        view=StartFormView()
                    )
                except Exception:
                    pass

    async def on_guild_available(self, guild: discord.Guild):
        # si le guild devient dispo après le boot, (re)sync
        if GUILD_ID and guild.id == GUILD_ID and not self.synced:
            try:
                cmds = await self.tree.sync(guild=discord.Object(id=GUILD_ID))
                print(f"[SYNC-guild_available] {len(cmds)} commandes sync sur {guild.name}")
                self.synced = True
            except Exception as e:
                print("[Slash sync on_guild_available error]", e)

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        try:
            if interaction.response.is_done():
                await interaction.followup.send(f"⚠️ Erreur: {error}", ephemeral=True)
            else:
                await interaction.response.send_message(f"⚠️ Erreur: {error}", ephemeral=True)
        except Exception:
            pass

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # --- Formulaire DM pas-à-pas ---
        if isinstance(message.channel, discord.DMChannel):
            uid = message.author.id

            # 1) session de formulaire
            if uid in dm_sessions:
                s = dm_sessions[uid]
                step = s["step"]
                content = message.content.strip()

                try:
                    if step == 0:
                        age_val = int(content)
                        if age_val < 18:
                            await message.channel.send("❌ Réservé aux 18 ans et plus. Donne un âge valide (≥18).")
                            return
                        s["answers"]["age"] = age_val
                        s["step"] = 1
                        await message.channel.send("2/5 — Ton **genre** ? (Fille / Homme)")
                        return

                    if step == 1:
                        s["answers"]["genre"] = content
                        s["step"] = 2
                        await message.channel.send("3/5 — Ton **attirance** ? (ex: Hétéro, Bi…) *(ou `skip`)*")
                        return

                    if step == 2:
                        s["answers"]["orientation"] = "" if content.lower()=="skip" else content
                        s["step"] = 3
                        await message.channel.send("4/5 — Tes **passions** ? *(ou `skip`)*")
                        return

                    if step == 3:
                        s["answers"]["passions"] = "" if content.lower()=="skip" else content
                        s["step"] = 4
                        await message.channel.send("5/5 — Ton **activité** ? *(ou `skip`)*")
                        return

                    if step == 4:
                        s["answers"]["activite"] = "" if content.lower()=="skip" else content
                        # terminé → demande photo
                        is_edit = s["is_edit"]
                        answers = s["answers"]
                        dm_sessions.pop(uid, None)

                        old = storage.get_profile(uid) or {}
                        photo_keep = old.get("photo_url", "")
                        profile = {
                            "age": answers["age"],
                            "genre": answers["genre"],
                            "orientation": answers.get("orientation",""),
                            "passions": answers.get("passions",""),
                            "activite": answers.get("activite",""),
                            "photo_url": photo_keep if is_edit else "",
                            "updated_at": datetime.now(TZ).isoformat()
                        }
                        awaiting_photo[uid] = {"profile": profile, "is_edit": is_edit}
                        await message.channel.send(
                            "✅ Formulaire reçu ! Maintenant, **envoie une photo** (upload ou lien). "
                            "Tu peux répondre `skip` pour ne pas mettre/changer la photo."
                        )
                        return

                except ValueError:
                    await message.channel.send("⚠️ Donne un **nombre** pour l’âge (ex: 22).")
                    return

            # 2) réception de la photo (ou skip)
            if uid in awaiting_photo:
                photo_url = None
                if message.attachments:
                    att = message.attachments[0]
                    if (att.content_type and att.content_type.startswith("image")) or att.filename.lower().endswith((".png",".jpg",".jpeg",".webp",".gif")):
                        photo_url = att.url
                if not photo_url:
                    m = re.search(r'https?://\S+', message.content)
                    if m:
                        photo_url = m.group(0)
                if message.content.strip().lower() in {"skip", "aucune", "non", "ignore"}:
                    photo_url = ""

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

                # donner le rôle accès si création — sécurisé
                if not is_edit and ROLE_ACCESS:
                    role = guild.get_role(ROLE_ACCESS)
                    if role:
                        if role in member.roles:
                            log_line(guild, f"ℹ️ Rôle déjà présent pour {member} ({member.id}) : {role.name}")
                        else:
                            try:
                                await member.add_roles(role, reason="Création du profil Rencontre")
                                log_line(guild, f"✅ Rôle attribué à {member} ({member.id}) : {role.name}")
                            except discord.Forbidden:
                                log_line(guild, f"⚠️ Permissions insuffisantes rôle {role.name} → {member} ({member.id})")
                            except discord.HTTPException as e:
                                log_line(guild, f"⚠️ Erreur HTTP rôle {role.name} → {member} ({member.id}) : {e}")

                if is_edit:
                    log_line(guild, f"✏️ Édition (photo {'changée' if photo_url else 'inchangée'}) : {member} ({member.id})")
                    await message.channel.send("✅ Profil mis à jour.")
                else:
                    log_line(guild, f"✅ Création profil : {member} ({member.id})")
                    await message.channel.send("✅ Profil créé. Bienvenue dans l’Espace Rencontre !")

# -------------------- Entrée --------------------
bot = RencontreBot()

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN est requis (mets-le en variable d’environnement).")
    bot.run(DISCORD_TOKEN)
