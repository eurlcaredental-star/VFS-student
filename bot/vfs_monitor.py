"""
VFS Global Monitor — Algeria Italy Student Visa
Détection fiable via web scraping (l'API mobile renvoie 403).
"""
import asyncio
import logging
import re
from datetime import datetime
from typing import Optional, Tuple

import httpx
import pytz
from config import CENTERS, TIMEZONE

logger = logging.getLogger(__name__)
TZ = pytz.timezone(TIMEZONE)

# ─── Headers réalistes Chrome ────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-DZ,fr;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
}

# URLs à vérifier pour chaque centre
BASE = "https://visa.vfsglobal.com/dza/en/ita"

# Phrases indiquant AUCUN créneau
NO_SLOT_PHRASES = [
    "no appointment slots are currently available",
    "aucun créneau de rendez-vous n'est actuellement disponible",
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
    "no appointment available",
    "aucun créneau de rendez-vous n'est actuellement disponible",
    "de nouveaux créneaux s'ouvrent à intervalles réguliers",
]



# Phrases/patterns indiquant des créneaux DISPONIBLES
SLOT_PHRASES = [
    "select a date",
    "choose a date",
    "available appointment",
    "book an appointment",
    "schedule an appointment",
    "pick a date",
    "appointment available",
    "créneau disponible",
    "réserver un rendez-vous",
    "choisir une date",
]

SLOT_PATTERNS = [
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}\b",
    r"\b\d{1,2}\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{4}\b",
    r"\"availableDate\"\s*:\s*\"[0-9]{4}-",
    r"\"slots\"\s*:\s*\[",
    r"data-available\s*=\s*[\"']true[\"']",
    r"class=[\"'][^\"']*available[^\"']*[\"']",
]


def _analyse_text(html: str) -> Optional[bool]:
    """
    Analyse le HTML pour détecter la disponibilité.
    Retourne True (créneaux dispo), False (pas de créneaux), None (indéterminé).
    """
    t = html.lower()

    # Vérifier d'abord les phrases "pas de créneaux"
    for phrase in NO_SLOT_PHRASES:
        if phrase.lower() in t:
            return False

    # Puis les phrases de disponibilité
    for phrase in SLOT_PHRASES:
        if phrase.lower() in t:
            return True

    # Patterns regex
    for pattern in SLOT_PATTERNS:
        if re.search(pattern, html, re.IGNORECASE):
            return True

    return None


async def _fetch(url: str, client: httpx.AsyncClient) -> Optional[str]:
    """Charge une URL et retourne le HTML, ou None en cas d'erreur."""
    try:
        r = await client.get(url, headers=HEADERS, follow_redirects=True, timeout=20)
        if r.status_code == 200:
            return r.text
        logger.debug(f"GET {url} → {r.status_code}")
    except Exception as e:
        logger.debug(f"GET {url} failed: {e}")
    return None


async def check_appointments_via_web(center_code: str) -> Tuple[bool, int, Optional[str]]:
    """
    Vérifie la disponibilité pour un centre.
    Retourne (has_slots, count, earliest_date).
    """
    center = CENTERS.get(center_code)
    if not center:
        return False, 0, None

    async with httpx.AsyncClient(verify=False) as client:

        # URL 1 : Page principale de prise de rendez-vous
        html = await _fetch(f"{BASE}/appointment", client)
        if html:
            result = _analyse_text(html)
            if result is not None:
                logger.info(f"[{center_code}] appointment page → {'SLOTS' if result else 'no slots'}")
                return result, 0, None

        # URL 2 : Page d'accueil VFS Algérie Italie
        html = await _fetch(f"{BASE}/", client)
        if html:
            result = _analyse_text(html)
            if result is not None:
                logger.info(f"[{center_code}] home page → {'SLOTS' if result else 'no slots'}")
                return result, 0, None

        # URL 3 : Page de statut par centre
        center_slug = center.get("code", center_code).lower()
        html = await _fetch(f"{BASE}/appointment/schedule?center={center_slug}", client)
        if html:
            result = _analyse_text(html)
            if result is not None:
                logger.info(f"[{center_code}] schedule page → {'SLOTS' if result else 'no slots'}")
                return result, 0, None

    # Par défaut : pas de créneaux (on n'envoie pas de fausse alerte)
    logger.info(f"[{center_code}] Statut indéterminé — pas d'alerte envoyée")
    return False, 0, None


async def check_all_centers() -> dict:
    """Vérifie tous les centres en parallèle."""
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
            logger.error(f"Error checking {code}: {e}")
            results[code] = {
                "has_slots": False, "count": 0, "earliest": None,
                "error": str(e), "checked_at": datetime.now(TZ).isoformat()
            }

    await asyncio.gather(*[_check_one(code) for code in CENTERS.keys()])
    return results
