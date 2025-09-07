# miri_rencontre.py — HYBRID SYNC (global + guild copy) + HARD RESET + /ping
import os, re, json, asyncio
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
intents.message_content = True  # pour lire les DM

# -------------------- Storage --------------------
class Storage:
    def __init__(self, path: str):
        self.path = path
        self.data: Dict[str, Any] = {
            "profiles": {}, "profile_msgs": {}, "first_msg_counts": {},
            "likes": {}, "passes": {}, "matches": []
        }
        self.load()
    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path,"r",encoding="utf-8") as f:
                    self.data.update(json.load(f))
            except Exception: pass
    def save(self):
        try:
            with open(self.path,"w",encoding="utf-8") as f:
                json.dump(self.data,f,ensure_ascii=False,indent=2)
        except Exception: pass
    def get_profile(self, uid:int)->Optional[Dict[str,Any]]: return self.data["profiles"].get(str(uid))
    def set_profile(self, uid:int, prof:Dict[str,Any]): self.data["profiles"][str(uid)] = prof; self.save()
    def delete_profile_everywhere(self, uid:int):
        self.data["profiles"].pop(str(uid), None)
        self.data["profile_msgs"].pop(str(uid), None)
        self.data["likes"].pop(str(uid), None)
        self.data["passes"].pop(str(uid), None)
        # reset anti-spam
        fmc = self.data.get("first_msg_counts", {})
        for k in list(fmc.keys()):
            if k.startswith(f"{uid}:") or k.endswith(f":{uid}"):
                fmc.pop(k, None)
        # matches
        self.data["matches"] = [[a,b] for a,b in self.data["matches"] if int(a)!=uid and int(b)!=uid]
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
        if target_id not in likes: likes.append(target_id); self.save()
        other=set(self.data["likes"].get(str(target_id),[]))
        if user_id in other:
            pair=sorted([user_id,target_id])
            if pair not in [[int(a),int(b)] for a,b in self.data["matches"]]:
                self.data["matches"].append([str(pair[0]),str(pair[1])]); self.save(); return True
        return False
    def pass_(self, user_id:int, target_id:int):
        p=self.data["passes"].setdefault(str(user_id),[])
        if target_id not in p: p.append(target_id); self.save()

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

# -------------------- States --------------------
awaiting_photo: Dict[int, Dict[str, Any]] = {}
dm_sessions: Dict[int, Dict[str, Any]] = {}

# -------------------- Views --------------------
class StartFormView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Créer mon profil", style=discord.ButtonStyle.success, custom_id="start_profile_btn")
    async def start_profile_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
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
                    color=discord.Color.purple()
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
        await interaction.response.send_message("✅ OK, on fait ça ici en DM. Réponds à mes questions ⤵️", ephemeral=True)
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
                try: msg=await ch.fetch_message(ref["message_id"]); await msg.delete()
                except Exception: pass
        member=interaction.guild.get_member(self.owner_id)
        log_line(interaction.guild, f"🗑️ Suppression : {member} ({member.id})")
        await interaction.edit_original_response(content="✅ Profil supprimé.")

def build_profile_embed(member: discord.Member, prof: Dict[str, Any])->discord.Embed:
    e=discord.Embed(title=f"Profil de {member.display_name}", description="Espace Rencontre — Miri", color=discord.Color.purple())
    e.set_author(name=str(member), icon_url=member.display_avatar.url if member.display_avatar else None)
    if prof.get("photo_url"): e.set_thumbnail(url=prof["photo_url"])
    for n,v,inline in [("Âge",f"{prof.get('age','—')}",True),
                       ("Genre",prof.get('genre','—') or "—",True),
                       ("Attirance",prof.get('orientation','—') or "—",True),
                       ("Passions",prof.get('passions','—') or "—",False),
                       ("Activité",prof.get('activite','—') or "—",False)]:
        e.add_field(name=n, value=v, inline=inline)
    e.set_footer(text="❤️ Like • ❌ Pass • 📩 Contacter • ✏️ Modifier • 🗑️ Supprimer")
    return e

def target_channel_for(guild: discord.Guild, prof: Dict[str, Any])->Optional[discord.TextChannel]:
    gender=(prof.get("genre") or "").strip().lower()
    return guild.get_channel(CH_GIRLS) if gender.startswith("f") else guild.get_channel(CH_BOYS)

async def publish_or_update_profile(guild: discord.Guild, member: discord.Member, prof: Dict[str, Any]):
    view=ProfileView(owner_id=member.id); embed=build_profile_embed(member, prof)
    ref=storage.get_profile_msg(member.id)
    if ref:
        ch=guild.get_channel(ref["channel_id"])
        if isinstance(ch, discord.TextChannel):
            try: msg=await ch.fetch_message(ref["message_id"]); await msg.edit(embed=embed, view=view, content=None); return
            except Exception: pass
    ch=target_channel_for(guild, prof)
    if not isinstance(ch, discord.TextChannel): return
    msg=await ch.send(embed=embed, view=view); storage.set_profile_msg(member.id, ch.id, msg.id)

# -------------- GUILD OBJECT (utilisé pour copy_global_to) --------------
GUILD_OBJ = discord.Object(id=GUILD_ID)

# -------------------- Slash COGS --------------------
class AdminCog(commands.Cog, name="Admin"):
    def __init__(self, bot: commands.Bot): self.bot=bot

    @app_commands.command(name="resetrencontre", description="⚠️ Réinitialise complètement tous les profils Rencontre (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def reset_rencontre(self, interaction: discord.Interaction):
        try:
            if os.path.exists(DATA_FILE): os.remove(DATA_FILE)
            storage.data={"profiles":{},"profile_msgs":{},"first_msg_counts":{},"likes":{},"passes":{},"matches":[]}
            storage.save()
            await interaction.response.send_message(
                "✅ Données Rencontre **réinitialisées**.\n"
                "• Supprime manuellement les vieux messages si besoin.\n"
                "• Les membres utilisent le **bouton** pour (re)créer leur profil.",
                ephemeral=True
            )
            log_line(interaction.guild, f"🗑️ Reset Rencontre (complet) par {interaction.user} ({interaction.user.id})")
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Erreur pendant le reset : {e}", ephemeral=True)

    @app_commands.command(name="resetprofil", description="🗑️ Supprime ton propre profil Rencontre")
    async def reset_profil(self, interaction: discord.Interaction):
        uid=interaction.user.id; had=storage.get_profile(uid) is not None
        storage.delete_profile_everywhere(uid)
        if had:
            await interaction.response.send_message("🗑️ Ton profil a été supprimé. Utilise le **bouton** pour recommencer.", ephemeral=True)
            log_line(interaction.guild, f"🗑️ Profil reset par {interaction.user} ({interaction.user.id})")
        else:
            await interaction.response.send_message("ℹ️ Tu n’avais pas encore de profil enregistré.", ephemeral=True)

    @app_commands.command(name="sync", description="Force la synchronisation des commandes (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def sync_cmds(self, interaction: discord.Interaction):
        try:
            client: commands.Bot = interaction.client
            # copie des globales vers le guild pour un effet immédiat
            client.tree.copy_global_to(guild=GUILD_OBJ)
            g = await client.tree.sync(guild=GUILD_OBJ)
            # sync globales (propagation plus lente, mais prête pour multi-serveurs)
            glob = await client.tree.sync()
            await interaction.response.send_message(
                f"🔁 Sync OK — Guild:{len(g)} Global:{len(glob)}", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Sync fail : {e}", ephemeral=True)

class SpeedCog(commands.Cog, name="SpeedDating"):
    def __init__(self, bot: commands.Bot): self.bot=bot

    @app_commands.command(name="speeddating", description="Crée des threads privés éphémères (staff)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def speeddating(self, interaction: discord.Interaction, couples:int=5):
        if not CH_SPEED: await interaction.response.send_message("❌ CH_SPEED non défini.", ephemeral=True); return
        speed_ch=interaction.guild.get_channel(CH_SPEED)
        if not isinstance(speed_ch, discord.TextChannel):
            await interaction.response.send_message("❌ Salon speed introuvable.", ephemeral=True); return
        cutoff=datetime.now(timezone.utc)-timedelta(hours=1)
        authors:List[int]=[]
        try:
            async for m in speed_ch.history(limit=500, oldest_first=False, after=cutoff):
                if m.author.bot: continue
                if m.author.id not in authors: authors.append(m.author.id)
        except Exception: pass
        if len(authors)<2:
            await interaction.response.send_message("Pas assez de personnes actives dans l’heure.", ephemeral=True); return
        import random; random.shuffle(authors)
        pairs:List[Tuple[int,int]]=[]
        while len(authors)>=2 and len(pairs)<couples:
            a=authors.pop(); b=authors.pop()
            if a!=b: pairs.append((a,b))
        created=[]
        for a,b in pairs:
            ma=interaction.guild.get_member(a); mb=interaction.guild.get_member(b)
            if not ma or not mb: continue
            name=f"Speed ⏳ {ma.display_name} × {mb.display_name}"
            try:
                th=await speed_ch.create_thread(name=name, type=discord.ChannelType.private_thread, invitable=False)
                await th.add_user(ma); await th.add_user(mb)
                await th.send(f"Bienvenue {ma.mention} et {mb.mention} — vous avez **5 minutes** ⏳. Soyez respectueux/sses.")
                created.append(th)
            except Exception: continue
        await interaction.response.send_message(f"✅ Créé {len(created)} threads éphémères.", ephemeral=True)
        await asyncio.sleep(5*60)
        for t in created:
            try: await t.edit(archived=True, locked=True)
            except Exception: pass

class DiagCog(commands.Cog, name="Diag"):
    def __init__(self, bot: commands.Bot): self.bot=bot
    @app_commands.command(name="ping", description="Test de présence des commandes")
    async def ping(self, interaction: discord.Interaction):
        await interaction.response.send_message("pong ✅", ephemeral=True)

# -------------------- BOT --------------------
class RencontreBot(commands.Bot):
    def __init__(self):
        # Pas de commandes texte : slash-only
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.synced = False  # évite de sync plusieurs fois

    async def setup_hook(self):
        # Charger les Cogs
        await self.add_cog(AdminCog(self))
        await self.add_cog(SpeedCog(self))
        await self.add_cog(DiagCog(self))

        # Vues persistantes (custom_id fixes)
        # ⚠️ Ne pas enregistrer ProfileView ici (owner_id dynamique)
        self.add_view(StartFormView())

    async def on_ready(self):
        # Sync HYBRIDE : guild (immédiat) + global (multi-serveurs)
        if not self.synced:
            try:
                # 1) copie les commandes globales vers le guild pour effet instant
                self.tree.copy_global_to(guild=GUILD_OBJ)
                await self.tree.sync(guild=GUILD_OBJ)

                # 2) sync global (propagation plus lente)
                await self.tree.sync()

                self.synced = True
                print(f"[SYNC] Global+Guild OK pour {GUILD_ID}")
            except Exception as e:
                print(f"[SYNC] Échec de la sync: {e}")

        print(f"Connecté comme {self.user} (id={self.user.id})")
        activity = discord.Game(name="Miri Rencontre")
        await self.change_presence(status=discord.Status.online, activity=activity)

# -------------------- LANCEMENT --------------------
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN manquant dans l'env.")

bot = RencontreBot()
bot.run(DISCORD_TOKEN)
