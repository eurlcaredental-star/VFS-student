import asyncio
import logging
from datetime import datetime
from typing import Optional
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from config import (
    CHECK_INTERVAL_SECONDS, TIMEZONE, CENTERS,
    BRIEFING_HOUR, BRIEFING_MINUTE
)
from database import (
    update_center_status, get_center_status,
    record_appointment_event, get_subscribers_for_center,
    get_all_active_users, get_briefing_users, get_historical_events
)
from vfs_monitor import check_all_centers
from briefing import get_daily_briefing, get_alert_message
from predictions import build_predictions
from vfs_monitor import set_alert_callback

logger = logging.getLogger(__name__)
TZ = pytz.timezone(TIMEZONE)

_scheduler: Optional[AsyncIOScheduler] = None
_bot = None
_previous_statuses = {}


def setup_scheduler(bot) -> AsyncIOScheduler:
    global _scheduler, _bot
    _bot = bot
    for admin_id in ADMIN_USER_IDS:
        set_alert_callback(lambda msg: send_message_safe(admin_id, msg))
        break

    scheduler = AsyncIOScheduler(timezone=TZ)


    scheduler.add_job(
        check_and_alert,
        trigger=IntervalTrigger(seconds=CHECK_INTERVAL_SECONDS),
        id="vfs_check",
        name="VFS Appointment Check",
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    scheduler.add_job(
        send_daily_briefing,
        trigger=CronTrigger(hour=BRIEFING_HOUR, minute=BRIEFING_MINUTE, timezone=TZ),
        id="daily_briefing",
        name="Daily Briefing",
        replace_existing=True,
        max_instances=1
    )

    scheduler.add_job(
        update_predictions_cache,
        trigger=CronTrigger(hour=0, minute=30, timezone=TZ),
        id="update_predictions",
        name="Update Predictions Cache",
        replace_existing=True,
        max_instances=1
    )

    _scheduler = scheduler
    return scheduler


async def check_and_alert():
    """Main monitoring function — checks all centers and sends alerts"""
    global _previous_statuses

    logger.info(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] Checking VFS appointments...")

    try:
        results = await check_all_centers()
    except Exception as e:
        logger.error(f"Error during check_all_centers: {e}")
        return

    for center_code, result in results.items():
        has_slots = result.get("has_slots", False)
        count = result.get("count", 0)
        earliest = result.get("earliest")

        prev = _previous_statuses.get(center_code, {})
        prev_had_slots = prev.get("has_slots", False)

        await update_center_status(center_code, has_slots, count, earliest)

        if has_slots and not prev_had_slots:
            logger.info(f"🚨 SLOTS OPENED at {center_code}!")
            await record_appointment_event(center_code, "SLOTS_OPENED", count, earliest)
            await notify_subscribers(center_code, has_slots=True, count=count, earliest=earliest)

        elif not has_slots and prev_had_slots:
            logger.info(f"Slots closed at {center_code}")
            await record_appointment_event(center_code, "SLOTS_CLOSED", 0, None)

        _previous_statuses[center_code] = {
            "has_slots": has_slots,
            "count": count,
            "earliest": earliest
        }


async def notify_subscribers(center_code: str, has_slots: bool, count: int = 0, earliest: Optional[str] = None):
    """Send notifications to all subscribers of a center"""
    if _bot is None:
        return

    subscribers = await get_subscribers_for_center(center_code)
    if not subscribers:
        logger.info(f"No subscribers for {center_code}")
        return

    message = get_alert_message(center_code, has_slots, earliest, count)

    logger.info(f"Sending alerts to {len(subscribers)} subscribers for {center_code}")

    tasks = []
    for user_id in subscribers:
        tasks.append(send_message_safe(user_id, message, parse_mode="Markdown"))

    await asyncio.gather(*tasks)


async def send_message_safe(user_id: int, text: str, parse_mode: str = "Markdown"):
    """Send a message safely, handling errors"""
    if _bot is None:
        return

    try:
        await _bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=True
        )
    except Exception as e:
        err_str = str(e)
        if "blocked" in err_str.lower() or "not found" in err_str.lower() or "deactivated" in err_str.lower():
            logger.warning(f"User {user_id} blocked/deactivated the bot")
        else:
            logger.error(f"Error sending to {user_id}: {e}")


async def send_daily_briefing():
    """Send daily briefing to users who have it enabled"""
    if _bot is None:
        return

    users = await get_briefing_users()
    logger.info(f"Sending daily briefing to {len(users)} users")

    for user_id, first_name in users:
        message = get_daily_briefing(first_name or "cher(e) étudiant(e)")
        await send_message_safe(user_id, message, parse_mode="Markdown")
        await asyncio.sleep(0.05)


async def update_predictions_cache():
    """Update the predictions cache from historical data"""
    try:
        for center_code in CENTERS.keys():
            events = await get_historical_events(center_code=center_code, limit=200)
            predictions = build_predictions(events, center_code)
            logger.info(f"Updated predictions for {center_code}: {len(events)} events")
    except Exception as e:
        logger.error(f"Error updating predictions: {e}")


def get_scheduler() -> Optional[AsyncIOScheduler]:
    return _scheduler
