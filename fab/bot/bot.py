"""
Main Telegram bot module for FAB.

Initializes and configures the Telegram bot with handlers
and manages bot lifecycle.
"""

import logging
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler,
    MessageHandler,
    filters
)

from ..config import config
from .handlers import start_command, help_command, button_callback, handle_text_message


logger = logging.getLogger(__name__)


class FABBot:
    """Main Telegram bot class for FAB."""
    
    def __init__(self) -> None:
        """Initialize the bot."""
        self.application = None
        self._setup_application()
    
    def _setup_application(self) -> None:
        """Setup the bot application with handlers."""
        # Create application
        self.application = Application.builder().token(config.telegram_bot_token).build()
        
        # Add command handlers
        self.application.add_handler(CommandHandler("start", start_command))
        self.application.add_handler(CommandHandler("help", help_command))
        
        # Add callback query handler for inline keyboards
        self.application.add_handler(CallbackQueryHandler(button_callback))
        
        # Add handler for unknown commands
        self.application.add_handler(
            MessageHandler(filters.COMMAND, self._unknown_command)
        )
        
        # Add handler for non-command messages
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
        )
        
        logger.info("Bot application configured with handlers")
    
    async def _unknown_command(self, update, context) -> None:
        """Handle unknown commands."""
        await update.message.reply_text(
            "❓ Неизвестная команда. Используйте /help для просмотра доступных команд."
        )
    

    
    async def start(self) -> None:
        """Start the bot."""
        try:
            logger.info("Starting FAB Telegram bot...")
            await self.application.initialize()
            await self.application.start()
            
            # Get bot info
            bot = self.application.bot
            bot_info = await bot.get_me()
            logger.info(f"Bot started successfully: @{bot_info.username}")
            
            # Start polling
            await self.application.updater.start_polling()
            logger.info("Bot is now polling for updates")
            
        except Exception as e:
            logger.error(f"Failed to start bot: {e}")
            raise
    
    async def stop(self) -> None:
        """Stop the bot."""
        try:
            logger.info("Stopping FAB Telegram bot...")
            
            if self.application.updater.running:
                await self.application.updater.stop()
            
            await self.application.stop()
            await self.application.shutdown()
            
            logger.info("Bot stopped successfully")
            
        except Exception as e:
            logger.error(f"Error stopping bot: {e}")
    
    def run(self) -> None:
        """Run the bot (blocking)."""
        try:
            logger.info("Running FAB Telegram bot...")
            self.application.run_polling(
                allowed_updates=["message", "callback_query"],
                drop_pending_updates=True
            )
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        except Exception as e:
            logger.error(f"Bot runtime error: {e}")
            raise


def create_bot() -> FABBot:
    """Create and return a new bot instance."""
    return FABBot()
