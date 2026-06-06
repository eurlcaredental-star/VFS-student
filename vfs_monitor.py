"""
VFS Global Monitor — Algeria Italy Student Visa
API directe lift-api.vfsglobal.com/master/centerwithslots
Anti-bot amélioré : rotation User-Agent, backoff exponentiel, cache.
"""
import asyncio
import json
import logging
import random
import time
from datetime import datetime
from typing import Optional, Tuple, List
import pytz
from config import CENTERS, TIMEZONE

logger = logging.getLogger(__name__)
TZ = pytz.timezone(TIMEZONE)

LIFT_API = "https://lift-api.vfsglobal.com"
MISSION  = "ita"
COUNTRY  = "dza"
CULTURE  = "en-us"

CATEGORIES = ["STUDLNG", "LNGSTUDENT"]

# Rotation de User-Agents — paraît comme différents appareils
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

# Cache du dernier résultat valide
_last_valid_result: Optional[dict] = None
_last_valid_time: float = 0
_consecutive_failures: int = 0
_backoff_until: float = 0


def _get_headers() -> dict:
    """Headers avec User-Agent aléatoire."""
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
    """Parse la réponse API."""
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
        if slots:
            return "SLOT", slots
        return "no-slots", []
    except Exception as e:
        logger.warning(f"Parse erreur: {e}")
        return "parse-err", []


async def _fetch_url(url: str, attempt: int = 0) -> Tuple[str, list]:
    """Appelle l'URL avec backoff exponentiel."""
    global _consecutive_failures, _backoff_until

    # Vérifier si on est en backoff
    if time.time() < _backoff_until:
        wait = _backoff_until - time.time()
        logger.info(f"Backoff actif — {wait:.0f}s restantes")
        return "backoff", []

    try:
        from curl_cffi.requests import AsyncSession
        impersonate = random.choice(["chrome120", "chrome124", "chrome131"])
        async with AsyncSession(impersonate=impersonate) as s:
            r = await s.get(url, headers=_get_headers(), timeout=20)
            txt = r.text or ""
            status, slots = _parse(txt, r.status_code)
            logger.info(f"[curl_cffi/{impersonate}] {r.status_code} → {status} | {txt[:150]}")

            if status == "rate-limit":
                _consecutive_failures += 1
                # Backoff exponentiel : 30s, 60s, 120s, 240s max
                wait = min(30 * (2 ** (_consecutive_failures - 1)), 240)
                _backoff_until = time.time() + wait
                logger.warning(f"Rate limit — backoff {wait}s (échec #{_consecutive_failures})")
            else:
                _consecutive_failures = 0
                _backoff_until = 0

            return status, slots

    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"curl_cffi erreur: {e}")

    # Fallback httpx
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
        return "error", []


async def _fetch_slots() -> Tuple[str, list]:
    """Essaie chaque catégorie avec backoff et cache."""
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

        elif status in ("rate-limit", "backoff"):
            # Utiliser le cache si disponible et récent (moins de 10 minutes)
            if _last_valid_result and (time.time() - _last_valid_time) < 600:
                logger.info(f"Cache utilisé (âge: {time.time() - _last_valid_time:.0f}s)")
                return _last_valid_result["status"], _last_valid_result["slots"]
            await asyncio.sleep(5)
            continue

        else:
            continue

    # Dernier recours — cache
    if _last_valid_result and (time.time() - _last_valid_time) < 600:
        logger.info("Cache utilisé en dernier recours")
        return _last_valid_result["status"], _last_valid_result["slots"]

    return "no-slots", []


async def check_all_centers() -> dict:
    """Vérifie tous les centres en une seule requête."""
    results = {}
    now = datetime.now(TZ).isoformat()

    status, slots = await _fetch_slots()
    logger.info(f"Résultat final: {status} | {len(slots)} slots trouvés")

    # Mapper les slots par centre
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
