"""
Configuration module for FAB.

Loads and validates environment variables and provides
application configuration settings.
"""

import os
import logging
from pathlib import Path

try:
    from dotenv import load_dotenv
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False


class Config:
    """Application configuration class."""
    
    def __init__(self) -> None:
        """Initialize configuration from environment variables."""
        self._load_env_file()
        
    def _load_env_file(self) -> None:
        """Load .env file if available."""
        env_file = Path(".env")
        
        if env_file.exists():
            if DOTENV_AVAILABLE:
                load_dotenv(env_file)
                logging.info(f"Loaded environment from {env_file}")
            else:
                logging.warning("python-dotenv not available, .env file found but not loaded")
        else:
            logging.info("No .env file found, using environment variables or defaults")
        
        # Telegram Bot Configuration
        self.telegram_bot_token: str = self._get_required_env("TELEGRAM_BOT_TOKEN")
        
        # Admin Configuration (comma-separated Telegram user IDs)
        admin_ids_str = self._get_required_env("ADMIN_TELEGRAM_IDS")
        self.admin_telegram_ids: set[int] = {
            int(id_str.strip()) for id_str in admin_ids_str.split(',') if id_str.strip()
        }
        
        # Web Server Configuration
        self.http_port: int = int(os.getenv("HTTP_PORT", "8080"))
        self.site_url: str = self._get_required_env("SITE_URL")
        self.host: str = os.getenv("HOST", "0.0.0.0")
        
        # RabbitMQ Configuration
        self.rabbitmq_enabled: bool = os.getenv("RABBITMQ_ENABLED", "false").lower() in ("true", "1", "yes")
        
        # Only load RabbitMQ settings if enabled
        if self.rabbitmq_enabled:
            self.rabbitmq_host: str = self._get_required_env("RABBITMQ_HOST")
            self.rabbitmq_port: int = int(os.getenv("RABBITMQ_PORT", "5672"))
            self.rabbitmq_username: str = os.getenv("RABBITMQ_USERNAME", "guest")
            self.rabbitmq_password: str = os.getenv("RABBITMQ_PASSWORD", "guest")
            self.rabbitmq_queue: str = os.getenv("RABBITMQ_QUEUE", "firewall_access")
            # Handle RABBITMQ_VHOST: if not set, default to "/"
            # User has full control over vhost value
            vhost = os.getenv("RABBITMQ_VHOST")
            if not vhost:
                vhost = "/"  # Default RabbitMQ vhost
            self.rabbitmq_vhost: str = vhost
            self.rabbitmq_exchange: str = os.getenv("RABBITMQ_EXCHANGE", "")
            self.rabbitmq_exchange_type: str = os.getenv("RABBITMQ_EXCHANGE_TYPE", "direct")
            self.rabbitmq_routing_key: str = os.getenv("RABBITMQ_ROUTING_KEY", "firewall.access")
            self.rabbitmq_queue_type: str = os.getenv("RABBITMQ_QUEUE_TYPE", "classic")
        else:
            # Set defaults when disabled (won't be used, but safe values)
            self.rabbitmq_host: str = ""
            self.rabbitmq_port: int = 5672
            self.rabbitmq_username: str = ""
            self.rabbitmq_password: str = ""
            self.rabbitmq_queue: str = ""
            self.rabbitmq_vhost: str = "/"  # Keep valid default even when disabled
            self.rabbitmq_exchange: str = ""
            self.rabbitmq_exchange_type: str = "direct"
            self.rabbitmq_routing_key: str = ""
            self.rabbitmq_queue_type: str = "classic"
        
        # Security Configuration
        self.secret_key: str = os.getenv("SECRET_KEY", self._generate_secret_key())
        self.access_token_expiry: int = int(os.getenv("ACCESS_TOKEN_EXPIRY", "3600"))(os.getenv("ACCESS_TOKEN_EXPIRY", "3600"))
        
        # Proxy Configuration
        self.nginx_enabled: bool = os.getenv("NGINX_ENABLED", "false").lower() in ("true", "1", "yes")
        
        # Database Configuration
        self.database_path: str = os.getenv("DATABASE_PATH", "data/fab.db")
        
        # Logging Configuration
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
        
    def _get_required_env(self, key: str) -> str:
        """Get required environment variable or raise exception."""
        if not (value := os.getenv(key)):
            raise ValueError(f"Required environment variable {key} is not set")
        return value
    
    def _generate_secret_key(self) -> str:
        """Generate a secret key if not provided."""
        import secrets
        return secrets.token_urlsafe(32)
    
    def setup_logging(self) -> None:
        """Setup application logging."""
        # Force reconfigure logging to ensure stdout output
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)
        
        logging.basicConfig(
            level=getattr(logging, self.log_level),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.StreamHandler(),
            ],
            force=True
        )
    
    @property
    def rabbitmq_url(self) -> str:
        """Get RabbitMQ connection URL."""
        if not self.rabbitmq_enabled:
            return ""
        
        return (
            f"amqp://{self.rabbitmq_username}:{self.rabbitmq_password}"
            f"@{self.rabbitmq_host}:{self.rabbitmq_port}{self.rabbitmq_vhost}"
        )


# Global configuration instance
config = Config()
