"""Shared CLI contract helpers for context, validate, save and shopping list."""

from __future__ import annotations

import json
from typing import Any

from app.config import settings
from app.core.canonical_pipeline import (
    assess_recipe_pool,
    create_plan_record,
    finalize_plan_record,
    load_candidate_recipes,
    load_user_profile,
)
from app.core.skills.aggregator import aggregate_shopping_list
from app.core.skills.validator import validate_day_plan
from app.db.models import MealPlanStatus
from app.db.session import async_session


async def build_context_payload(user_id: str, day: int = 1) -> dict[str, Any]:
    """Build the same context payload that the CLI exposes to an agent."""
    async with async_session() as session:
        user = await load_user_profile(session, user_id)
        recipes = await load_candidate_recipes(
            session,
            user,
            limit=settings.LLM_CONTEXT_RECIPE_LIMIT,
        )

    recipe_list = [
        {
            "id": recipe["id"],
            "title": recipe["title"],
            "calories": recipe["calories"],
            "protein": recipe["protein"],
            "fat": recipe["fat"],
            "carbs": recipe["carbs"],
            "tags": recipe.get("tags", []),
            "ingredients": recipe.get("ingredients", []),
            "meal_type": recipe.get("meal_type"),
            "ingredients_short": recipe.get("ingredients_short", ""),
        }
        for recipe in recipes
    ]

    return {
        "user": {
            "id": user["id"],
            "gender": user["gender"],
            "age": user["age"],
            "weight_kg": user["weight_kg"],
            "height_cm": user["height_cm"],
            "goal": user["goal"],
            "target_calories": user["target_calories"],
            "allergies": user.get("allergies") or [],
            "preferences": user.get("preferences") or [],
            "disliked_ingredients": user.get("disliked_ingredients") or [],
            "diseases": user.get("diseases") or [],
            "meal_schedule": user.get("meal_schedule") or [],
        },
        "day_number": day,
        "available_recipes": recipe_list,
        "catalog_diagnostics": assess_recipe_pool(
            recipe_list,
            user_profile=user,
        ),
        "output_schema": {
            "daily_target_calories": "int",
            "day": {
                "day_number": "int",
                "total_calories": "float",
                "total_protein": "float",
                "total_fat": "float",
                "total_carbs": "float",
                "meals": [
                    {
                        "type": "breakfast|lunch|dinner|snack|second_snack",
                        "recipe_id": "идентификатор из available_recipes",
                        "title": "str",
                        "calories": "float",
                        "protein": "float",
                        "fat": "float",
                        "carbs": "float",
                    }
                ],
            },
        },
    }


def validate_plan_payload(
    raw_payload: str | dict[str, Any],
    *,
    target_calories: int | None = None,
    meal_schedule: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], int]:
    """Validate a one-day plan payload and return CLI-shaped output plus exit code."""
    from app.core.agent.schemas import MealPlanOutput

    try:
        if isinstance(raw_payload, str):
            output = MealPlanOutput.model_validate_json(raw_payload)
        else:
            output = MealPlanOutput.model_validate(raw_payload)
    except Exception as exc:
        return {"valid": False, "error": f"Parse error: {exc}"}, 1

    target = target_calories or output.daily_target_calories
    is_valid, error = validate_day_plan(
        output.day,
        target,
        meal_schedule=meal_schedule,
    )
    deviation_pct = (
        round(abs(output.day.total_calories - target) / target * 100, 1) if target > 0 else None
    )

    result = {
        "valid": is_valid,
        "total_calories": output.day.total_calories,
        "target_calories": target,
        "deviation_pct": deviation_pct,
        "meals_count": len(output.day.meals),
    }
    if error:
        result["error"] = error
    return result, 0 if is_valid else 1


def normalize_plan_for_shopping(
    plan_data: dict[str, Any],
    *,
    input_format: str = "auto",
) -> dict[str, Any]:
    """Normalize a day-plan payload to weekly shape before aggregation."""
    if input_format == "day" or (
        input_format == "auto" and "day" in plan_data and "days" not in plan_data
    ):
        if "day" not in plan_data:
            raise ValueError("Expected day-format JSON with top-level key 'day'")
        return {
            "total_days": 1,
            "daily_target_calories": plan_data.get("daily_target_calories"),
            "days": [plan_data["day"]],
        }
    return plan_data


def build_shopping_list_payload(
    plan_data: dict[str, Any],
    *,
    input_format: str = "auto",
) -> list[dict[str, Any]]:
    """Build shopping list from a day or weekly plan payload."""
    normalized = normalize_plan_for_shopping(plan_data, input_format=input_format)
    return aggregate_shopping_list(normalized)


async def save_plan_payload(
    user_id: str,
    plan_data: dict[str, Any],
    *,
    days_count: int,
) -> dict[str, Any]:
    """Persist a plan payload and return CLI-shaped save response."""
    async with async_session() as session:
        plan_record = await create_plan_record(
            session,
            user_id=user_id,
            days=days_count,
            status=MealPlanStatus.generating,
        )
        await finalize_plan_record(
            session,
            plan_record=plan_record,
            plan_data=plan_data,
            status=MealPlanStatus.ready,
        )
        return {
            "plan_id": str(plan_record.id),
            "status": "READY",
            "days": days_count,
        }


def dump_json(payload: dict[str, Any] | list[dict[str, Any]]) -> str:
    """Render payload as CLI-friendly JSON."""
    return json.dumps(payload, ensure_ascii=False, indent=2)
