#!/usr/bin/env python3
"""
Main entry point for FAB - Firewall Access Bot.

Starts both Telegram bot and web server components.
"""

import asyncio
import logging
import signal
import sys
from concurrent.futures import ThreadPoolExecutor

from fab.config import config
from fab.bot.bot import create_bot
from fab.web.server import create_server
from fab.utils.rabbitmq import rabbitmq_service
from fab.db.database import Database
from fab.db.manager import db_manager
from fab.db import database as db_module


logger = logging.getLogger(__name__)


class FABApplication:
    """Main application class for FAB."""
    
    def __init__(self) -> None:
        """Initialize FAB application."""
        self.bot = None
        self.web_server = None
        self.database = None
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.shutdown_event = asyncio.Event()
        
    async def start(self) -> None:
        """Start all application components."""
        try:
            # Setup configuration and logging first
            config.setup_logging()
            
            logger.info("Starting FAB - Firewall Access Bot...")
            logger.info(f"Log level: {config.log_level}")
            logger.info(f"RabbitMQ enabled: {config.rabbitmq_enabled}")
            logger.info(f"Nginx proxy mode: {config.nginx_enabled}")
            logger.info(f"Database path: {config.database_path}")
            
            # Initialize database
            logger.info("Initializing database...")
            self.database = Database(config.database_path)
            
            # Set global database instance for models to use
            db_module.db = self.database
            
            # Initialize access manager after database is ready
            from fab.models import access as access_module
            access_module._initialize_access_manager()
            
            logger.info("Database initialized successfully")
            
            # Start RabbitMQ service (optional)
            if not rabbitmq_service.start():
                if config.rabbitmq_enabled:
                    logger.error("Failed to connect to RabbitMQ")
                    raise RuntimeError("RabbitMQ connection failed")
                else:
                    logger.warning("RabbitMQ connection failed, but it's disabled - continuing")
            
            # Create and start web server
            logger.info("Starting web server...")
            self.web_server = create_server()
            self.web_server.start()
            
            # Create and start telegram bot
            logger.info("Starting Telegram bot...")
            self.bot = create_bot()
            await self.bot.start()
            
            logger.info("FAB started successfully!")
            logger.info(f"Web server: http://{config.host}:{config.http_port}")
            logger.info(f"Site URL: {config.site_url}")
            
            # Setup signal handlers for graceful shutdown
            self._setup_signal_handlers()
            
            # Wait for shutdown
            await self.shutdown_event.wait()
            
        except Exception as e:
            logger.error(f"Failed to start FAB: {e}")
            raise
    
    async def stop(self) -> None:
        """Stop all application components."""
        logger.info("Shutting down FAB...")
        
        try:
            # Stop telegram bot
            if self.bot:
                logger.info("Stopping Telegram bot...")
                await self.bot.stop()
            
            # Stop web server
            if self.web_server:
                logger.info("Stopping web server...")
                self.web_server.stop()
            
            # Stop RabbitMQ service
            logger.info("Disconnecting from RabbitMQ...")
            rabbitmq_service.stop()
            
            # Close database connections
            if self.database:
                logger.info("Closing database connections...")
                db_manager.close()
                self.database.close()
            
            # Shutdown executor
            self.executor.shutdown(wait=True)
            
            logger.info("FAB stopped successfully")
            
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
    
    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating shutdown...")
            asyncio.create_task(self._handle_shutdown())
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def _handle_shutdown(self) -> None:
        """Handle shutdown sequence."""
        self.shutdown_event.set()
        await self.stop()


async def main() -> None:
    """Main function."""
    app = FABApplication()
    
    try:
        await app.start()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Application error: {e}")
        sys.exit(1)
    finally:
        await app.stop()


def run_sync() -> None:
    """Synchronous entry point for running the application."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run_sync()
