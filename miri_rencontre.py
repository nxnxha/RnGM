# miri_rencontre.py — Miri Rencontre (Cogs + slash OK, ACK immédiat, reset admin)
# ✅ Slash commands stables via Cogs : /resetrencontre (admin), /resetprofil, /speeddating (staff)
# ✅ "Interaction failed" corrigé : ACK immédiat + restauration des vues persistantes au boot
# ✅ Création/édition du profil en DM + photo (upload ou URL)
# ✅ Tinder: Like / Pass / Match (+ DM aux deux)
# ✅ Logs horodatés [JJ/MM/AAAA HH:MM]
# ✅ Rôle Accès Rencontre ajouté en sécurité (si déjà présent → log)

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
GUILD_ID      = env_int("GUILD_ID",      1382730341944397967)
ROLE_ACCESS   = env_int("ROLE_ACCESS",   1401403405729267762)
CH_GIRLS      = env_int("CH_GIRLS",      1400520391793053841)
CH_BOYS       = env_int("CH_BOYS",       1400520396557521058)
CH_SPEED      = env_int("CH_SPEED",      1402665906546413679)
CH_LOGS       = env_int("CH_LOGS",       1403154919913033728)
CH_WELCOME    = env_int("CH_WELCOME",    0)
FIRST_MSG_LIMIT = env_int("FIRST_MSG_LIMIT", 1)
DATA_FILE     = os.getenv("DATA_FILE", "rencontre_data.json")
TZ = ZoneInfo("Europe/Paris")

# intents
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True  # pour lire les DM (photo/lien)

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
        self.data["profiles"].pop(str(uid), None)
        self.data["profile_msgs"].pop(str(uid), None)
        self.data["likes"].pop(str(uid), None)
        self.data["passes"].pop(str(uid), None)
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

# -------------------- State (photo après modal) --------------------
awaiting_photo: Dict[int, Dict[str, Any]] = {}  # uid -> {"profile":..., "is_edit": bool}

# -------------------- Views & Modals --------------------
class StartFormView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Créer mon profil", style=discord.ButtonStyle.success, custom_id="start_profile_btn")
    async def start_profile_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # ACK immédiat pour éviter le timeout
        await interaction.response.send_message("⏳ J’ouvre un DM avec toi…", ephemeral=True)
        ok = True
        try:
            dm = await interaction.user.create_dm()
            await dm.send(
                embed=discord.Embed(
                    title="Création de ton profil — DM",
                    description=(
                        "On va remplir le formulaire en **privé**.\n\n"
                        "1) Clique sur **Démarrer** pour ouvrir le formulaire (modal)\n"
                        "2) Ensuite, **envoie une photo** (upload ou lien) dans ce DM\n"
                        "3) Je publierai ton profil et je te donnerai le **rôle Accès Rencontre** ✅"
                    ),
                    color=discord.Color.purple()
                ),
                view=OpenModalView(is_edit=False)
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

class OpenModalView(discord.ui.View):
    def __init__(self, is_edit: bool):
        super().__init__(timeout=None)
        self.is_edit = is_edit

    @discord.ui.button(label="Démarrer", style=discord.ButtonStyle.primary, custom_id="open_modal_btn")
    async def open_modal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Ouvrir la Modal EST la réponse (ACK inclus)
        await interaction.response.send_modal(ProfilModal(is_edit=self.is_edit))

class ProfilModal(discord.ui.Modal, title="Profil — Formulaire"):
    def __init__(self, is_edit: bool):
        super().__init__(timeout=300)
        self.is_edit = is_edit
        self.age = discord.ui.TextInput(label="Âge (>=18)", min_length=1, max_length=3, placeholder="18")
        self.genre = discord.ui.TextInput(label="Genre (Fille/Homme)", min_length=1, max_length=10, placeholder="Fille")
        self.orientation = discord.ui.TextInput(label="Attirance", required=False, max_length=50, placeholder="Hétéro, Bi, etc.")
        self.passions = discord.ui.TextInput(label="Passions", required=False, style=discord.TextStyle.paragraph, max_length=300)
        self.activite = discord.ui.TextInput(label="Activité", required=False, max_length=100)

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

class ContactModal(discord.ui.Modal, title="Premier message"):
    def __init__(self, target_id: int):
        super().__init__(timeout=300)
        self.target_id = target_id
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
        try:
            dm = await target.create_dm()
            await dm.send(txt)
            await interaction.response.send_message("✅ Message envoyé en DM à la personne.", ephemeral=True)
            log_line(guild, f"📨 Contact : {author} ({author.id}) → {target} ({target.id})")
        except Exception:
            await interaction.response.send_message("⚠️ Impossible d’envoyer le DM (DM fermés ?).", ephemeral=True)
            log_line(guild, f"⚠️ Contact raté (DM fermés) : {author} ({author.id}) → {target} ({target.id})")

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
        await interaction.response.send_modal(ContactModal(target_id=self.owner_id))  # Modal = ACK inclus

    @discord.ui.button(emoji="✏️", label="Modifier", style=discord.ButtonStyle.secondary, custom_id="pf_edit")
    async def edit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("⏳ J’ouvre un DM pour modifier ton profil…", ephemeral=True)
        if not allowed_to_manage(interaction, self.owner_id):
            await interaction.edit_original_response(content="❌ Tu ne peux pas modifier ce profil.")
            return
        prof = storage.get_profile(self.owner_id)
        if not prof:
            await interaction.edit_original_response(content="Profil introuvable.")
            return
        ok = True
        try:
            dm = await interaction.user.create_dm()
            await dm.send("✏️ Ouvre ce formulaire pour modifier ton profil :", delete_after=120)
            await dm.send(view=OpenModalView(is_edit=True))
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

# -------------------- BOT --------------------
class RencontreBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.synced = False

    async def setup_hook(self):
        # Vues persistantes globales
        self.add_view(StartFormView())
        self.add_view(OpenModalView(is_edit=False))
        self.add_view(OpenModalView(is_edit=True))

        # 🔁 Restaurer les vues des profils publiés (après reboot)
        try:
            for uid_str, ref in storage.data.get("profile_msgs", {}).items():
                owner_id = int(uid_str)
                message_id = int(ref.get("message_id", 0))
                if message_id:
                    self.add_view(ProfileView(owner_id=owner_id), message_id=message_id)
        except Exception as e:
            print("[Persistent views restore error]", e)

        # Ajouter les Cogs (slash commands)
        self.add_cog(AdminCog(self))
        self.add_cog(SpeedCog(self))

        # Sync des slash sur le guild (plus rapide)
        try:
            if GUILD_ID:
                await self.tree.sync(guild=discord.Object(id=GUILD_ID))
            else:
                await self.tree.sync()
        except Exception as e:
            print("[Slash sync error]", e)

    async def on_ready(self):
        print(f"✅ Connecté en tant que {self.user} ({self.user.id})")
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

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        # Handler global des erreurs slash
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
        # Gestion de la photo en DM après le formulaire
        if isinstance(message.channel, discord.DMChannel):
            uid = message.author.id
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

                # Donner le rôle accès si création — sécurisé
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
                                log_line(guild, f"⚠️ Permissions insuffisantes pour donner {role.name} à {member} ({member.id}). "
                                                f"Vérifie Manage Roles et hiérarchie du rôle du bot > {role.name}")
                            except discord.HTTPException as e:
                                log_line(guild, f"⚠️ Erreur HTTP rôle {role.name} → {member} ({member.id}) : {e}")

                if is_edit:
                    log_line(guild, f"✏️ Édition (photo {'changée' if photo_url else 'inchangée'}) : {member} ({member.id})")
                    await message.channel.send("✅ Profil mis à jour.")
                else:
                    log_line(guild, f"✅ Création profil : {member} ({member.id})")
                    await message.channel.send("✅ Profil créé. Bienvenue dans l’Espace Rencontre !")

# -------------------- COGS: Admin & Staff --------------------
class AdminCog(commands.Cog, name="Admin"):
    """Slash admin/user: resetrencontre, resetprofil"""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

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
                "• Les anciens messages de profils n’auront plus de boutons valides (supprime-les si besoin).\n"
                "• Les membres peuvent recréer leur profil via le bouton.",
                ephemeral=True
            )
            log_line(interaction.guild, f"🗑️ Reset Rencontre (complet) par {interaction.user} ({interaction.user.id})")
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Erreur pendant le reset : {e}", ephemeral=True)

    @app_commands.command(name="resetprofil", description="🗑️ Supprime ton propre profil Rencontre")
    async def reset_profil(self, interaction: discord.Interaction):
        uid = interaction.user.id
        had = storage.get_profile(uid) is not None
        storage.delete_profile_everywhere(uid)
        if had:
            await interaction.response.send_message(
                "🗑️ Ton profil a été supprimé. Utilise le bouton **Créer mon profil** pour recommencer.",
                ephemeral=True
            )
            log_line(interaction.guild, f"🗑️ Profil reset par {interaction.user} ({interaction.user.id})")
        else:
            await interaction.response.send_message("ℹ️ Tu n’avais pas encore de profil enregistré.", ephemeral=True)

class SpeedCog(commands.Cog, name="SpeedDating"):
    """Slash staff: speeddating"""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

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

# -------------------- Entrée --------------------
bot = RencontreBot()

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN est requis (mets-le en variable d’environnement).")
    bot.run(DISCORD_TOKEN)
