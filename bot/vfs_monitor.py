"""
VFS Global Monitor — Algeria Italy Student Visa
Détection via Playwright (contourne Cloudflare).
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional, Tuple
import pytz
from config import CENTERS, TIMEZONE

logger = logging.getLogger(__name__)
TZ = pytz.timezone(TIMEZONE)
BASE = "https://visa.vfsglobal.com/dza/en/ita"

NO_SLOT_PHRASES = [
   "no appointment slots are currently available",
   "aucun créneau de rendez-vous n'est actuellement disponible",
   "de nouveaux créneaux s'ouvrent à intervalles réguliers",
   "no slots are currently available",
   "there are no available slots",
   "appointments are not available",
   "new slots open at regular intervals",
   "nouveaux créneaux s'ouvrent à intervalles réguliers",
   "please try again later",
   "veuillez réessayer plus tard",
   "temporarily unavailable",
   "currently not accepting",
   "no appointment available",
]

SLOT_PHRASES = [
   "select a date",
   "choose a date",
   "available appointment",
   "book an appointment",
   "appointment available",
   "créneau disponible",
   "réserver un rendez-vous",
]

def _analyse_text(html: str) -> Optional[bool]:
   t = html.lower()
   for phrase in NO_SLOT_PHRASES:
       if phrase.lower() in t:
           return False
   for phrase in SLOT_PHRASES:
       if phrase.lower() in t:
           return True
   return None

async def check_appointments_via_web(center_code: str) -> Tuple[bool, int, Optional[str]]:
   try:
       from playwright.async_api import async_playwright
       async with async_playwright() as p:
           browser = await p.chromium.launch(headless=True)
           context = await browser.new_context(
               user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
               locale="fr-FR",
           )
           page = await context.new_page()
           await page.goto(f"{BASE}/appointment", wait_until="networkidle", timeout=30000)
           html = await page.content()
           await browser.close()
           result = _analyse_text(html)
           if result is not None:
               logger.info(f"[{center_code}] playwright → {'SLOTS' if result else 'no slots'}")
               return result, 0, None
   except Exception as e:
       logger.warning(f"[{center_code}] Playwright failed: {e}")
   return False, 0, None

async def check_all_centers() -> dict:
   results = {}
   async def _check_one(code: str):
       try:
           has_slots, count, earliest = await check_appointments_via_web(code)
           results[code] = {
               "has_slots": has_slots,
               "count": count,
               "earliest": earliest,
               "checked_at": datetime.now(TZ).isoformat(),
               "error": None,
           }
       except Exception as e:
           results[code] = {
               "has_slots": False,
               "count": 0,
               "earliest": None,
               "error": str(e),
               "checked_at": datetime.now(TZ).isoformat(),
           }
   await asyncio.gather(*[_check_one(code) for code in CENTERS.keys()])
   return results
