"""
VFS Global Monitor — Algeria Italy Student Visa
Version améliorée :
- Rotation User-Agent + impersonate
- Backoff exponentiel + cache
- Double vérification avant alerte
- Alerte admin si trop d'échecs
- Fréquence intelligente selon l'heure
"""
import asyncio
import json
import logging
import random
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

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

IMPERSONATES = ["chrome120", "chrome124", "chrome131"]

# État global
_last_valid_result: Optional[dict] = None
_last_valid_time: float = 0
_consecutive_failures: int = 0
_backoff_until: float = 0
_admin_alerted: bool = False

# Callback pour alerter l'admin (sera initialisé par scheduler.py)
_alert_admin_callback = None

MAX_FAILURES_BEFORE_ALERT = 10


def set_alert_callback(callback):
    """Permet au scheduler d'enregistrer une fonction d'alerte admin."""
    global _alert_admin_callback
    _alert_admin_callback = callback


def get_check_interval() -> int:
    """
    Retourne l'intervalle de vérification selon l'heure Alger.
    Plus fréquent entre 8h-12h et 14h-17h (heures d'ouverture VFS).
    """
    now = datetime.now(TZ)
    hour = now.hour
    # Heures creuses VFS : vérification toutes les 6 minutes
    if 0 <= hour < 7 or hour >= 22:
        return 360
    # Heures de pointe : vérification toutes les 3 minutes
    elif (8 <= hour <= 12) or (14 <= hour <= 17):
        return 180
    # Heures normales : toutes les 4 minutes
    else:
        return 250


def _get_headers() -> dict:
    return {
        "accept": "application/json",
        "accept-language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        "origin": "https://visa.vfsglobal.com",
        "referer": "https://visa.vfsglobal.com/",
        "route": f"{COUNTRY}/en/{MISSION}",
        "user-agent": random.choice(USER_AGENTS),
        "cache-control": "no-cache",
        "pragma": "no-cache",
    }


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
    """Requête avec rotation User-Agent et impersonate."""
    global _consecutive_failures, _backoff_until, _admin_alerted

    if time.time() < _backoff_until:
        wait = _backoff_until - time.time()
        logger.info(f"Backoff actif — {wait:.0f}s restantes")
        return "backoff", []

    try:
        from curl_cffi.requests import AsyncSession
        imp = random.choice(IMPERSONATES)
        async with AsyncSession(impersonate=imp) as s:
            r = await s.get(url, headers=_get_headers(), timeout=20)
            txt = r.text or ""
            status, slots = _parse(txt, r.status_code)
            logger.info(f"[curl_cffi/{imp}] {r.status_code} → {status} | {txt[:150]}")

            if status in ("rate-limit", "block", "error", "empty", "parse-err"):
                _consecutive_failures += 1
                if status == "rate-limit":
                    wait = min(30 * (2 ** (_consecutive_failures - 1)), 240)
                    _backoff_until = time.time() + wait
                    logger.warning(f"Rate limit — backoff {wait}s (échec #{_consecutive_failures})")

                # Alerte admin si trop d'échecs
                if _consecutive_failures >= MAX_FAILURES_BEFORE_ALERT and not _admin_alerted:
                    _admin_alerted = True
                    if _alert_admin_callback:
                        asyncio.create_task(_alert_admin_callback(
                            f"⚠️ *Alerte bot VFS*\n\n"
                            f"{_consecutive_failures} échecs consécutifs sur l'API VFS.\n"
                            f"Dernière erreur : `{status}`\n"
                            f"Le bot continue de surveiller."
                        ))
            else:
                _consecutive_failures = 0
                _backoff_until = 0
                _admin_alerted = False

            return status, slots

    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"curl_cffi erreur: {e}")

    try:
        import httpx
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url, headers=_get_headers())
            txt = r.text or ""
            status, slots = _parse(txt, r.status_code)
            logger.info(f"[httpx] {r.status_code} → {status} | {txt[:150]}")
            return status, slots
    except Exception as e:
        logger.warning(f"httpx erreur: {e}")
        _consecutive_failures += 1
        return "error", []


async def _verify_slots() -> Tuple[str, list]:
    global _last_valid_result, _last_valid_time
    for cat in CATEGORIES:

        url = f"{LIFT_API}/master/centerwithslots/{MISSION}/{COUNTRY}/{cat}/{CULTURE}"
        status, slots = await _fetch_url(url)

        if status == "SLOT":
            logger.info(f"SLOT détecté avec {cat} — double vérification dans 5s...")
            await asyncio.sleep(5)
            status2, slots2 = await _fetch_url(url)
            if status2 == "SLOT":
                logger.info(f"✅ SLOT CONFIRMÉ après double vérification !")
                return "SLOT", slots2
            else:
                logger.warning(f"Faux positif détecté — 1ère: SLOT, 2ème: {status2}")
                return "no-slots", []

        elif status == "no-slots":
            return "no-slots", []

        elif status in ("rate-limit", "backoff"):
            if _last_valid_result and (time.time() - _last_valid_time) < 600:
                logger.info(f"Cache utilisé (âge: {time.time() - _last_valid_time:.0f}s)")
                return _last_valid_result["status"], _last_valid_result["slots"]
            await asyncio.sleep(5)
            continue
        else:
            continue
            
    if _last_valid_result and (time.time() - _last_valid_time) < 600:
        return _last_valid_result["status"], _last_valid_result["slots"]

    return "no-slots", []


async def _fetch_slots() -> Tuple[str, list]:
    global _last_valid_result, _last_valid_time
    status, slots = await _verify_slots()

    if status in ("SLOT", "no-slots"):
        _last_valid_result = {"status": status, "slots": slots}
        _last_valid_time = time.time()

    return status, slots


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
