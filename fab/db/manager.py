"""
Database manager for FAB.

Provides high-level interface for database operations with whitelist-based system.
"""

import logging
from typing import Optional, List
from datetime import datetime

from .models import WhitelistUser, UserSession, AccessRequest, SOURCE_TELEGRAM, SOURCE_VK
from . import database as database_module
from ..config import config


def _get_db():
    """Get database instance with proper error handling."""
    if database_module.db is None:
        raise RuntimeError("Database not initialized. Call Database() in main.py first.")
    return database_module.db

logger = logging.getLogger(__name__)


class DatabaseManager:
    """High-level database manager for FAB operations."""
    
    def __init__(self) -> None:
        """Initialize database manager."""
        logger.info("Database manager initialized")
    
    # Authorization methods

    def is_user_authorized(self, user_id: int, source: str = SOURCE_TELEGRAM) -> bool:
        """Check if user is authorized (admin or in whitelist) for the given source."""
        if source == SOURCE_TELEGRAM:
            if user_id in config.admin_telegram_ids:
                return True
        else:
            if getattr(config, "admin_vk_ids", set()) and user_id in config.admin_vk_ids:
                return True
        return WhitelistUser.is_whitelisted(source, user_id)

    def is_admin(self, user_id: int, source: str = SOURCE_TELEGRAM) -> bool:
        """Check if user is admin for the given source."""
        if source == SOURCE_TELEGRAM:
            return user_id in config.admin_telegram_ids
        return user_id in getattr(config, "admin_vk_ids", set())

    # Whitelist management methods

    def add_to_whitelist(
        self,
        source: str,
        telegram_user_id: int,
        added_by_admin_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> WhitelistUser:
        """Add user to whitelist for the given source."""
        return WhitelistUser.add(
            source=source,
            telegram_user_id=telegram_user_id,
            added_by_admin_id=added_by_admin_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )

    def remove_from_whitelist(self, source: str, telegram_user_id: int) -> bool:
        """Remove user from whitelist for the given source."""
        return WhitelistUser.remove(source, telegram_user_id)

    def get_whitelist_users(self, source: str) -> List[WhitelistUser]:
        """Get all whitelisted users for the given source."""
        return WhitelistUser.get_all(source)

    # Session management methods

    def create_session(
        self,
        source: str,
        telegram_user_id: int,
        chat_id: int,
        expiry_seconds: int,
    ) -> UserSession:
        """Create a new user session for web interface."""
        return UserSession.create(source, telegram_user_id, chat_id, expiry_seconds)
    
    def get_session(self, token: str) -> Optional[UserSession]:
        """Get session by token, automatically remove if expired."""
        session = UserSession.get_by_token(token)
        if session and session.is_expired():
            session.delete()
            return None
        return session
    
    def remove_session(self, token: str) -> None:
        """Remove session by token."""
        session = UserSession.get_by_token(token)
        if session:
            session.delete()
    
    # Access request management methods
    
    def create_access_request(
        self,
        source: str,
        telegram_user_id: int,
        chat_id: int,
        duration: int,
        ip_address: Optional[str] = None,
    ) -> AccessRequest:
        """Create a new access request."""
        return AccessRequest.create(
            source, telegram_user_id, chat_id, duration, ip_address
        )

    def get_access_request(self, request_id: str) -> Optional[AccessRequest]:
        """Get access request by ID."""
        return AccessRequest.get_by_id(request_id)

    def close_access_request(self, request_id: str) -> Optional[AccessRequest]:
        """Close access request by ID."""
        request = AccessRequest.get_by_id(request_id)
        if request:
            request.close()
        return request

    def get_active_requests_for_user(
        self, source: str, telegram_user_id: int
    ) -> List[AccessRequest]:
        """Get all active access requests for a user for the given source."""
        return AccessRequest.get_active_for_user(source, telegram_user_id)
    
    # Maintenance methods
    
    def cleanup_expired_data(self) -> dict:
        """Clean up expired sessions and access requests."""
        sessions_removed = _get_db().cleanup_expired_sessions()
        requests_closed = _get_db().cleanup_expired_access_requests()
        
        return {
            'expired_sessions_removed': sessions_removed,
            'expired_requests_closed': requests_closed
        }
    
    def get_statistics(self) -> dict:
        """Get database statistics."""
        return _get_db().get_stats()
    
    def close(self) -> None:
        """Close database connections."""
        _get_db().close()


# Global database manager instance
db_manager = DatabaseManager()
