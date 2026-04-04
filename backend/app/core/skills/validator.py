"""Валидатор сгенерированного плана питания."""

from __future__ import annotations

from loguru import logger

from app.core.agent.schemas import DayPlan
from app.db.models import DEFAULT_MEAL_SCHEDULE


def validate_day_plan(
    plan: DayPlan,
    target_calories: int,
    meal_schedule: list[dict] | None = None,
    tolerance_pct: float = 5.0,
) -> tuple[bool, str | None]:
    """Проверяет план дня на корректность КБЖУ.

    Args:
        plan: сгенерированный план дня
        target_calories: целевой калораж
        meal_schedule: расписание пользователя (для проверки типов приёмов)
        tolerance_pct: допустимое отклонение в %

    Returns:
        (is_valid, error_message_or_none)
    """
    if target_calories <= 0:
        msg = f"Некорректный target_calories: {target_calories}"
        logger.warning("Validation: {}", msg)
        return False, msg

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

    # Validate required meal types from schedule
    schedule = meal_schedule or DEFAULT_MEAL_SCHEDULE
    required_types = {slot["type"] for slot in schedule}
    actual_types = {m.type for m in plan.meals}

    missing = required_types - actual_types
    if missing:
        msg = f"Отсутствуют приёмы пищи из расписания: {', '.join(sorted(missing))}"
        logger.warning("Validation: {}", msg)
        return False, msg

    # Check for unexpected duplicates (same type twice)
    meal_types = [m.type for m in plan.meals]
    if len(meal_types) != len(set(meal_types)):
        msg = "Дублируются типы приёмов пищи в рамках одного дня"
        logger.warning("Validation: {}", msg)
        return False, msg

    logger.info(
        "Validation passed: {} kcal (target {}, deviation {:.1f}%)",
        plan.total_calories,
        target_calories,
        deviation_pct,
    )
    return True, None
