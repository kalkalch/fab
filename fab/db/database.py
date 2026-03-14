"""
Core database module for FAB.

Handles SQLite database connection, schema creation, and migration management.
"""

import sqlite3
import logging
import threading
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional, Any, Dict, List

logger = logging.getLogger(__name__)


class Database:
    """SQLite database manager with connection pooling and schema management."""
    
    def __init__(self, db_path: str = "fab.db") -> None:
        """Initialize database manager.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self._local = threading.local()
        self._ensure_database_exists()
        self._create_schema()
        logger.info(f"Database initialized at {self.db_path}")
    
    def _ensure_database_exists(self) -> None:
        """Ensure database directory exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
    
    def get_connection(self) -> sqlite3.Connection:
        """Get database connection (public method for testing)."""
        return self._get_connection()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'connection'):
            self._local.connection = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30.0
            )
            # Enable foreign keys and row factory
            self._local.connection.execute("PRAGMA foreign_keys = ON")
            # Improve durability and concurrency
            try:
                self._local.connection.execute("PRAGMA journal_mode = WAL")
                self._local.connection.execute("PRAGMA synchronous = NORMAL")
            except Exception:
                # Some SQLite builds may not support all PRAGMAs
                logger.debug("SQLite PRAGMA tuning not fully supported on this build")
            self._local.connection.row_factory = sqlite3.Row
            
        return self._local.connection

    def _reset_connection(self) -> sqlite3.Connection:
        """Force reset the thread-local connection (e.g., after 'closed database' errors)."""
        if hasattr(self._local, 'connection'):
            try:
                self._local.connection.close()
            except Exception:
                pass
            delattr(self._local, 'connection')
        return self._get_connection()
    
    @contextmanager
    def transaction(self):
        """Context manager for database transactions."""
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    
    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute SQL query with parameters."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor
        except sqlite3.ProgrammingError as e:
            # Attempt to recover from 'closed database'
            if "closed" in str(e).lower():
                logger.warning("SQLite connection closed unexpectedly. Recreating connection and retrying once.")
                conn = self._reset_connection()
                cursor = conn.execute(sql, params)
                conn.commit()
                return cursor
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"Database programming error executing query: {sql[:100]}... Error: {e}")
            raise
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"Database error executing query: {sql[:100]}... Error: {e}")
            raise
    
    def fetchone(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        """Execute query and fetch one row."""
        cursor = self.execute(sql, params)
        return cursor.fetchone()
    
    def fetchall(self, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
        """Execute query and fetch all rows."""
        cursor = self.execute(sql, params)
        return cursor.fetchall()
    
    def _create_schema(self) -> None:
        """Create database schema if it doesn't exist."""
        with self.transaction():
            # Create whitelist table for authorized users
            # source: 'telegram' | 'vk'; (source, telegram_user_id) unique per platform
            self.execute('''
                CREATE TABLE IF NOT EXISTS whitelist_users (
                    source TEXT NOT NULL DEFAULT 'telegram',
                    telegram_user_id INTEGER NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    added_by_admin_id INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (source, telegram_user_id)
                )
            ''')
            
            # Create user_sessions table
            self.execute('''
                CREATE TABLE IF NOT EXISTS user_sessions (
                    token TEXT PRIMARY KEY,
                    source TEXT NOT NULL DEFAULT 'telegram',
                    telegram_user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    ip_address TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    expires_at DATETIME NOT NULL,
                    used BOOLEAN DEFAULT 0
                )
            ''')
            
            # Create access_requests table
            self.execute('''
                CREATE TABLE IF NOT EXISTS access_requests (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL DEFAULT 'telegram',
                    telegram_user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    ip_address TEXT,
                    duration INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    expires_at DATETIME,
                    closed_at DATETIME
                )
            ''')
            
            # Migrate existing tables that don't have source (legacy installs)
            self._migrate_add_source()
            
            # Create indexes for performance
            self._create_indexes()
            
            logger.info("Database schema created successfully")
    
    def _has_column(self, table: str, column: str) -> bool:
        """Return True if table has the given column (for migrations)."""
        rows = self.fetchall(
            "SELECT name FROM pragma_table_info(?) WHERE name = ?",
            (table, column)
        )
        return len(rows) > 0

    def _migrate_add_source(self) -> None:
        """Add source column to existing tables; migrate whitelist to composite PK if needed."""
        # user_sessions: add source if missing
        if not self._has_column("user_sessions", "source"):
            logger.info("Migration: adding source column to user_sessions")
            self.execute(
                "ALTER TABLE user_sessions ADD COLUMN source TEXT NOT NULL DEFAULT 'telegram'"
            )
        # access_requests: add source if missing
        if not self._has_column("access_requests", "source"):
            logger.info("Migration: adding source column to access_requests")
            self.execute(
                "ALTER TABLE access_requests ADD COLUMN source TEXT NOT NULL DEFAULT 'telegram'"
            )
        # whitelist_users: may have old schema (telegram_user_id PK only) or no source
        if not self._has_column("whitelist_users", "source"):
            logger.info("Migration: adding source column to whitelist_users and converting to composite PK")
            self.execute(
                "ALTER TABLE whitelist_users ADD COLUMN source TEXT NOT NULL DEFAULT 'telegram'"
            )
            # Recreate table with composite PK (SQLite cannot ALTER PRIMARY KEY)
            self.execute('''
                CREATE TABLE whitelist_users_new (
                    source TEXT NOT NULL DEFAULT 'telegram',
                    telegram_user_id INTEGER NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    added_by_admin_id INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (source, telegram_user_id)
                )
            ''')
            self.execute('''
                INSERT INTO whitelist_users_new
                (source, telegram_user_id, username, first_name, last_name, added_by_admin_id, created_at, updated_at)
                SELECT source, telegram_user_id, username, first_name, last_name, added_by_admin_id, created_at, updated_at
                FROM whitelist_users
            ''')
            self.execute("DROP TABLE whitelist_users")
            self.execute("ALTER TABLE whitelist_users_new RENAME TO whitelist_users")
        else:
            # Has source; check if PK is composite (old SQLite may have created table with single PK)
            # If table was created by new schema, it already has (source, telegram_user_id) PK - nothing to do
            pass

    def _create_indexes(self) -> None:
        """Create database indexes for better performance."""
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_whitelist_source_user ON whitelist_users (source, telegram_user_id)",
            "CREATE INDEX IF NOT EXISTS idx_whitelist_telegram_id ON whitelist_users (telegram_user_id)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_source_user ON user_sessions (source, telegram_user_id)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_telegram_id ON user_sessions (telegram_user_id)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_expires ON user_sessions (expires_at)",
            "CREATE INDEX IF NOT EXISTS idx_access_source_user ON access_requests (source, telegram_user_id)",
            "CREATE INDEX IF NOT EXISTS idx_access_telegram_id ON access_requests (telegram_user_id)",
            "CREATE INDEX IF NOT EXISTS idx_access_status ON access_requests (status)",
            "CREATE INDEX IF NOT EXISTS idx_access_expires ON access_requests (expires_at)"
        ]
        
        for index_sql in indexes:
            self.execute(index_sql)
    
    def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions and return count of removed sessions."""
        cursor = self.execute(
            "DELETE FROM user_sessions WHERE expires_at < ?",
            (datetime.now(timezone.utc),)
        )
        count = cursor.rowcount
        if count > 0:
            logger.info(f"Cleaned up {count} expired sessions")
        return count
    
    def cleanup_expired_access_requests(self) -> int:
        """Mark expired access requests as closed and return count."""
        cursor = self.execute(
            """UPDATE access_requests 
               SET status = 'closed', closed_at = CURRENT_TIMESTAMP 
               WHERE status = 'open' AND expires_at < ?""",
            (datetime.now(timezone.utc),)
        )
        count = cursor.rowcount
        if count > 0:
            logger.info(f"Closed {count} expired access requests")
        return count
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        stats = {}
        
        # Whitelist statistics
        row = self.fetchone("SELECT COUNT(*) as total FROM whitelist_users")
        stats['whitelist_users'] = row['total']
        
        # Session statistics  
        row = self.fetchone("SELECT COUNT(*) as total FROM user_sessions WHERE expires_at > ?", (datetime.now(timezone.utc),))
        stats['active_sessions'] = row['total']
        
        # Access request statistics
        rows = self.fetchall("SELECT status, COUNT(*) as count FROM access_requests GROUP BY status")
        stats['access_requests'] = {row['status']: row['count'] for row in rows}
        
        return stats
    
    def close(self) -> None:
        """Close database connections."""
        if hasattr(self._local, 'connection'):
            self._local.connection.close()
            delattr(self._local, 'connection')
        logger.info("Database connections closed")


# Global database instance - will be initialized in main.py
db = None
