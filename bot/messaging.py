"""
Système de messagerie Admin ↔ Utilisateurs
Permet aux utilisateurs de contacter l'admin via le bot.
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_USER_IDS

logger = logging.getLogger(__name__)

# Mapping: (chat_id, message_id) → user_id pour les réponses admin
_reply_map: dict = {}


async def forward_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Transfère un message utilisateur à tous les admins."""
    user = update.effective_user
    text = update.message.text

    username_part = f" (@{user.username})" if user.username else ""
    msg = (
        f"📩 *Message de {user.first_name}*{username_part}\n"
        f"🆔 ID: `{user.id}`\n\n"
        f"💬 {text}\n\n"
        f"_Répondez à ce message pour répondre à l'utilisateur._"
    )

    for admin_id in ADMIN_USER_IDS:
        try:
            sent = await context.bot.send_message(
                chat_id=admin_id,
                text=msg,
                parse_mode="Markdown"
            )
            # Stocker le mapping message_id → user_id
            _reply_map[(admin_id, sent.message_id)] = user.id
            logger.info(f"Message de {user.id} transféré à admin {admin_id}")
        except Exception as e:
            logger.error(f"Erreur transfert à admin {admin_id}: {e}")


async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Gère la réponse d'un admin à un message transféré.
    Retourne True si c'était une réponse admin, False sinon.
    """
    message = update.message
    if not message:
        return False

    # Vérifier que c'est un admin
    if update.effective_user.id not in ADMIN_USER_IDS:
        return False

    # Vérifier que c'est une réponse à un message
    if not message.reply_to_message:
        return False

    admin_id = message.chat_id
    reply_to_id = message.reply_to_message.message_id

    # Chercher le user_id dans le mapping
    user_id = _reply_map.get((admin_id, reply_to_id))
    if not user_id:
        return False

    # Envoyer la réponse à l'utilisateur
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"💬 *Réponse du support :*\n\n{message.text}",
            parse_mode="Markdown"
        )
        await message.reply_text("✅ Réponse envoyée à l'utilisateur.")
        logger.info(f"Réponse admin envoyée à user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Erreur envoi réponse à {user_id}: {e}")
        await message.reply_text(f"❌ Erreur : impossible d'envoyer la réponse.")
        return False


async def cmd_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /contact pour les utilisateurs."""
    await update.message.reply_text(
        "📩 *Contacter le support*\n\n"
        "Écrivez votre message et il sera transmis à l'administrateur.\n"
        "Vous recevrez une réponse dès que possible.",
        parse_mode="Markdown"
    )
