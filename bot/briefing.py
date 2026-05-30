import random
from datetime import datetime
from typing import Optional
import pytz
from config import TIMEZONE, STUDENT_VISA_TIPS, CENTERS

TZ = pytz.timezone(TIMEZONE)

ITALY_UNIVERSITY_INFO = [
    "🎓 **Università di Bologna** — La plus ancienne université du monde (fondée en 1088). Top pour droit, médecine, sciences.",
    "🎓 **Politecnico di Milano** — #1 en Italie pour ingénierie, architecture et design.",
    "🎓 **Sapienza Roma** — La plus grande université d'Europe par nombre d'étudiants (~110,000).",
    "🎓 **Università di Padova** — Excellent en médecine, pharmacie et sciences.",
    "🎓 **Università di Firenze** — Réputée pour arts, humanités et sciences sociales.",
]

VISA_PROCESS_STEPS = """
📋 *ÉTAPES DU VISA ÉTUDIANT ITALIE*

1️⃣ **Admission universitaire**
   → Acceptation de l'université italienne
   → Attestation d'inscription (lettera di ammissione)

2️⃣ **Préparation des documents**
   → Passeport valide 3 mois après fin de séjour
   → Photos d'identité conformes
   → Justificatifs financiers (≥448€/mois)
   → Assurance maladie/voyage
   → Justificatif hébergement

3️⃣ **Prise de rendez-vous VFS**
   → Créer compte sur visa.vfsglobal.com
   → Choisir "Long Stay > Students"
   → 🔔 *Activez les alertes de ce bot !*

4️⃣ **Dépôt de dossier VFS**
   → Payer les frais (environ 50-80€ + service VFS)
   → Données biométriques

5️⃣ **Attente décision**
   → Délai moyen: 15-30 jours ouvrables
   → Suivi via VFS/ambassade

6️⃣ **Collecte du visa & départ**
   → Retrait du passeport avec visa
   → Inscription à la Questura à l'arrivée (dans les 8 jours)
"""

FINANCIAL_INFO = """
💰 *JUSTIFICATIFS FINANCIERS — VISA ÉTUDIANT*

L'Italie exige que vous prouviez avoir suffisamment d'argent pour vivre.

📊 *Montant minimum requis :*
• **448,08 €/mois** (ou 5 376,96 €/an)
• Pour un séjour de moins de 3 mois : 269,61 €/mois

✅ *Documents acceptés :*
• Relevés bancaires des 3 derniers mois
• Attestation bancaire traduite + apostille
• Lettre de sponsor (parents) avec déclaration de revenus
• Bourse d'études officielle

⚠️ *Conseils :*
• Préparez les documents EN FRANÇAIS ou ITALIEN
• Traduction assermentée recommandée pour l'arabe
• Les fonds doivent être sur un compte à votre nom (ou parents + lettre sponsor)
"""

LIFE_IN_ITALY = """
🇮🇹 *VIE ÉTUDIANTE EN ITALIE*

🏠 *Logement :*
• Résidences universitaires : 150-400€/mois
• Colocation privée : 300-600€/mois
• Cherchez sur : Unipol, Idealista, Subito

🍕 *Budget mensuel moyen :*
• Logement : 350-500€
• Alimentation : 150-250€
• Transport : 30-50€ (pass étudiant)
• Divers : 100-150€
• **Total : ~700-1000€/mois**

🚌 *Transport :*
• Carte étudiant = réductions importantes
• Trains régionaux = tarifs réduits
• Vélo recommandé dans les petites villes

🎓 *Droits des étudiants :*
• Travailler jusqu'à **20h/semaine** légalement
• Accès aux universités en bonne santé : Droit aux soins (SSN)
• DSU (aide sociale) : bourses et logements subventionnés
"""

DOCUMENT_CHECKLIST = """
📁 *CHECKLIST COMPLÈTE DES DOCUMENTS*

✅ **Passeport** original + copie (validité +3 mois)
✅ **2 photos** d'identité (3,5x4,5cm, fond blanc)
✅ **Formulaire de demande** rempli et signé
✅ **Lettre d'acceptation** universitaire (originale)
✅ **Preuve d'inscription** (lettera di ammissione)
✅ **Justificatifs financiers** (relevés bancaires 3 mois)
✅ **Assurance voyage/santé** (couvrant tout le séjour + Schengen)
✅ **Justificatif d'hébergement** (contrat de location ou attestation université)
✅ **CV/Lettre de motivation** (optionnel mais recommandé)
✅ **Acte de naissance** avec traduction certifiée
✅ **Casier judiciaire** (certaines universités le demandent)

💡 *Préparez des copies de TOUS les documents !*
"""

WEEKLY_BRIEFINGS = {
    0: "tips_monday",
    1: "process_steps",
    2: "financial_info",
    3: "life_in_italy",
    4: "tips_friday",
    5: "document_checklist",
    6: "tips_sunday",
}


def get_daily_tip() -> str:
    today = datetime.now(TZ)
    idx = today.day % len(STUDENT_VISA_TIPS)
    return STUDENT_VISA_TIPS[idx]


def get_daily_briefing(user_name: str = "cher(e) étudiant(e)") -> str:
    now = datetime.now(TZ)
    day_of_week = now.weekday()
    day_name_fr = {
        0: "Lundi", 1: "Mardi", 2: "Mercredi", 3: "Jeudi",
        4: "Vendredi", 5: "Samedi", 6: "Dimanche"
    }
    month_name_fr = {
        1: "janvier", 2: "février", 3: "mars", 4: "avril",
        5: "mai", 6: "juin", 7: "juillet", 8: "août",
        9: "septembre", 10: "octobre", 11: "novembre", 12: "décembre"
    }

    date_str = f"{day_name_fr[day_of_week]} {now.day} {month_name_fr[now.month]} {now.year}"

    greetings = [
        f"🌅 Bonjour {user_name} !",
        f"☀️ Belle journée {user_name} !",
        f"🎓 Salut {user_name} !",
    ]
    greeting = greetings[now.day % len(greetings)]

    tip = get_daily_tip()

    if day_of_week == 0:
        special_content = f"""
🎯 *Conseil de la semaine :*
Les créneaux VFS ont tendance à s'ouvrir en début de semaine (Lundi-Mardi).
Restez vigilant et gardez votre compte VFS prêt !
"""
    elif day_of_week == 2:
        special_content = f"""
💡 *Info financière :*
Avez-vous préparé vos justificatifs de revenus ?
Minimum requis : 448€/mois sur votre compte bancaire.
"""
    elif day_of_week == 4:
        special_content = f"""
📋 *Rappel documents :*
Le week-end est idéal pour préparer votre dossier.
Vérifiez votre checklist : passeport, photos, assurance !
"""
    else:
        special_content = f"""
{random.choice(ITALY_UNIVERSITY_INFO[:3])}
"""

    message = f"""
{greeting}
📅 *{date_str}*

━━━━━━━━━━━━━━━━━━━━

💡 *Conseil du jour :*
{tip}

━━━━━━━━━━━━━━━━━━━━
{special_content}
━━━━━━━━━━━━━━━━━━━━

🔔 Le bot surveille VFS 24h/24 pour vous.
Vous serez alerté dès qu'un créneau s'ouvre !

Bonne journée et bonne chance pour votre visa 🇮🇹✨
""".strip()

    return message


def get_full_visa_guide() -> str:
    return VISA_PROCESS_STEPS


def get_financial_guide() -> str:
    return FINANCIAL_INFO


def get_life_guide() -> str:
    return LIFE_IN_ITALY


def get_document_checklist() -> str:
    return DOCUMENT_CHECKLIST


def get_random_university_info() -> str:
    return random.choice(ITALY_UNIVERSITY_INFO)


def get_alert_message(center_code: str, has_slots: bool, earliest_date: Optional[str] = None, slots_count: int = 0) -> str:
    center = CENTERS.get(center_code, {})
    center_name = center.get("name", center_code)
    flag = center.get("flag", "📍")

    if has_slots:
        date_info = f"\n📅 *Première date disponible :* {earliest_date}" if earliest_date else ""
        count_info = f"\n🔢 *Créneaux disponibles :* {slots_count}" if slots_count > 0 else ""

        return f"""
🚨🚨🚨 *ALERTE RENDEZ-VOUS* 🚨🚨🚨

{flag} *{center_name}*

✅ *DES CRÉNEAUX SONT DISPONIBLES !*{date_info}{count_info}

⚡ *AGISSEZ MAINTENANT !*
Les créneaux disparaissent en quelques minutes.

👉 Réservez sur :
🌐 visa.vfsglobal.com/dza/en/ita

📱 Ou sur l'app *VFS Global* (iOS/Android)

Catégorie : **Long Stay → Students - Long Stay**
Centre : **{center_name}**

━━━━━━━━━━━━━━━━━━━━
_Bot VFS Algeria Monitor • Alerte automatique_
""".strip()
    else:
        return f"""
ℹ️ *Mise à jour — {flag} {center_name}*

❌ Aucun créneau disponible actuellement.
Le bot continue de surveiller...
""".strip()
