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
from telegram.request import HTTPXRequest
from telegram.error import NetworkError, RetryAfter, TimedOut

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
        # Create custom request with longer timeouts
        request = HTTPXRequest(
            connection_pool_size=10,
            read_timeout=30.0,
            write_timeout=30.0,
            connect_timeout=15.0,
            pool_timeout=10.0
        )
        
        # Create application with custom request and rate limiting
        self.application = (
            Application.builder()
            .token(config.telegram_bot_token)
            .request(request)
            .rate_limiter(rate_limiter=None)  # Let Telegram handle rate limiting
            .build()
        )
        
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
        
        # Add global error handler for runtime errors
        self.application.add_error_handler(self._error_handler)
        
        logger.info("Bot application configured with handlers")
    
    async def _unknown_command(self, update, context) -> None:
        """Handle unknown commands."""
        await update.message.reply_text(
            "❓ Неизвестная команда. Используйте /help для просмотра доступных команд."
        )
    
    async def _error_handler(self, update, context) -> None:
        """Handle errors that occur during message processing."""
        import traceback
        
        error = context.error
        logger.error(f"Bot error occurred: {error}")
        
        # Handle specific error types
        if isinstance(error, RetryAfter):
            logger.warning(f"Rate limited during runtime. Retry after {error.retry_after}s")
            return
        
        if isinstance(error, NetworkError):
            if "bad gateway" in str(error).lower() or "502" in str(error):
                logger.warning("Network error during runtime: Bad Gateway (502)")
            else:
                logger.error(f"Network error during runtime: {error}")
            return
        
        if isinstance(error, TimedOut):
            logger.warning(f"Timeout during runtime: {error}")
            return
        
        # Log full traceback for unknown errors
        logger.error("Full error traceback:")
        logger.error(''.join(traceback.format_exception(type(error), error, error.__traceback__)))
    
    async def _polling_error_callback(self, error):
        """Handle polling errors during runtime."""
        if isinstance(error, NetworkError):
            if "bad gateway" in str(error).lower() or "502" in str(error):
                logger.warning("Polling: Bad Gateway (502) - Telegram servers overloaded")
            else:
                logger.error(f"Polling network error: {error}")
        elif isinstance(error, RetryAfter):
            logger.warning(f"Polling rate limited. Retry after {error.retry_after}s")
        else:
            logger.error(f"Polling error: {error}")
    

    
    async def start(self) -> None:
        """Start the bot with retry mechanism."""
        import asyncio
        
        max_retries = 3
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Starting FAB Telegram bot... (attempt {attempt + 1}/{max_retries})")
                
                # Initialize application
                logger.debug("Initializing bot application...")
                await self.application.initialize()
                
                # Start application  
                logger.debug("Starting bot application...")
                await self.application.start()
                
                # Test connection by getting bot info
                logger.debug("Testing connection to Telegram API...")
                bot = self.application.bot
                bot_info = await bot.get_me()
                logger.info(f"Bot connected successfully: @{bot_info.username} (ID: {bot_info.id})")
                
                # Start polling with optimal settings for stability
                logger.debug("Starting polling for updates...")
                await self.application.updater.start_polling(
                    drop_pending_updates=True,
                    timeout=40,           # Near maximum for fewer requests
                    bootstrap_retries=5,  # More retries for Bad Gateway
                    read_timeout=50,      # Account for 40s timeout + network delay
                    write_timeout=30,
                    connect_timeout=15,
                    pool_timeout=10,
                    allowed_updates=["message", "callback_query"],  # Only needed updates
                    error_callback=self._polling_error_callback
                )
                logger.info("Bot is now polling for updates")
                
                return  # Success - exit retry loop
                
            except RetryAfter as e:
                # Rate limiting - wait the specified time
                wait_time = e.retry_after + 1  # Add 1 second buffer
                logger.warning(f"Rate limited by Telegram. Waiting {wait_time} seconds...")
                await asyncio.sleep(wait_time)
                continue
            
            except NetworkError as e:
                # Network errors including Bad Gateway (502)
                logger.error(f"Network error on attempt {attempt + 1}: {e}")
                if "bad gateway" in str(e).lower() or "502" in str(e):
                    logger.warning("Telegram API Bad Gateway (502) - servers overloaded")
                
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    logger.error("All connection attempts failed due to network errors")
                    raise
            
            except TimedOut as e:
                logger.error(f"Timeout on attempt {attempt + 1}: {e}")
                
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    logger.error("All connection attempts timed out")
                    raise
            
            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed: {e}")
                
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    # All attempts failed
                    logger.error("All connection attempts failed")
                    logger.error("Possible causes:")
                    logger.error("1. Invalid bot token")
                    logger.error("2. Network connectivity issues")
                    logger.error("3. Telegram API rate limiting/overload (502 Bad Gateway)")
                    logger.error("4. Firewall blocking Telegram API")
                    logger.error("5. Telegram servers temporarily unavailable")
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
