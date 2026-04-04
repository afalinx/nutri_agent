"""
Калькулятор КБЖУ.

Формула Миффлина — Сан Жеора:
  Мужчины: BMR = 10 * вес(кг) + 6.25 * рост(см) - 5 * возраст - 161 + 166
  Женщины: BMR = 10 * вес(кг) + 6.25 * рост(см) - 5 * возраст - 161

Итоговый калораж = BMR * коэффициент активности * коэффициент цели.
"""

from app.db.models import ActivityLevel, Gender, Goal

ACTIVITY_MULTIPLIERS: dict[ActivityLevel, float] = {
    ActivityLevel.sedentary: 1.2,
    ActivityLevel.light: 1.375,
    ActivityLevel.moderate: 1.55,
    ActivityLevel.active: 1.725,
    ActivityLevel.very_active: 1.9,
}

GOAL_MULTIPLIERS: dict[Goal, float] = {
    Goal.lose: 0.85,
    Goal.maintain: 1.0,
    Goal.gain: 1.15,
}


def calculate_bmr(
    weight_kg: float,
    height_cm: float,
    age: int,
    gender: Gender,
) -> float:
    bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age
    if gender == Gender.male:
        bmr += 5
    else:
        bmr -= 161
    return bmr


def calculate_target_calories(
    weight_kg: float,
    height_cm: float,
    age: int,
    gender: Gender,
    activity_level: ActivityLevel,
    goal: Goal,
) -> int:
    bmr = calculate_bmr(weight_kg, height_cm, age, gender)
    tdee = bmr * ACTIVITY_MULTIPLIERS[activity_level]
    target = tdee * GOAL_MULTIPLIERS[goal]
    return round(target)


def validate_meal_calories(
    meal_ingredients: list[dict],
    declared_calories: float,
    tolerance_pct: float = 5.0,
) -> tuple[bool, float]:
    """Проверяет, что заявленные калории совпадают с суммой ингредиентов.

    Returns:
        (is_valid, actual_total)
    """
    actual_total = sum(ingredient.get("calories", 0) for ingredient in meal_ingredients)
    if actual_total == 0:
        return (True, declared_calories)

    deviation_pct = abs(actual_total - declared_calories) / declared_calories * 100
    return (deviation_pct <= tolerance_pct, actual_total)
