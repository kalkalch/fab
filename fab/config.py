"""
Configuration module for FAB.

Loads and validates environment variables and provides
application configuration settings.
"""

import os
import logging
from pathlib import Path
from ipaddress import ip_network

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
        
        # MQTT Configuration
        self.mqtt_enabled: bool = os.getenv("MQTT_ENABLED", "false").lower() in (
            "true",
            "1",
            "yes"
        )
        if self.mqtt_enabled:
            self.mqtt_host: str = self._get_required_env("MQTT_HOST")
            self.mqtt_port: int = int(os.getenv("MQTT_PORT", "1883"))
            self.mqtt_client_id: str = self._get_required_env("MQTT_CLIENT_ID")
            self.mqtt_username: str = os.getenv("MQTT_USERNAME", "")
            self.mqtt_password: str = os.getenv("MQTT_PASSWORD", "")
            self.mqtt_keepalive: int = int(os.getenv("MQTT_KEEPALIVE", "60"))
            self.mqtt_qos: int = int(os.getenv("MQTT_QOS", "1"))
            self.mqtt_topic_prefix: str = os.getenv(
                "MQTT_TOPIC_PREFIX",
                "mikrotik/whitelist/ip"
            )
        else:
            self.mqtt_host = ""
            self.mqtt_port = 1883
            self.mqtt_client_id = ""
            self.mqtt_username = ""
            self.mqtt_password = ""
            self.mqtt_keepalive = 60
            self.mqtt_qos = 1
            self.mqtt_topic_prefix = "mikrotik/whitelist/ip"
            
        # Global exclude IPs (always-open policy) as CIDR
        # Default: standard private/link-local/test ranges
        default_excludes = (
            "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,"
            "127.0.0.0/8,169.254.0.0/16,192.0.2.0/24,198.51.100.0/24,203.0.113.0/24"
        )
        exclude_ips = os.getenv("EXCLUDE_IPS", default_excludes)
        self.exclude_ips: list[str] = [ip.strip() for ip in exclude_ips.split(',') if ip.strip()]
        # Parsed networks for fast checks
        self.exclude_networks = []
        for cidr in self.exclude_ips:
            try:
                self.exclude_networks.append(ip_network(cidr, strict=False))
            except Exception:
                logging.warning(f"Invalid EXCLUDE_IPS entry skipped: {cidr}")
        
        # Security Configuration
        self.secret_key: str = os.getenv("SECRET_KEY", self._generate_secret_key())
        self.access_token_expiry: int = int(os.getenv("ACCESS_TOKEN_EXPIRY", "3600"))
        
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
    def mqtt_url(self) -> str:
        """Get MQTT connection URL."""
        if not self.mqtt_enabled:
            return ""
        return f"mqtt://{self.mqtt_host}:{self.mqtt_port}"


# Global configuration instance
config = Config()
