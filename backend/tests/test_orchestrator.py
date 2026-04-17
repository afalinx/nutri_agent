"""Unit-тесты оркестратора генерации плана через LLM."""

from __future__ import annotations

import pytest

from app.core.agent import orchestrator


class _DummyTemplate:
    def render(self, **_: object) -> str:
        return "dummy"


def _valid_llm_json(total_calories: int = 2000) -> str:
    return f"""
    {{
      "daily_target_calories": 2000,
      "day": {{
        "day_number": 1,
        "total_calories": {total_calories},
        "total_protein": 140,
        "total_fat": 70,
        "total_carbs": 180,
        "meals": [
          {{
            "type": "breakfast",
            "time": "08:00",
            "recipe_id": "recipe-1",
            "title": "Breakfast bowl",
            "calories": 500,
            "protein": 35,
            "fat": 15,
            "carbs": 45
          }},
          {{
            "type": "lunch",
            "time": "13:00",
            "recipe_id": "recipe-2",
            "title": "Lunch plate",
            "calories": 700,
            "protein": 45,
            "fat": 20,
            "carbs": 60
          }},
          {{
            "type": "dinner",
            "time": "19:00",
            "recipe_id": "recipe-3",
            "title": "Dinner plate",
            "calories": 600,
            "protein": 40,
            "fat": 20,
            "carbs": 50
          }},
          {{
            "type": "snack",
            "time": "16:00",
            "recipe_id": "recipe-4",
            "title": "Snack",
            "calories": 200,
            "protein": 20,
            "fat": 15,
            "carbs": 25
          }}
        ]
      }}
    }}
    """


def _recipes() -> list[dict]:
    return [
        {
            "id": "recipe-1",
            "title": "Breakfast bowl",
            "calories": 500,
            "protein": 35,
            "fat": 15,
            "carbs": 45,
            "ingredients": [{"name": "Oats", "amount": 80, "unit": "g"}],
        },
        {
            "id": "recipe-2",
            "title": "Lunch plate",
            "calories": 700,
            "protein": 45,
            "fat": 20,
            "carbs": 60,
            "ingredients": [{"name": "Chicken", "amount": 200, "unit": "g"}],
        },
        {
            "id": "recipe-3",
            "title": "Dinner plate",
            "calories": 600,
            "protein": 40,
            "fat": 20,
            "carbs": 50,
            "ingredients": [{"name": "Rice", "amount": 150, "unit": "g"}],
        },
        {
            "id": "recipe-4",
            "title": "Snack",
            "calories": 200,
            "protein": 20,
            "fat": 15,
            "carbs": 25,
            "ingredients": [{"name": "Yogurt", "amount": 180, "unit": "g"}],
        },
    ]


def _user_profile() -> dict:
    return {
        "gender": "male",
        "age": 30,
        "weight_kg": 80,
        "height_cm": 180,
        "goal": "maintain",
        "target_calories": 2000,
        "meal_schedule": [
            {"type": "breakfast", "time": "08:00", "calories_pct": 25},
            {"type": "lunch", "time": "13:00", "calories_pct": 35},
            {"type": "dinner", "time": "19:00", "calories_pct": 30},
            {"type": "snack", "time": "16:00", "calories_pct": 10},
        ],
    }


@pytest.mark.asyncio
async def test_orchestrator_retries_after_parse_error(monkeypatch):
    responses = iter(["not-json", _valid_llm_json()])

    async def fake_call_llm(messages):
        return next(responses)

    monkeypatch.setattr(
        orchestrator,
        "_load_prompt",
        lambda: {"system": _DummyTemplate(), "retry": _DummyTemplate()},
    )
    monkeypatch.setattr(orchestrator, "_call_llm", fake_call_llm)
    monkeypatch.setattr(orchestrator, "validate_day_plan", lambda *args, **kwargs: (True, None))

    result = await orchestrator.generate_day_plan(_user_profile(), _recipes(), day_number=1)

    assert result.quality_status == "valid"
    assert result.attempts_used == 2
    assert result.plan.meals[0].ingredients_summary[0].name == "Oats"


@pytest.mark.asyncio
async def test_orchestrator_returns_partially_valid_after_exhausting_retries(monkeypatch):
    async def fake_call_llm(messages):
        return _valid_llm_json(total_calories=1920)

    monkeypatch.setattr(
        orchestrator,
        "_load_prompt",
        lambda: {"system": _DummyTemplate(), "retry": _DummyTemplate()},
    )
    monkeypatch.setattr(orchestrator, "_call_llm", fake_call_llm)
    monkeypatch.setattr(
        orchestrator,
        "validate_day_plan",
        lambda *args, **kwargs: (False, "Отклонение по калориям"),
    )

    result = await orchestrator.generate_day_plan(_user_profile(), _recipes(), day_number=1)

    assert result.quality_status == "partially_valid"
    assert result.attempts_used == orchestrator.MAX_RETRIES
    assert "лучший доступный вариант" in (result.validation_error or "")
    assert result.plan.total_calories == 2000


@pytest.mark.asyncio
async def test_orchestrator_normalizes_derived_totals_before_validation(monkeypatch):
    validate_calls: list[tuple[float, float, float, float]] = []

    async def fake_call_llm(messages):
        return """
        {
          "daily_target_calories": 2000,
          "day": {
            "day_number": 1,
            "total_calories": 2630,
            "total_protein": 999,
            "total_fat": 999,
            "total_carbs": 999,
            "meals": [
              {
                "type": "breakfast",
                "time": "08:00",
                "recipe_id": "recipe-1",
                "title": "Breakfast bowl",
                "calories": 500,
                "protein": 35,
                "fat": 15,
                "carbs": 45
              },
              {
                "type": "lunch",
                "time": "13:00",
                "recipe_id": "recipe-2",
                "title": "Lunch plate",
                "calories": 700,
                "protein": 45,
                "fat": 20,
                "carbs": 60
              },
              {
                "type": "dinner",
                "time": "19:00",
                "recipe_id": "recipe-3",
                "title": "Dinner plate",
                "calories": 600,
                "protein": 40,
                "fat": 20,
                "carbs": 50
              },
              {
                "type": "snack",
                "time": "16:00",
                "recipe_id": "recipe-4",
                "title": "Snack",
                "calories": 200,
                "protein": 20,
                "fat": 15,
                "carbs": 25
              }
            ]
          }
        }
        """

    def fake_validate(plan, *args, **kwargs):
        validate_calls.append(
            (
                plan.total_calories,
                plan.total_protein,
                plan.total_fat,
                plan.total_carbs,
            )
        )
        return True, None

    monkeypatch.setattr(
        orchestrator,
        "_load_prompt",
        lambda: {"system": _DummyTemplate(), "retry": _DummyTemplate()},
    )
    monkeypatch.setattr(orchestrator, "_call_llm", fake_call_llm)
    monkeypatch.setattr(orchestrator, "validate_day_plan", fake_validate)

    result = await orchestrator.generate_day_plan(_user_profile(), _recipes(), day_number=1)

    assert result.quality_status == "valid"
    assert validate_calls == [(2000, 140, 70, 180)]
    assert result.plan.total_calories == 2000
    assert result.plan.total_protein == 140
    assert result.plan.total_fat == 70
    assert result.plan.total_carbs == 180
