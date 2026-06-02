"""
VFS Global Monitor — Algeria Italy Student Visa
API directe lift-api.vfsglobal.com avec httpx (pas de navigateur).
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional, Tuple
import pytz
import httpx
from config import CENTERS, TIMEZONE, VFS_EMAIL, VFS_PASSWORD

logger = logging.getLogger(__name__)
TZ = pytz.timezone(TIMEZONE)

API_BASE = "https://lift-api.vfsglobal.com"
MISSION_CODE = "ITA"
COUNTRY_CODE = "DZA"

HEADERS = {
    "User-Agent": "VFSGlobal/3.0.2 CFNetwork/1474 Darwin/23.0.0",
    "Accept": "application/json",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://visa.vfsglobal.com",
    "Referer": "https://visa.vfsglobal.com/",
}

# Token global — récupéré une fois, réutilisé
_token: Optional[str] = None


async def _login() -> bool:
    """Se connecte à l'API VFS et récupère le token."""
    global _token
    try:
        logger.info("Login API VFS...")
        async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
            response = await client.post(
                f"{API_BASE}/user/login",
                json={
                    "username": VFS_EMAIL,
                    "password": VFS_PASSWORD,
                    "missionCode": MISSION_CODE,
                    "countryCode": COUNTRY_CODE,
                }
            )
            logger.info(f"Login status: {response.status_code}")
            logger.info(f"Login response: {response.text[:300]}")

            if response.status_code == 200:
                data = response.json()
                token = (
                    data.get("token") or
                    data.get("access_token") or
                    data.get("accessToken") or
                    data.get("data", {}).get("token") or
                    data.get("data", {}).get("accessToken")
                )
                if token:
                    _token = token
                    logger.info("Login réussi — token récupéré")
                    return True
                else:
                    logger.warning(f"Token non trouvé dans: {data}")
                    return False
            else:
                logger.warning(f"Login échoué: {response.status_code} — {response.text[:200]}")
                return False

    except Exception as e:
        logger.error(f"Erreur login: {e}")
        return False


async def _ensure_token() -> bool:
    """S'assure qu'on a un token valide."""
    global _token
    if not _token:
        return await _login()
    return True


async def check_appointments_via_web(center_code: str) -> Tuple[bool, int, Optional[str]]:
    """Vérifie les créneaux pour un centre via l'API directe."""
    global _token

    center_info = CENTERS.get(center_code, {})
    vac_id = center_info.get("vac_id", center_code)

    try:
        ok = await _ensure_token()
        if not ok:
            logger.warning(f"[{center_code}] Pas de token disponible")
            return False, 0, None

        async with httpx.AsyncClient(timeout=30) as client:
            auth_headers = {**HEADERS, "Authorization": f"Bearer {_token}"}

            endpoints = [
                f"{API_BASE}/appointment/slots/{COUNTRY_CODE}/{MISSION_CODE}/{vac_id}",
                f"{API_BASE}/appointment/checkslots/{COUNTRY_CODE}/{MISSION_CODE}/{vac_id}",
                f"{API_BASE}/slot/checkavailability/{COUNTRY_CODE}/{MISSION_CODE}/{vac_id}",
                f"{API_BASE}/appointment/{COUNTRY_CODE}/{MISSION_CODE}/slots?vacId={vac_id}",
            ]

            for endpoint in endpoints:
                try:
                    response = await client.get(endpoint, headers=auth_headers)
                    logger.info(f"[{center_code}] {endpoint} → {response.status_code}: {response.text[:200]}")

                    if response.status_code == 401:
                        logger.info("Token expiré, re-login...")
                        _token = None
                        ok = await _login()
                        if ok:
                            auth_headers = {**HEADERS, "Authorization": f"Bearer {_token}"}
                            response = await client.get(endpoint, headers=auth_headers)

                    if response.status_code == 200:
                        data = response.json()
                        logger.info(f"[{center_code}] Réponse: {data}")

                        if isinstance(data, list) and len(data) > 0:
                            return True, len(data), str(data[0])
                        elif isinstance(data, dict):
                            slots = (
                                data.get("slots") or
                                data.get("availableSlots") or
                                data.get("data") or
                                []
                            )
                            if slots and len(slots) > 0:
                                return True, len(slots), str(slots[0])
                            elif data.get("available") is True:
                                return True, 1, None
                            elif data.get("available") is False:
                                return False, 0, None

                except Exception as e:
                    logger.warning(f"[{center_code}] Endpoint {endpoint} échoué: {e}")
                    continue

        logger.info(f"[{center_code}] Aucun créneau trouvé")
        return False, 0, None

    except Exception as e:
        logger.error(f"[{center_code}] Erreur: {e}")
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
