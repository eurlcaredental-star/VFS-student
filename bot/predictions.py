from collections import defaultdict
from datetime import datetime
from typing import Optional
import pytz
from config import TIMEZONE, CENTERS

TZ = pytz.timezone(TIMEZONE)

DAY_NAMES_FR = {
    0: "Lundi", 1: "Mardi", 2: "Mercredi", 3: "Jeudi",
    4: "Vendredi", 5: "Samedi", 6: "Dimanche"
}

MONTH_NAMES_FR = {
    1: "Janvier", 2: "Février", 3: "Mars", 4: "Avril",
    5: "Mai", 6: "Juin", 7: "Juillet", 8: "Août",
    9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre"
}


def build_predictions(events: list, center_code: Optional[str] = None) -> dict:
    """
    Analyze historical events to build predictions.
    Returns a dict with patterns and recommendations.
    """
    if not events:
        return get_default_predictions(center_code)

    day_of_month_counts = defaultdict(int)
    day_of_week_counts = defaultdict(int)
    hour_counts = defaultdict(int)
    center_counts = defaultdict(int)

    for event in events:
        dom = event.get("day_of_month")
        dow = event.get("day_of_week")
        hour = event.get("hour_detected")
        center = event.get("center_code")

        if dom is not None:
            day_of_month_counts[dom] += 1
        if dow is not None:
            day_of_week_counts[dow] += 1
        if hour is not None:
            hour_counts[hour] += 1
        if center:
            center_counts[center] += 1

    total_events = len(events)

    top_days_of_month = sorted(day_of_month_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_days_of_week = sorted(day_of_week_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    top_hours = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)[:4]

    best_dom_groups = group_consecutive_days(top_days_of_month)
    best_dow = top_days_of_week[0] if top_days_of_week else (0, 0)
    best_hour = top_hours[0] if top_hours else (9, 0)

    dom_percentages = {
        day: (count / total_events * 100)
        for day, count in day_of_month_counts.items()
    }

    hour_percentages = {
        hour: (count / total_events * 100)
        for hour, count in hour_counts.items()
    }

    return {
        "total_events": total_events,
        "top_days_of_month": top_days_of_month,
        "top_days_of_week": top_days_of_week,
        "top_hours": top_hours,
        "best_dom_groups": best_dom_groups,
        "best_day_of_week": best_dow,
        "best_hour": best_hour,
        "dom_percentages": dom_percentages,
        "hour_percentages": hour_percentages,
        "center_code": center_code,
        "has_data": True
    }


def group_consecutive_days(sorted_days: list) -> list:
    """Group consecutive days of month that tend to open together"""
    if not sorted_days:
        return []

    days_only = sorted(set([d for d, _ in sorted_days]))
    groups = []
    current_group = [days_only[0]] if days_only else []

    for day in days_only[1:]:
        if day - current_group[-1] <= 2:
            current_group.append(day)
        else:
            if current_group:
                groups.append(current_group)
            current_group = [day]

    if current_group:
        groups.append(current_group)

    return sorted(groups, key=lambda g: sum(1 for d, _ in sorted_days if d in g), reverse=True)


def get_default_predictions(center_code: Optional[str] = None) -> dict:
    """Default predictions when no historical data exists"""
    return {
        "total_events": 0,
        "top_days_of_month": [(1, 3), (2, 2), (15, 2), (16, 1)],
        "top_days_of_week": [(0, 5), (1, 4), (2, 3)],
        "top_hours": [(9, 5), (10, 4), (8, 3), (14, 2)],
        "best_dom_groups": [[1, 2, 3], [14, 15, 16]],
        "best_day_of_week": (0, 5),
        "best_hour": (9, 5),
        "dom_percentages": {1: 25, 2: 20, 15: 18, 16: 15},
        "hour_percentages": {9: 35, 10: 25, 8: 20, 14: 15},
        "center_code": center_code,
        "has_data": False
    }


def format_predictions_message(predictions: dict, center_code: Optional[str] = None) -> str:
    """Format predictions as a nice Telegram message"""
    center_info = CENTERS.get(center_code, {}) if center_code else {}
    center_name = center_info.get("name", "Tous les centres") if center_info else "Tous les centres"
    center_flag = center_info.get("flag", "📍") if center_info else "📍"

    has_data = predictions.get("has_data", False)
    total = predictions.get("total_events", 0)

    lines = []
    lines.append(f"🔮 *PRÉDICTIONS — {center_flag} {center_name}*")
    lines.append("")

    if has_data:
        lines.append(f"📊 Basé sur *{total} ouvertures* enregistrées")
    else:
        lines.append("📊 *Données estimées* (historique en cours de collecte)")
        lines.append("_Les prédictions s'affineront avec le temps_")
    lines.append("")

    lines.append("📅 *MEILLEURS JOURS DU MOIS*")
    best_groups = predictions.get("best_dom_groups", [])
    dom_pct = predictions.get("dom_percentages", {})

    if best_groups:
        for i, group in enumerate(best_groups[:3], 1):
            if len(group) == 1:
                day_str = f"{group[0]}"
            elif len(group) == 2:
                day_str = f"{group[0]}-{group[1]}"
            else:
                day_str = f"{group[0]}-{group[-1]}"

            avg_pct = sum(dom_pct.get(d, 0) for d in group) / len(group) if group else 0
            stars = "🔥" * min(i, 3) if i == 1 else "⚡" if i == 2 else "📌"
            lines.append(f"{stars} *{day_str} du mois* — {avg_pct:.0f}% de chance")
    else:
        lines.append("📌 *1-3 du mois* — 25% de chance")
        lines.append("📌 *14-16 du mois* — 18% de chance")

    lines.append("")
    lines.append("📆 *MEILLEURS JOURS DE LA SEMAINE*")
    top_dow = predictions.get("top_days_of_week", [])
    for i, (dow, count) in enumerate(top_dow[:3], 1):
        day_name = DAY_NAMES_FR.get(dow, "?")
        stars = "🥇" if i == 1 else "🥈" if i == 2 else "🥉"
        lines.append(f"{stars} *{day_name}*")

    if not top_dow:
        lines.append("🥇 *Lundi* — Plus actif")
        lines.append("🥈 *Mardi*")
        lines.append("🥉 *Mercredi*")

    lines.append("")
    lines.append("⏰ *MEILLEURES HEURES*")
    top_hours = predictions.get("top_hours", [])
    hour_pct = predictions.get("hour_percentages", {})

    if top_hours:
        for i, (hour, count) in enumerate(top_hours[:4], 1):
            pct = hour_pct.get(hour, 0)
            bar = "█" * min(int(pct / 5), 10)
            lines.append(f"  `{hour:02d}h00` {bar} {pct:.0f}%")
    else:
        lines.append("  `09h00` ████████ 35%")
        lines.append("  `10h00` ██████ 25%")
        lines.append("  `08h00` ████ 20%")
        lines.append("  `14h00` ███ 15%")

    lines.append("")
    lines.append("💡 *CONSEIL STRATÉGIQUE*")

    best_group = best_groups[0] if best_groups else [1, 2, 3]
    best_dow_name = DAY_NAMES_FR.get(predictions.get("best_day_of_week", (0,))[0], "Lundi")
    best_hour = predictions.get("best_hour", (9,))[0]

    lines.append(
        f"Soyez connecté le *{best_dow_name}* entre *{best_group[0] if best_group else 1}-{best_group[-1] if best_group else 3} du mois* "
        f"vers *{best_hour:02d}h00*."
    )
    lines.append("🔔 Activez les notifications pour ne jamais manquer une ouverture !")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("_Prédictions basées sur les patterns VFS historiques._")
    lines.append("_Aucune ouverture n'est garantie._")

    return "\n".join(lines)


def get_next_likely_opening(predictions: dict) -> str:
    """Get a human-readable estimate of when the next opening might be"""
    now = datetime.now(TZ)
    current_day = now.day
    current_month = now.month
    current_year = now.year

    best_groups = predictions.get("best_dom_groups", [[1, 2, 3], [14, 15, 16]])
    best_hour = predictions.get("best_hour", (9,))[0]

    if best_groups:
        group = best_groups[0]
        next_start = group[0]
        next_end = group[-1]

        if current_day < next_start:
            month_name = MONTH_NAMES_FR.get(current_month, "")
            return f"Vers le *{next_start}-{next_end} {month_name}* à *{best_hour:02d}h00*"
        elif current_day <= next_end:
            return f"*Maintenant* (période favorable en cours !)"
        else:
            if current_month == 12:
                next_month_num = 1
                next_year = current_year + 1
            else:
                next_month_num = current_month + 1
                next_year = current_year

            month_name = MONTH_NAMES_FR.get(next_month_num, "")
            return f"Vers le *{next_start}-{next_end} {month_name} {next_year}* à *{best_hour:02d}h00*"

    return "Incertain — continuez à surveiller"
