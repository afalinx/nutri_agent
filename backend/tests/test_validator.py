"""Unit-тесты валидатора дневного плана."""

from app.core.agent.schemas import MealPlanOutput
from app.core.skills.validator import validate_day_plan


def _valid_output_json() -> str:
    return """
    {
      "daily_target_calories": 2000,
      "day": {
        "day_number": 1,
        "total_calories": 2000,
        "total_protein": 150,
        "total_fat": 70,
        "total_carbs": 200,
        "meals": [
          {
            "type": "breakfast",
            "time": "08:00",
            "recipe_id": "id-bf",
            "title": "Breakfast",
            "calories": 500,
            "protein": 30,
            "fat": 20,
            "carbs": 50
          },
          {
            "type": "lunch",
            "time": "13:00",
            "recipe_id": "id-lunch",
            "title": "Lunch",
            "calories": 700,
            "protein": 60,
            "fat": 20,
            "carbs": 60
          },
          {
            "type": "dinner",
            "time": "19:00",
            "recipe_id": "id-dinner",
            "title": "Dinner",
            "calories": 600,
            "protein": 40,
            "fat": 20,
            "carbs": 80
          },
          {
            "type": "snack",
            "time": "16:00",
            "recipe_id": "id-snack",
            "title": "Snack",
            "calories": 200,
            "protein": 20,
            "fat": 10,
            "carbs": 10
          }
        ]
      }
    }
    """


def test_validator_passes_valid_day_plan():
    output = MealPlanOutput.model_validate_json(_valid_output_json())
    is_valid, error = validate_day_plan(output.day, target_calories=2000)
    assert is_valid is True
    assert error is None


def test_validator_rejects_non_positive_target():
    output = MealPlanOutput.model_validate_json(_valid_output_json())
    is_valid, error = validate_day_plan(output.day, target_calories=0)
    assert is_valid is False
    assert "target_calories" in (error or "")


def test_validator_rejects_duplicate_meal_types():
    output = MealPlanOutput.model_validate_json(_valid_output_json())
    # Change dinner to breakfast (creates duplicate breakfast, but snack still present)
    output.day.meals[2].type = "breakfast"
    # Use schedule without dinner to avoid "missing meal" error
    schedule = [
        {"type": "breakfast", "time": "08:00", "calories_pct": 50},
        {"type": "lunch", "time": "13:00", "calories_pct": 35},
        {"type": "snack", "time": "16:00", "calories_pct": 15},
    ]
    is_valid, error = validate_day_plan(output.day, target_calories=2000, meal_schedule=schedule)
    assert is_valid is False
    assert "Дублируются типы" in (error or "")


def test_validator_with_custom_schedule():
    """Валидация по кастомному расписанию (3 приёма, без snack)."""
    output = MealPlanOutput.model_validate_json(_valid_output_json())
    # Remove snack from plan
    output.day.meals = [m for m in output.day.meals if m.type != "snack"]
    output.day.total_calories = sum(m.calories for m in output.day.meals)

    schedule_3_meals = [
        {"type": "breakfast", "time": "08:00", "calories_pct": 30},
        {"type": "lunch", "time": "13:00", "calories_pct": 40},
        {"type": "dinner", "time": "19:00", "calories_pct": 30},
    ]

    is_valid, error = validate_day_plan(
        output.day, target_calories=1800, meal_schedule=schedule_3_meals
    )
    assert is_valid is True
    assert error is None


def test_validator_rejects_missing_scheduled_meal():
    """Если в расписании есть second_snack, но в плане его нет — ошибка."""
    output = MealPlanOutput.model_validate_json(_valid_output_json())

    schedule_5_meals = [
        {"type": "breakfast", "time": "08:00", "calories_pct": 20},
        {"type": "lunch", "time": "13:00", "calories_pct": 30},
        {"type": "dinner", "time": "19:00", "calories_pct": 25},
        {"type": "snack", "time": "16:00", "calories_pct": 10},
        {"type": "second_snack", "time": "21:00", "calories_pct": 15},
    ]

    is_valid, error = validate_day_plan(
        output.day, target_calories=2000, meal_schedule=schedule_5_meals
    )
    assert is_valid is False
    assert "second_snack" in (error or "")
