# miri_rencontre.py — GUILD-ONLY + Purge Global + Welcome brandé + Full DM Flow + SpeedPerms + RencontreBan + Auto-clean leave + SpeedDating robuste
import os, re, json, asyncio, time
from datetime import datetime, timedelta, timezone
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
GUILD_ID      = env_int("GUILD_ID",      1382730341944397967)  # Miri
ROLE_ACCESS   = env_int("ROLE_ACCESS",   1401403405729267762)
CH_GIRLS      = env_int("CH_GIRLS",      1400520391793053841)
CH_BOYS       = env_int("CH_BOYS",       1400520396557521058)
CH_SPEED      = env_int("CH_SPEED",      1402665906546413679)
CH_LOGS       = env_int("CH_LOGS",       1403154919913033728)
CH_WELCOME    = env_int("CH_WELCOME",    1400808431941849178)
FIRST_MSG_LIMIT = env_int("FIRST_MSG_LIMIT", 1)
DATA_FILE     = os.getenv("DATA_FILE", "rencontre_data.json")
BRAND_COLOR   = 0x7C3AED
TZ = ZoneInfo("Europe/Paris")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True          # nécessaire pour on_member_remove + roles
intents.message_content = True  # pour DM

GUILD_OBJ = discord.Object(id=GUILD_ID)

# -------------------- Storage --------------------
class Storage:
    def __init__(self, path: str):
        self.path = path
        self.data: Dict[str, Any] = {
            "profiles": {}, "profile_msgs": {}, "first_msg_counts": {},
            "likes": {}, "passes": {}, "matches": [],
            "speed_perms": {"roles": [], "users": []},
            "welcome_panel": None,
            "banned_users": [],
            "speed_last_run": 0.0
        }
        self.load()
    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path,"r",encoding="utf-8") as f:
                    d=json.load(f)
                    self.data.update(d)
                    self.data.setdefault("speed_perms", {"roles": [], "users": []})
                    self.data.setdefault("banned_users", [])
                    self.data.setdefault("speed_last_run", 0.0)
            except Exception: pass
    def save(self):
        try:
            with open(self.path,"w",encoding="utf-8") as f:
                json.dump(self.data,f,ensure_ascii=False,indent=2)
        except Exception: pass

    # profils
    def get_profile(self, uid:int)->Optional[Dict[str,Any]]: return self.data["profiles"].get(str(uid))
    def set_profile(self, uid:int, prof:Dict[str,Any]): self.data["profiles"][str(uid)] = prof; self.save()
    def delete_profile_everywhere(self, uid:int):
        self.data["profiles"].pop(str(uid), None)
        self.data["likes"].pop(str(uid), None)
        self.data["passes"].pop(str(uid), None)
        # reset anti-spam pair counts
        fmc = self.data.get("first_msg_counts", {})
        for k in list(fmc.keys()):
            a,b = (k.split(":")+["",""])[:2]
            if a == str(uid) or b == str(uid):
                fmc.pop(k, None)
        # matches purge
        self.data["matches"] = [[a,b] for a,b in self.data["matches"] if int(a)!=uid and int(b)!=uid]
        # ref message
        self.data["profile_msgs"].pop(str(uid), None)
        self.save()
    def set_profile_msg(self, uid:int, channel_id:int, message_id:int):
        self.data["profile_msgs"][str(uid)] = {"channel_id":channel_id,"message_id":message_id}; self.save()
    def get_profile_msg(self, uid:int)->Optional[Dict[str,int]]: return self.data["profile_msgs"].get(str(uid))
    def inc_first_msg(self, author_id:int, target_id:int)->int:
        key=f"{author_id}:{target_id}"; val=self.data["first_msg_counts"].get(key,0)+1
        self.data["first_msg_counts"][key]=val; self.save(); return val

    def like(self, user_id:int, target_id:int)->bool:
        if user_id==target_id: return False
        likes=self.data["likes"].setdefault(str(user_id),[])
        if target_id not in likes:
            likes.append(target_id); self.save()
        other=set(self.data["likes"].get(str(target_id),[]))
        if user_id in other:
            pair=sorted([user_id,target_id])
            if pair not in [[int(a),int(b)] for a,b in self.data["matches"]]:
                self.data["matches"].append([str(pair[0]),str(pair[1])]); self.save(); return True
        return False
    def pass_(self, user_id:int, target_id:int):
        p=self.data["passes"].setdefault(str(user_id),[])
        if target_id not in p: p.append(target_id); self.save()

    # speed perms
    def get_speed_roles(self)->List[int]: return list(map(int, self.data["speed_perms"].get("roles", [])))
    def get_speed_users(self)->List[int]: return list(map(int, self.data["speed_perms"].get("users", [])))
    def add_speed_role(self, rid:int):
        r=self.data["speed_perms"].setdefault("roles", [])
        if rid not in r: r.append(rid); self.save()
    def remove_speed_role(self, rid:int):
        r=self.data["speed_perms"].setdefault("roles", [])
        if rid in r: r.remove(rid); self.save()
    def add_speed_user(self, uid:int):
        u=self.data["speed_perms"].setdefault("users", [])
        if uid not in u: u.append(uid); self.save()
    def remove_speed_user(self, uid:int):
        u=self.data["speed_perms"].setdefault("users", [])
        if uid in u: u.remove(uid); self.save()

    # bans rencontre
    def is_banned(self, uid:int)->bool: return int(uid) in set(map(int, self.data.get("banned_users", [])))
    def ban_user(self, uid:int):
        b=self.data.setdefault("banned_users", [])
        if uid not in b: b.append(uid); self.save()
    def unban_user(self, uid:int):
        b=self.data.setdefault("banned_users", [])
        if uid in b: b.remove(uid); self.save()
    def list_bans(self)->List[int]:
        return list(map(int, self.data.get("banned_users", [])))

storage = Storage(DATA_FILE)

# -------------------- Utils --------------------
def now_ts()->str: return datetime.now(TZ).strftime("[%d/%m/%Y %H:%M]")
def log_line(guild: Optional[discord.Guild], text:str):
    if not guild or not CH_LOGS: return
    ch = guild.get_channel(CH_LOGS)
    if isinstance(ch, discord.TextChannel):
        asyncio.create_task(ch.send(f"{now_ts()} {text}"))

def allowed_to_manage(inter: discord.Interaction, owner_id:int)->bool:
    if inter.user.id==owner_id: return True
    if isinstance(inter.user, discord.Member) and inter.user.guild_permissions.manage_guild: return True
    return False

def _clean(v: Optional[str], fallback: str = "—") -> str:
    v = (v or "").strip()
    return v if v else fallback

def can_run_speed(cooldown_sec=300) -> bool:
    last = storage.data.get("speed_last_run", 0.0)
    return (time.time() - float(last)) >= cooldown_sec
def mark_speed_run():
    storage.data["speed_last_run"] = time.time(); storage.save()

# -------------------- States --------------------
dm_sessions: Dict[int, Dict[str, Any]] = {}

# -------------------- Embeds --------------------
def make_welcome_embed(guild: Optional[discord.Guild]) -> discord.Embed:
    e = discord.Embed(
        title="**Bienvenue dans l’Espace Rencontre de Miri !**",
        description=(
            "Crée ton profil et découvre ceux des autres membres.\n"
            "Likes, matchs, MP privés, et soirées speed dating pour de **vraies connexions**.\n\n"
            "⚠️ Réservé aux **18 ans et plus**.\n\n"
            "Clique ci-dessous pour **commencer** :"
        ),
        color=BRAND_COLOR
    )
    if guild and guild.icon:
        e.set_author(name=guild.name, icon_url=guild.icon.url)
    e.set_footer(text="Miri • Rencontre")
    return e

def build_profile_embed(member: discord.Member, prof: Dict[str, Any]) -> discord.Embed:
    e = discord.Embed(
        title=f"Profil de {member.display_name}",
        description="Espace Rencontre — Miri",
        color=BRAND_COLOR
    )
    e.set_author(name=str(member), icon_url=member.display_avatar.url)
    if _clean(prof.get("photo_url"), ""):
        e.set_thumbnail(url=prof["photo_url"])

    e.add_field(name="Âge",        value=str(prof.get("age", "—")), inline=True)
    e.add_field(name="Genre",      value=_clean(prof.get("genre")), inline=True)
    e.add_field(name="Attirance",  value=_clean(prof.get("orientation")), inline=True)
    e.add_field(name="Passions",   value=_clean(prof.get("passions")), inline=False)
    e.add_field(name="Activité",   value=_clean(prof.get("activite")), inline=False)

    e.set_footer(text="Miri • Rencontre")
    e.timestamp = datetime.now(timezone.utc)
    return e

# -------------------- Views --------------------
class StartFormView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="✨ Créer mon profil maintenant", style=discord.ButtonStyle.success, custom_id="start_profile_btn")
    async def start_profile_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if storage.is_banned(interaction.user.id):
            await interaction.response.send_message("🚫 Tu n’es pas autorisé(e) à utiliser l’Espace Rencontre.", ephemeral=True)
            return
        await interaction.response.send_message("⏳ J’ouvre un DM avec toi…", ephemeral=True)
        ok=True
        try:
            dm=await interaction.user.create_dm()
            await dm.send(
                embed=discord.Embed(
                    title="Création de ton profil — DM",
                    description=("On va remplir le formulaire en **privé**.\n\n"
                                 "👉 Clique **Démarrer**, réponds aux questions, puis **envoie une photo** (upload ou lien) dans ce DM.\n"
                                 "Je publierai ton profil et te donnerai le **rôle Accès Rencontre** ✅"),
                    color=BRAND_COLOR
                ),
                view=StartDMFormView(is_edit=False)
            )
        except Exception: ok=False
        try:
            await interaction.edit_original_response(
                content=("📩 Regarde tes DM pour créer ton profil." if ok else "⚠️ Impossible de t’écrire en DM (DM fermés ?).")
            )
        except Exception: pass

class StartDMFormView(discord.ui.View):
    def __init__(self, is_edit: bool): super().__init__(timeout=None); self.is_edit=is_edit
    @discord.ui.button(label="Démarrer", style=discord.ButtonStyle.primary, custom_id="start_dm_form")
    async def start_dm_form(self, interaction: discord.Interaction, button: discord.ui.Button):
        if storage.is_banned(interaction.user.id):
            await interaction.response.send_message("🚫 Accès Rencontre retiré. Contacte un admin si c’est une erreur.", ephemeral=True)
            return
        await interaction.response.send_message("✅ OK, on fait ça ici en DM. Réponds aux questions ⤵️", ephemeral=True)
        uid=interaction.user.id
        dm_sessions[uid]={"step":0,"is_edit":self.is_edit,"answers":{}}
        await interaction.channel.send("1/5 — Quel est **ton âge** ? (nombre ≥ 18)")

class ProfileView(discord.ui.View):
    def __init__(self, owner_id:int): super().__init__(timeout=None); self.owner_id=owner_id
    @discord.ui.button(emoji="❤️", label="Like", style=discord.ButtonStyle.success, custom_id="pf_like")
    async def like_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("⏳ Je note ton like…", ephemeral=True)
        if interaction.user.id==self.owner_id:
            await interaction.edit_original_response(content="🤨 Tu ne peux pas te liker toi-même."); return
        is_match = storage.like(interaction.user.id, self.owner_id)
        log_line(interaction.guild, f"❤️ Like : {interaction.user} ({interaction.user.id}) → {self.owner_id}")
        await interaction.edit_original_response(content="❤️ Like enregistré.")
        if is_match:
            a = interaction.guild.get_member(interaction.user.id); b = interaction.guild.get_member(self.owner_id)
            for m1,m2 in [(a,b),(b,a)]:
                try: dm=await m1.create_dm(); await dm.send(f"🔥 **C’est un match !** Tu as liké **{m2.display_name}** et c’est réciproque. Écrivez-vous !")
                except Exception: pass
            log_line(interaction.guild, f"🔥 Match : {a} ({a.id}) ❤️ {b} ({b.id})")
    @discord.ui.button(emoji="❌", label="Pass", style=discord.ButtonStyle.secondary, custom_id="pf_pass")
    async def pass_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("⏳ Je note ton pass…", ephemeral=True)
        if interaction.user.id==self.owner_id:
            await interaction.edit_original_response(content="… Pourquoi passer sur toi-même ? 😅"); return
        storage.pass_(interaction.user.id, self.owner_id)
        log_line(interaction.guild, f"❌ Pass : {interaction.user} ({interaction.user.id}) → {self.owner_id}")
        await interaction.edit_original_response(content="👌 C’est noté.")
    @discord.ui.button(emoji="📩", label="Contacter", style=discord.ButtonStyle.primary, custom_id="pf_contact")
    async def contact_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        class ContactModal(discord.ui.Modal, title="Premier message"):
            def __init__(self, target_id:int):
                super().__init__(timeout=300); self.target_id=target_id
                self.msg = discord.ui.TextInput(label="Ton message (1er contact)", style=discord.TextStyle.paragraph, min_length=5, max_length=600)
                self.add_item(self.msg)
            async def on_submit(self, inter: discord.Interaction):
                author=inter.user; guild=inter.guild; target=guild.get_member(self.target_id) if guild else None
                if not target: await inter.response.send_message("❌ Utilisateur introuvable.", ephemeral=True); return
                count=storage.inc_first_msg(author.id, target.id)
                if count>FIRST_MSG_LIMIT:
                    await inter.response.send_message(f"❌ Tu as déjà envoyé {FIRST_MSG_LIMIT} premier message à cette personne.", ephemeral=True); return
                txt=f"**{author.display_name}** souhaite te contacter :\n> {self.msg.value}\n\n(Tu peux répondre directement à ce message.)"
                try: dm=await target.create_dm(); await dm.send(txt); await inter.response.send_message("✅ Message envoyé en DM à la personne.", ephemeral=True); log_line(guild, f"📨 Contact : {author} ({author.id}) → {target} ({target.id})")
                except Exception: await inter.response.send_message("⚠️ Impossible d’envoyer le DM (DM fermés ?).", ephemeral=True); log_line(guild, f"⚠️ Contact raté (DM fermés) : {author} ({author.id}) → {target} ({target.id})")
        await interaction.response.send_modal(ContactModal(target_id=self.owner_id))
    @discord.ui.button(emoji="✏️", label="Modifier", style=discord.ButtonStyle.secondary, custom_id="pf_edit")
    async def edit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("⏳ J’ouvre un DM pour modifier ton profil…", ephemeral=True)
        if not allowed_to_manage(interaction, self.owner_id):
            await interaction.edit_original_response(content="❌ Tu ne peux pas modifier ce profil."); return
        ok=True
        try:
            dm=await interaction.user.create_dm()
            await dm.send("✏️ On modifie ton profil ici. Clique **Démarrer** :", view=StartDMFormView(is_edit=True))
        except Exception: ok=False
        await interaction.edit_original_response(content=("📩 DM envoyé, ouvre le formulaire." if ok else "⚠️ Impossible d’ouvrir un DM pour l’édition."))

    @discord.ui.button(emoji="🗑️", label="Supprimer", style=discord.ButtonStyle.danger, custom_id="pf_delete")
    async def del_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("⏳ Je supprime ton profil…", ephemeral=True)
        if not allowed_to_manage(interaction, self.owner_id):
            await interaction.edit_original_response(content="❌ Tu ne peux pas supprimer ce profil."); return
        ref=storage.get_profile_msg(self.owner_id); storage.delete_profile_everywhere(self.owner_id)
        if ref:
            ch=interaction.guild.get_channel(ref["channel_id"])
            if isinstance(ch, discord.TextChannel):
                try:
                    msg=await ch.fetch_message(ref["message_id"]); await msg.delete()
                except Exception: pass
        member=interaction.guild.get_member(self.owner_id)
        log_line(interaction.guild, f"🗑️ Suppression : {member} ({member.id})")
        await interaction.edit_original_response(content="✅ Profil supprimé.")

# -------------------- Publication --------------------
def target_channel_for(guild: discord.Guild, prof: Dict[str, Any])->Optional[discord.TextChannel]:
    gender=(prof.get("genre") or "").strip().lower()
    return guild.get_channel(CH_GIRLS) if gender.startswith("f") else guild.get_channel(CH_BOYS)

async def publish_or_update_profile(guild: discord.Guild, member: discord.Member, prof: Dict[str, Any]):
    view=ProfileView(owner_id=member.id); embed=build_profile_embed(member, prof)
    ref=storage.get_profile_msg(member.id)
    if ref:
        ch=guild.get_channel(ref["channel_id"])
        if isinstance(ch, discord.TextChannel):
            try:
                msg=await ch.fetch_message(ref["message_id"])
                await msg.edit(embed=embed, view=view, content=None); return
            except Exception: pass
    ch=target_channel_for(guild, prof)
    if not isinstance(ch, discord.TextChannel): return
    msg=await ch.send(embed=embed, view=view)
    storage.set_profile_msg(member.id, ch.id, msg.id)

# -------------------- Slash COGS --------------------
class AdminCog(commands.Cog, name="Admin"):
    def __init__(self, bot: commands.Bot): self.bot=bot

    @app_commands.command(name="resetrencontre", description="⚠️ Réinitialise complètement (banlist conservée)")
    @app_commands.guilds(GUILD_OBJ)
    @app_commands.checks.has_permissions(administrator=True)
    async def reset_rencontre(self, interaction: discord.Interaction):
        try:
            welcome = storage.data.get("welcome_panel")
            banned  = storage.list_bans()
            storage.data={"profiles":{},"profile_msgs":{},"first_msg_counts":{},"likes":{},"passes":{},"matches":[],
                          "speed_perms":{"roles":[],"users":[]}, "welcome_panel": welcome, "banned_users": banned,
                          "speed_last_run": storage.data.get("speed_last_run", 0.0)}
            storage.save()
            await interaction.response.send_message("✅ Données Rencontre **réinitialisées** (banlist conservée).", ephemeral=True)
            log_line(interaction.guild, f"🗑️ Reset Rencontre (complet) par {interaction.user} ({interaction.user.id})")
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Erreur pendant le reset : {e}", ephemeral=True)

    @app_commands.command(name="resetprofil", description="🗑️ Supprime ton propre profil Rencontre")
    @app_commands.guilds(GUILD_OBJ)
    async def reset_profil(self, interaction: discord.Interaction):
        uid=interaction.user.id
        had=storage.get_profile(uid) is not None
        ref=storage.get_profile_msg(uid)
        storage.delete_profile_everywhere(uid)
        if ref:
            ch=interaction.guild.get_channel(ref["channel_id"])
            if isinstance(ch, discord.TextChannel):
                try:
                    msg=await ch.fetch_message(ref["message_id"]); await msg.delete()
                except Exception: pass
        if had:
            await interaction.response.send_message("🗑️ Ton profil a été supprimé. Utilise le **bouton** pour recommencer.", ephemeral=True)
            log_line(interaction.guild, f"🗑️ Profil reset par {interaction.user} ({interaction.user.id})")
        else:
            await interaction.response.send_message("ℹ️ Tu n’avais pas encore de profil enregistré.", ephemeral=True)

    # --------- SpeedPerms ----------
    speed_group = app_commands.Group(name="speedperms", description="Gérer qui peut lancer le speed dating", guild_ids=[GUILD_ID])

    @speed_group.command(name="addrole", description="Autoriser un rôle à lancer /speeddating")
    async def sp_addrole(self, interaction: discord.Interaction, role: discord.Role):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin requis.", ephemeral=True); return
        storage.add_speed_role(role.id)
        await interaction.response.send_message(f"✅ Rôle **{role.name}** autorisé.", ephemeral=True)

    @speed_group.command(name="removerole", description="Retirer un rôle autorisé")
    async def sp_removerole(self, interaction: discord.Interaction, role: discord.Role):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin requis.", ephemeral=True); return
        storage.remove_speed_role(role.id)
        await interaction.response.send_message(f"✅ Rôle **{role.name}** retiré.", ephemeral=True)

    @speed_group.command(name="adduser", description="Autoriser un membre à lancer /speeddating")
    async def sp_adduser(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin requis.", ephemeral=True); return
        storage.add_speed_user(user.id)
        await interaction.response.send_message(f"✅ Membre **{user.display_name}** autorisé.", ephemeral=True)

    @speed_group.command(name="removeuser", description="Retirer un membre autorisé")
    async def sp_removeuser(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin requis.", ephemeral=True); return
        storage.remove_speed_user(user.id)
        await interaction.response.send_message(f"✅ Membre **{user.display_name}** retiré.", ephemeral=True)

    @speed_group.command(name="list", description="Voir les rôles/membres autorisés")
    async def sp_list(self, interaction: discord.Interaction):
        roles_ids = storage.get_speed_roles()
        users_ids = storage.get_speed_users()
        roles = [interaction.guild.get_role(rid) for rid in roles_ids]
        users = [interaction.guild.get_member(uid) for uid in users_ids]
        r_txt = ", ".join([r.mention for r in roles if r]) or "—"
        u_txt = ", ".join([u.mention for u in users if u]) or "—"
        await interaction.response.send_message(f"**Rôles autorisés :** {r_txt}\n**Membres autorisés :** {u_txt}", ephemeral=True)

    # --------- Rencontre BAN ----------
    ban_group = app_commands.Group(name="rencontreban", description="Gérer l'accès Rencontre (ban/unban/list)", guild_ids=[GUILD_ID])

    @ban_group.command(name="add", description="Retirer l'accès Rencontre à un membre (supprime profil + rôle)")
    async def rb_add(self, interaction: discord.Interaction, user: discord.Member, raison: Optional[str] = None):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin requis.", ephemeral=True); return
        storage.ban_user(user.id)

        # retirer rôle Accès Rencontre
        if ROLE_ACCESS:
            role = interaction.guild.get_role(ROLE_ACCESS)
            if role and role in user.roles:
                try: await user.remove_roles(role, reason="Ban Rencontre")
                except Exception: pass

        # supprimer profil + message
        ref = storage.get_profile_msg(user.id)
        storage.delete_profile_everywhere(user.id)
        if ref:
            ch=interaction.guild.get_channel(ref["channel_id"])
            if isinstance(ch, discord.TextChannel):
                try:
                    msg=await ch.fetch_message(ref["message_id"]); await msg.delete()
                except Exception: pass

        await interaction.response.send_message(f"🚫 **{user.display_name}** banni de l’Espace Rencontre.", ephemeral=True)
        log_line(interaction.guild, f"🚫 RencontreBan ADD : {user} ({user.id}) — {raison or '—'}")

    @ban_group.command(name="remove", description="Rendre l'accès Rencontre à un membre")
    async def rb_remove(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin requis.", ephemeral=True); return
        storage.unban_user(user.id)
        await interaction.response.send_message(f"✅ **{user.display_name}** peut à nouveau utiliser l’Espace Rencontre.", ephemeral=True)
        log_line(interaction.guild, f"✅ RencontreBan REMOVE : {user} ({user.id})")

    @ban_group.command(name="list", description="Voir les membres bannis de l'Espace Rencontre")
    async def rb_list(self, interaction: discord.Interaction):
        ids = storage.list_bans()
        if not ids:
            await interaction.response.send_message("Aucun membre banni.", ephemeral=True); return
        names = []
        for i in ids:
            m = interaction.guild.get_member(i)
            names.append(m.mention if m else f"`{i}`")
        await interaction.response.send_message("**Bannis Rencontre :** " + ", ".join(names), ephemeral=True)

    @app_commands.command(name="ping", description="Test de présence des commandes")
    @app_commands.guilds(GUILD_OBJ)
    async def ping(self, interaction: discord.Interaction):
        await interaction.response.send_message("pong ✅", ephemeral=True)

class SpeedCog(commands.Cog, name="SpeedDating"):
    def __init__(self, bot: commands.Bot): self.bot=bot

    @app_commands.command(name="speeddating", description="Crée des threads privés éphémères (rôles/membres autorisés)")
    @app_commands.guilds(GUILD_OBJ)
    async def speeddating(self, interaction: discord.Interaction, couples:int=5):
        # Autorisations : Admin/ManageChannels OU whitelist (rôle ou user)
        m: discord.Member = interaction.user
        ok = (
            m.guild_permissions.administrator or
            m.guild_permissions.manage_channels or
            any(r.id in storage.get_speed_roles() for r in m.roles) or
            (m.id in storage.get_speed_users())
        )
        if not ok:
            await interaction.response.send_message("❌ Tu n’es pas autorisé(e) à lancer le speed dating.", ephemeral=True); return

        # Cooldown anti-spam (5 min)
        if not can_run_speed(300):
            await interaction.response.send_message("⏳ Patiente un peu avant de relancer un speed dating.", ephemeral=True)
            return

        if not CH_SPEED:
            await interaction.response.send_message("❌ CH_SPEED non défini.", ephemeral=True); return
        speed_ch=interaction.guild.get_channel(CH_SPEED)
        if not isinstance(speed_ch, discord.TextChannel):
            await interaction.response.send_message("❌ Salon speed introuvable.", ephemeral=True); return

        # participants actifs (1h)
        cutoff=datetime.now(timezone.utc)-timedelta(hours=1)
        authors:List[int]=[]
        try:
            async for msg in speed_ch.history(limit=500, oldest_first=False, after=cutoff):
                if msg.author.bot: continue
                uid = msg.author.id
                if uid not in authors: authors.append(uid)
        except Exception: pass

        # Filtre éligibles : non banni + ROLE_ACCESS si défini
        eligible: List[int] = []
        for uid in authors:
            if storage.is_banned(uid): continue
            member = interaction.guild.get_member(uid)
            if not member: continue
            if ROLE_ACCESS:
                role = interaction.guild.get_role(ROLE_ACCESS)
                if role and role not in member.roles: continue
            eligible.append(uid)

        if len(eligible) < 2:
            await interaction.response.send_message("Pas assez de personnes **éligibles et actives** dans l’heure.", ephemeral=True)
            return

        import random
        random.shuffle(eligible)
        max_pairs = min(max(1, couples), len(eligible)//2)
        pairs: List[Tuple[int,int]] = []
        while len(pairs) < max_pairs and len(eligible) >= 2:
            a = eligible.pop()
            b = eligible.pop()
            if a != b:
                pairs.append((a,b))

        created=[]
        for a,b in pairs:
            ma=interaction.guild.get_member(a); mb=interaction.guild.get_member(b)
            if not ma or not mb: continue
            name=f"Speed ⏳ {ma.display_name} × {mb.display_name}"
            try:
                th=await speed_ch.create_thread(
                    name=name,
                    type=discord.ChannelType.private_thread,
                    invitable=False,
                    auto_archive_duration=60  # archive auto
                )
                await th.add_user(ma); await th.add_user(mb)
                await th.send(f"Bienvenue {ma.mention} et {mb.mention} — vous avez **5 minutes** ⏳. "
                              f"Soyez respectueux/sses. Le fil sera verrouillé à la fin.")
                created.append(th)
            except Exception:
                continue

        mark_speed_run()
        await interaction.response.send_message(f"✅ Créé {len(created)} threads éphémères.", ephemeral=True)

        await asyncio.sleep(5*60)
        for t in created:
            try: await t.edit(archived=True, locked=True)
            except Exception: pass

class DiagCog(commands.Cog, name="Diag"):
    def __init__(self, bot: commands.Bot): self.bot=bot

    @app_commands.command(name="sync", description="Resynchronise les commandes (admin)")
    @app_commands.guilds(GUILD_OBJ)
    @app_commands.checks.has_permissions(administrator=True)
    async def sync_cmds(self, interaction: discord.Interaction):
        try:
            cmds = await interaction.client.tree.sync(guild=GUILD_OBJ)
            await interaction.response.send_message(f"🔁 Sync OK — {len(cmds)} commandes (guild).", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Sync fail : {e}", ephemeral=True)

    @app_commands.command(name="clearglobals", description="Purger toutes les commandes GLOBAL (admin)")
    @app_commands.guilds(GUILD_OBJ)
    @app_commands.checks.has_permissions(administrator=True)
    async def clear_globals(self, interaction: discord.Interaction):
        try:
            t = interaction.client.tree
            t.clear_commands(guild=None)
            await t.sync()  # pousse 0 → supprime toutes les globales
            await interaction.response.send_message("🧹 Global slash **purgées**. Il ne reste que les guild-only.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Clear globals fail : {e}", ephemeral=True)

# -------------------- Accueil Auto --------------------
async def ensure_welcome_panel(bot: commands.Bot):
    if not CH_WELCOME: return
    guild = bot.get_guild(GUILD_ID)
    if not guild: return
    ch = guild.get_channel(CH_WELCOME)
    if not isinstance(ch, discord.TextChannel): return

    ref = storage.data.get("welcome_panel")
    if isinstance(ref, dict):
        try:
            msg = await ch.fetch_message(ref.get("message_id", 0))
            if msg: return
        except Exception:
            pass

    embed = make_welcome_embed(guild)
    try:
        msg = await ch.send(embed=embed, view=StartFormView())
        storage.data["welcome_panel"] = {"channel_id": ch.id, "message_id": msg.id}
        storage.save()
    except Exception:
        pass

# ================== DM WORKFLOW HELPERS ==================
async def _send_next_step(dm_ch: discord.DMChannel, uid: int):
    step = dm_sessions[uid]["step"]
    if step == 0:
        await dm_ch.send("1/5 — Quel est **ton âge** ? (nombre ≥ 18)")
    elif step == 1:
        await dm_ch.send("2/5 — Ton **genre** ? (Fille / Homme)")
    elif step == 2:
        await dm_ch.send("3/5 — Ton **attirance** (orientation) ? (ex: hétéro, bi, pan…)")
    elif step == 3:
        await dm_ch.send("4/5 — Tes **passions** ? (quelques mots)")
    elif step == 4:
        await dm_ch.send("5/5 — Ton **activité** (ce que tu fais dans la vie) ?")
    elif step == 5:
        await dm_ch.send("📸 Envoie maintenant **ta photo** (pièce jointe) **ou** un **lien URL** d’image.")

# -------------------- BOT --------------------
class RencontreBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.synced=False
        self.purged_globals=False

    async def setup_hook(self):
        await self.add_cog(AdminCog(self))
        await self.add_cog(SpeedCog(self))
        await self.add_cog(DiagCog(self))
        self.add_view(StartFormView())  # vues persistantes

    async def on_ready(self):
        if not self.synced:
            try:
                # 1) Purge toutes les commandes GLOBAL une bonne fois
                if not self.purged_globals:
                    self.tree.clear_commands(guild=None)
                    await self.tree.sync()  # publie 0 → supprime global
                    self.purged_globals = True

                # 2) Sync GUILD-ONLY (source de vérité)
                await self.tree.sync(guild=GUILD_OBJ)
                self.synced = True
                print(f"[SYNC] Purge global OK + Guild-only OK pour {GUILD_ID}")
            except Exception as e:
                print(f"[SYNC] Échec: {e}")

        await ensure_welcome_panel(self)
        print(f"Connecté comme {self.user} (id={self.user.id})")
        await self.change_presence(status=discord.Status.online, activity=discord.Game("Miri Rencontre"))

    async def on_message(self, message: discord.Message):
        await self.process_commands(message)
        # DM uniquement
        if message.author.bot or message.guild is not None:
            return
        uid = message.author.id
        if uid not in dm_sessions:
            return

        sess = dm_sessions[uid]
        dm_ch: discord.DMChannel = message.channel  # type: ignore
        content = (message.content or "").strip()

        # Étape 0 — âge
        if sess["step"] == 0:
            try:
                age = int(re.sub(r"\D+", "", content))
                if age < 18:
                    await dm_ch.send("❌ Désolé, c’est réservé aux **18+**.")
                    dm_sessions.pop(uid, None)
                    return
                sess["answers"]["age"] = age
                sess["step"] = 1
                await _send_next_step(dm_ch, uid)
            except Exception:
                await dm_ch.send("⚠️ Entre un **nombre** (ex: 21).")
            return

        # Étape 1 — genre
        if sess["step"] == 1:
            g = content.lower()
            if g.startswith("f"):
                sess["answers"]["genre"] = "Fille"
            elif g.startswith("h"):
                sess["answers"]["genre"] = "Homme"
            else:
                await dm_ch.send("⚠️ Réponds par **Fille** ou **Homme**.")
                return
            sess["step"] = 2
            await _send_next_step(dm_ch, uid)
            return

        # Étape 2 — orientation
        if sess["step"] == 2:
            sess["answers"]["orientation"] = content[:100] if content else "—"
            sess["step"] = 3
            await _send_next_step(dm_ch, uid)
            return

        # Étape 3 — passions
        if sess["step"] == 3:
            sess["answers"]["passions"] = content[:200] if content else "—"
            sess["step"] = 4
            await _send_next_step(dm_ch, uid)
            return

        # Étape 4 — activité
        if sess["step"] == 4:
            sess["answers"]["activite"] = content[:150] if content else "—"
            sess["step"] = 5
            await _send_next_step(dm_ch, uid)
            return

        # Étape 5 — photo (fichier ou lien)
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
                await dm_ch.send("⚠️ Envoie une **image** (pièce jointe) ou un **lien** direct (png/jpg/gif/webp).")
                return

            sess["answers"]["photo_url"] = photo_url

            # Sauvegarde profil
            profile = {
                "age": sess["answers"].get("age"),
                "genre": sess["answers"].get("genre"),
                "orientation": sess["answers"].get("orientation"),
                "passions": sess["answers"].get("passions"),
                "activite": sess["answers"].get("activite"),
                "photo_url": sess["answers"].get("photo_url"),
            }
            storage.set_profile(uid, profile)

            # Publier/mettre à jour sur le serveur + rôle
            guild = self.get_guild(GUILD_ID)
            if guild:
                member = guild.get_member(uid)
                if member:
                    try:
                        await publish_or_update_profile(guild, member, profile)
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
            await dm_ch.send("✅ **Profil enregistré.** Il a été publié sur le serveur. Tu peux le modifier/supprimer via les boutons sous ton profil.")
            return

    async def on_member_remove(self, member: discord.Member):
        # Auto-clean : supprime profil + message publié quand un membre quitte
        uid = member.id
        ref = storage.get_profile_msg(uid)
        storage.delete_profile_everywhere(uid)
        if ref:
            ch = member.guild.get_channel(ref["channel_id"])
            if isinstance(ch, discord.TextChannel):
                try:
                    msg = await ch.fetch_message(ref["message_id"]); await msg.delete()
                except Exception: pass
        log_line(member.guild, f"👋 Leave cleanup : {member} ({uid}) — profil supprimé")

# -------------------- RUN --------------------
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN manquant dans l'env.")
bot = RencontreBot()
bot.run(DISCORD_TOKEN)
