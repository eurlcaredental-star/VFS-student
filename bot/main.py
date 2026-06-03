#!/usr/bin/env python3
"""
VFS GLOBAL ITALY VISA MONITOR — ALGERIA
Bot Telegram qui surveille les rendez-vous VFS Global pour le visa étudiant Italie.
"""

import asyncio
import logging
import os
import sys
from datetime import datetime
from typing import Optional

import pytz
from telegram import (
    Update, BotCommand, BotCommandScopeChat, BotCommandScopeDefault,
    InlineKeyboardButton, InlineKeyboardMarkup,
    MenuButtonCommands, ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

sys.path.insert(0, os.path.dirname(__file__))

from config import TELEGRAM_BOT_TOKEN, CENTERS, TIMEZONE, ADMIN_USER_IDS
from database import (
    init_db, add_or_update_user, subscribe_to_center, unsubscribe_from_center,
    get_user_subscriptions, get_center_status, get_historical_events, get_stats,
    toggle_briefing, get_all_users_detailed, get_user_detail,
    get_subs_per_center, ban_user, get_all_active_users
)
from vfs_monitor import check_appointments_via_web
from predictions import build_predictions, format_predictions_message, get_next_likely_opening
from briefing import (
    get_daily_briefing, get_full_visa_guide, get_financial_guide,
    get_life_guide, get_document_checklist, get_daily_tip
)
from scheduler import setup_scheduler, check_and_alert, send_message_safe

_log_handlers = [logging.StreamHandler(sys.stdout)]
_log_file = os.path.join(os.path.dirname(__file__), "bot.log")
try:
    _log_handlers.append(logging.FileHandler(_log_file, encoding="utf-8"))
except Exception:
    pass

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    level=logging.INFO,
    handlers=_log_handlers
)
logger = logging.getLogger(__name__)
TZ = pytz.timezone(TIMEZONE)

BOT_VERSION = "2.0.0"
BOT_NAME = "VFS Italy Monitor 🇮🇹"


def center_keyboard(action: str, selected_codes: list = None) -> InlineKeyboardMarkup:
    """Build inline keyboard for center selection"""
    buttons = []
    row = []

    for code, info in CENTERS.items():
        selected = selected_codes and code in selected_codes
        label = f"✅ {info['flag']} {info['name']}" if selected else f"{info['flag']} {info['name']}"
        row.append(InlineKeyboardButton(label, callback_data=f"{action}:{code}"))

        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    if action == "sub":
        buttons.append([InlineKeyboardButton("✅ Tous les centres", callback_data="sub:ALL")])
    elif action == "unsub":
        buttons.append([InlineKeyboardButton("❌ Se désabonner de tout", callback_data="unsub:ALL")])

    return InlineKeyboardMarkup(buttons)


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Build persistent reply keyboard"""
    keyboard = [
        [KeyboardButton("🔔 Mes alertes"), KeyboardButton("📊 Statut VFS")],
        [KeyboardButton("🔮 Prédictions"), KeyboardButton("📋 Guide visa")],
        [KeyboardButton("💡 Conseil du jour"), KeyboardButton("❓ Aide")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await add_or_update_user(
        user.id, user.username, user.first_name,
        user.language_code or "fr"
    )

    welcome = f"""
🇮🇹 *Bienvenue sur VFS Italy Monitor !*

Salut *{user.first_name}* ! 👋

Je surveille les créneaux de rendez-vous VFS Global pour le *Visa Étudiant Italie* (Long Stay) en Algérie — *24h/24, 7j/7*.

━━━━━━━━━━━━━━━━━━━━

🔔 *Ce que je fais pour toi :*
• Vérification automatique toutes les 2 minutes
• Alerte instantanée dès qu'un créneau s'ouvre
• Prédictions des meilleures dates d'ouverture
• Briefing quotidien avec conseils visa
• Guide complet pour préparer ton dossier

━━━━━━━━━━━━━━━━━━━━

🚀 *Par où commencer ?*
1. /subscribe — Choisir ton centre VFS à surveiller
2. /status — Voir la disponibilité actuelle
3. /prediction — Voir les prédictions

Ou utilise le menu ci-dessous 👇
""".strip()

    await update.message.reply_text(
        welcome,
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )

    info_msg = """
📋 *Centres disponibles en Algérie :*

🏙️ Alger (Algiers)
🏛️ Constantine
🌊 Oran
🌿 Annaba
🕌 Tlemcen

Catégorie surveillée : *Long Stay → Students - Long Stay*

👉 Tape /subscribe pour commencer !
""".strip()

    await update.message.reply_text(info_msg, parse_mode="Markdown")


async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await add_or_update_user(user.id, user.username, user.first_name)

    current_subs = await get_user_subscriptions(user.id)

    msg = """
🔔 *S'abonner aux alertes VFS*

Choisis le(s) centre(s) que tu veux surveiller.
Tu recevras une alerte dès qu'un créneau s'ouvre !

✅ = Déjà abonné
""".strip()

    await update.message.reply_text(
        msg,
        parse_mode="Markdown",
        reply_markup=center_keyboard("sub", current_subs)
    )


async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    current_subs = await get_user_subscriptions(user.id)

    if not current_subs:
        await update.message.reply_text(
            "ℹ️ Tu n'es abonné à aucun centre pour le moment.\nUtilise /subscribe pour t'abonner.",
            parse_mode="Markdown"
        )
        return

    msg = "❌ *Se désabonner*\n\nChoisis les centres à supprimer de tes alertes :"

    await update.message.reply_text(
        msg,
        parse_mode="Markdown",
        reply_markup=center_keyboard("unsub", current_subs)
    )


async def cmd_mycenters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    subs = await get_user_subscriptions(user.id)

    if not subs:
        await update.message.reply_text(
            "📭 *Tu n'es abonné à aucun centre.*\n\nUtilise /subscribe pour choisir un centre !",
            parse_mode="Markdown"
        )
        return

    lines = ["📋 *Tes centres surveillés :*\n"]
    for code in subs:
        info = CENTERS.get(code, {})
        lines.append(f"✅ {info.get('flag', '📍')} *{info.get('name', code)}* ({info.get('region', '')})")

    lines.append("\n_Tu recevras une alerte dès qu'un créneau s'ouvre dans ces centres._")
    lines.append("\n/subscribe pour modifier • /unsubscribe pour retirer")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔍 Vérification en cours... Cela peut prendre quelques secondes.")

    lines = ["📊 *STATUT VFS GLOBAL — ITALIE ALGÉRIE*\n"]
    lines.append(f"_Vérifié le {datetime.now(TZ).strftime('%d/%m/%Y à %H:%M')} (heure Alger)_\n")
    lines.append("━━━━━━━━━━━━━━━━━━━━\n")

    for code, info in CENTERS.items():
        try:
            has_slots, count, earliest = await check_appointments_via_web(code)
            status_emoji = "✅" if has_slots else "❌"
            slots_info = f" ({count} créneaux)" if has_slots and count > 0 else ""
            date_info = f"\n   📅 Dispo : {earliest}" if has_slots and earliest else ""

            lines.append(
                f"{info['flag']} *{info['name']}*\n"
                f"   {status_emoji} {'DISPONIBLE' + slots_info if has_slots else 'Aucun créneau'}"
                f"{date_info}\n"
            )
        except Exception as e:
            lines.append(f"{info['flag']} *{info['name']}*\n   ⚠️ Erreur de vérification\n")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("🔄 Vérification automatique toutes les 2 minutes")
    lines.append("🔔 /subscribe pour recevoir les alertes")

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


async def cmd_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    center_code = None

    if args and args[0].upper() in CENTERS:
        center_code = args[0].upper()

    if not center_code:
        buttons = []
        row = []
        for code, info in CENTERS.items():
            row.append(InlineKeyboardButton(f"{info['flag']} {info['name']}", callback_data=f"pred:{code}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton("🌍 Tous les centres", callback_data="pred:ALL")])

        await update.message.reply_text(
            "🔮 *Prédictions d'ouverture*\n\nChoisis un centre :",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    await _show_prediction(update.message, center_code)


async def _show_prediction(message, center_code: str):
    if center_code == "ALL":
        events = await get_historical_events(limit=500)
    else:
        events = await get_historical_events(center_code=center_code, limit=200)

    predictions = build_predictions(events, center_code if center_code != "ALL" else None)
    text = format_predictions_message(predictions, center_code if center_code != "ALL" else None)

    next_opening = get_next_likely_opening(predictions)
    text += f"\n\n⏳ *Prochaine ouverture estimée :*\n{next_opening}"

    try:
        await message.reply_text(text, parse_mode="Markdown")
    except Exception:
        await message.reply_text(text.replace("*", "").replace("_", ""))


async def cmd_guide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Étapes du visa", callback_data="guide:process"),
            InlineKeyboardButton("💰 Justificatifs financiers", callback_data="guide:financial"),
        ],
        [
            InlineKeyboardButton("🏠 Vie en Italie", callback_data="guide:life"),
            InlineKeyboardButton("📁 Checklist documents", callback_data="guide:checklist"),
        ],
    ])

    await update.message.reply_text(
        "📚 *Guide Visa Étudiant Italie*\n\nChoisis une section :",
        parse_mode="Markdown",
        reply_markup=keyboard
    )


async def cmd_briefing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = get_daily_briefing(user.first_name or "cher(e) étudiant(e)")
    await update.message.reply_text(message, parse_mode="Markdown")


async def cmd_tip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tip = get_daily_tip()
    await update.message.reply_text(
        f"💡 *Conseil du jour :*\n\n{tip}",
        parse_mode="Markdown"
    )


async def cmd_togglebriefing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    if args and args[0].lower() in ("off", "0", "non", "stop"):
        await toggle_briefing(user.id, False)
        await update.message.reply_text(
            "🔕 *Briefing quotidien désactivé.*\n\nTu ne recevras plus les briefings du matin.\n/briefing_on pour réactiver.",
            parse_mode="Markdown"
        )
    else:
        await toggle_briefing(user.id, True)
        await update.message.reply_text(
            f"🔔 *Briefing quotidien activé !*\n\nTu recevras un briefing chaque matin à *09h00* (heure Alger).\n/briefing_off pour désactiver.",
            parse_mode="Markdown"
        )


async def cmd_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔍 Vérification du système en cours...")

    checks = []

    try:
        from database import get_stats
        stats = await get_stats()
        checks.append(f"✅ Base de données OK\n   👥 {stats['total_users']} utilisateurs • 📊 {stats['total_subscriptions']} abonnements")
    except Exception as e:
        checks.append(f"❌ Base de données: {e}")

    try:
        from vfs_monitor import check_appointments_via_web
        has_slots, count, earliest = await check_appointments_via_web("ALGIERS")
        checks.append(f"✅ Connexion VFS OK\n   Centre Alger: {'créneau disponible !' if has_slots else 'aucun créneau'}")
    except Exception as e:
        checks.append(f"⚠️ Connexion VFS: {e}")

    try:
        from scheduler import get_scheduler
        sched = get_scheduler()
        if sched and sched.running:
            jobs = sched.get_jobs()
            checks.append(f"✅ Planificateur OK\n   {len(jobs)} tâches actives")
        else:
            checks.append("⚠️ Planificateur non démarré")
    except Exception as e:
        checks.append(f"❌ Planificateur: {e}")

    now = datetime.now(TZ)
    checks.append(f"✅ Heure système: {now.strftime('%d/%m/%Y %H:%M:%S')} (Alger)")

    report = f"""
🛠️ *VÉRIFICATION SYSTÈME*

{"──────────────────────".join([''])}
{chr(10).join(checks)}
━━━━━━━━━━━━━━━━━━━━
🤖 *{BOT_NAME}* v{BOT_VERSION}
Fréquence de vérification : toutes les **2 minutes**
""".strip()

    await msg.edit_text(report, parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = f"""
🤖 *{BOT_NAME}* — Aide

━━━━━━━━━━━━━━━━━━━━

📡 *Surveillance & Alertes*
/subscribe — S'abonner aux alertes d'un centre
/unsubscribe — Se désabonner d'un centre
/mycenters — Voir mes abonnements
/status — Vérifier les créneaux maintenant

━━━━━━━━━━━━━━━━━━━━

🔮 *Prédictions*
/prediction — Voir quand les créneaux ouvrent
/prediction ALGIERS — Prédiction pour Alger
/prediction ORAN — Prédiction pour Oran
_(centres : ALGIERS, CONSTANTINE, ORAN, ANNABA, TLEMCEN)_

━━━━━━━━━━━━━━━━━━━━

📚 *Guide & Conseils*
/guide — Guide complet visa étudiant
/briefing — Briefing quotidien
/tip — Conseil du jour
/briefing\_on — Activer le briefing quotidien
/briefing\_off — Désactiver le briefing quotidien

━━━━━━━━━━━━━━━━━━━━

🛠️ *Système*
/verify — Vérifier que le bot fonctionne
/start — Recommencer depuis le début
/help — Cette aide

━━━━━━━━━━━━━━━━━━━━

🌐 *Lien VFS Global :*
visa.vfsglobal.com/dza/en/ita

Catégorie : Long Stay → Students - Long Stay
""".strip()

    await update.message.reply_text(help_text, parse_mode="Markdown", disable_web_page_preview=True)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    data = query.data

    if ":" not in data:
        return

    parts = data.split(":", 2)
    action = parts[0]
    value = parts[1] if len(parts) > 1 else ""
    extra = parts[2] if len(parts) > 2 else ""

    if action in ("bc_confirm", "bc_cancel"):
        # Obsolète — broadcast envoyé directement maintenant
        await query.edit_message_text("ℹ️ Utilise /broadcast pour envoyer un message.")
        return

    elif action == "admin":
        if not is_admin(user.id):
            await query.answer("⛔ Non autorisé", show_alert=True)
            return
        if value == "stats":
            await query.answer()
            await cmd_stats_from_query(query)
            return
        elif value == "check":
            await query.edit_message_text("🔍 Vérification VFS en cours...")
            from scheduler import check_and_alert as do_check
            await do_check()
            await query.edit_message_text("✅ Vérification terminée ! Résultats dans les logs.")
            return
        elif value == "broadcast_help":
            await query.edit_message_text(
                "📢 *Broadcast*\n\nUtilise la commande :\n`/broadcast Ton message ici`",
                parse_mode="Markdown"
            )
            return
        elif value == "logs":
            events = await get_historical_events(limit=5)
            if events:
                lines = ["📋 *5 dernières ouvertures détectées :*\n"]
                for e in events:
                    center = CENTERS.get(e["center_code"], {})
                    name = center.get("name", e["center_code"])
                    flag = center.get("flag", "📍")
                    try:
                        dt = datetime.fromisoformat(e["detected_at"])
                        date_str = dt.strftime("%d/%m/%Y %H:%M")
                    except Exception:
                        date_str = e["detected_at"]
                    lines.append(f"• {flag} *{name}* — {date_str}")
                await query.edit_message_text("\n".join(lines), parse_mode="Markdown")
            else:
                await query.edit_message_text("Aucune ouverture enregistrée pour le moment.")
            return
        elif value == "users":
            await query.edit_message_text("👥 Chargement...")
            users = await get_all_users_detailed()
            lines = [f"👥 *UTILISATEURS* ({len(users)} total)\n"]
            for u in users[:20]:
                uname = f"@{u['username']}" if u['username'] else "—"
                briefing_icon = "🔔" if u["receive_briefing"] else "🔕"
                sub_icon = f"📡{u['sub_count']}" if u["sub_count"] else "📭"
                lines.append(f"`{u['user_id']}` {briefing_icon}{sub_icon} *{u['first_name'] or '?'}* {uname}")
            if len(users) > 20:
                lines.append(f"_+{len(users)-20} autres — /users pour la liste complète_")
            await query.edit_message_text("\n".join(lines), parse_mode="Markdown")
            return
        elif value == "centers":
            await query.edit_message_text("📡 Chargement...")
            subs_per_center = await get_subs_per_center()
            events = await get_historical_events(limit=200)
            events_per_center = {}
            for e in events:
                c = e["center_code"]
                events_per_center[c] = events_per_center.get(c, 0) + 1
            lines = ["📡 *STATS PAR CENTRE*\n"]
            for code, info in CENTERS.items():
                subs = subs_per_center.get(code, 0)
                evts = events_per_center.get(code, 0)
                status = await get_center_status(code)
                ind = "🟢" if (status and status["has_slots"]) else "🔴"
                lines.append(f"{ind} {info['flag']} *{info['name']}* — {subs} abonnés • {evts} ouvertures")
            await query.edit_message_text("\n".join(lines), parse_mode="Markdown")
            return

    if action == "sub":
        if value == "ALL":
            for code in CENTERS.keys():
                await subscribe_to_center(user.id, code)
            subs = list(CENTERS.keys())
            names = ", ".join(CENTERS[c]["name"] for c in subs)
            await query.edit_message_text(
                f"✅ *Abonné à tous les centres !*\n\n{names}\n\nTu recevras des alertes pour tous les centres.",
                parse_mode="Markdown"
            )
        else:
            center = CENTERS.get(value)
            if center:
                await subscribe_to_center(user.id, value)
                current_subs = await get_user_subscriptions(user.id)

                await query.edit_message_text(
                    f"✅ *Abonné à {center['flag']} {center['name']} !*\n\nTu recevras une alerte dès qu'un créneau s'ouvre.\n\nAbonnements actifs : {len(current_subs)} centre(s)",
                    parse_mode="Markdown",
                    reply_markup=center_keyboard("sub", current_subs)
                )

    elif action == "unsub":
        if value == "ALL":
            for code in CENTERS.keys():
                await unsubscribe_from_center(user.id, code)
            await query.edit_message_text(
                "✅ *Désabonné de tous les centres.*\n\nUtilise /subscribe pour te réabonner.",
                parse_mode="Markdown"
            )
        else:
            center = CENTERS.get(value)
            if center:
                await unsubscribe_from_center(user.id, value)
                current_subs = await get_user_subscriptions(user.id)
                await query.edit_message_text(
                    f"❌ *Désabonné de {center['name']}.*\n\nAbonnements restants : {len(current_subs)} centre(s)",
                    parse_mode="Markdown",
                    reply_markup=center_keyboard("unsub", current_subs) if current_subs else None
                )

    elif action == "pred":
        await query.edit_message_text("🔮 Calcul des prédictions en cours...")
        events = await get_historical_events(
            center_code=value if value != "ALL" else None,
            limit=200
        )
        predictions = build_predictions(events, value if value != "ALL" else None)
        text = format_predictions_message(predictions, value if value != "ALL" else None)
        next_opening = get_next_likely_opening(predictions)
        text += f"\n\n⏳ *Prochaine ouverture estimée :*\n{next_opening}"
        try:
            await query.edit_message_text(text, parse_mode="Markdown")
        except Exception:
            await query.edit_message_text(text.replace("*", "").replace("_", ""))

    elif action == "guide":
        if value == "process":
            text = get_full_visa_guide()
        elif value == "financial":
            text = get_financial_guide()
        elif value == "life":
            text = get_life_guide()
        elif value == "checklist":
            text = get_document_checklist()
        else:
            text = "Section non trouvée."

        back_button = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Retour au guide", callback_data="guide:menu")]
        ])

        # Telegram limite à 4096 caractères — tronquer si nécessaire
        if len(text) > 4000:
            text = text[:3997] + "…"
        try:
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=back_button)
        except Exception:
            try:
                plain = text.replace("*", "").replace("_", "").replace("`", "")
                await query.edit_message_text(plain[:4000], reply_markup=back_button)
            except Exception as e:
                logger.error(f"Guide edit failed: {e}")
                await query.answer("Erreur d'affichage — réessaie.", show_alert=True)

    elif action == "guide" and value == "menu":
        await cmd_guide_from_callback(query)


async def cmd_guide_from_callback(query):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Étapes du visa", callback_data="guide:process"),
            InlineKeyboardButton("💰 Finances", callback_data="guide:financial"),
        ],
        [
            InlineKeyboardButton("🏠 Vie en Italie", callback_data="guide:life"),
            InlineKeyboardButton("📁 Checklist", callback_data="guide:checklist"),
        ],
    ])
    await query.edit_message_text(
        "📚 *Guide Visa Étudiant Italie*\n\nChoisis une section :",
        parse_mode="Markdown",
        reply_markup=keyboard
    )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle persistent keyboard button presses and conversational states."""
    text = update.message.text
    user = update.effective_user

    # ── Admin broadcast conversationnel ─────────────────────────────────────
    if is_admin(user.id) and context.user_data.get("awaiting_broadcast"):
        context.user_data["awaiting_broadcast"] = False
        await _do_broadcast(update, text, send_bot=context.bot)
        return

    # ── Boutons du clavier persistant ───────────────────────────────────────
    if text == "🔔 Mes alertes":
        await cmd_mycenters(update, context)
    elif text == "📊 Statut VFS":
        await cmd_status(update, context)
    elif text == "🔮 Prédictions":
        await cmd_prediction(update, context)
    elif text == "📋 Guide visa":
        await cmd_guide(update, context)
    elif text == "💡 Conseil du jour":
        await cmd_tip(update, context)
    elif text == "❓ Aide":
        await cmd_help(update, context)


HARDCODED_ADMIN_ID = 1077263521  # anasfks — permanent, immuable

def is_admin(user_id: int) -> bool:
    if user_id == HARDCODED_ADMIN_ID:
        return True
    # Re-lit l'env var à chaque appel pour éviter les problèmes de redémarrage
    raw = os.getenv("ADMIN_USER_IDS", "")
    live_ids = [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]
    return user_id in live_ids


async def _build_stats_text() -> str:
    stats = await get_stats()
    events = await get_historical_events(limit=10)
    center_status_lines = []
    for code, info in CENTERS.items():
        status = await get_center_status(code)
        if status:
            last = status["last_checked"] or "jamais"
            try:
                dt = datetime.fromisoformat(last)
                last = dt.strftime("%d/%m %H:%M")
            except Exception:
                pass
            indicator = "🟢" if status["has_slots"] else "🔴"
            center_status_lines.append(f"  {indicator} {info['flag']} {info['name']} — vérifié {last}")
        else:
            center_status_lines.append(f"  ⚪ {info['flag']} {info['name']} — pas encore vérifié")
    from scheduler import get_scheduler
    sched = get_scheduler()
    sched_status = "✅ Actif" if sched and sched.running else "❌ Arrêté"
    return f"""📊 *STATISTIQUES ADMIN — VFS Italy Monitor*

━━━━━━━━━━━━━━━━━━━━
👥 *Utilisateurs*
   • Total actifs : *{stats['total_users']}*
   • Abonnements actifs : *{stats['total_subscriptions']}*

📡 *Monitoring*
   • Ouvertures détectées (total) : *{stats['total_slot_events']}*
   • Planificateur : {sched_status}

🏙️ *Statut des centres*
{"".join(chr(10) + l for l in center_status_lines)}

━━━━━━━━━━━━━━━━━━━━
🤖 *{BOT_NAME}* v{BOT_VERSION}
🕐 {datetime.now(TZ).strftime('%d/%m/%Y %H:%M:%S')}""".strip()


async def cmd_stats_from_query(query):
    text = await _build_stats_text()
    try:
        await query.edit_message_text(text, parse_mode="Markdown")
    except Exception:
        await query.edit_message_text(text.replace("*", "").replace("_", ""))


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Accès réservé à l'administrateur.")
        return

    msg = await update.message.reply_text("📊 Chargement des statistiques...")
    stats = await get_stats()
    events = await get_historical_events(limit=50)
    recent_centers = {}
    for e in events[:10]:
        c = e["center_code"]
        if c not in recent_centers:
            recent_centers[c] = e["detected_at"]

    center_status_lines = []
    for code, info in CENTERS.items():
        status = await get_center_status(code)
        if status:
            last = status["last_checked"] or "jamais"
            try:
                dt = datetime.fromisoformat(last)
                last = dt.strftime("%d/%m %H:%M")
            except Exception:
                pass
            indicator = "🟢" if status["has_slots"] else "🔴"
            center_status_lines.append(f"  {indicator} {info['flag']} {info['name']} — vérifié {last}")
        else:
            center_status_lines.append(f"  ⚪ {info['flag']} {info['name']} — pas encore vérifié")

    from scheduler import get_scheduler
    sched = get_scheduler()
    sched_status = "✅ Actif" if sched and sched.running else "❌ Arrêté"

    text = f"""
📊 *STATISTIQUES ADMIN — VFS Italy Monitor*

━━━━━━━━━━━━━━━━━━━━
👥 *Utilisateurs*
   • Total actifs : *{stats['total_users']}*
   • Abonnements actifs : *{stats['total_subscriptions']}*

📡 *Monitoring*
   • Ouvertures détectées (total) : *{stats['total_slot_events']}*
   • Planificateur : {sched_status}

🏙️ *Statut des centres*
{"".join(chr(10) + l for l in center_status_lines)}

━━━━━━━━━━━━━━━━━━━━
🤖 *{BOT_NAME}* v{BOT_VERSION}
🕐 {datetime.now(TZ).strftime('%d/%m/%Y %H:%M:%S')}
""".strip()

    await msg.edit_text(text, parse_mode="Markdown")


async def _do_broadcast(update: Update, message_text: str, send_bot=None):
    """Envoie le broadcast directement à tous les utilisateurs actifs."""
    try:
        users = await get_all_active_users()
    except Exception as db_err:
        logger.error(f"Broadcast DB error: {db_err}")
        await update.message.reply_text(
            f"❌ Erreur base de données :\n<code>{db_err}</code>",
            parse_mode="HTML"
        )
        return

    if not users:
        await update.message.reply_text("❌ Aucun utilisateur actif trouvé dans la DB.")
        return

    status_msg = await update.message.reply_text(
        f"📢 Envoi en cours à {len(users)} utilisateur(s)..."
    )
    bot_to_use = send_bot or update.get_bot()
    sent, failed = 0, 0
    for uid, _ in users:
        try:
            await bot_to_use.send_message(chat_id=uid, text=message_text)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Broadcast failed for {uid}: {e}")
            failed += 1

    try:
        await status_msg.edit_text(
            f"✅ Message envoyé !\n\n"
            f"✉️ Reçu par : {sent} utilisateur(s)\n"
            f"❌ Échecs : {failed}"
        )
    except Exception:
        await update.message.reply_text(
            f"✅ Broadcast terminé : {sent} envoyés, {failed} échecs"
        )


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Accès réservé à l'administrateur.")
        return

    if context.args:
        # Message fourni directement : /broadcast Votre texte
        await _do_broadcast(update, " ".join(context.args), send_bot=context.bot)
        return

    # Mode conversationnel : demander le message
    context.user_data["awaiting_broadcast"] = True
    await update.message.reply_text(
        "📢 Tape ton message ci-dessous :\n"
        "(Le bot l'enverra à tous les utilisateurs dès que tu l'envoies)"
    )


async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"🆔 *Ton ID Telegram*\n\n"
        f"`{user.id}`\n\n"
        f"Copie ce numéro et ajoute-le dans la variable `ADMIN_USER_IDS` sur Railway.",
        parse_mode="Markdown"
    )


def _esc(text: str) -> str:
    """Escape special Markdown v1 characters in user-provided text."""
    if not text:
        return "?"
    for ch in ["*", "_", "`", "["]:
        text = text.replace(ch, f"\\{ch}")
    return text


async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    msg = await update.message.reply_text("👥 Chargement des utilisateurs...")
    users = await get_all_users_detailed()
    if not users:
        await msg.edit_text(f"👥 Aucun utilisateur enregistré pour l'instant.")
        return

    lines = [f"👥 LISTE DES UTILISATEURS ({len(users)} total)\n"]
    for u in users[:30]:
        uname = f"@{u['username']}" if u['username'] else "-"
        try:
            joined = datetime.fromisoformat(u["joined_at"]).strftime("%d/%m/%y")
        except Exception:
            joined = "?"
        briefing_icon = "🔔" if u["receive_briefing"] else "🔕"
        sub_icon = f"📡{u['sub_count']}" if u["sub_count"] else "📭"
        name = (u['first_name'] or '?')[:20]
        lines.append(
            f"{u['user_id']} {briefing_icon}{sub_icon} {name} {uname} — {joined}"
        )
    if len(users) > 30:
        lines.append(f"\n...et {len(users)-30} autres.")
    lines.append(f"\n/userdata ID — pour les détails")
    # Texte simple sans Markdown pour éviter les erreurs de parsing
    await msg.edit_text("\n".join(lines))


async def cmd_userdata(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage : `/userdata <telegram_id>`", parse_mode="Markdown")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID invalide — doit être un nombre.")
        return

    user = await get_user_detail(uid)
    if not user:
        await update.message.reply_text(f"❌ Utilisateur `{uid}` non trouvé.", parse_mode="Markdown")
        return

    try:
        joined = datetime.fromisoformat(user["joined_at"]).strftime("%d/%m/%Y %H:%M")
    except Exception:
        joined = user["joined_at"]
    try:
        last = datetime.fromisoformat(user["last_active"]).strftime("%d/%m/%Y %H:%M")
    except Exception:
        last = user["last_active"]

    subs = user["subscriptions"]
    sub_lines = ""
    if subs:
        for s in subs:
            c = CENTERS.get(s["center"], {})
            sub_lines += f"\n   • {c.get('flag','📍')} {c.get('name', s['center'])}"
    else:
        sub_lines = "\n   Aucun abonnement"

    text = f"""
👤 *DONNÉES UTILISATEUR*

🆔 ID Telegram : `{user['user_id']}`
👤 Nom : *{user['first_name'] or '?'}*
🔗 Username : {'@' + user['username'] if user['username'] else '—'}
🌐 Langue : {user['language_code'] or '?'}
📅 Inscrit : {joined}
🕐 Dernier actif : {last}
🔔 Briefing : {'Activé' if user['receive_briefing'] else 'Désactivé'}
✅ Compte actif : {'Oui' if user['is_active'] else 'Non'}

📡 *Abonnements :*{sub_lines}
""".strip()

    ban_btn = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"🚫 Bannir cet utilisateur", callback_data=f"admin_ban:{uid}")
    ]])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=ban_btn)


async def cmd_centers_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    subs_per_center = await get_subs_per_center()
    events = await get_historical_events(limit=200)

    events_per_center = {}
    for e in events:
        c = e["center_code"]
        events_per_center[c] = events_per_center.get(c, 0) + 1

    lines = ["📡 *STATS PAR CENTRE*\n"]
    for code, info in CENTERS.items():
        subs = subs_per_center.get(code, 0)
        evts = events_per_center.get(code, 0)
        status = await get_center_status(code)
        indicator = "🟢" if (status and status["has_slots"]) else "🔴"
        last_open = status["last_available"] if status and status["last_available"] else "jamais"
        try:
            last_open = datetime.fromisoformat(last_open).strftime("%d/%m/%Y %H:%M")
        except Exception:
            pass
        lines.append(
            f"{indicator} {info['flag']} *{info['name']}*\n"
            f"   👥 {subs} abonnés • 📊 {evts} ouvertures détectées\n"
            f"   🕐 Dernière ouverture : {last_open}"
        )
    await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")


async def cmd_forcecheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    msg = await update.message.reply_text("🔍 Vérification forcée de tous les centres...")
    from scheduler import check_and_alert as do_check
    await do_check()
    await msg.edit_text(
        "✅ *Vérification terminée !*\n\nLes abonnés ont été notifiés si des créneaux sont disponibles.",
        parse_mode="Markdown"
    )


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Accès réservé à l'administrateur.")
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Statistiques", callback_data="admin:stats"),
            InlineKeyboardButton("🔍 Check VFS maintenant", callback_data="admin:check"),
        ],
        [
            InlineKeyboardButton("👥 Utilisateurs", callback_data="admin:users"),
            InlineKeyboardButton("📡 Stats centres", callback_data="admin:centers"),
        ],
        [
            InlineKeyboardButton("📢 Broadcast", callback_data="admin:broadcast_help"),
            InlineKeyboardButton("📋 Dernières ouvertures", callback_data="admin:logs"),
        ],
    ])

    await update.message.reply_text(
        f"🔧 *PANNEAU ADMIN*\n\n"
        f"Bienvenue, *{update.effective_user.first_name}* !\n\n"
        f"🤖 Bot actif • Surveillance toutes les 2 min",
        parse_mode="Markdown",
        reply_markup=keyboard
    )


async def post_init(application: Application):
    """Setup bot after init"""
    await init_db()
    logger.info("Database initialized")

    user_commands = [
        BotCommand("start", "🚀 Démarrer le bot"),
        BotCommand("subscribe", "🔔 S'abonner aux alertes"),
        BotCommand("unsubscribe", "🔕 Se désabonner"),
        BotCommand("mycenters", "📋 Mes centres surveillés"),
        BotCommand("status", "📊 Statut actuel VFS"),
        BotCommand("prediction", "🔮 Prédictions d'ouverture"),
        BotCommand("briefing", "☀️ Briefing quotidien"),
        BotCommand("guide", "📚 Guide visa étudiant"),
        BotCommand("tip", "💡 Conseil du jour"),
        BotCommand("briefing_on", "🔔 Activer le briefing matin"),
        BotCommand("briefing_off", "🔕 Désactiver le briefing"),
        BotCommand("help", "❓ Aide & commandes"),
    ]

    admin_only_commands = [
        BotCommand("admin", "🔧 Panneau admin"),
        BotCommand("stats", "📊 Statistiques du bot"),
        BotCommand("users", "👥 Liste des utilisateurs"),
        BotCommand("userdata", "👤 Données d'un utilisateur"),
        BotCommand("centers_stats", "📡 Stats par centre"),
        BotCommand("forcecheck", "🔍 Vérification VFS forcée"),
        BotCommand("broadcast", "📢 Message à tous"),
    ]

    await application.bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())

    for admin_id in ADMIN_USER_IDS:
        try:
            await application.bot.set_my_commands(
                user_commands + admin_only_commands,
                scope=BotCommandScopeChat(chat_id=admin_id)
            )
            logger.info(f"Admin commands set for user {admin_id}")
        except Exception as e:
            logger.warning(f"Could not set admin commands for {admin_id}: {e}")

    await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    logger.info("Bot commands configured (user + admin scopes)")

    scheduler = setup_scheduler(application.bot)
    scheduler.start()
    logger.info(f"Scheduler started — checking every {120}s")

    asyncio.create_task(check_and_alert())
    logger.info("Initial VFS check triggered")


def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN not set!")
        sys.exit(1)

    # Empêcher le conflit 409 : si on tourne sur Replit (pas Railway), ne pas démarrer
    on_railway = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_SERVICE_ID"))
    on_replit = bool(os.getenv("REPL_ID") or os.getenv("REPLIT_DEPLOYMENT"))
    if on_replit and not on_railway:
        logger.warning("Instance Replit détectée — bot désactivé localement pour éviter le conflit avec Railway.")
        logger.warning("Le bot tourne sur Railway. Cette instance locale est arrêtée.")
        print("\n" + "="*60)
        print("⚠️  BOT DÉSACTIVÉ LOCALEMENT")
        print("Le bot tourne sur Railway (production).")
        print("Deux instances = conflit Telegram 409.")
        print("Cette instance Replit est arrêtée automatiquement.")
        print("="*60 + "\n")
        sys.exit(0)

    logger.info(f"Starting {BOT_NAME} v{BOT_VERSION}")
    logger.info(f"Monitoring centers: {', '.join(CENTERS.keys())}")

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CommandHandler("mycenters", cmd_mycenters))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("prediction", cmd_prediction))
    app.add_handler(CommandHandler("briefing", cmd_briefing))
    app.add_handler(CommandHandler("guide", cmd_guide))
    app.add_handler(CommandHandler("tip", cmd_tip))
    app.add_handler(CommandHandler("verify", cmd_verify))
    app.add_handler(CommandHandler("briefing_on", lambda u, c: cmd_togglebriefing(u, c)))
    app.add_handler(CommandHandler("briefing_off", lambda u, c: cmd_togglebriefing(u, c)))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CommandHandler("userdata", cmd_userdata))
    app.add_handler(CommandHandler("centers_stats", cmd_centers_stats))
    app.add_handler(CommandHandler("forcecheck", cmd_forcecheck))
    app.add_handler(CommandHandler("myid", cmd_myid))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    logger.info("Bot is running... Press Ctrl+C to stop.")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )
async def check_appointments_via_web(center_code: str):
    """Alias pour compatibilité avec main.py"""
    results = await check_all_centers()

    r = results.get(center_code, {})
    return r.get("has_slots", False), r.get("count", 0), r.get("earliest")

if __name__ == "__main__":
    main()
    
    
