import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
VFS_EMAIL = os.getenv("VFS_EMAIL", "")
VFS_PASSWORD = os.getenv("VFS_PASSWORD", "")

DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "vfs_bot.db"))

CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL", "120"))

BRIEFING_HOUR = 9
BRIEFING_MINUTE = 0

TIMEZONE = "Africa/Algiers"

VFS_BASE_URL = "https://lift-api.vfsglobal.com"
VFS_WEB_BASE = "https://visa.vfsglobal.com"

MISSION_CODE = "ITA"
COUNTRY_CODE = "DZA"
VISA_CATEGORY = "Long Stay"
VISA_SUBCATEGORY = "Students - Long Stay"

CENTERS = {
    "ALGIERS": {
        "name": "Alger (Algiers)",
        "code": "Algiers",
        "vac_id": "ALG",
        "flag": "🏙️",
        "region": "Nord"
    },
    "CONSTANTINE": {
        "name": "Constantine",
        "code": "Constantine",
        "vac_id": "CON",
        "flag": "🏛️",
        "region": "Est"
    },
    "ORAN": {
        "name": "Oran",
        "code": "Oran",
        "vac_id": "ORA",
        "flag": "🌊",
        "region": "Ouest"
    },
    "ANNABA": {
        "name": "Annaba",
        "code": "Annaba",
        "vac_id": "ANN",
        "flag": "🌿",
        "region": "Est"
    },
    "TLEMCEN": {
        "name": "Tlemcen",
        "code": "Tlemcen",
        "vac_id": "TLE",
        "flag": "🕌",
        "region": "Ouest"
    },
}

STUDENT_VISA_TIPS = [
    "📚 Préparez votre dossier 3 mois avant la date prévue de départ.",
    "📋 La lettre d'acceptation universitaire doit être originale et traduite en italien.",
    "💰 Justificatif financier requis : minimum 448€/mois ou 5.376€/an sur compte bancaire.",
    "🏠 Justificatif d'hébergement en Italie obligatoire (contrat de location ou attestation de l'université).",
    "📸 Photos conformes : fond blanc, 3.5x4.5 cm, récentes (moins de 6 mois).",
    "✅ Assurance voyage couvrant tout le séjour et toute la zone Schengen obligatoire.",
    "🎓 Le visa étudiant long séjour permet de travailler 20h/semaine en Italie.",
    "📅 Déposez votre demande au minimum 3 mois avant le début des cours.",
    "🔄 Renouvellement possible en Italie via le Questura (commissariat) de votre ville.",
    "📞 Le centre VFS ouvre les créneaux généralement en début de mois (1-15).",
    "🌐 Créez votre compte VFS dès maintenant sur vfsglobal.com pour être prêt.",
    "📁 Gardez des copies numériques de TOUS vos documents dans le cloud.",
    "⏰ Soyez ponctuel au rendez-vous, le retard peut causer l'annulation.",
    "💳 Les frais VFS sont non-remboursables même en cas de refus de visa.",
    "🇮🇹 Apprenez quelques mots d'italien pour l'entretien — ça fait bonne impression !",
]

VFS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Content-Type": "application/json",
    "Origin": "https://visa.vfsglobal.com",
    "Referer": "https://visa.vfsglobal.com/",
}
