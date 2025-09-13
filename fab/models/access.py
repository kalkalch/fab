"""
Access management models for FAB.

Provides backward compatibility interface while delegating to the new 
database-backed storage system.
"""

import logging
from ..db.manager import db_manager
from ..db.models import AccessRequest, UserSession, AccessStatus

logger = logging.getLogger(__name__)


class AccessManager:
    """Access manager that provides backward compatibility with database backend."""
    
    def __init__(self) -> None:
        """Initialize access manager with database backend."""
        logger.info("Access manager initialized with database backend")
    
    def create_session(self, telegram_user_id: int, chat_id: int, expiry_seconds: int) -> UserSession:
        """Create a new user session."""
        return db_manager.create_session(telegram_user_id, chat_id, expiry_seconds)
    
    def get_session(self, token: str) -> Optional[UserSession]:
        """Get session by token."""
        return db_manager.get_session(token)
    
    def remove_session(self, token: str) -> None:
        """Remove session by token."""
        db_manager.remove_session(token)
    
    def create_access_request(
        self,
        telegram_user_id: int,
        chat_id: int,
        duration: int,
        ip_address: Optional[str] = None
    ) -> AccessRequest:
        """Create a new access request."""
        return db_manager.create_access_request(telegram_user_id, chat_id, duration, ip_address)
    
    def get_access_request(self, request_id: str) -> Optional[AccessRequest]:
        """Get access request by ID."""
        return db_manager.get_access_request(request_id)
    
    def close_access_request(self, request_id: str) -> Optional[AccessRequest]:
        """Close access request by ID."""
        return db_manager.close_access_request(request_id)
    
    def get_active_requests_for_user(self, telegram_user_id: int) -> List[AccessRequest]:
        """Get all active access requests for a user."""
        return db_manager.get_active_requests_for_user(telegram_user_id)
    
    def cleanup_expired_requests(self) -> None:
        """Clean up expired access requests."""
        db_manager.cleanup_expired_data()


# Global access manager instance (initialized after database)
access_manager = None


def _initialize_access_manager():
    """Initialize access manager after database is ready."""
    global access_manager
    if access_manager is None:
        access_manager = AccessManager()
        logger.info("Access manager initialized")
