import asyncpg
import os
from datetime import datetime
from typing import Optional
import pytz
from config import TIMEZONE

TZ = pytz.timezone(TIMEZONE)

def _get_db_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    # asyncpg requires postgresql:// not postgres://
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url

async def get_conn():
    url = _get_db_url()
    if not url:
        raise RuntimeError("DATABASE_URL n'est pas défini dans les variables d'environnement Railway.")
    return await asyncpg.connect(url)

async def init_db():
    conn = await get_conn()
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                language_code TEXT DEFAULT 'fr',
                joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_active TEXT DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1,
                receive_briefing INTEGER DEFAULT 1
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                center_code TEXT,
                subscribed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1,
                UNIQUE(user_id, center_code)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS appointment_events (
                id SERIAL PRIMARY KEY,
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
        await conn.execute("""
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
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS notifications_sent (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                center_code TEXT,
                sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
                message_id INTEGER
            )
        """)
    finally:
        await conn.close()


async def add_or_update_user(user_id: int, username: str, first_name: str, language_code: str = "fr"):
    conn = await get_conn()
    try:
        now = datetime.now(TZ).isoformat()
        await conn.execute("""
            INSERT INTO users (user_id, username, first_name, language_code, joined_at, last_active)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT(user_id) DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_active = EXCLUDED.last_active,
                is_active = 1
        """, user_id, username or "", first_name or "Utilisateur", language_code, now, now)
    finally:
        await conn.close()


async def subscribe_to_center(user_id: int, center_code: str) -> bool:
    conn = await get_conn()
    try:
        await conn.execute("""
            INSERT INTO subscriptions (user_id, center_code, subscribed_at, is_active)
            VALUES ($1, $2, CURRENT_TIMESTAMP, 1)
            ON CONFLICT(user_id, center_code) DO UPDATE SET is_active = 1
        """, user_id, center_code)
        return True
    except Exception:
        return False
    finally:
        await conn.close()


async def unsubscribe_from_center(user_id: int, center_code: str) -> bool:
    conn = await get_conn()
    try:
        await conn.execute("""
            UPDATE subscriptions SET is_active = 0
            WHERE user_id = $1 AND center_code = $2
        """, user_id, center_code)
        return True
    finally:
        await conn.close()


async def get_user_subscriptions(user_id: int) -> list:
    conn = await get_conn()
    try:
        rows = await conn.fetch("""
            SELECT center_code FROM subscriptions
            WHERE user_id = $1 AND is_active = 1
        """, user_id)
        return [row["center_code"] for row in rows]
    finally:
        await conn.close()


async def get_subscribers_for_center(center_code: str) -> list:
    conn = await get_conn()
    try:
        rows = await conn.fetch("""
            SELECT DISTINCT s.user_id FROM subscriptions s
            JOIN users u ON s.user_id = u.user_id
            WHERE s.center_code = $1 AND s.is_active = 1 AND u.is_active = 1
        """, center_code)
        return [row["user_id"] for row in rows]
    finally:
        await conn.close()


async def get_all_active_users() -> list:
    """Retourne TOUS les utilisateurs actifs (broadcast + briefing)."""
    conn = await get_conn()
    try:
        rows = await conn.fetch("""
            SELECT user_id, first_name FROM users WHERE is_active = 1
        """)
        return [(row["user_id"], row["first_name"]) for row in rows]
    finally:
        await conn.close()


async def get_briefing_users() -> list:
    """Retourne uniquement les utilisateurs avec briefing activé."""
    conn = await get_conn()
    try:
        rows = await conn.fetch("""
            SELECT user_id, first_name FROM users
            WHERE is_active = 1 AND receive_briefing = 1
        """)
        return [(row["user_id"], row["first_name"]) for row in rows]
    finally:
        await conn.close()


async def update_center_status(center_code: str, has_slots: bool, slots_count: int, earliest_date: Optional[str]):
    conn = await get_conn()
    try:
        now = datetime.now(TZ).isoformat()
        last_available = now if has_slots else None
        await conn.execute("""
            INSERT INTO center_status (center_code, last_checked, has_slots, slots_count, earliest_date, last_available, consecutive_checks)
            VALUES ($1, $2, $3, $4, $5, $6, 0)
            ON CONFLICT(center_code) DO UPDATE SET
                last_checked = EXCLUDED.last_checked,
                has_slots = EXCLUDED.has_slots,
                slots_count = EXCLUDED.slots_count,
                earliest_date = EXCLUDED.earliest_date,
                last_available = CASE WHEN EXCLUDED.has_slots = 1 THEN EXCLUDED.last_available ELSE center_status.last_available END,
                consecutive_checks = CASE WHEN EXCLUDED.has_slots = 1 THEN center_status.consecutive_checks + 1 ELSE 0 END
        """, center_code, now, 1 if has_slots else 0, slots_count, earliest_date, last_available)
    finally:
        await conn.close()


async def get_center_status(center_code: str) -> Optional[dict]:
    conn = await get_conn()
    try:
        row = await conn.fetchrow("""
            SELECT center_code, last_checked, has_slots, slots_count, earliest_date, last_available, consecutive_checks
            FROM center_status WHERE center_code = $1
        """, center_code)
        if row:
            return {
                "center_code": row["center_code"],
                "last_checked": row["last_checked"],
                "has_slots": bool(row["has_slots"]),
                "slots_count": row["slots_count"],
                "earliest_date": row["earliest_date"],
                "last_available": row["last_available"],
                "consecutive_checks": row["consecutive_checks"]
            }
        return None
    finally:
        await conn.close()


async def record_appointment_event(center_code: str, event_type: str, slots_count: int, earliest_date: Optional[str]):
    conn = await get_conn()
    try:
        now = datetime.now(TZ)
        await conn.execute("""
            INSERT INTO appointment_events
            (center_code, event_type, slots_count, earliest_date, detected_at, day_of_week, day_of_month, hour_detected)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """, center_code, event_type, slots_count, earliest_date,
            now.isoformat(), now.weekday(), now.day, now.hour)
    finally:
        await conn.close()


async def get_historical_events(center_code: Optional[str] = None, limit: int = 500) -> list:
    conn = await get_conn()
    try:
        if center_code:
            rows = await conn.fetch("""
                SELECT center_code, event_type, detected_at, day_of_week, day_of_month, hour_detected
                FROM appointment_events WHERE center_code = $1 AND event_type = 'SLOTS_OPENED'
                ORDER BY detected_at DESC LIMIT $2
            """, center_code, limit)
        else:
            rows = await conn.fetch("""
                SELECT center_code, event_type, detected_at, day_of_week, day_of_month, hour_detected
                FROM appointment_events WHERE event_type = 'SLOTS_OPENED'
                ORDER BY detected_at DESC LIMIT $1
            """, limit)
        return [
            {
                "center_code": row["center_code"],
                "event_type": row["event_type"],
                "detected_at": row["detected_at"],
                "day_of_week": row["day_of_week"],
                "day_of_month": row["day_of_month"],
                "hour_detected": row["hour_detected"]
            }
            for row in rows
        ]
    finally:
        await conn.close()


async def get_stats() -> dict:
    conn = await get_conn()
    try:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_active = 1")
        total_subs = await conn.fetchval("SELECT COUNT(*) FROM subscriptions WHERE is_active = 1")
        total_events = await conn.fetchval("SELECT COUNT(*) FROM appointment_events WHERE event_type = 'SLOTS_OPENED'")
        return {
            "total_users": total_users,
            "total_subscriptions": total_subs,
            "total_slot_events": total_events
        }
    finally:
        await conn.close()


async def toggle_briefing(user_id: int, enabled: bool):
    conn = await get_conn()
    try:
        await conn.execute("""
            UPDATE users SET receive_briefing = $1 WHERE user_id = $2
        """, 1 if enabled else 0, user_id)
    finally:
        await conn.close()


async def get_all_users_detailed() -> list:
    conn = await get_conn()
    try:
        rows = await conn.fetch("""
            SELECT u.user_id, u.username, u.first_name, u.joined_at,
                   u.last_active, u.receive_briefing,
                   COUNT(s.id) as sub_count
            FROM users u
            LEFT JOIN subscriptions s ON u.user_id = s.user_id AND s.is_active = 1
            WHERE u.is_active = 1
            GROUP BY u.user_id
            ORDER BY u.joined_at DESC
        """)
        return [
            {
                "user_id": row["user_id"],
                "username": row["username"],
                "first_name": row["first_name"],
                "joined_at": row["joined_at"],
                "last_active": row["last_active"],
                "receive_briefing": bool(row["receive_briefing"]),
                "sub_count": row["sub_count"],
            }
            for row in rows
        ]
    finally:
        await conn.close()


async def get_user_detail(user_id: int) -> Optional[dict]:
    conn = await get_conn()
    try:
        row = await conn.fetchrow("""
            SELECT user_id, username, first_name, language_code,
                   joined_at, last_active, is_active, receive_briefing
            FROM users WHERE user_id = $1
        """, user_id)
        if not row:
            return None
        user = {
            "user_id": row["user_id"], "username": row["username"], "first_name": row["first_name"],
            "language_code": row["language_code"], "joined_at": row["joined_at"],
            "last_active": row["last_active"], "is_active": bool(row["is_active"]),
            "receive_briefing": bool(row["receive_briefing"]),
        }
        subs = await conn.fetch("""
            SELECT center_code, subscribed_at FROM subscriptions
            WHERE user_id = $1 AND is_active = 1
        """, user_id)
        user["subscriptions"] = [{"center": r["center_code"], "since": r["subscribed_at"]} for r in subs]
        return user
    finally:
        await conn.close()


async def get_subs_per_center() -> dict:
    conn = await get_conn()
    try:
        rows = await conn.fetch("""
            SELECT center_code, COUNT(*) as cnt
            FROM subscriptions WHERE is_active = 1
            GROUP BY center_code ORDER BY cnt DESC
        """)
        return {row["center_code"]: row["cnt"] for row in rows}
    finally:
        await conn.close()


async def ban_user(user_id: int):
    conn = await get_conn()
    try:
        await conn.execute("UPDATE users SET is_active = 0 WHERE user_id = $1", user_id)
        await conn.execute("UPDATE subscriptions SET is_active = 0 WHERE user_id = $1", user_id)
    finally:
        await conn.close()
