"""
VFS Global Session Manager
Maintains authenticated session for better appointment detection.
Uses a combination of browser cookies + API calls to check appointments.
"""

import asyncio
import json
import logging
import re
import time
from datetime import datetime
from typing import Optional, Tuple, Dict
import httpx
import pytz
from config import VFS_EMAIL, VFS_PASSWORD, VFS_WEB_BASE, TIMEZONE, CENTERS

logger = logging.getLogger(__name__)
TZ = pytz.timezone(TIMEZONE)

_session_cookies: Dict[str, str] = {}
_session_expiry: float = 0.0

SCHEDULE_URL = f"{VFS_WEB_BASE}/dza/en/ita/appointment/schedule"
LOGIN_URL = f"{VFS_WEB_BASE}/dza/en/ita/login"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}

NO_SLOT_PATTERNS = [
    r"aucun cr.neau de rendez-vous",
    r"no appointment slots are currently available",
    r"no slots available",
    r"nouveaux cr.neaux s.ouvrent",
    r"veuillez r.essayer plus tard",
    r"please try again later",
    r"appointment not available",
]

SLOT_AVAILABLE_PATTERNS = [
    r"select.{0,10}appointment.{0,10}date",
    r"choose.{0,10}date",
    r"available.{0,10}slot",
    r"cr.neau.{0,20}disponible",
    r"choisir.{0,10}date",
    r"book.{0,10}appointment",
    r"r.server.{0,10}rendez",
]


def check_html_for_slots(html: str) -> Optional[bool]:
    """
    Analyze HTML content for appointment slot indicators.
    Returns True (slots available), False (no slots), or None (unknown).
    """
    text = html.lower()

    for pattern in NO_SLOT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return False

    for pattern in SLOT_AVAILABLE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True

    if "calendar" in text and ("date" in text or "slot" in text):
        return True

    if "sorry" in text and ("appointment" in text or "slot" in text):
        return False

    return None


async def check_with_playwright(center_code: str) -> Tuple[bool, int, Optional[str]]:
    """
    Use Playwright to fully render the VFS page and check appointment availability.
    This bypasses JavaScript challenges and Cloudflare protection.
    """
    center = CENTERS.get(center_code, {})

    try:
        from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--window-size=1920,1080",
                ]
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
                locale="fr-FR",
                timezone_id=TIMEZONE,
                extra_http_headers={
                    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
                }
            )

            page = await context.new_page()
            await page.set_extra_http_headers({
                "Accept-Language": "fr-FR,fr;q=0.9",
                "Sec-Fetch-Site": "none",
            })

            try:
                await page.goto(
                    f"{VFS_WEB_BASE}/dza/en/ita/",
                    wait_until="domcontentloaded",
                    timeout=20000
                )
                await asyncio.sleep(2)
            except Exception:
                pass

            try:
                await page.goto(
                    SCHEDULE_URL,
                    wait_until="networkidle",
                    timeout=30000
                )
            except PlaywrightTimeout:
                await page.wait_for_timeout(3000)

            await page.wait_for_timeout(2000)
            content = await page.content()
            result = check_html_for_slots(content)

            if result is None:
                try:
                    selects = await page.query_selector_all("select")
                    for sel in selects:
                        options = await sel.query_selector_all("option")
                        for opt in options:
                            opt_text = (await opt.text_content() or "").lower()
                            if center["name"].lower().split()[0] in opt_text or center_code.lower() in opt_text:
                                await sel.select_option(value=await opt.get_attribute("value") or "")
                                await page.wait_for_timeout(3000)
                                content = await page.content()
                                result = check_html_for_slots(content)
                                break
                        if result is not None:
                            break
                except Exception as e:
                    logger.debug(f"Center selection failed: {e}")

            date_slots = []
            try:
                date_elements = await page.query_selector_all(
                    "[class*='date']:not([disabled]), "
                    "[class*='slot']:not([disabled]), "
                    ".available-date, "
                    ".calendar-day:not(.disabled)"
                )
                for el in date_elements:
                    date_text = await el.text_content()
                    if date_text and date_text.strip().isdigit():
                        date_slots.append(date_text.strip())
            except Exception:
                pass

            if date_slots:
                result = True

            await browser.close()

            if result is True:
                return True, len(date_slots) if date_slots else 1, None
            elif result is False:
                return False, 0, None
            else:
                logger.warning(f"Could not determine slot status for {center_code}")
                return False, 0, None

    except ImportError:
        logger.warning("Playwright not installed — cannot use browser automation")
        return False, 0, None
    except Exception as e:
        logger.error(f"Playwright check failed for {center_code}: {e}")
        return False, 0, None


async def smart_check(center_code: str) -> Tuple[bool, int, Optional[str]]:
    """
    Smart check that tries multiple methods in order of reliability.
    """
    result = await check_with_playwright(center_code)
    if result[0] is not None:
        return result

    return False, 0, None
