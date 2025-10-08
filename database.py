import aiosqlite
from typing import Optional, List, Dict
from datetime import datetime
import config


class Database:
    def __init__(self, db_path: str = config.DATABASE_PATH):
        self.db_path = db_path

    async def init_db(self):
        """Initialize database with required tables"""
        async with aiosqlite.connect(self.db_path) as db:
            # Users table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    full_name TEXT,
                    phone TEXT,
                    email TEXT,
                    company_name TEXT,
                    role TEXT,
                    bitrix_id INTEGER,
                    traffic_source TEXT,
                    referral_code TEXT,
                    is_blocked INTEGER DEFAULT 0,
                    privacy_consent INTEGER DEFAULT 0,
                    registration_date TEXT,
                    last_activity TEXT
                )
            ''')

            # Deals table (cache from Bitrix)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS deals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    deal_number TEXT UNIQUE,
                    bitrix_deal_id INTEGER,
                    designer_telegram_id INTEGER,
                    client_full_name TEXT,
                    client_phone TEXT,
                    project_file_id TEXT,
                    comment TEXT,
                    status TEXT,
                    created_date TEXT,
                    FOREIGN KEY (designer_telegram_id) REFERENCES users(telegram_id)
                )
            ''')

            # User states table for FSM
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_states (
                    telegram_id INTEGER PRIMARY KEY,
                    state TEXT,
                    data TEXT,
                    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
                )
            ''')

            await db.commit()

    # User operations
    async def add_user(self, telegram_id: int, traffic_source: str = None):
        """Add new user to database"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                '''INSERT OR IGNORE INTO users
                   (telegram_id, traffic_source, registration_date, last_activity)
                   VALUES (?, ?, ?, ?)''',
                (telegram_id, traffic_source, datetime.now().isoformat(), datetime.now().isoformat())
            )
            await db.commit()

    async def update_user(self, telegram_id: int, **kwargs):
        """Update user information"""
        fields = ', '.join([f"{key} = ?" for key in kwargs.keys()])
        values = list(kwargs.values()) + [telegram_id]

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                f"UPDATE users SET {fields}, last_activity = ? WHERE telegram_id = ?",
                values + [datetime.now().isoformat(), telegram_id]
            )
            await db.commit()

    async def get_user(self, telegram_id: int) -> Optional[Dict]:
        """Get user by telegram_id"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users WHERE telegram_id = ?",
                (telegram_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_user_by_phone(self, phone: str) -> Optional[Dict]:
        """Get user by phone number"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users WHERE phone = ?",
                (phone,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_all_users(self) -> List[Dict]:
        """Get all users"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users") as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_users_by_role(self, role: str) -> List[Dict]:
        """Get users filtered by role"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users WHERE role = ?",
                (role,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def set_user_blocked(self, telegram_id: int, is_blocked: bool):
        """Set user blocked status"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET is_blocked = ? WHERE telegram_id = ?",
                (1 if is_blocked else 0, telegram_id)
            )
            await db.commit()

    # Deal operations
    async def add_deal(self, deal_data: Dict):
        """Add new deal to database"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                '''INSERT INTO deals
                   (deal_number, bitrix_deal_id, designer_telegram_id, client_full_name,
                    client_phone, project_file_id, comment, status, created_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    deal_data.get('deal_number'),
                    deal_data.get('bitrix_deal_id'),
                    deal_data.get('designer_telegram_id'),
                    deal_data.get('client_full_name'),
                    deal_data.get('client_phone'),
                    deal_data.get('project_file_id'),
                    deal_data.get('comment'),
                    deal_data.get('status'),
                    datetime.now().isoformat()
                )
            )
            await db.commit()

    async def get_user_deals(self, telegram_id: int) -> List[Dict]:
        """Get all deals for a specific user"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM deals WHERE designer_telegram_id = ? ORDER BY created_date DESC",
                (telegram_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_deal_by_number(self, deal_number: str) -> Optional[Dict]:
        """Get deal by deal number"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM deals WHERE deal_number = ?",
                (deal_number,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def update_deal_status(self, deal_number: str, status: str):
        """Update deal status"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE deals SET status = ? WHERE deal_number = ?",
                (status, deal_number)
            )
            await db.commit()

    # State management
    async def set_state(self, telegram_id: int, state: str, data: str = None):
        """Set user state for FSM"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                '''INSERT OR REPLACE INTO user_states (telegram_id, state, data)
                   VALUES (?, ?, ?)''',
                (telegram_id, state, data)
            )
            await db.commit()

    async def get_state(self, telegram_id: int) -> Optional[Dict]:
        """Get user state"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM user_states WHERE telegram_id = ?",
                (telegram_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def clear_state(self, telegram_id: int):
        """Clear user state"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "DELETE FROM user_states WHERE telegram_id = ?",
                (telegram_id,)
            )
            await db.commit()
