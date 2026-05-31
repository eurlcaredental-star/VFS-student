"""
VFS Global Monitor — Algeria Italy Student Visa
Reverse-engineered mobile API + web fallback.
"""
import asyncio
import hashlib
import json
import logging
import re
import time
from datetime import datetime
from typing import Optional, Tuple
import httpx
import pytz
from config import (
    VFS_BASE_URL, VFS_WEB_BASE, VFS_EMAIL, VFS_PASSWORD,
    MISSION_CODE, COUNTRY_CODE, CENTERS, TIMEZONE
)

logger = logging.getLogger(__name__)
TZ = pytz.timezone(TIMEZONE)

# ─── Authenticated session state ─────────────────────────────────────────────
_session_token: Optional[str] = None
_session_expiry: float = 0.0
_session_cookies: dict = {}

# ─── Headers that mimic the VFS Global iOS app ───────────────────────────────
MOBILE_APP_HEADERS = {
    "User-Agent": "VFS Global/4.0.1 CFNetwork/1490.0.4 Darwin/23.2.0",
    "Accept": "application/json",
    "Accept-Language": "fr-DZ;q=1.0, en-DZ;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Content-Type": "application/json",
    "X-Requested-With": "com.vfs.vfsGlobal",
    "Origin": "https://visa.vfsglobal.com",
    "Referer": "https://visa.vfsglobal.com/",
}

# Headers mimicking a real Chrome browser session
CHROME_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-DZ,fr;q=0.9,en-US;q=0.8,en;q=0.7,ar;q=0.6",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

# Known VFS API base URLs (mobile app endpoints)
VFS_API_ENDPOINTS = [
    "https://lift-api.vfsglobal.com",
    "https://api.vfsglobal.com",
    "https://visa.vfsglobal.com/api",
]

# Text patterns indicating NO slots
NO_SLOT_PATTERNS = [
    r"aucun cr[eé]neau de rendez-vous n.est actuellement disponible",
    r"no appointment slots are currently available",
    r"no slot[s]? available",
    r"nouveaux cr[eé]neaux s.ouvrent [àa] intervalles r[eé]guliers",
    r"veuillez r[eé]essayer plus tard",
    r"please try again later",
    r"temporarily unavailable",
    r"pas de cr[eé]neau",
    r"appointment[s]? not available",
    r"aucune disponibilit[eé]",
]

# Text patterns indicating slots ARE available
SLOT_AVAILABLE_PATTERNS = [
    r"select.{0,20}(date|appointment|slot)",
    r"choose.{0,20}(date|appointment)",
    r"available.{0,15}(date|slot|appointment)",
    r"cr[eé]neau.{0,20}disponible",
    r"choisir.{0,15}(date|rendez)",
    r"book.{0,20}appointment",
    r"r[eé]server.{0,15}rendez",
    r"calendar.{0,30}(open|available|select)",
    r"(january|february|march|april|may|june|july|august|september|october|november|december).{0,10}\d{4}",
]


def _detect_slots_in_text(text: str) -> Optional[bool]:
    """Return True=slots available, False=no slots, None=unknown."""
    t = text.lower()
    for p in NO_SLOT_PATTERNS:
        if re.search(p, t, re.IGNORECASE | re.DOTALL):
            return False
    for p in SLOT_AVAILABLE_PATTERNS:
        if re.search(p, t, re.IGNORECASE | re.DOTALL):
            return True
    return None


async def _authenticate_mobile() -> Optional[str]:
    """Try to get a JWT from the VFS mobile API."""
    global _session_token, _session_expiry

    now = time.time()
    if _session_token and now < _session_expiry:
        return _session_token

    login_payloads = [
        {"username": VFS_EMAIL, "password": VFS_PASSWORD,
         "grant_type": "password", "client_id": "VFSPORTALUSER"},
        {"email": VFS_EMAIL, "password": VFS_PASSWORD},
        {"loginId": VFS_EMAIL, "password": VFS_PASSWORD,
         "missionCode": MISSION_CODE, "countryCode": COUNTRY_CODE},
    ]

    login_paths = ["/token", "/login", "/user/login", "/auth/login"]

    for base in VFS_API_ENDPOINTS:
        for path in login_paths:
            for payload in login_payloads:
                try:
                    async with httpx.AsyncClient(
                        timeout=15, verify=False,
                        headers=MOBILE_APP_HEADERS
                    ) as client:
                        r = await client.post(f"{base}{path}", json=payload)
                        if r.status_code == 200:
                            data = r.json()
                            token = (
                                data.get("access_token") or
                                data.get("token") or
                                data.get("data", {}).get("token") or
                                data.get("accessToken")
                            )
                            if token:
                                _session_token = token
                                _session_expiry = now + 3300  # ~55 min
                                logger.info("VFS mobile auth successful")
                                return token
                except Exception:
                    continue

    logger.warning("VFS mobile auth failed — will use anonymous checks")
    return None


async def _check_via_mobile_api(center_code: str, token: Optional[str]) -> Tuple[bool, int, Optional[str]]:
    """Check appointments using the mobile API endpoints."""
    center = CENTERS.get(center_code)
    if not center:
        return False, 0, None

    headers = {**MOBILE_APP_HEADERS}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Various endpoint + payload combinations VFS mobile uses
    checks = [
        {
            "url": f"{VFS_API_ENDPOINTS[0]}/appointment/CheckAppointmentAvailability",
            "payload": {
                "missionCode": MISSION_CODE,
                "countryCode": COUNTRY_CODE,
                "centerCode": center["code"],
                "visaCategoryCode": "LS",
                "visaSubCategoryCode": "SLS",
                "languageCode": "en",
            }
        },
        {
            "url": f"{VFS_API_ENDPOINTS[0]}/appointment/GetSlots",
            "payload": {
                "missionCode": MISSION_CODE,
                "countryCode": COUNTRY_CODE,
                "centerCode": center["code"],
                "categoryCode": "Long Stay",
                "subCategoryCode": "Students - Long Stay",
            }
        },
        {
            "url": f"https://visa.vfsglobal.com/dza/en/ita/appointment/GetAvailableSlots",
            "payload": {
                "center": center["code"],
                "visaType": "Students - Long Stay",
            }
        },
    ]

    async with httpx.AsyncClient(timeout=20, verify=False) as client:
        for check in checks:
            try:
                r = await client.post(check["url"], json=check["payload"], headers=headers)
                if r.status_code == 200:
                    try:
                        data = r.json()
                        result = _parse_json_response(data)
                        if result is not None:
                            return result
                    except Exception:
                        result = _detect_slots_in_text(r.text)
                        if result is not None:
                            return result, 0, None
            except Exception:
                continue

    return False, 0, None


def _parse_json_response(data) -> Optional[Tuple[bool, int, Optional[str]]]:
    """Parse a JSON API response to determine slot availability."""
    if isinstance(data, list):
        if len(data) > 0:
            dates = []
            for item in data:
                if isinstance(item, dict):
                    d = item.get("date") or item.get("appointmentDate") or item.get("slotDate")
                    if d:
                        dates.append(str(d))
            return True, len(data), min(dates) if dates else None
        return False, 0, None

    if isinstance(data, dict):
        # Boolean availability flag
        for key in ("isAppointmentAvailable", "available", "hasSlots", "isAvailable"):
            if key in data:
                avail = bool(data[key])
                earliest = (
                    data.get("firstAvailableDate") or
                    data.get("earliestDate") or
                    data.get("nextAvailableDate")
                )
                count = data.get("availableCount", 1 if avail else 0)
                return avail, int(count), earliest

        # Slot list in response
        for key in ("slots", "availableSlots", "dates", "availableDates", "appointmentSlots"):
            if key in data:
                items = data[key]
                if isinstance(items, list) and len(items) > 0:
                    return True, len(items), None
                elif isinstance(items, list):
                    return False, 0, None

        # Error / no-slot message
        msg = str(data.get("message", "") or data.get("error", "") or data.get("description", "")).lower()
        if msg:
            if any(p in msg for p in ["no slot", "no appointment", "unavailable", "not available"]):
                return False, 0, None
            if any(p in msg for p in ["available", "slot found", "créneau"]):
                return True, 0, None

    return None


async def _check_via_web(center_code: str) -> Tuple[bool, int, Optional[str]]:
    """
    Check using the web interface with a real browser session cookie approach.
    We load the home page first to get cookies, then check the schedule page.
    """
    center = CENTERS.get(center_code)
    if not center:
        return False, 0, None

    async with httpx.AsyncClient(
        timeout=25,
        follow_redirects=True,
        verify=False,
        headers=CHROME_HEADERS,
    ) as client:
        try:
            # Step 1: Get home page cookies
            home_url = f"{VFS_WEB_BASE}/dza/en/ita/"
            try:
                r0 = await client.get(home_url)
                logger.debug(f"Home page: {r0.status_code}")
            except Exception:
                pass

            # Step 2: Check the schedule page
            schedule_url = f"{VFS_WEB_BASE}/dza/en/ita/appointment/schedule"
            r = await client.get(schedule_url)

            if r.status_code == 200:
                result = _detect_slots_in_text(r.text)
                if result is not None:
                    logger.info(f"Web check {center_code}: {'SLOTS' if result else 'NO SLOTS'}")
                    return result, 0, None

        except Exception as e:
            logger.debug(f"Web check failed for {center_code}: {e}")

    return False, 0, None


async def _check_via_public_status(center_code: str) -> Tuple[bool, int, Optional[str]]:
    """
    Parse the VFS public-facing page for center status info.
    This URL always returns 200 and contains slot status text.
    """
    center = CENTERS.get(center_code)
    if not center:
        return False, 0, None

    urls = [
        f"{VFS_WEB_BASE}/dza/en/ita/",
        f"https://www.vfsglobal.com/en/individuals/article.html?n=italy-visa-application-centre-algeria",
    ]

    async with httpx.AsyncClient(
        timeout=20, follow_redirects=True, verify=False, headers=CHROME_HEADERS
    ) as client:
        for url in urls:
            try:
                r = await client.get(url)
                if r.status_code == 200:
                    result = _detect_slots_in_text(r.text)
                    if result is not None:
                        return result, 0, None
            except Exception:
                continue

    return False, 0, None


async def check_appointments_via_web(center_code: str) -> Tuple[bool, int, Optional[str]]:
    """
    Main entry point — tries multiple methods in order of reliability.
    Returns (has_slots, count, earliest_date).
    """
    # Method 1: Mobile API (most accurate if auth works)
    token = await _authenticate_mobile()
    has_slots, count, earliest = await _check_via_mobile_api(center_code, token)
    if count > 0 or has_slots:
        logger.info(f"[API] {center_code}: SLOTS AVAILABLE (count={count})")
        return has_slots, count, earliest

    # Method 2: Web schedule page (reliable, always returns slot status)
    has_slots, count, earliest = await _check_via_web(center_code)
    # If we got a clear answer from the web, trust it
    # (False here means either "no slots" OR "couldn't determine" — check public page too)

    # Method 3: Public VFS page (fallback)
    pub_result, _, _ = await _check_via_public_status(center_code)

    # Combine: if either web OR public detects slots, alert
    final = has_slots or pub_result
    logger.info(f"[FINAL] {center_code}: {'SLOTS' if final else 'no slots'} "
                f"(web={has_slots}, public={pub_result})")
    return final, count, earliest


async def check_all_centers() -> dict:
    """Check all centers in parallel and return combined results."""
    results = {}

    async def _check_one(code):
        try:
            has_slots, count, earliest = await check_appointments_via_web(code)
            results[code] = {
                "has_slots": has_slots,
                "count": count,
                "earliest": earliest,
                "checked_at": datetime.now(TZ).isoformat()
            }
        except Exception as e:
            logger.error(f"Error checking {code}: {e}")
            results[code] = {"has_slots": False, "count": 0, "earliest": None, "error": str(e)}

    await asyncio.gather(*[_check_one(code) for code in CENTERS.keys()])
    return results
