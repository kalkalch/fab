"""
Database models for FAB.

Contains data access objects (DAO) for simplified whitelist-based system.
"""

import json
import uuid
import logging
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Optional, List
from enum import Enum

from . import database as database_module


def _get_db():
    """Get database instance with proper error handling."""
    if database_module.db is None:
        raise RuntimeError("Database not initialized. Call Database() in main.py first.")
    return database_module.db

logger = logging.getLogger(__name__)


class AccessStatus(Enum):
    """Enumeration for access status."""
    OPEN = "open"
    CLOSED = "closed"


@dataclass
class WhitelistUser:
    """Whitelist user data model with database operations."""
    
    telegram_user_id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    added_by_admin_id: int
    created_at: datetime
    updated_at: datetime
    
    @classmethod
    def add(
        cls,
        telegram_user_id: int,
        added_by_admin_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None
    ) -> "WhitelistUser":
        """Add user to whitelist."""
        now = datetime.now(timezone.utc)
        
        _get_db().execute(
            """INSERT OR REPLACE INTO whitelist_users 
               (telegram_user_id, username, first_name, last_name, 
                added_by_admin_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (telegram_user_id, username, first_name, last_name,
             added_by_admin_id, now, now)
        )
        
        user = cls(
            telegram_user_id=telegram_user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            added_by_admin_id=added_by_admin_id,
            created_at=now,
            updated_at=now
        )
        
        logger.info(f"Added user {telegram_user_id} to whitelist by admin {added_by_admin_id}")
        return user
    
    @classmethod
    def remove(cls, telegram_user_id: int) -> bool:
        """Remove user from whitelist."""
        cursor = _get_db().execute(
            "DELETE FROM whitelist_users WHERE telegram_user_id = ?",
            (telegram_user_id,)
        )
        removed = cursor.rowcount > 0
        if removed:
            logger.info(f"Removed user {telegram_user_id} from whitelist")
        return removed
    
    @classmethod
    def is_whitelisted(cls, telegram_user_id: int) -> bool:
        """Check if user is in whitelist."""
        row = _get_db().fetchone(
            "SELECT 1 FROM whitelist_users WHERE telegram_user_id = ?",
            (telegram_user_id,)
        )
        return row is not None
    
    @classmethod
    def get_all(cls) -> List["WhitelistUser"]:
        """Get all whitelisted users."""
        rows = _get_db().fetchall(
            "SELECT * FROM whitelist_users ORDER BY created_at"
        )
        return [cls._from_row(row) for row in rows]
    
    @classmethod
    def _from_row(cls, row) -> "WhitelistUser":
        """Create WhitelistUser instance from database row."""
        return cls(
            telegram_user_id=row['telegram_user_id'],
            username=row['username'],
            first_name=row['first_name'],
            last_name=row['last_name'],
            added_by_admin_id=row['added_by_admin_id'],
            created_at=datetime.fromisoformat(row['created_at']),
            updated_at=datetime.fromisoformat(row['updated_at'])
        )


@dataclass
class UserSession:
    """User session data model with database operations."""
    
    token: str
    telegram_user_id: int
    chat_id: int
    ip_address: Optional[str]
    created_at: datetime
    expires_at: datetime
    used: bool = False
    
    @classmethod
    def create(cls, telegram_user_id: int, chat_id: int, expiry_seconds: int) -> "UserSession":
        """Create new user session in database."""
        token = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=expiry_seconds)
        
        _get_db().execute(
            """INSERT INTO user_sessions 
               (token, telegram_user_id, chat_id, created_at, expires_at, used)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (token, telegram_user_id, chat_id, now, expires_at, False)
        )
        
        session = cls(
            token=token,
            telegram_user_id=telegram_user_id,
            chat_id=chat_id,
            ip_address=None,
            created_at=now,
            expires_at=expires_at,
            used=False
        )
        
        logger.info(f"Created session {token} for user {telegram_user_id}")
        return session
    
    @classmethod
    def get_by_token(cls, token: str) -> Optional["UserSession"]:
        """Get session by token."""
        row = _get_db().fetchone(
            "SELECT * FROM user_sessions WHERE token = ?",
            (token,)
        )
        return cls._from_row(row) if row else None
    
    def is_expired(self) -> bool:
        """Check if session has expired."""
        return datetime.now(timezone.utc) > self.expires_at
    
    def set_ip(self, ip_address: str) -> None:
        """Set IP address without marking session as used."""
        self.ip_address = ip_address
        
        _get_db().execute(
            "UPDATE user_sessions SET ip_address = ? WHERE token = ?",
            (ip_address, self.token)
        )
        logger.debug(f"Session {self.token} IP set to {ip_address}")
    
    def use(self, ip_address: str) -> None:
        """Mark session as used and set IP address (deprecated - use use_atomic)."""
        self.used = True
        self.ip_address = ip_address
        
        _get_db().execute(
            "UPDATE user_sessions SET used = 1, ip_address = ? WHERE token = ?",
            (ip_address, self.token)
        )
        logger.info(f"Session {self.token} used by IP {ip_address}")
    
    def use_atomic(self, ip_address: str) -> bool:
        """Atomically mark session as used if not already used."""
        cursor = _get_db().execute(
            "UPDATE user_sessions SET used = 1, ip_address = ? WHERE token = ? AND used = 0",
            (ip_address, self.token)
        )
        
        if cursor.rowcount == 1:
            # Successfully marked as used
            self.used = True
            self.ip_address = ip_address
            logger.info(f"Session {self.token} used by IP {ip_address}")
            return True
        else:
            # Session was already used by another request
            logger.warning(f"Session {self.token} already used - atomic update failed")
            return False
    
    def delete(self) -> None:
        """Delete session from database."""
        _get_db().execute("DELETE FROM user_sessions WHERE token = ?", (self.token,))
        logger.info(f"Deleted session {self.token}")
    
    @classmethod
    def _from_row(cls, row) -> "UserSession":
        """Create UserSession instance from database row."""
        return cls(
            token=row['token'],
            telegram_user_id=row['telegram_user_id'],
            chat_id=row['chat_id'],
            ip_address=row['ip_address'],
            created_at=datetime.fromisoformat(row['created_at']),
            expires_at=datetime.fromisoformat(row['expires_at']),
            used=bool(row['used'])
        )


@dataclass
class AccessRequest:
    """Access request data model with database operations."""
    
    id: str
    telegram_user_id: int
    chat_id: int
    ip_address: Optional[str]
    duration: int
    status: AccessStatus
    created_at: datetime
    expires_at: Optional[datetime]
    closed_at: Optional[datetime]
    
    @classmethod
    def create(
        cls,
        telegram_user_id: int,
        chat_id: int,
        duration: int,
        ip_address: Optional[str] = None
    ) -> "AccessRequest":
        """Create new access request in database."""
        request_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=duration) if duration > 0 else None
        
        _get_db().execute(
            """INSERT INTO access_requests 
               (id, telegram_user_id, chat_id, ip_address, duration, status, 
                created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (request_id, telegram_user_id, chat_id, ip_address, duration,
             AccessStatus.OPEN.value, now, expires_at)
        )
        
        request = cls(
            id=request_id,
            telegram_user_id=telegram_user_id,
            chat_id=chat_id,
            ip_address=ip_address,
            duration=duration,
            status=AccessStatus.OPEN,
            created_at=now,
            expires_at=expires_at,
            closed_at=None
        )
        
        logger.info(f"Created access request {request_id} for user {telegram_user_id}")
        return request
    
    @classmethod
    def get_by_id(cls, request_id: str) -> Optional["AccessRequest"]:
        """Get access request by ID."""
        row = _get_db().fetchone(
            "SELECT * FROM access_requests WHERE id = ?",
            (request_id,)
        )
        return cls._from_row(row) if row else None
    
    @classmethod
    def get_active_for_user(cls, telegram_user_id: int) -> List["AccessRequest"]:
        """Get all active access requests for user."""
        rows = _get_db().fetchall(
            """SELECT * FROM access_requests 
               WHERE telegram_user_id = ? AND status = 'open' 
               AND (expires_at IS NULL OR expires_at > ?)
               ORDER BY created_at DESC""",
            (telegram_user_id, datetime.now(timezone.utc))
        )
        return [cls._from_row(row) for row in rows]
    
    def close(self) -> None:
        """Close the access request."""
        self.status = AccessStatus.CLOSED
        self.closed_at = datetime.now(timezone.utc)
        
        _get_db().execute(
            """UPDATE access_requests 
               SET status = 'closed', closed_at = ? 
               WHERE id = ?""",
            (self.closed_at, self.id)
        )
        logger.info(f"Closed access request {self.id}")
    
    def is_expired(self) -> bool:
        """Check if access request has expired."""
        if not self.expires_at:
            return False
        return datetime.now(timezone.utc) > self.expires_at
    
    def to_mqtt_payload(self) -> str:
        """Convert access request to MQTT JSON payload."""
        message = {
            "ttl": self.duration
        }
        return json.dumps(message, ensure_ascii=False)
    
    @classmethod
    def _from_row(cls, row) -> "AccessRequest":
        """Create AccessRequest instance from database row."""
        return cls(
            id=row['id'],
            telegram_user_id=row['telegram_user_id'],
            chat_id=row['chat_id'],
            ip_address=row['ip_address'],
            duration=row['duration'],
            status=AccessStatus(row['status']),
            created_at=datetime.fromisoformat(row['created_at']),
            expires_at=datetime.fromisoformat(row['expires_at']) if row['expires_at'] else None,
            closed_at=datetime.fromisoformat(row['closed_at']) if row['closed_at'] else None
        )



