"""Unit-тесты server-side runtime для agent_cli."""

from __future__ import annotations

import pytest

from app.core.agent.orchestrator import GeneratedDayResult
from app.core.agent.schemas import DayPlanFull, MealItemFull
from app.core import agent_cli_runtime


def _context(day_number: int) -> dict:
    return {
        "user": {
            "id": "user-1",
            "target_calories": 2000,
            "meal_schedule": [
                {"type": "breakfast", "time": "08:00", "calories_pct": 25},
                {"type": "lunch", "time": "13:00", "calories_pct": 35},
                {"type": "dinner", "time": "19:00", "calories_pct": 30},
                {"type": "snack", "time": "16:00", "calories_pct": 10},
            ],
        },
        "day_number": day_number,
        "catalog_diagnostics": {
            "slot_counts": {"breakfast": 1, "lunch": 1, "dinner": 1, "snack": 1},
            "max_achievable_calories": 2000,
            "target_calories": 2000,
            "feasible": True,
        },
        "available_recipes": [
            {
                "id": "recipe-breakfast",
                "title": "Breakfast Recipe",
                "meal_type": "breakfast",
                "calories": 500,
                "protein": 30,
                "fat": 15,
                "carbs": 45,
                "ingredients": [],
            },
            {
                "id": "recipe-lunch",
                "title": "Lunch Recipe",
                "meal_type": "lunch",
                "calories": 700,
                "protein": 45,
                "fat": 20,
                "carbs": 60,
                "ingredients": [],
            },
            {
                "id": "recipe-dinner",
                "title": "Dinner Recipe",
                "meal_type": "dinner",
                "calories": 600,
                "protein": 40,
                "fat": 20,
                "carbs": 50,
                "ingredients": [],
            },
            {
                "id": "recipe-snack",
                "title": "Snack Recipe",
                "meal_type": "snack",
                "calories": 200,
                "protein": 20,
                "fat": 15,
                "carbs": 25,
                "ingredients": [],
            },
        ],
    }


def _day_result(day_number: int, quality_status: str = "valid") -> GeneratedDayResult:
    return GeneratedDayResult(
        plan=DayPlanFull(
            day_number=day_number,
            total_calories=2000,
            total_protein=140,
            total_fat=70,
            total_carbs=180,
            meals=[
                MealItemFull(
                    type="breakfast",
                    time="08:00",
                    recipe_id=f"recipe-{day_number}",
                    title="Recipe",
                    calories=2000,
                    protein=140,
                    fat=70,
                    carbs=180,
                    ingredients_summary=[],
                )
            ],
        ),
        quality_status=quality_status,
        attempts_used=2 if quality_status != "valid" else 1,
        validation_error=(
            "Не удалось получить полностью валидный план за 3 попытки"
            if quality_status != "valid"
            else None
        ),
    )


@pytest.mark.asyncio
async def test_agent_cli_runtime_returns_ready_and_progress(monkeypatch):
    progress_events: list[tuple[str, dict]] = []

    async def fake_context(user_id: str, day: int):
        return _context(day)

    async def fake_generate(user, recipes, day_number: int):
        return _day_result(day_number, quality_status="partially_valid" if day_number == 2 else "valid")

    async def fake_save(user_id: str, plan_data: dict, *, days_count: int):
        assert plan_data["generation_meta"]["mode"] == "agent_cli"
        return {"plan_id": "plan-123", "status": "READY", "days": days_count}

    monkeypatch.setattr(agent_cli_runtime, "build_context_payload", fake_context)
    monkeypatch.setattr(agent_cli_runtime, "generate_day_plan", fake_generate)
    monkeypatch.setattr(
        agent_cli_runtime,
        "validate_plan_payload",
        lambda *args, **kwargs: ({"valid": True}, 0),
    )
    monkeypatch.setattr(agent_cli_runtime, "save_plan_payload", fake_save)
    monkeypatch.setattr(
        agent_cli_runtime,
        "build_shopping_list_payload",
        lambda *args, **kwargs: [{"name": "Oats", "amount": 80.0, "unit": "g"}],
    )

    def progress_callback(state: dict, celery_state: str):
        progress_events.append((celery_state, state))

    result = await agent_cli_runtime.run_agent_cli_pipeline(
        user_id="user-1",
        days=2,
        progress_callback=progress_callback,
    )

    assert result["status"] == "READY"
    assert result["mode"] == "agent_cli"
    assert result["quality_status"] == "partially_valid"
    assert result["shopping_list"][0]["name"] == "Oats"
    assert any("Day 2:" in warning for warning in result["warnings"])
    assert result["steps"][-1]["key"] == "shopping-list"
    assert result["steps"][-1]["status"] == "completed"
    assert progress_events[-1][0] == "SUCCESS"


@pytest.mark.asyncio
async def test_agent_cli_runtime_marks_failed_progress_on_validation_error(monkeypatch):
    progress_events: list[tuple[str, dict]] = []

    async def fake_context(user_id: str, day: int):
        return _context(day)

    async def fake_generate(user, recipes, day_number: int):
        return _day_result(day_number)

    monkeypatch.setattr(agent_cli_runtime, "build_context_payload", fake_context)
    monkeypatch.setattr(agent_cli_runtime, "generate_day_plan", fake_generate)
    monkeypatch.setattr(
        agent_cli_runtime,
        "validate_plan_payload",
        lambda *args, **kwargs: ({"valid": False, "error": "calories mismatch"}, 1),
    )

    def progress_callback(state: dict, celery_state: str):
        progress_events.append((celery_state, state))

    with pytest.raises(RuntimeError, match="calories mismatch"):
        await agent_cli_runtime.run_agent_cli_pipeline(
            user_id="user-1",
            days=1,
            progress_callback=progress_callback,
        )

    assert progress_events[-1][0] == "GENERATING"
    failed_steps = progress_events[-1][1]["steps"]
    assert any(step["key"] == "auto-fix" and step["status"] == "failed" for step in failed_steps)


@pytest.mark.asyncio
async def test_agent_cli_runtime_auto_fixes_duplicate_meal_types(monkeypatch):
    progress_events: list[tuple[str, dict]] = []

    async def fake_context(user_id: str, day: int):
        return _context(day)

    async def fake_generate(user, recipes, day_number: int):
        return GeneratedDayResult(
            plan=DayPlanFull(
                day_number=day_number,
                total_calories=2630,
                total_protein=140,
                total_fat=70,
                total_carbs=180,
                meals=[
                    MealItemFull(
                        type="breakfast",
                        time="08:00",
                        recipe_id="recipe-breakfast",
                        title="Breakfast Recipe",
                        calories=500,
                        protein=30,
                        fat=15,
                        carbs=45,
                        ingredients_summary=[],
                    ),
                    MealItemFull(
                        type="lunch",
                        time="13:00",
                        recipe_id="recipe-lunch",
                        title="Lunch Recipe",
                        calories=700,
                        protein=45,
                        fat=20,
                        carbs=60,
                        ingredients_summary=[],
                    ),
                    MealItemFull(
                        type="lunch",
                        time="19:00",
                        recipe_id="recipe-lunch",
                        title="Lunch Recipe",
                        calories=700,
                        protein=45,
                        fat=20,
                        carbs=60,
                        ingredients_summary=[],
                    ),
                    MealItemFull(
                        type="snack",
                        time="16:00",
                        recipe_id="recipe-snack",
                        title="Snack Recipe",
                        calories=200,
                        protein=20,
                        fat=15,
                        carbs=25,
                        ingredients_summary=[],
                    ),
                ],
            ),
            quality_status="valid",
            attempts_used=2,
            validation_error=None,
        )

    def fake_validate(raw_payload, *, target_calories=None, meal_schedule=None):
        day = raw_payload["day"]
        meal_types = [meal["type"] for meal in day["meals"]]
        if len(meal_types) != len(set(meal_types)):
            return {"valid": False, "error": "Дублируются типы приёмов пищи в рамках одного дня"}, 1
        total = sum(meal["calories"] for meal in day["meals"])
        if abs(total - target_calories) > 100:
            return {"valid": False, "error": "Отклонение по калоражу"}, 1
        return {"valid": True}, 0

    async def fake_save(user_id: str, plan_data: dict, *, days_count: int):
        repaired_day = plan_data["days"][0]
        assert [meal["type"] for meal in repaired_day["meals"]] == [
            "breakfast",
            "lunch",
            "dinner",
            "snack",
        ]
        assert repaired_day["total_calories"] == 2000
        return {"plan_id": "plan-123", "status": "READY", "days": days_count}

    monkeypatch.setattr(agent_cli_runtime, "build_context_payload", fake_context)
    monkeypatch.setattr(agent_cli_runtime, "generate_day_plan", fake_generate)
    monkeypatch.setattr(agent_cli_runtime, "validate_plan_payload", fake_validate)
    monkeypatch.setattr(agent_cli_runtime, "save_plan_payload", fake_save)
    monkeypatch.setattr(
        agent_cli_runtime,
        "build_shopping_list_payload",
        lambda *args, **kwargs: [{"name": "Oats", "amount": 80.0, "unit": "g"}],
    )

    def progress_callback(state: dict, celery_state: str):
        progress_events.append((celery_state, state))

    result = await agent_cli_runtime.run_agent_cli_pipeline(
        user_id="user-1",
        days=1,
        progress_callback=progress_callback,
    )

    assert result["status"] == "READY"
    assert result["quality_status"] == "partially_valid"
    assert any("auto-fix after" in warning for warning in result["warnings"])
    assert any(step["key"] == "auto-fix" and step["status"] == "completed" for step in result["steps"])
    assert progress_events[-1][0] == "SUCCESS"


@pytest.mark.asyncio
async def test_agent_cli_runtime_fails_fast_on_catalog_insufficiency(monkeypatch):
    progress_events: list[tuple[str, dict]] = []

    async def fake_context(user_id: str, day: int):
        context = _context(day)
        context["user"]["target_calories"] = 2600
        context["catalog_diagnostics"] = {
            "slot_counts": {"breakfast": 1, "lunch": 1, "dinner": 1, "snack": 1},
            "max_achievable_calories": 1800,
            "target_calories": 2600,
            "feasible": False,
        }
        return context

    async def fake_generate(user, recipes, day_number: int):
        raise AssertionError("generate_day_plan should not run when catalog is infeasible")

    monkeypatch.setattr(agent_cli_runtime, "build_context_payload", fake_context)
    monkeypatch.setattr(agent_cli_runtime, "generate_day_plan", fake_generate)

    def progress_callback(state: dict, celery_state: str):
        progress_events.append((celery_state, state))

    with pytest.raises(RuntimeError, match="catalog_insufficient"):
        await agent_cli_runtime.run_agent_cli_pipeline(
            user_id="user-1",
            days=1,
            progress_callback=progress_callback,
        )

    assert progress_events[-1][0] == "GENERATING"
    assert any(step["key"] == "context" and step["status"] == "failed" for step in progress_events[-1][1]["steps"])
