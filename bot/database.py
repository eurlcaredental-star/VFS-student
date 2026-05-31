import aiosqlite
import json
from datetime import datetime
from typing import Optional
import pytz
from config import DB_PATH, TIMEZONE

TZ = pytz.timezone(TIMEZONE)


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                language_code TEXT DEFAULT 'fr',
                joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_active TEXT DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1,
                receive_briefing INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                center_code TEXT,
                subscribed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1,
                UNIQUE(user_id, center_code)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS appointment_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                center_code TEXT,
                event_type TEXT,
                slots_count INTEGER DEFAULT 0,
                earliest_date TEXT,
                detected_at TEXT DEFAULT CURRENT_TIMESTAMP,
                day_of_week INTEGER,
                day_of_month INTEGER,
                hour_detected INTEGER,
                raw_data TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS center_status (
                center_code TEXT PRIMARY KEY,
                last_checked TEXT,
                has_slots INTEGER DEFAULT 0,
                slots_count INTEGER DEFAULT 0,
                earliest_date TEXT,
                last_available TEXT,
                consecutive_checks INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS notifications_sent (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                center_code TEXT,
                sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
                message_id INTEGER
            )
        """)
        await db.commit()


async def add_or_update_user(user_id: int, username: str, first_name: str, language_code: str = "fr"):
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.now(TZ).isoformat()
        await db.execute("""
            INSERT INTO users (user_id, username, first_name, language_code, joined_at, last_active)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_active = excluded.last_active,
                is_active = 1
        """, (user_id, username or "", first_name or "Utilisateur", language_code, now, now))
        await db.commit()


async def subscribe_to_center(user_id: int, center_code: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("""
                INSERT INTO subscriptions (user_id, center_code, subscribed_at, is_active)
                VALUES (?, ?, CURRENT_TIMESTAMP, 1)
                ON CONFLICT(user_id, center_code) DO UPDATE SET is_active = 1
            """, (user_id, center_code))
            await db.commit()
            return True
        except Exception:
            return False


async def unsubscribe_from_center(user_id: int, center_code: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE subscriptions SET is_active = 0
            WHERE user_id = ? AND center_code = ?
        """, (user_id, center_code))
        await db.commit()
        return True


async def get_user_subscriptions(user_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT center_code FROM subscriptions
            WHERE user_id = ? AND is_active = 1
        """, (user_id,)) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


async def get_subscribers_for_center(center_code: str) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT DISTINCT s.user_id FROM subscriptions s
            JOIN users u ON s.user_id = u.user_id
            WHERE s.center_code = ? AND s.is_active = 1 AND u.is_active = 1
        """, (center_code,)) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


async def get_all_active_users() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT user_id, first_name FROM users
            WHERE is_active = 1 AND receive_briefing = 1
        """) as cursor:
            rows = await cursor.fetchall()
            return [(row[0], row[1]) for row in rows]


async def update_center_status(center_code: str, has_slots: bool, slots_count: int, earliest_date: Optional[str]):
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.now(TZ).isoformat()
        last_available = now if has_slots else None

        await db.execute("""
            INSERT INTO center_status (center_code, last_checked, has_slots, slots_count, earliest_date, last_available)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(center_code) DO UPDATE SET
                last_checked = excluded.last_checked,
                has_slots = excluded.has_slots,
                slots_count = excluded.slots_count,
                earliest_date = excluded.earliest_date,
                last_available = CASE WHEN excluded.has_slots = 1 THEN excluded.last_available ELSE center_status.last_available END,
                consecutive_checks = CASE WHEN excluded.has_slots = 1 THEN center_status.consecutive_checks + 1 ELSE 0 END
        """, (center_code, now, 1 if has_slots else 0, slots_count, earliest_date, last_available))
        await db.commit()


async def get_center_status(center_code: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT center_code, last_checked, has_slots, slots_count, earliest_date, last_available, consecutive_checks
            FROM center_status WHERE center_code = ?
        """, (center_code,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "center_code": row[0],
                    "last_checked": row[1],
                    "has_slots": bool(row[2]),
                    "slots_count": row[3],
                    "earliest_date": row[4],
                    "last_available": row[5],
                    "consecutive_checks": row[6]
                }
            return None


async def record_appointment_event(center_code: str, event_type: str, slots_count: int, earliest_date: Optional[str]):
    now = datetime.now(TZ)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO appointment_events
            (center_code, event_type, slots_count, earliest_date, detected_at, day_of_week, day_of_month, hour_detected)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            center_code, event_type, slots_count, earliest_date,
            now.isoformat(), now.weekday(), now.day, now.hour
        ))
        await db.commit()


async def get_historical_events(center_code: Optional[str] = None, limit: int = 500) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        if center_code:
            query = """
                SELECT center_code, event_type, detected_at, day_of_week, day_of_month, hour_detected
                FROM appointment_events WHERE center_code = ? AND event_type = 'SLOTS_OPENED'
                ORDER BY detected_at DESC LIMIT ?
            """
            params = (center_code, limit)
        else:
            query = """
                SELECT center_code, event_type, detected_at, day_of_week, day_of_month, hour_detected
                FROM appointment_events WHERE event_type = 'SLOTS_OPENED'
                ORDER BY detected_at DESC LIMIT ?
            """
            params = (limit,)

        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "center_code": row[0],
                    "event_type": row[1],
                    "detected_at": row[2],
                    "day_of_week": row[3],
                    "day_of_month": row[4],
                    "hour_detected": row[5]
                }
                for row in rows
            ]


async def get_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_active = 1") as c:
            total_users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM subscriptions WHERE is_active = 1") as c:
            total_subs = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM appointment_events WHERE event_type = 'SLOTS_OPENED'") as c:
            total_events = (await c.fetchone())[0]
        return {
            "total_users": total_users,
            "total_subscriptions": total_subs,
            "total_slot_events": total_events
        }


async def toggle_briefing(user_id: int, enabled: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE users SET receive_briefing = ? WHERE user_id = ?
        """, (1 if enabled else 0, user_id))
        await db.commit()


async def get_all_users_detailed() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT u.user_id, u.username, u.first_name, u.joined_at,
                   u.last_active, u.receive_briefing,
                   COUNT(s.id) as sub_count
            FROM users u
            LEFT JOIN subscriptions s ON u.user_id = s.user_id AND s.is_active = 1
            WHERE u.is_active = 1
            GROUP BY u.user_id
            ORDER BY u.joined_at DESC
        """) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "user_id": row[0],
                    "username": row[1],
                    "first_name": row[2],
                    "joined_at": row[3],
                    "last_active": row[4],
                    "receive_briefing": bool(row[5]),
                    "sub_count": row[6],
                }
                for row in rows
            ]


async def get_user_detail(user_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT user_id, username, first_name, language_code,
                   joined_at, last_active, is_active, receive_briefing
            FROM users WHERE user_id = ?
        """, (user_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            user = {
                "user_id": row[0], "username": row[1], "first_name": row[2],
                "language_code": row[3], "joined_at": row[4],
                "last_active": row[5], "is_active": bool(row[6]),
                "receive_briefing": bool(row[7]),
            }
        async with db.execute("""
            SELECT center_code, subscribed_at FROM subscriptions
            WHERE user_id = ? AND is_active = 1
        """, (user_id,)) as cursor:
            subs = await cursor.fetchall()
            user["subscriptions"] = [{"center": r[0], "since": r[1]} for r in subs]
        return user


async def get_subs_per_center() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT center_code, COUNT(*) as cnt
            FROM subscriptions WHERE is_active = 1
            GROUP BY center_code ORDER BY cnt DESC
        """) as cursor:
            rows = await cursor.fetchall()
            return {row[0]: row[1] for row in rows}


async def ban_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_active = 0 WHERE user_id = ?", (user_id,))
        await db.execute("UPDATE subscriptions SET is_active = 0 WHERE user_id = ?", (user_id,))
        await db.commit()


from typing import Optional
