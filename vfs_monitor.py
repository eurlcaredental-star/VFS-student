VFS Global Monitor — Algeria Italy Student Visa
Une seule requête toutes les 2 minutes — retourne tous les centres.
"""
import asyncio
import json
import logging
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

# Catégories confirmées — on essaie dans l'ordre
CATEGORIES = ["STUDLNG", "LNGSTUDENT"]

HEADERS = {
    "accept": "application/json",
    "accept-language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "origin": "https://visa.vfsglobal.com",
    "referer": "https://visa.vfsglobal.com/",
    "route": f"{COUNTRY}/en/{MISSION}",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


async def _fetch_url(url: str) -> Tuple[str, list]:
    """Appelle l'URL — essaie curl_cffi puis httpx en fallback."""
    try:
        from curl_cffi.requests import AsyncSession
        async with AsyncSession(impersonate="chrome120") as s:
            r = await s.get(url, headers=HEADERS, timeout=20)
            txt = r.text or ""
            logger.info(f"[curl_cffi] {r.status_code} | {txt[:200]}")
            return _parse(txt, r.status_code)
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"curl_cffi erreur: {e}")

    # Fallback httpx
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


async def _fetch_slots() -> Tuple[str, list]:
    """Essaie chaque catégorie jusqu'à avoir une réponse valide."""
    for cat in CATEGORIES:
        url = f"{LIFT_API}/master/centerwithslots/{MISSION}/{COUNTRY}/{cat}/{CULTURE}"
        status, slots = await _fetch_url(url)
        logger.info(f"cat={cat} → {status} | {len(slots)} slots")

        if status == "SLOT":
            return "SLOT", slots
        elif status == "no-slots":
            return "no-slots", []
        elif status == "rate-limit":
            # Attendre et réessayer avec la prochaine catégorie
            await asyncio.sleep(5)
            continue
        else:
            continue

    return "no-slots", []


async def check_all_centers() -> dict:
    """Vérifie tous les centres en une seule requête."""
    results = {}
    now = datetime.now(TZ).isoformat()

    status, slots = await _fetch_slots()
    logger.info(f"Résultat final: {status} | {len(slots)} slots trouvés")

    # Mapper les slots par centre via isoCode ou vac_id
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
