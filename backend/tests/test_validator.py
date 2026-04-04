"""Unit-тесты валидатора дневного плана."""

from app.core.agent.schemas import DayPlan, MealPlanOutput
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
            "recipe_id": "id-bf",
            "title": "Breakfast",
            "calories": 500,
            "protein": 30,
            "fat": 20,
            "carbs": 50,
            "ingredients_summary": [{"name": "A", "amount": 100, "unit": "g"}]
          },
          {
            "type": "lunch",
            "recipe_id": "id-lunch",
            "title": "Lunch",
            "calories": 700,
            "protein": 60,
            "fat": 20,
            "carbs": 60,
            "ingredients_summary": [{"name": "B", "amount": 200, "unit": "g"}]
          },
          {
            "type": "dinner",
            "recipe_id": "id-dinner",
            "title": "Dinner",
            "calories": 600,
            "protein": 40,
            "fat": 20,
            "carbs": 80,
            "ingredients_summary": [{"name": "C", "amount": 150, "unit": "g"}]
          },
          {
            "type": "snack",
            "recipe_id": "id-snack",
            "title": "Snack",
            "calories": 200,
            "protein": 20,
            "fat": 10,
            "carbs": 10,
            "ingredients_summary": [{"name": "D", "amount": 50, "unit": "g"}]
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
    output.day.meals[3].type = "breakfast"
    is_valid, error = validate_day_plan(output.day, target_calories=2000)
    assert is_valid is False
    assert "Дублируются типы" in (error or "")


def test_schema_rejects_unknown_meal_type():
    invalid = """
    {
      "daily_target_calories": 2000,
      "day": {
        "day_number": 1,
        "total_calories": 1000,
        "total_protein": 60,
        "total_fat": 30,
        "total_carbs": 100,
        "meals": [
          {
            "type": "brunch",
            "recipe_id": "id",
            "title": "Brunch",
            "calories": 1000,
            "protein": 60,
            "fat": 30,
            "carbs": 100,
            "ingredients_summary": [{"name": "X", "amount": 100, "unit": "g"}]
          }
        ]
      }
    }
    """
    try:
        MealPlanOutput.model_validate_json(invalid)
        assert False, "Expected validation error for unknown meal type"
    except Exception as exc:
        assert "brunch" in str(exc)
