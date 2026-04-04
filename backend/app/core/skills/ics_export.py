"""Генерация .ics (iCalendar) файла из плана питания.

RFC 5545 — совместим с Google Calendar, Apple Calendar, Outlook.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

MEAL_TYPE_LABELS = {
    "breakfast": "Завтрак",
    "lunch": "Обед",
    "dinner": "Ужин",
    "snack": "Перекус",
    "second_snack": "Второй перекус",
}

MEAL_DURATION_MINUTES = {
    "breakfast": 30,
    "lunch": 45,
    "dinner": 45,
    "snack": 15,
    "second_snack": 15,
}


def _escape_ics(text: str) -> str:
    return text.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def _format_dt(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")


def generate_ics(plan_data: dict, plan_id: str, start_date: date | None = None) -> str:
    """Генерирует .ics строку из плана питания.

    Args:
        plan_data: dict из MealPlan.plan_data (содержит days[])
        plan_id: UUID плана (для UID событий)
        start_date: дата начала плана

    Returns:
        Строка в формате iCalendar
    """
    base_date = start_date or date.today()
    now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//NutriAgent//MealPlan//RU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:NutriAgent — План питания",
    ]

    for day in plan_data.get("days", []):
        day_number = day.get("day_number", 1)
        day_date = base_date + timedelta(days=day_number - 1)

        for meal in day.get("meals", []):
            meal_type = meal.get("type", "snack")
            meal_time = meal.get("time", "12:00")
            title = meal.get("title", "Приём пищи")
            calories = meal.get("calories", 0)
            protein = meal.get("protein", 0)
            fat = meal.get("fat", 0)
            carbs = meal.get("carbs", 0)

            # Parse time
            try:
                hour, minute = map(int, meal_time.split(":"))
            except (ValueError, AttributeError):
                hour, minute = 12, 0

            dt_start = datetime(day_date.year, day_date.month, day_date.day, hour, minute)
            duration = MEAL_DURATION_MINUTES.get(meal_type, 30)
            dt_end = dt_start + timedelta(minutes=duration)

            label = MEAL_TYPE_LABELS.get(meal_type, meal_type.capitalize())
            summary = f"{label}: {title}"

            # Build description
            desc_parts = [
                f"{calories:.0f} ккал | Б:{protein:.0f} Ж:{fat:.0f} У:{carbs:.0f}",
            ]
            ingredients = meal.get("ingredients_summary", [])
            if ingredients:
                ing_text = ", ".join(
                    f"{i.get('name', '')} {i.get('amount', '')} {i.get('unit', '')}"
                    for i in ingredients
                )
                desc_parts.append(f"Состав: {ing_text}")

            description = _escape_ics("\\n".join(desc_parts))
            uid = f"{plan_id}-d{day_number}-{meal_type}@nutriagent"

            lines.extend(
                [
                    "BEGIN:VEVENT",
                    f"UID:{uid}",
                    f"DTSTAMP:{now}",
                    f"DTSTART:{_format_dt(dt_start)}",
                    f"DTEND:{_format_dt(dt_end)}",
                    f"SUMMARY:{_escape_ics(summary)}",
                    f"DESCRIPTION:{description}",
                    "STATUS:CONFIRMED",
                    f"CATEGORIES:{label}",
                    "END:VEVENT",
                ]
            )

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)
