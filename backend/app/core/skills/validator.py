"""Валидатор сгенерированного плана питания."""

from __future__ import annotations

from loguru import logger

from app.core.agent.schemas import DayPlan


def validate_day_plan(
    plan: DayPlan,
    target_calories: int,
    tolerance_pct: float = 5.0,
) -> tuple[bool, str | None]:
    """Проверяет план дня на корректность КБЖУ.

    Returns:
        (is_valid, error_message_or_none)
    """
    total_from_meals = sum(m.calories for m in plan.meals)

    if abs(total_from_meals - plan.total_calories) > 1:
        msg = (
            f"Сумма калорий блюд ({total_from_meals:.0f}) "
            f"не совпадает с total_calories ({plan.total_calories:.0f})"
        )
        logger.warning("Validation: {}", msg)
        return False, msg

    deviation = abs(plan.total_calories - target_calories)
    deviation_pct = (deviation / target_calories) * 100

    if deviation_pct > tolerance_pct:
        msg = (
            f"Отклонение от целевого калоража: "
            f"{plan.total_calories:.0f} vs {target_calories} "
            f"({deviation_pct:.1f}% > {tolerance_pct}%)"
        )
        logger.warning("Validation: {}", msg)
        return False, msg

    meal_types = [m.type for m in plan.meals]
    for required in ("breakfast", "lunch", "dinner"):
        if required not in meal_types:
            msg = f"Отсутствует обязательный приём пищи: {required}"
            logger.warning("Validation: {}", msg)
            return False, msg

    logger.info(
        "Validation passed: {} kcal (target {}, deviation {:.1f}%)",
        plan.total_calories, target_calories, deviation_pct,
    )
    return True, None
