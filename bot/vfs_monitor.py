"""
VFS Global Monitor — Algeria Italy Student Visa
Version stable + cache + alerte admin.
"""
import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Optional, Tuple
import pytz
from config import CENTERS, TIMEZONE

logger = logging.getLogger(__name__)
TZ = pytz.timezone(TIMEZONE)

LIFT_API = "https://lift-api.vfsglobal.com"
MISSION  = "ita"
COUNTRY  = "dza"
CULTURE  = "en-us"

CATEGORIES = ["LNGSTUDENT", "STUDLNG"]

HEADERS = {
    "accept": "application/json",
    "accept-language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "origin": "https://visa.vfsglobal.com",
    "referer": "https://visa.vfsglobal.com/",
    "route": f"{COUNTRY}/en/{MISSION}",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

# Cache du dernier résultat valide
_last_valid_result: Optional[dict] = None
_last_valid_time: float = 0
_consecutive_failures: int = 0
_admin_alerted: bool = False
_alert_callback = None

MAX_FAILURES_BEFORE_ALERT = 10
CACHE_TTL = 600  # 10 minutes


def set_alert_callback(callback):
    """Enregistre la fonction d'alerte admin."""
    global _alert_callback
    _alert_callback = callback


def _parse(txt: str, sc: int) -> Tuple[str, list]:
    if sc == 429:
        return "rate-limit", []
    if sc == 403:
        return "block", []
    if sc != 200:
        return f"http-{sc}", []
    if not txt:
        return "empty", []
    try:
        arr = json.loads(txt)
        if not isinstance(arr, list):
            return "no-slots", []
        slots = [
            x for x in arr
            if isinstance(x, dict)
            and x.get("centerName")
            and x.get("isoCode")
            and (
                x.get("error") is None
                or (isinstance(x.get("error"), dict) and not x.get("error", {}).get("code"))
            )
        ]
        return ("SLOT", slots) if slots else ("no-slots", [])
    except Exception as e:
        logger.warning(f"Parse erreur: {e}")
        return "parse-err", []


async def _fetch_url(url: str) -> Tuple[str, list]:
    global _consecutive_failures, _admin_alerted

    try:
        from curl_cffi.requests import AsyncSession
        async with AsyncSession(impersonate="chrome120") as s:
            r = await s.get(url, headers=HEADERS, timeout=20)
            txt = r.text or ""
            logger.info(f"[curl_cffi] {r.status_code} | {txt[:200]}")
            status, slots = _parse(txt, r.status_code)

            if status in ("rate-limit", "block", "error", "empty", "parse-err"):
                _consecutive_failures += 1
                if _consecutive_failures >= MAX_FAILURES_BEFORE_ALERT and not _admin_alerted:
                    _admin_alerted = True
                    if _alert_callback:
                        asyncio.create_task(_alert_callback(
                            f"⚠️ *Alerte VFS Monitor*\n\n"
                            f"{_consecutive_failures} échecs consécutifs.\n"
                            f"Dernière erreur : `{status}`\n"
                            f"Le bot continue de surveiller."
                        ))
            else:
                _consecutive_failures = 0
                _admin_alerted = False

            return status, slots

    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"curl_cffi erreur: {e}")

    try:
        import httpx
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url, headers=HEADERS)
            txt = r.text or ""
            logger.info(f"[httpx] {r.status_code} | {txt[:200]}")
            return _parse(txt, r.status_code)
    except Exception as e:
        logger.warning(f"httpx erreur: {e}")
        return "error", []


async def _fetch_slots() -> Tuple[str, list]:
    global _last_valid_result, _last_valid_time

    for cat in CATEGORIES:
        url = f"{LIFT_API}/master/centerwithslots/{MISSION}/{COUNTRY}/{cat}/{CULTURE}"
        status, slots = await _fetch_url(url)
        logger.info(f"cat={cat} → {status} | {len(slots)} slots")

        if status == "SLOT":
            _last_valid_result = {"status": "SLOT", "slots": slots}
            _last_valid_time = time.time()
            return "SLOT", slots

        elif status == "no-slots":
            _last_valid_result = {"status": "no-slots", "slots": []}
            _last_valid_time = time.time()
            return "no-slots", []

        elif status in ("rate-limit", "block"):
            # Utiliser le cache si disponible et récent
            if _last_valid_result and (time.time() - _last_valid_time) < CACHE_TTL:
                age = int(time.time() - _last_valid_time)
                logger.info(f"Cache utilisé (âge: {age}s) suite à {status}")
                return _last_valid_result["status"], _last_valid_result["slots"]
            await asyncio.sleep(5)
            continue

        else:
            continue

    # Dernier recours — cache
    if _last_valid_result and (time.time() - _last_valid_time) < CACHE_TTL:
        logger.info("Cache utilisé en dernier recours")
        return _last_valid_result["status"], _last_valid_result["slots"]

    return "no-slots", []


async def check_all_centers() -> dict:
    results = {}
    now = datetime.now(TZ).isoformat()

    status, slots = await _fetch_slots()
    logger.info(f"Résultat final: {status} | {len(slots)} slots trouvés")

    slots_by_center = {}
    for slot in slots:
        iso = (slot.get("isoCode") or "").upper()
        city = (slot.get("city") or "").upper()
        for code, info in CENTERS.items():
            vac = info.get("vac_id", "").upper()
            center_code = info.get("code", "").upper()
            if vac == iso or center_code == iso or center_code == city or vac == city:
                slots_by_center[code] = slot
                logger.info(f"Match: {code} ← isoCode={iso}")

    for code in CENTERS.keys():
        if code in slots_by_center:
            results[code] = {
                "has_slots": True,
                "count": 1,
                "earliest": slots_by_center[code].get("city"),
                "checked_at": now,
                "error": None,
            }
        else:
            results[code] = {
                "has_slots": False,
                "count": 0,
                "earliest": None,
                "checked_at": now,
                "error": None if status in ("no-slots", "SLOT") else status,
            }

    return results


async def check_appointments_via_web(center_code: str):
    """Alias pour compatibilité avec main.py"""
    results = await check_all_centers()
    r = results.get(center_code, {})
    return r.get("has_slots", False), r.get("count", 0), r.get("earliest")
