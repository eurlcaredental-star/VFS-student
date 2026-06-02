"""
VFS Global Monitor — Algeria Italy Student Visa
API directe lift-api.vfsglobal.com/master/centerwithslots
Sans login, sans token — curl_cffi imite Chrome natif.
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

# Catégories à surveiller — on essaie plusieurs variantes
CATEGORIES = [
    "LSTUDENT",
    "LNGSTUDENT",
    "STUDENT",
    "LONGSTAY",
    "LSTSTUDENT",
    "LNGSTUDY",
]

HEADERS = {
    "accept": "application/json",
    "accept-language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "origin": "https://visa.vfsglobal.com",
    "referer": "https://visa.vfsglobal.com/",
    "route": f"{COUNTRY}/en/{MISSION}",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
}


def _classify(txt: str, sc: int) -> str:
    """Analyse la réponse API."""
    if sc == 403:
        return "block-403"
    if sc == 429:
        return "rate-limit"
    if sc != 200:
        return f"http-{sc}"
    if not txt:
        return "empty"
    if '"centerName":null' in txt or txt.strip() in ("[]", "[{}]", "{}"):
        return "no-slots"
    try:
        arr = json.loads(txt)
        if isinstance(arr, list):
            for item in arr:
                if isinstance(item, dict):
                    cname = item.get("centerName")
                    err = item.get("error")
                    if cname and (err is None or (isinstance(err, dict) and not err.get("code"))):
                        return "SLOT"
        return "no-slots"
    except Exception:
        return "parse-err"


async def _hit_url(url: str) -> Tuple[str, str, int]:
    """Appelle l'URL avec curl_cffi (imite Chrome)."""
    try:
        from curl_cffi.requests import AsyncSession
        async with AsyncSession(impersonate="chrome120") as s:
            r = await s.get(url, headers=HEADERS, timeout=20)
            txt = r.text or ""
            status = _classify(txt, r.status_code)
            logger.info(f"URL: {url} → {r.status_code} → {status} | {txt[:150]}")
            return status, txt[:500], r.status_code
    except ImportError:
        # Fallback httpx si curl_cffi pas installé
        import httpx
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url, headers=HEADERS)
            txt = r.text or ""
            status = _classify(txt, r.status_code)
            logger.info(f"[httpx] URL: {url} → {r.status_code} → {status} | {txt[:150]}")
            return status, txt[:500], r.status_code
    except Exception as e:
        logger.warning(f"Erreur requête: {e}")
        return "timeout-err", str(e)[:120], 0


async def check_appointments_via_web(center_code: str) -> Tuple[bool, int, Optional[str]]:
    """Vérifie les créneaux pour un centre."""
    center_info = CENTERS.get(center_code, {})
    vac_id = center_info.get("vac_id", center_code)

    # Essayer chaque catégorie
    for cat in CATEGORIES:
        url = f"{LIFT_API}/master/centerwithslots/{MISSION}/{COUNTRY}/{cat}/{CULTURE}"
        status, body, sc = await _hit_url(url)

        if status == "SLOT":
            logger.info(f"[{center_code}] 🟢 CRÉNEAUX TROUVÉS — cat={cat}")
            # Parser pour compter les slots
            try:
                arr = json.loads(body)
                slots = [x for x in arr if isinstance(x, dict) and x.get("centerName")]
                return True, len(slots), cat
            except Exception:
                return True, 1, cat

        elif status == "no-slots":
            logger.info(f"[{center_code}] cat={cat} → no slots")
            # On continue avec la prochaine catégorie mais on note que ça répond
            continue

        elif status == "block-403":
            logger.warning(f"[{center_code}] cat={cat} → 403 bloqué")
            continue

        await asyncio.sleep(0.5)

    return False, 0, None


async def check_all_centers() -> dict:
    """Vérifie tous les centres."""
    results = {}
    for code in CENTERS.keys():
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
        await asyncio.sleep(1)
    return results
