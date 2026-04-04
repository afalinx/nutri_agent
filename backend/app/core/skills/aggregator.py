"""Агрегация списка покупок из плана питания."""

from __future__ import annotations

from collections import defaultdict


def aggregate_shopping_list(plan_data: dict) -> list[dict]:
    """Агрегирует ингредиенты из всех дней плана в единый список покупок.

    Суммирует одинаковые ингредиенты (по имени + единице измерения).
    """
    totals: dict[tuple[str, str], float] = defaultdict(float)

    for day in plan_data.get("days", []):
        for meal in day.get("meals", []):
            for ing in meal.get("ingredients_summary", []):
                raw_name = str(ing.get("name", "")).strip().lower()
                if not raw_name:
                    continue
                unit = str(ing.get("unit", "g")).strip() or "g"
                key = (raw_name, unit)
                totals[key] += float(ing.get("amount", 0))

    result = []
    for (name, unit), amount in sorted(totals.items()):
        display_name = name[0].upper() + name[1:] if name else name
        result.append(
            {
                "name": display_name,
                "amount": round(amount, 1),
                "unit": unit,
            }
        )

    return result
