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
            async def _table_exists(table: str) -> bool:
                async with db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
                    (table,)
                ) as cursor:
                    return await cursor.fetchone() is not None

            async def _column_exists(table: str, column: str) -> bool:
                async with db.execute(f"PRAGMA table_info({table})") as cursor:
                    rows = await cursor.fetchall()
                return any(row[1] == column for row in rows)

            async def _ensure_column(table: str, column: str, definition: str):
                if not await _column_exists(table, column):
                    await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

            async def _rename_column(table: str, old: str, new: str):
                if await _column_exists(table, old) and not await _column_exists(table, new):
                    await db.execute(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")

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

            # Leads table (cache from Bitrix)
            legacy_table = 'd' + 'eals'
            if await _table_exists(legacy_table) and not await _table_exists('leads'):
                await db.execute(f"ALTER TABLE {legacy_table} RENAME TO leads")

            await db.execute('''
                CREATE TABLE IF NOT EXISTS leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lead_number TEXT UNIQUE,
                    bitrix_lead_id INTEGER,
                    designer_telegram_id INTEGER,
                    client_full_name TEXT,
                    client_phone TEXT,
                    project_file_id TEXT,
                    project_file_name TEXT,
                    comment TEXT,
                    status TEXT,
                    entity_type TEXT DEFAULT 'lead',
                    owner_role TEXT,
                    created_date TEXT,
                    FOREIGN KEY (designer_telegram_id) REFERENCES users(telegram_id)
                )
            ''')

            await _rename_column('leads', 'd' + 'eal_number', 'lead_number')
            await _rename_column('leads', 'bitrix_' + 'de' + 'al_id', 'bitrix_lead_id')

            # Backwards compatibility for additional columns
            await _ensure_column('leads', 'project_file_name', 'TEXT')
            await _ensure_column('leads', 'entity_type', "TEXT DEFAULT 'lead'")
            await _ensure_column('leads', 'owner_role', 'TEXT')

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
        values = list(kwargs.values())

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

    # Lead operations
    async def add_lead(self, lead_data: Dict):
        """Add new lead to database"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                '''INSERT INTO leads
                   (lead_number, bitrix_lead_id, designer_telegram_id, client_full_name,
                    client_phone, project_file_id, project_file_name, comment, status,
                    entity_type, owner_role, created_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    lead_data.get('lead_number'),
                    lead_data.get('bitrix_lead_id'),
                    lead_data.get('designer_telegram_id'),
                    lead_data.get('client_full_name'),
                    lead_data.get('client_phone'),
                    lead_data.get('project_file_id'),
                    lead_data.get('project_file_name'),
                    lead_data.get('comment'),
                    lead_data.get('status'),
                    lead_data.get('entity_type', 'lead'),
                    lead_data.get('owner_role'),
                    datetime.now().isoformat()
                )
            )
            await db.commit()

    async def get_user_leads(self, telegram_id: int) -> List[Dict]:
        """Get all leads for a specific user"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM leads WHERE designer_telegram_id = ? ORDER BY created_date DESC",
                (telegram_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_lead_by_number(self, lead_number: str) -> Optional[Dict]:
        """Get lead by lead number"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM leads WHERE lead_number = ?",
                (lead_number,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def update_lead_status(self, lead_number: str, status: str):
        """Update lead status"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE leads SET status = ? WHERE lead_number = ?",
                (status, lead_number)
            )
            await db.commit()

    async def delete_lead(self, lead_number: str):
        """Delete lead from database"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "DELETE FROM leads WHERE lead_number = ?",
                (lead_number,)
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
