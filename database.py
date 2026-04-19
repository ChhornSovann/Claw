# database.py
"""
Database module for Claw Bot
Async SQLite operations with caching and analytics
"""

import json
import sqlite3
import threading
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List


class Database:
    """
    Async SQLite database handler for user data, sessions, and bot analytics.
    Uses thread-local connections for thread safety.
    """
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._local = threading.local()
        self.logger = logging.getLogger(__name__)
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local connection"""
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            self._local.connection = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.connection.row_factory = sqlite3.Row
        return self._local.connection
    
    async def init_db(self) -> None:
        """Initialize database tables"""
        def _init():
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Users table - stores user profiles and activity
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    language_code TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    message_count INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1
                )
            ''')
            
            # Conversations table - for survey/state tracking
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    state TEXT,
                    data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            # Command logs - for analytics and debugging
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS command_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    command TEXT,
                    args TEXT,
                    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    success INTEGER DEFAULT 1,
                    error_message TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            # API cache - to respect rate limits and improve performance
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS api_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    api_type TEXT,
                    query TEXT,
                    response TEXT,
                    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP
                )
            ''')
            
            # Create indexes for better query performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_activity ON users(last_activity)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_cache_lookup ON api_cache(api_type, query)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_command_logs_user ON command_logs(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id)')
            
            conn.commit()
            self.logger.info("Database tables initialized")
        
        await asyncio.to_thread(_init)
    
    # ============ User Management ============
    
    async def upsert_user(self, user_id: int, username: str, first_name: str, 
                          last_name: str, language_code: str) -> None:
        """Add new user or update existing user activity"""
        def _upsert():
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO users (user_id, username, first_name, last_name, language_code)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    last_activity = CURRENT_TIMESTAMP,
                    message_count = message_count + 1
            ''', (user_id, username, first_name, last_name, language_code))
            conn.commit()
        
        await asyncio.to_thread(_upsert)
    
    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user by ID"""
        def _get():
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        
        return await asyncio.to_thread(_get)
    
    async def get_all_users(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all users (for admin purposes)"""
        def _get():
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users ORDER BY last_activity DESC LIMIT ?', (limit,))
            return [dict(row) for row in cursor.fetchall()]
        
        return await asyncio.to_thread(_get)
    
    # ============ Analytics ============
    
    async def log_command(self, user_id: int, command: str, args: str = '', 
                          success: bool = True, error_message: str = '') -> None:
        """Log command usage for analytics"""
        def _log():
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO command_logs (user_id, command, args, success, error_message)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, command, args, int(success), error_message))
            conn.commit()
        
        await asyncio.to_thread(_log)
    
    async def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        """Get comprehensive user statistics"""
        def _get():
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # User basic stats
            cursor.execute('''
                SELECT message_count, created_at, last_activity
                FROM users WHERE user_id = ?
            ''', (user_id,))
            user_row = cursor.fetchone()
            
            if not user_row:
                return {}
            
            # Command counts
            cursor.execute('''
                SELECT command, COUNT(*) as count 
                FROM command_logs 
                WHERE user_id = ? 
                GROUP BY command
            ''', (user_id,))
            commands = {row['command']: row['count'] for row in cursor.fetchall()}
            
            return {
                'message_count': user_row['message_count'],
                'created_at': user_row['created_at'],
                'last_activity': user_row['last_activity'],
                'commands_used': commands,
                'total_commands': sum(commands.values())
            }
        
        return await asyncio.to_thread(_get)
    
    async def get_bot_stats(self) -> Dict[str, Any]:
        """Get overall bot statistics"""
        def _get():
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Total users
            cursor.execute('SELECT COUNT(*) as total FROM users')
            total_users = cursor.fetchone()['total']
            
            # Active users (last 7 days)
            cursor.execute('''
                SELECT COUNT(*) as active FROM users 
                WHERE last_activity > datetime('now', '-7 days')
            ''')
            active_users = cursor.fetchone()['active']
            
            # Total commands
            cursor.execute('SELECT COUNT(*) as total FROM command_logs')
            total_commands = cursor.fetchone()['total']
            
            # Popular commands
            cursor.execute('''
                SELECT command, COUNT(*) as count 
                FROM command_logs 
                GROUP BY command 
                ORDER BY count DESC 
                LIMIT 5
            ''')
            popular_commands = [dict(row) for row in cursor.fetchall()]
            
            return {
                'total_users': total_users,
                'active_users_7d': active_users,
                'total_commands': total_commands,
                'popular_commands': popular_commands
            }
        
        return await asyncio.to_thread(_get)
    
    # ============ Conversation State ============
    
    async def save_conversation_state(self, user_id: int, state: str, 
                                       data: Dict[str, Any]) -> None:
        """Save conversation state for multi-step interactions"""
        def _save():
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO conversations (user_id, state, data)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    state = excluded.state,
                    data = excluded.data,
                    updated_at = CURRENT_TIMESTAMP
            ''', (user_id, state, json.dumps(data)))
            conn.commit()
        
        await asyncio.to_thread(_save)
    
    async def get_conversation_state(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve conversation state"""
        def _get():
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT state, data FROM conversations 
                WHERE user_id = ? 
                ORDER BY updated_at DESC LIMIT 1
            ''', (user_id,))
            row = cursor.fetchone()
            if row:
                return {'state': row['state'], 'data': json.loads(row['data'])}
            return None
        
        return await asyncio.to_thread(_get)
    
    async def clear_conversation_state(self, user_id: int) -> None:
        """Clear conversation state"""
        def _clear():
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM conversations WHERE user_id = ?', (user_id,))
            conn.commit()
        
        await asyncio.to_thread(_clear)
    
    # ============ API Caching ============
    
    async def cache_api_response(self, api_type: str, query: str, 
                                  response: str, ttl_minutes: int = 30) -> None:
        """Cache API response to respect rate limits"""
        def _cache():
            conn = self._get_connection()
            cursor = conn.cursor()
            expires = datetime.now() + timedelta(minutes=ttl_minutes)
            
            # Delete old cache entries for this query
            cursor.execute('''
                DELETE FROM api_cache 
                WHERE api_type = ? AND query = ?
            ''', (api_type, query))
            
            # Insert new cache
            cursor.execute('''
                INSERT INTO api_cache (api_type, query, response, expires_at)
                VALUES (?, ?, ?, ?)
            ''', (api_type, query, response, expires))
            conn.commit()
        
        await asyncio.to_thread(_cache)
    
    async def get_cached_response(self, api_type: str, query: str) -> Optional[str]:
        """Get cached API response if not expired"""
        def _get():
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT response FROM api_cache 
                WHERE api_type = ? AND query = ? AND expires_at > CURRENT_TIMESTAMP
                ORDER BY cached_at DESC LIMIT 1
            ''', (api_type, query))
            row = cursor.fetchone()
            return row['response'] if row else None
        
        return await asyncio.to_thread(_get)
    
    async def clear_expired_cache(self) -> int:
        """Clear expired cache entries, returns count deleted"""
        def _clear():
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM api_cache WHERE expires_at < CURRENT_TIMESTAMP
            ''')
            conn.commit()
            return cursor.rowcount
        
        return await asyncio.to_thread(_clear)