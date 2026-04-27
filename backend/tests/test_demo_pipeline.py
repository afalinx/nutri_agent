"""Unit-тесты demo pipeline как отдельного режима выполнения."""

from __future__ import annotations

import types

import pytest

from app.core import demo_pipeline


class _DummySessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _profile() -> dict:
    return {
        "id": "user-1",
        "email": "demo@nutriagent.local",
        "gender": "male",
        "age": 30,
        "weight_kg": 80,
        "height_cm": 180,
        "goal": "maintain",
        "target_calories": 2200,
        "allergies": [],
        "preferences": ["high-protein"],
        "disliked_ingredients": [],
        "diseases": [],
        "meal_schedule": [
            {"type": "breakfast", "time": "08:00", "calories_pct": 25},
        ],
    }


def _day(day_number: int) -> dict:
    return {
        "day_number": day_number,
        "total_calories": 1800.0,
        "total_protein": 120.0,
        "total_fat": 60.0,
        "total_carbs": 150.0,
        "meals": [
            {
                "type": "breakfast",
                "time": "08:00",
                "recipe_id": f"recipe-{day_number}",
                "title": "Breakfast",
                "calories": 1800.0,
                "protein": 120.0,
                "fat": 60.0,
                "carbs": 150.0,
                "ingredients_summary": [{"name": "Eggs", "amount": 3, "unit": "pcs"}],
            }
        ],
    }


@pytest.mark.asyncio
async def test_demo_pipeline_tracks_warnings_and_ready_status(monkeypatch):
    task = demo_pipeline.create_demo_task("user-1", 1)

    async def fake_load_user_profile(session, user_id: str):
        return _profile()

    async def fake_load_demo_recipes(session, user_profile: dict):
        return ([{"id": "recipe-1", "title": "Breakfast", "ingredients": []}], "Для демо soft-предпочтения ослаблены, чтобы собрать валидный рацион.")

    async def fake_create_plan_record(session, *, user_id: str, days: int, status):
        return types.SimpleNamespace(id="plan-123")

    async def fake_finalize_plan_record(session, *, plan_record, plan_data: dict, status):
        return None

    monkeypatch.setattr(demo_pipeline, "async_session", lambda: _DummySessionContext())
    monkeypatch.setattr(demo_pipeline, "load_user_profile", fake_load_user_profile)
    monkeypatch.setattr(demo_pipeline, "_load_demo_recipes", fake_load_demo_recipes)
    monkeypatch.setattr(
        demo_pipeline,
        "_resolve_demo_target_calories",
        lambda *args, **kwargs: (
            1800,
            "Для демо target_calories скорректирован с 2200 до 1800.",
        ),
    )
    monkeypatch.setattr(
        demo_pipeline,
        "_find_plan_combination",
        lambda **kwargs: (_day(kwargs["day_number"]), None),
    )
    monkeypatch.setattr(demo_pipeline, "validate_day_plan", lambda *args, **kwargs: (True, None))
    monkeypatch.setattr(demo_pipeline, "create_plan_record", fake_create_plan_record)
    monkeypatch.setattr(demo_pipeline, "finalize_plan_record", fake_finalize_plan_record)
    monkeypatch.setattr(
        demo_pipeline,
        "aggregate_shopping_list",
        lambda plan_data: [{"name": "Eggs", "amount": 3.0, "unit": "pcs"}],
    )

    await demo_pipeline.run_demo_pipeline(task)

    assert task.status == "READY"
    assert task.quality_status == "partially_valid"
    assert len(task.warnings or []) == 2
    assert task.plan_id == "plan-123"
    assert task.payload()["mode"] == "demo"


@pytest.mark.asyncio
async def test_demo_pipeline_marks_failed_step_on_exception(monkeypatch):
    task = demo_pipeline.create_demo_task("user-1", 1)

    async def fake_load_user_profile(session, user_id: str):
        raise ValueError("Профиль пользователя не найден.")

    monkeypatch.setattr(demo_pipeline, "async_session", lambda: _DummySessionContext())
    monkeypatch.setattr(demo_pipeline, "load_user_profile", fake_load_user_profile)

    await demo_pipeline.run_demo_pipeline(task)

    assert task.status == "FAILED"
    assert task.error == "Профиль пользователя не найден."
    context_step = next(step for step in task.steps if step["key"] == "context")
    assert context_step["status"] == "failed"
