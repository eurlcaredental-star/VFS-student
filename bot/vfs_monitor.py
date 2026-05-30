import asyncio
import httpx
import json
import re
from datetime import datetime
from typing import Optional, Tuple
import logging
import pytz
from config import (
    VFS_BASE_URL, VFS_WEB_BASE, VFS_EMAIL, VFS_PASSWORD,
    MISSION_CODE, COUNTRY_CODE, CENTERS, TIMEZONE
)

logger = logging.getLogger(__name__)
TZ = pytz.timezone(TIMEZONE)

VFS_API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-DZ,fr;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Content-Type": "application/json",
    "Origin": "https://visa.vfsglobal.com",
    "Referer": "https://visa.vfsglobal.com/dza/en/ita/",
    "x-correlation-id": "vfs-dza-ita-student",
}

WEB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://visa.vfsglobal.com/dza/en/ita/",
}

_vfs_token: Optional[str] = None
_token_expiry: Optional[datetime] = None


async def get_vfs_token() -> Optional[str]:
    global _vfs_token, _token_expiry

    now = datetime.now(TZ)
    if _vfs_token and _token_expiry and now < _token_expiry:
        return _vfs_token

    try:
        async with httpx.AsyncClient(timeout=30, verify=False) as client:
            payload = {
                "username": VFS_EMAIL,
                "password": VFS_PASSWORD,
                "grant_type": "password",
                "client_id": "VFSPORTALUSER"
            }
            resp = await client.post(
                f"{VFS_BASE_URL}/token",
                json=payload,
                headers=VFS_API_HEADERS
            )
            if resp.status_code == 200:
                data = resp.json()
                _vfs_token = data.get("access_token") or data.get("token")
                import datetime as dt
                _token_expiry = now + dt.timedelta(minutes=55)
                logger.info("VFS token obtained successfully")
                return _vfs_token
    except Exception as e:
        logger.error(f"Error getting VFS token: {e}")

    return None


async def check_appointments_via_web(center_code: str) -> Tuple[bool, int, Optional[str]]:
    """
    Check appointment availability via the VFS Global web interface.
    Returns (has_slots, count, earliest_date)
    """
    center = CENTERS.get(center_code)
    if not center:
        return False, 0, None

    urls_to_try = [
        f"{VFS_WEB_BASE}/dza/en/ita/appointment/schedule",
        f"{VFS_WEB_BASE}/dza/fr/ita/appointment/schedule",
        f"{VFS_BASE_URL}/appointment/CheckAppointmentAvailability",
    ]

    try:
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            verify=False,
            headers=WEB_HEADERS
        ) as client:
            for url in urls_to_try[:2]:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        text = resp.text
                        has_slots = check_page_for_slots(text, center["code"])
                        if has_slots is not None:
                            return has_slots, 1 if has_slots else 0, None
                except Exception as e:
                    logger.debug(f"URL {url} failed: {e}")
                    continue

    except Exception as e:
        logger.error(f"Web check failed for {center_code}: {e}")

    return await check_appointments_via_api(center_code)


def check_page_for_slots(html_content: str, center_name: str) -> Optional[bool]:
    no_slot_phrases = [
        "aucun créneau",
        "no appointment slots",
        "no slots available",
        "Aucun créneau de rendez-vous",
        "nouveaux créneaux s'ouvrent à intervalles",
        "No appointment slots are currently available",
    ]

    slot_phrases = [
        "select a date",
        "choisir une date",
        "available dates",
        "dates disponibles",
    ]

    text_lower = html_content.lower()

    for phrase in no_slot_phrases:
        if phrase.lower() in text_lower:
            return False

    for phrase in slot_phrases:
        if phrase.lower() in text_lower:
            return True

    return None


async def check_appointments_via_api(center_code: str) -> Tuple[bool, int, Optional[str]]:
    """Try to check via VFS API endpoints"""
    center = CENTERS.get(center_code)
    if not center:
        return False, 0, None

    api_endpoints = [
        {
            "url": f"{VFS_BASE_URL}/appointment/CheckAppointmentAvailability",
            "method": "POST",
            "payload": {
                "missionCode": MISSION_CODE,
                "countryCode": COUNTRY_CODE,
                "centerCode": center["code"],
                "visaCategoryCode": "LS",
                "visaSubCategoryCode": "SLS",
                "languageCode": "en"
            }
        },
        {
            "url": f"{VFS_BASE_URL}/appointment/GetAppointmentSlots",
            "method": "POST",
            "payload": {
                "missionCode": MISSION_CODE,
                "countryCode": COUNTRY_CODE,
                "centerCode": center["code"],
                "categoryCode": "Long Stay",
                "subCategoryCode": "Students - Long Stay"
            }
        },
    ]

    token = await get_vfs_token()
    headers = {**VFS_API_HEADERS}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(timeout=30, verify=False) as client:
        for endpoint in api_endpoints:
            try:
                if endpoint["method"] == "POST":
                    resp = await client.post(
                        endpoint["url"],
                        json=endpoint["payload"],
                        headers=headers
                    )
                else:
                    resp = await client.get(endpoint["url"], headers=headers)

                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        return parse_api_response(data)
                    except Exception:
                        text = resp.text
                        result = check_page_for_slots(text, center["code"])
                        if result is not None:
                            return result, 0, None

            except Exception as e:
                logger.debug(f"API endpoint failed: {e}")
                continue

    return await check_via_playwright(center_code)


async def check_via_playwright(center_code: str) -> Tuple[bool, int, Optional[str]]:
    """Fallback: use Playwright browser automation"""
    center = CENTERS.get(center_code)
    if not center:
        return False, 0, None

    try:
        from playwright.async_api import async_playwright

        url = f"{VFS_WEB_BASE}/dza/en/ita/appointment/schedule"

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                locale="fr-FR",
                viewport={"width": 1280, "height": 800}
            )
            page = await context.new_page()

            await page.goto(url, wait_until="networkidle", timeout=30000)

            content = await page.content()
            result = check_page_for_slots(content, center["code"])

            try:
                center_dropdown = await page.query_selector("select[name='center'], #center-select, .center-dropdown")
                if center_dropdown:
                    await center_dropdown.select_option(value=center["code"])
                    await asyncio.sleep(2)
                    content = await page.content()
                    result = check_page_for_slots(content, center["code"])
            except Exception:
                pass

            await browser.close()

            if result is not None:
                return result, 0, None

    except ImportError:
        logger.warning("Playwright not available, using fallback")
    except Exception as e:
        logger.error(f"Playwright check failed for {center_code}: {e}")

    return await check_via_status_page(center_code)


async def check_via_status_page(center_code: str) -> Tuple[bool, int, Optional[str]]:
    """
    Last resort: check the VFS page and try to extract slot info
    from any API calls intercepted or from the page source.
    """
    center = CENTERS.get(center_code)
    if not center:
        return False, 0, None

    check_urls = [
        f"{VFS_WEB_BASE}/dza/en/ita/",
        f"https://www.vfsglobal.com/en/individuals/article.html?n=italy-visa-application-centre-algeria",
    ]

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, verify=False, headers=WEB_HEADERS) as client:
            for url in check_urls:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        result = check_page_for_slots(resp.text, center["code"])
                        if result is not None:
                            return result, 0, None
                except Exception:
                    continue
    except Exception as e:
        logger.error(f"Status page check failed: {e}")

    logger.info(f"All methods exhausted for {center_code}, assuming no slots")
    return False, 0, None


def parse_api_response(data: dict) -> Tuple[bool, int, Optional[str]]:
    """Parse VFS API response for slot availability"""
    if isinstance(data, list):
        if len(data) > 0:
            dates = [item.get("date") or item.get("appointmentDate") for item in data if isinstance(item, dict)]
            dates = [d for d in dates if d]
            earliest = min(dates) if dates else None
            return True, len(data), earliest
        return False, 0, None

    if isinstance(data, dict):
        if data.get("isAppointmentAvailable") is not None:
            available = data["isAppointmentAvailable"]
            earliest = data.get("firstAvailableDate") or data.get("earliestDate")
            count = data.get("availableCount", 1 if available else 0)
            return bool(available), count, earliest

        if "slots" in data:
            slots = data["slots"]
            if isinstance(slots, list) and len(slots) > 0:
                return True, len(slots), None
            return False, 0, None

        if "availableDates" in data:
            dates = data["availableDates"]
            if dates and len(dates) > 0:
                return True, len(dates), min(dates) if isinstance(dates, list) else None
            return False, 0, None

        if data.get("message") and "no" in data["message"].lower():
            return False, 0, None

    return False, 0, None


async def check_all_centers() -> dict:
    """
    Check all centers and return status dict.
    """
    results = {}

    async def check_one(code):
        try:
            has_slots, count, earliest = await check_appointments_via_web(code)
            results[code] = {
                "has_slots": has_slots,
                "count": count,
                "earliest": earliest,
                "checked_at": datetime.now(TZ).isoformat()
            }
            logger.info(f"Center {code}: has_slots={has_slots}, count={count}")
        except Exception as e:
            logger.error(f"Error checking center {code}: {e}")
            results[code] = {"has_slots": False, "count": 0, "earliest": None, "error": str(e)}

    tasks = [check_one(code) for code in CENTERS.keys()]
    await asyncio.gather(*tasks)
    return results
