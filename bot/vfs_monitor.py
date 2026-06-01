"""
VFS Global Monitor — Algeria Italy Student Visa
Session persistante avec playwright-stealth pour contourner Cloudflare.
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional, Tuple
import pytz
from config import CENTERS, TIMEZONE, VFS_EMAIL, VFS_PASSWORD

logger = logging.getLogger(__name__)
TZ = pytz.timezone(TIMEZONE)
BASE = "https://visa.vfsglobal.com/dza/en/ita"
LOGIN_URL = f"{BASE}/login"
APPOINTMENT_URL = f"{BASE}/appointment"

NO_SLOT_PHRASES = [
    "no appointment slots are currently available",
    "aucun créneau de rendez-vous n'est actuellement disponible",
    "de nouveaux créneaux s'ouvrent à intervalles réguliers",
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
    "403201",
    "json-formatter-container",
]

SLOT_PHRASES = [
    "select a date",
    "choose a date",
    "available appointment",
    "book an appointment",
    "appointment available",
    "créneau disponible",
    "réserver un rendez-vous",
]

# Session persistante globale
_browser = None
_context = None
_page = None
_logged_in = False
_playwright_instance = None


def _analyse_text(html: str) -> Optional[bool]:
    t = html.lower()
    for phrase in NO_SLOT_PHRASES:
        if phrase.lower() in t:
            return False
    for phrase in SLOT_PHRASES:
        if phrase.lower() in t:
            return True
    return None


async def _init_browser():
    """Initialise le navigateur avec stealth une seule fois."""
    global _browser, _context, _page, _playwright_instance
    try:
        from playwright.async_api import async_playwright
        _playwright_instance = await async_playwright().start()
        _browser = await _playwright_instance.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ]
        )
        _context = await _browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
            viewport={"width": 1280, "height": 800},
            extra_http_headers={
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            }
        )
        # Masquer les traces Playwright
        await _context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
            Object.defineProperty(navigator, 'languages', { get: () => ['fr-FR', 'fr', 'en'] });
            window.chrome = { runtime: {} };
        """)
        _page = await _context.new_page()
        logger.info("Navigateur initialisé avec stealth")
        return True
    except Exception as e:
        logger.error(f"Erreur init navigateur: {e}")
        return False


async def _login() -> bool:
    """Se connecte à VFS avec email/password."""
    global _logged_in
    try:
        logger.info("Tentative de login VFS...")
        await _page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)  # Laisser Cloudflare charger

        # Laisser Cloudflare résoudre
        await asyncio.sleep(8)
        html = await _page.content()
        logger.info(f"LOGIN PAGE: {html[:500]}")

        # Remplir email
        email_field = await _page.query_selector('input[type="email"], input[name="email"], #email')
        if email_field:
            await email_field.click()
            await asyncio.sleep(0.5)
            await email_field.fill(VFS_EMAIL)
            await asyncio.sleep(0.5)

        # Remplir password
        pwd_field = await _page.query_selector('input[type="password"], input[name="password"], #password')
        if pwd_field:
            await pwd_field.click()
            await asyncio.sleep(0.5)
            await pwd_field.fill(VFS_PASSWORD)
            await asyncio.sleep(0.5)

        # Attendre Cloudflare Turnstile (jusqu'à 10 secondes)
        await asyncio.sleep(5)

        # Cliquer Sign In
        sign_in_btn = await _page.query_selector('button[type="submit"], button:has-text("Sign In"), button:has-text("sign in")')
        if sign_in_btn:
            await sign_in_btn.click()
        else:
            await _page.keyboard.press("Enter")

        # Attendre la redirection post-login
        await asyncio.sleep(5)
        current_url = _page.url
        html = await _page.content()

        if "login" not in current_url.lower() or "dashboard" in current_url.lower() or "appointment" in current_url.lower():
            _logged_in = True
            logger.info(f"Login réussi — URL: {current_url}")
            return True

        # Vérifier si on est connecté via le contenu
        if "sign out" in html.lower() or "logout" in html.lower() or "my account" in html.lower():
            _logged_in = True
            logger.info("Login réussi (détecté via contenu)")
            return True

        logger.warning(f"Login échoué — URL: {current_url}")
        _logged_in = False
        return False

    except Exception as e:
        logger.error(f"Erreur login: {e}")
        _logged_in = False
        return False


async def _ensure_session() -> bool:
    """S'assure que le navigateur et la session sont actifs."""
    global _browser, _page, _logged_in

    # Init navigateur si nécessaire
    if _browser is None or _page is None:
        ok = await _init_browser()
        if not ok:
            return False

    # Login si nécessaire
    if not _logged_in:
        return await _login()

    # Vérifier que la session est toujours valide
    try:
        html = await _page.content()
        if "403201" in html or "sign in" in html.lower() and "sign out" not in html.lower():
            logger.info("Session expirée, re-login...")
            _logged_in = False
            return await _login()
        return True
    except Exception:
        _logged_in = False
        return await _login()


async def check_appointments_via_web(center_code: str) -> Tuple[bool, int, Optional[str]]:
    """Vérifie les créneaux pour un centre donné."""
    try:
        session_ok = await _ensure_session()
        if not session_ok:
            logger.warning(f"[{center_code}] Session non disponible")
            return False, 0, None

        await _page.goto(APPOINTMENT_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)
        html = await _page.content()
        logger.info(f"[{center_code}] PAGE (200 chars): {html[:200]}")

        result = _analyse_text(html)
        if result is not None:
            logger.info(f"[{center_code}] → {'🟢 CRÉNEAUX DISPONIBLES' if result else 'no slots'}")
            return result, 0, None

        logger.warning(f"[{center_code}] Résultat indéterminé")
        return False, 0, None

    except Exception as e:
        logger.warning(f"[{center_code}] Erreur check: {e}")
        return False, 0, None


async def check_all_centers() -> dict:
    """Vérifie tous les centres en séquentiel (même session)."""
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
    return results


async def close_browser():
    """Ferme le navigateur proprement (à appeler à l'arrêt du bot)."""
    global _browser, _context, _page, _playwright_instance, _logged_in
    try:
        if _page:
            await _page.close()
        if _context:
            await _context.close()
        if _browser:
            await _browser.close()
        if _playwright_instance:
            await _playwright_instance.stop()
        _logged_in = False
        logger.info("Navigateur fermé proprement")
    except Exception as e:
        logger.error(f"Erreur fermeture navigateur: {e}")