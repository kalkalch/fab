"""
Telegram bot handlers for FAB.

Contains message handlers, callback handlers, and command processors
for the Telegram bot interface.
"""

import logging
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from ..config import config
from ..models import access as access_module
from ..utils.rabbitmq import rabbitmq_service
from ..utils.i18n import i18n
from ..db.manager import db_manager

logger = logging.getLogger(__name__)


def get_user_language(user_id: int, user_language_code: Optional[str]) -> str:
    """Get user's preferred language - just auto-detect from Telegram for now."""
    return i18n.detect_language_from_code(user_language_code)


def is_user_authorized(user) -> bool:
    """Check if user is authorized to use the bot (admin or whitelist)."""
    if not user:
        return False
    
    try:
        return db_manager.is_user_authorized(user.id)
    except Exception as e:
        msg = str(e).lower()
        # Graceful degradation on startup or transient DB issues
        if "database not initialized" in msg or "closed database" in msg:
            logger.warning("Database temporarily unavailable, denying access temporarily")
            return False
        raise


def is_admin(user) -> bool:
    """Check if user is admin."""
    if not user:
        return False
    
    return db_manager.is_admin(user.id)



async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    user = update.effective_user
    chat_id = update.effective_chat.id

    logger.info(f"User {user.id} ({user.username}) started bot in chat {chat_id}")

    # Check if user is authorized
    if not is_user_authorized(user):
        logger.warning(f"Unauthorized user {user.id} attempted to use bot")
        # Get language for unauthorized message
        language = i18n.detect_language_from_code(user.language_code)
        i18n.set_language(language)
        
        await update.message.reply_text(
            i18n.get_text("bot.unauthorized", user_id=user.id)
        )
        return

    # Get user's preferred language (from database or auto-detect)
    language = get_user_language(user.id, user.language_code)
    i18n.set_language(language)
    
    welcome_text = i18n.get_text("bot.welcome")
    
    keyboard = [
        [InlineKeyboardButton(i18n.get_text("bot.add_access"), callback_data="add_access")],
        [InlineKeyboardButton(i18n.get_text("bot.my_accesses"), callback_data="my_access")],
        [InlineKeyboardButton(i18n.get_text("bot.help"), callback_data="help")]
    ]
    
    # Add admin commands if user is admin
    if is_admin(user):
        keyboard.append([InlineKeyboardButton(i18n.get_text("bot.manage_users"), callback_data="manage_users")])
    
    # Add language switch button (show opposite language)
    if language == "ru":
        keyboard.append([InlineKeyboardButton("🇺🇸 English", callback_data="set_language_en")])
    else:
        keyboard.append([InlineKeyboardButton("🇷🇺 Русский", callback_data="set_language_ru")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    user = update.effective_user
    
    # Check if user is authorized
    if not is_user_authorized(user):
        logger.warning(f"Unauthorized user {user.id} attempted to use /help")
        # Get language for unauthorized message
        language = i18n.detect_language_from_code(user.language_code)
        i18n.set_language(language)
        
        await update.message.reply_text(
            i18n.get_text("bot.unauthorized", user_id=user.id)
        )
        return
    
    # Get user's preferred language (from database or auto-detect)
    language = get_user_language(user.id, user.language_code)
    i18n.set_language(language)
    
    help_text = i18n.get_text("bot.help_text")
    
    keyboard = [
        [InlineKeyboardButton(i18n.get_text("bot.main_menu"), callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(help_text, reply_markup=reply_markup)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard button presses."""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    chat_id = query.message.chat_id
    data = query.data
    
    logger.info(f"User {user.id} pressed button: {data}")
    
    # Check if user is authorized
    if not is_user_authorized(user):
        logger.warning(f"Unauthorized user {user.id} attempted to use button: {data}")
        # Get language for unauthorized message
        language = i18n.detect_language_from_code(user.language_code)
        i18n.set_language(language)
        
        await query.edit_message_text(
            i18n.get_text("bot.unauthorized", user_id=user.id)
        )
        return
    
    if data == "add_access":
        await handle_add_access(query, user.id, chat_id)
    elif data == "my_access":
        await handle_my_access(query, user.id)
    elif data == "help":
        await handle_help_callback(query)
    elif data == "main_menu":
        await handle_main_menu(query, user.first_name)
    elif data == "manage_users":
        await handle_manage_users(query, user.id)
    elif data == "add_user":
        await handle_add_user_prompt(query, user.id)
    elif data == "list_users":
        await handle_list_users(query)
    elif data.startswith("remove_user_"):
        user_to_remove = int(data.replace("remove_user_", ""))
        await handle_remove_user(query, user.id, user_to_remove)
    elif data.startswith("close_access_"):
        access_id = data.replace("close_access_", "")
        await handle_close_access(query, user.id, access_id)
    elif data.startswith("set_language_"):
        language_code = data.replace("set_language_", "")
        await handle_set_language(query, user.id, language_code)


async def handle_add_access(query, user_id: int, chat_id: int) -> None:
    """Handle add access button press."""
    try:
        user = query.from_user
        
        # Get user's preferred language (from memory or auto-detect)
        language = get_user_language(user.id, user.language_code)
        i18n.set_language(language)
        
        # Create session for web interface
        session = access_module.access_manager.create_session(
            telegram_user_id=user_id,
            chat_id=chat_id,
            expiry_seconds=config.access_token_expiry
        )
        
        # Generate dynamic link
        access_url = f"{config.site_url}/{session.token}"
        
        # Inform user if IP is excluded from RabbitMQ publishing (always open policy)
        excluded_note = ""
        if config.exclude_ips:
            excluded_note = (
                "\n\n" + i18n.get_text(
                    "bot.excluded_ips_note",
                    ips=", ".join(config.exclude_ips)
                )
            )
        response_text = i18n.get_text("bot.access_link_created", link=access_url) + excluded_note
        
        keyboard = [
            [InlineKeyboardButton(i18n.get_text("bot.main_menu"), callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(response_text, reply_markup=reply_markup)
        
        logger.info(f"Created access session {session.token} for user {user_id}")
        
    except Exception as e:
        logger.error(f"Error creating access link for user {user_id}: {e}")
        
        # Set language for error message too
        user = query.from_user
        language = get_user_language(user.id, user.language_code)
        i18n.set_language(language)
        
        await query.edit_message_text(
            i18n.get_text("bot.error", error="Failed to create access link"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(i18n.get_text("bot.main_menu"), callback_data="main_menu")]
            ])
        )


async def handle_my_access(query, user_id: int) -> None:
    """Handle my access button press."""
    try:
        user = query.from_user
        
        # Get user's preferred language (from memory or auto-detect)
        language = get_user_language(user.id, user.language_code)
        i18n.set_language(language)
        
        active_requests = access_module.access_manager.get_active_requests_for_user(user_id)
        
        if not active_requests:
            response_text = i18n.get_text("bot.no_active_accesses")
            keyboard = [
                [InlineKeyboardButton(i18n.get_text("bot.add_access"), callback_data="add_access")],
                [InlineKeyboardButton(i18n.get_text("bot.main_menu"), callback_data="main_menu")]
            ]
        else:
            response_text = i18n.get_text("bot.active_accesses_title") + "\n\n"
            keyboard = []
            
            for i, request in enumerate(active_requests, 1):
                # Format duration using i18n utility
                duration_hours = request.duration // 3600
                duration_text = f" {i18n.format_duration(duration_hours)}"
                
                # Calculate remaining time from now to expiration
                time_left = ""
                expires_text = ""
                if request.expires_at:
                    from datetime import datetime, timezone
                    now = datetime.now(timezone.utc)
                    remaining_seconds = int((request.expires_at - now).total_seconds())
                    
                    if remaining_seconds > 0:
                        time_left = f" ({i18n.format_remaining_time(remaining_seconds)})"
                    else:
                        time_left = f" ({i18n.get_text('time.expired')})"
                    
                    # Format expiration time with localized text
                    expires_text = f"\n   {i18n.get_text('web.expires')}: {request.expires_at.strftime('%d.%m.%Y %H:%M:%S')}"

                response_text += (
                    f"{i}. 🟢 {i18n.get_text('bot.access_opened', hours=i18n.format_duration(duration_hours))}{time_left}\n"
                    f"   IP: {request.ip_address or i18n.get_text('web.unknown')}\n"
                    f"   {i18n.get_text('web.created')}: {request.created_at.strftime('%d.%m.%Y %H:%M:%S')}"
                    f"{expires_text}\n\n"
                )
                
                keyboard.append([
                    InlineKeyboardButton(
                        i18n.get_text("bot.close_access", number=i), 
                        callback_data=f"close_access_{request.id}"
                    )
                ])
            
            keyboard.append([InlineKeyboardButton(i18n.get_text("bot.main_menu"), callback_data="main_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(response_text, reply_markup=reply_markup)
        
    except Exception as e:
        logger.error(f"Error fetching access requests for user {user_id}: {e}")
        
        # Set language for error message
        user = query.from_user
        language = get_user_language(user.id, user.language_code)
        i18n.set_language(language)
        
        await query.edit_message_text(
            i18n.get_text("bot.error", error="Failed to fetch access information"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(i18n.get_text("bot.main_menu"), callback_data="main_menu")]
            ])
        )


async def handle_close_access(query, user_id: int, access_id: str) -> None:
    """Handle close access button press."""
    try:
        user = query.from_user
        
        # Get user's preferred language (from memory or auto-detect)  
        language = get_user_language(user.id, user.language_code)
        i18n.set_language(language)
        
        request = access_module.access_manager.close_access_request(access_id)
        
        if request and request.telegram_user_id == user_id:
            # Send message to RabbitMQ and log
            message = request.to_rabbitmq_message()
            rabbitmq_service.publish_access_event(message)
            
            response_text = i18n.get_text("bot.access_closed", 
                                        ip=request.ip_address or i18n.get_text("web.unknown"),
                                        created=request.created_at.strftime('%H:%M:%S'),
                                        closed=request.closed_at.strftime('%H:%M:%S'))
            
            logger.info(f"Access {access_id} closed by user {user_id}")
        else:
            response_text = i18n.get_text("bot.access_not_found")
        
        keyboard = [
            [InlineKeyboardButton(i18n.get_text("bot.my_accesses"), callback_data="my_access")],
            [InlineKeyboardButton(i18n.get_text("bot.main_menu"), callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(response_text, reply_markup=reply_markup)
        
    except Exception as e:
        logger.error(f"Error closing access {access_id} for user {user_id}: {e}")
        
        # Set language for error message
        user = query.from_user
        language = get_user_language(user.id, user.language_code)
        i18n.set_language(language)
        
        await query.edit_message_text(
            i18n.get_text("bot.error", error="Failed to close access"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(i18n.get_text("bot.main_menu"), callback_data="main_menu")]
            ])
        )


async def handle_help_callback(query) -> None:
    """Handle help button callback."""
    user = query.from_user
    
    # Get user's preferred language (from memory or auto-detect)
    language = get_user_language(user.id, user.language_code)
    i18n.set_language(language)
    
    help_text = i18n.get_text("bot.help_text")
    
    keyboard = [
        [InlineKeyboardButton(i18n.get_text("bot.main_menu"), callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(help_text, reply_markup=reply_markup)


async def handle_main_menu(query, first_name: str) -> None:
    """Handle main menu button callback."""
    user = query.from_user
    
    # Get user's preferred language (from memory or auto-detect)
    language = get_user_language(user.id, user.language_code)
    i18n.set_language(language)
    
    welcome_text = i18n.get_text("bot.welcome")
    
    keyboard = [
        [InlineKeyboardButton(i18n.get_text("bot.add_access"), callback_data="add_access")],
        [InlineKeyboardButton(i18n.get_text("bot.my_accesses"), callback_data="my_access")],
        [InlineKeyboardButton(i18n.get_text("bot.help"), callback_data="help")]
    ]
    
    # Add admin commands if user is admin
    if db_manager.is_admin(user.id):
        keyboard.append([InlineKeyboardButton(i18n.get_text("bot.manage_users"), callback_data="manage_users")])
    
    # Add language switch button (show opposite language)
    if language == "ru":
        keyboard.append([InlineKeyboardButton("🇺🇸 English", callback_data="set_language_en")])
    else:
        keyboard.append([InlineKeyboardButton("🇷🇺 Русский", callback_data="set_language_ru")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(welcome_text, reply_markup=reply_markup)


async def handle_manage_users(query, admin_id: int) -> None:
    """Handle manage users menu for admins."""
    try:
        user = query.from_user
        
        if not db_manager.is_admin(admin_id):
            await query.edit_message_text("❌ Access denied")
            return
        
        language = get_user_language(user.id, user.language_code)
        i18n.set_language(language)
        
        response_text = i18n.get_text("bot.admin_menu")
        
        keyboard = [
            [InlineKeyboardButton(i18n.get_text("bot.add_user"), callback_data="add_user")],
            [InlineKeyboardButton(i18n.get_text("bot.list_users"), callback_data="list_users")],
            [InlineKeyboardButton(i18n.get_text("bot.main_menu"), callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(response_text, reply_markup=reply_markup)
        
    except Exception as e:
        logger.error(f"Error in admin menu for user {admin_id}: {e}")
        await query.edit_message_text("❌ Error accessing admin menu")


async def handle_add_user_prompt(query, admin_id: int) -> None:
    """Prompt admin to send user ID to add to whitelist."""
    try:
        user = query.from_user
        
        if not db_manager.is_admin(admin_id):
            await query.edit_message_text("❌ Access denied")
            return
        
        language = get_user_language(user.id, user.language_code)
        i18n.set_language(language)
        
        response_text = i18n.get_text("bot.add_user_prompt")
        
        keyboard = [
            [InlineKeyboardButton(i18n.get_text("bot.back"), callback_data="manage_users")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(response_text, reply_markup=reply_markup)
        
    except Exception as e:
        logger.error(f"Error in add user prompt for admin {admin_id}: {e}")


async def handle_list_users(query) -> None:
    """List all whitelisted users for admin."""
    try:
        user = query.from_user
        
        if not db_manager.is_admin(user.id):
            await query.edit_message_text("❌ Access denied")
            return
        
        language = get_user_language(user.id, user.language_code)
        i18n.set_language(language)
        
        whitelist_users = db_manager.get_whitelist_users()
        
        if not whitelist_users:
            response_text = i18n.get_text("bot.no_users_in_whitelist")
            keyboard = [
                [InlineKeyboardButton(i18n.get_text("bot.add_user"), callback_data="add_user")],
                [InlineKeyboardButton(i18n.get_text("bot.back"), callback_data="manage_users")]
            ]
        else:
            response_text = i18n.get_text("bot.whitelist_users_title") + "\n\n"
            keyboard = []
            
            for i, wl_user in enumerate(whitelist_users, 1):
                username_text = f"@{wl_user.username}" if wl_user.username else "—"
                name_text = f"{wl_user.first_name} {wl_user.last_name}".strip() if wl_user.first_name else "—"
                
                response_text += (
                    f"{i}. ID: {wl_user.telegram_user_id}\n"
                    f"   {i18n.get_text('bot.username')}: {username_text}\n"
                    f"   {i18n.get_text('bot.name')}: {name_text}\n"
                    f"   {i18n.get_text('bot.added')}: {wl_user.created_at.strftime('%d.%m.%Y')}\n\n"
                )
                
                keyboard.append([
                    InlineKeyboardButton(
                        i18n.get_text("bot.remove_user", number=i),
                        callback_data=f"remove_user_{wl_user.telegram_user_id}"
                    )
                ])
            
            keyboard.append([InlineKeyboardButton(i18n.get_text("bot.back"), callback_data="manage_users")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(response_text, reply_markup=reply_markup)
        
    except Exception as e:
        logger.error(f"Error listing users: {e}")
        await query.edit_message_text("❌ Error listing users")


async def handle_remove_user(query, admin_id: int, user_to_remove: int) -> None:
    """Remove user from whitelist."""
    try:
        user = query.from_user
        
        if not db_manager.is_admin(admin_id):
            await query.edit_message_text("❌ Access denied")
            return
        
        language = get_user_language(user.id, user.language_code)
        i18n.set_language(language)
        
        success = db_manager.remove_from_whitelist(user_to_remove)
        
        if success:
            response_text = i18n.get_text("bot.user_removed", user_id=user_to_remove)
            logger.info(f"Admin {admin_id} removed user {user_to_remove} from whitelist")
        else:
            response_text = i18n.get_text("bot.user_not_found")
        
        keyboard = [
            [InlineKeyboardButton(i18n.get_text("bot.list_users"), callback_data="list_users")],
            [InlineKeyboardButton(i18n.get_text("bot.back"), callback_data="manage_users")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(response_text, reply_markup=reply_markup)
        
    except Exception as e:
        logger.error(f"Error removing user {user_to_remove}: {e}")
        await query.edit_message_text("❌ Error removing user")


async def handle_set_language(query, user_id: int, language_code: str) -> None:
    """Handle language selection button press."""
    try:
        # Set language for this conversation
        i18n.set_language(language_code)
        
        # Send confirmation message
        if language_code == "ru":
            response_text = "🇷🇺 Язык изменен на русский"
        else:
            response_text = "🇺🇸 Language changed to English"
        
        # Show main menu with new language
        welcome_text = i18n.get_text("bot.welcome")
        
        keyboard = [
            [InlineKeyboardButton(i18n.get_text("bot.add_access"), callback_data="add_access")],
            [InlineKeyboardButton(i18n.get_text("bot.my_accesses"), callback_data="my_access")],
            [InlineKeyboardButton(i18n.get_text("bot.help"), callback_data="help")]
        ]
        
        # Add admin commands if user is admin
        if db_manager.is_admin(user_id):
            keyboard.append([InlineKeyboardButton(i18n.get_text("bot.manage_users"), callback_data="manage_users")])
        
        # Add language switch button (show opposite language)
        if language_code == "ru":
            keyboard.append([InlineKeyboardButton("🇺🇸 English", callback_data="set_language_en")])
        else:
            keyboard.append([InlineKeyboardButton("🇷🇺 Русский", callback_data="set_language_ru")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(welcome_text, reply_markup=reply_markup)
        
        # Log language change
        logger.info(f"User {user_id} changed language to {language_code}")
        
    except Exception as e:
        logger.error(f"Error changing language for user {user_id}: {e}")
        await query.edit_message_text(
            "❌ Error changing language",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
            ])
        )


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages (for adding users to whitelist)."""
    user = update.effective_user
    text = update.message.text
    
    # Check if user is authorized
    if not is_user_authorized(user):
        language = i18n.detect_language_from_code(user.language_code)
        i18n.set_language(language)
        await update.message.reply_text(
            i18n.get_text("bot.unauthorized", user_id=user.id)
        )
        return
    
    # Check if admin is sending user ID to add to whitelist
    if db_manager.is_admin(user.id) and text.isdigit():
        await handle_add_user_to_whitelist(update, int(text))
        return
    
    # Default response
    language = get_user_language(user.id, user.language_code)
    i18n.set_language(language)
    
    await update.message.reply_text(
        i18n.get_text("bot.use_commands")
    )


async def handle_add_user_to_whitelist(update: Update, user_id_to_add: int) -> None:
    """Add user to whitelist via admin text message."""
    admin = update.effective_user
    language = get_user_language(admin.id, admin.language_code)
    i18n.set_language(language)
    
    try:
        # Add user to whitelist
        db_manager.add_to_whitelist(
            telegram_user_id=user_id_to_add,
            added_by_admin_id=admin.id,
            username=None,  # Will be updated when user starts bot
            first_name=None,
            last_name=None
        )
        
        response_text = i18n.get_text("bot.user_added_to_whitelist", user_id=user_id_to_add)
        logger.info(f"Admin {admin.id} added user {user_id_to_add} to whitelist")
        
    except Exception as e:
        logger.error(f"Error adding user {user_id_to_add} to whitelist: {e}")
        response_text = i18n.get_text("bot.error_adding_user")
    
    await update.message.reply_text(response_text)
