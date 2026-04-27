"""Canonical deterministic repair helpers for invalid LLM day plans.

This module is intentionally narrow: it repairs derived totals, schedule
alignment, duplicate meal types and moderate calorie drift using the current
recipe pool. It is not a replacement for generation.
"""

from __future__ import annotations

from copy import deepcopy
from itertools import product
from typing import Any

from app.core.agent.schemas import DayPlan
from app.core.skills.validator import validate_day_plan


def _normalize_meal_type(value: str | None) -> set[str]:
    if not value:
        return set()
    return {
        chunk.strip().lower()
        for chunk in value.replace(",", "/").split("/")
        if chunk.strip()
    }


def _slot_compatible_types(slot_type: str) -> set[str]:
    if slot_type == "breakfast":
        return {"breakfast"}
    if slot_type == "snack":
        return {"snack", "second_snack"}
    if slot_type == "second_snack":
        return {"snack", "second_snack"}
    if slot_type == "lunch":
        return {"lunch", "lunch/dinner", "universal"}
    if slot_type == "dinner":
        return {"dinner", "lunch/dinner", "universal"}
    return {slot_type}


def _recipe_matches_slot(recipe: dict[str, Any], slot_type: str) -> bool:
    recipe_types = _normalize_meal_type(recipe.get("meal_type"))
    if not recipe_types:
        return False
    return bool(recipe_types & _slot_compatible_types(slot_type))


def _recipe_base_id(recipe: dict[str, Any]) -> str:
    base_id = recipe.get("base_recipe_id")
    if base_id:
        return str(base_id)
    recipe_id = str(recipe.get("id"))
    return recipe_id.split("::", 1)[0]


def _meal_base_id(meal: dict[str, Any]) -> str:
    recipe_id = str(meal.get("recipe_id"))
    return recipe_id.split("::", 1)[0]


def _normalize_day_totals(day_plan: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(day_plan)
    meals = normalized.get("meals", [])
    normalized["total_calories"] = round(sum(float(meal["calories"]) for meal in meals), 1)
    normalized["total_protein"] = round(sum(float(meal["protein"]) for meal in meals), 1)
    normalized["total_fat"] = round(sum(float(meal["fat"]) for meal in meals), 1)
    normalized["total_carbs"] = round(sum(float(meal["carbs"]) for meal in meals), 1)
    return normalized


def _build_meal(recipe: dict[str, Any], slot: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": slot["type"],
        "time": slot["time"],
        "recipe_id": recipe["id"],
        "title": recipe["title"],
        "calories": round(float(recipe["calories"]), 1),
        "protein": round(float(recipe["protein"]), 1),
        "fat": round(float(recipe["fat"]), 1),
        "carbs": round(float(recipe["carbs"]), 1),
        "ingredients_summary": [
            {
                "name": ingredient["name"],
                "amount": float(ingredient["amount"]),
                "unit": ingredient["unit"],
            }
            for ingredient in (recipe.get("ingredients") or [])
        ],
    }


def _build_day_plan(
    *,
    day_number: int,
    schedule: list[dict[str, Any]],
    chosen_recipes: list[dict[str, Any]],
) -> dict[str, Any]:
    return _normalize_day_totals(
        {
            "day_number": day_number,
            "meals": [
                _build_meal(recipe, slot)
                for slot, recipe in zip(schedule, chosen_recipes, strict=False)
            ],
        }
    )


def _validate(day_plan: dict[str, Any], *, target_calories: int, meal_schedule: list[dict[str, Any]]):
    normalized = _normalize_day_totals(day_plan)
    validated = DayPlan.model_validate(normalized)
    return validate_day_plan(
        validated,
        target_calories=target_calories,
        meal_schedule=meal_schedule,
    )


def _candidate_lists(
    *,
    recipes: list[dict[str, Any]],
    schedule: list[dict[str, Any]],
    target_calories: int,
    preferred_recipe_ids: set[str],
    avoid_recipe_base_ids: set[str],
    max_candidates_per_slot: int = 8,
) -> list[list[dict[str, Any]]]:
    candidate_lists: list[list[dict[str, Any]]] = []
    for slot in schedule:
        slot_target = target_calories * slot["calories_pct"] / 100
        ranked = sorted(
            [recipe for recipe in recipes if _recipe_matches_slot(recipe, slot["type"])],
            key=lambda recipe: (
                0 if _recipe_base_id(recipe) not in avoid_recipe_base_ids else 1,
                0 if str(recipe["id"]) in preferred_recipe_ids else 1,
                abs(float(recipe["calories"]) - slot_target),
                recipe["title"],
            ),
        )
        candidate_lists.append(ranked[:max_candidates_per_slot])
    return candidate_lists


def repair_day_plan(
    *,
    day_plan: dict[str, Any],
    recipes: list[dict[str, Any]],
    meal_schedule: list[dict[str, Any]],
    target_calories: int,
    avoid_recipe_base_ids: set[str] | None = None,
) -> tuple[dict[str, Any] | None, list[str], str | None]:
    """Repair a generated day plan using the current recipe pool.

    Returns `(repaired_plan, applied_fixes, error_if_any)`.
    """
    normalized_plan = _normalize_day_totals(day_plan)
    is_valid, _ = _validate(
        normalized_plan,
        target_calories=target_calories,
        meal_schedule=meal_schedule,
    )
    if is_valid:
        return normalized_plan, [], None

    current_recipe_ids = {
        str(meal["recipe_id"])
        for meal in normalized_plan.get("meals", [])
        if meal.get("recipe_id")
    }
    candidate_lists = _candidate_lists(
        recipes=recipes,
        schedule=meal_schedule,
        target_calories=target_calories,
        preferred_recipe_ids=current_recipe_ids,
        avoid_recipe_base_ids=avoid_recipe_base_ids or set(),
    )
    if not candidate_lists or any(not group for group in candidate_lists):
        return None, [], "Недостаточно рецептов для восстановления расписания."

    day_number = int(normalized_plan["day_number"])
    current_meals_by_type = {meal["type"]: meal for meal in normalized_plan.get("meals", [])}
    preferred_ids_by_slot = {
        slot["type"]: str(meal["recipe_id"])
        for slot in meal_schedule
        if (meal := current_meals_by_type.get(slot["type"])) is not None
    }

    best_plan: dict[str, Any] | None = None
    best_error: str | None = None
    best_score: tuple[float, float] | None = None

    for combination in product(*candidate_lists):
        recipe_ids = [str(recipe["id"]) for recipe in combination]
        if len(recipe_ids) != len(set(recipe_ids)):
            continue

        candidate_day = _build_day_plan(
            day_number=day_number,
            schedule=meal_schedule,
            chosen_recipes=list(combination),
        )
        is_valid, error = _validate(
            candidate_day,
            target_calories=target_calories,
            meal_schedule=meal_schedule,
        )
        changed_slots = sum(
            1
            for slot, recipe in zip(meal_schedule, combination, strict=False)
            if preferred_ids_by_slot.get(slot["type"]) != str(recipe["id"])
        )
        repeated_base_recipes = sum(
            1
            for recipe in combination
            if _recipe_base_id(recipe) in (avoid_recipe_base_ids or set())
        )
        deviation = abs(float(candidate_day["total_calories"]) - float(target_calories))
        score = (
            0.0 if is_valid else 1.0,
            repeated_base_recipes,
            changed_slots + deviation / 1000.0,
        )

        if best_score is None or score < best_score:
            best_plan = candidate_day
            best_score = score
            best_error = error
            if is_valid:
                break

    if best_plan is None:
        return None, [], "Не удалось подобрать неповторяющуюся комбинацию рецептов."

    final_valid, final_error = _validate(
        best_plan,
        target_calories=target_calories,
        meal_schedule=meal_schedule,
    )
    if not final_valid:
        return None, [], final_error or best_error or "Auto-fix не смог восстановить план."

    original_meals = {
        meal["type"]: str(meal["recipe_id"])
        for meal in normalized_plan.get("meals", [])
    }
    applied_fixes = [
        (
            f"{slot['type']}: {original_meals.get(slot['type'], 'missing')} -> "
            f"{meal['recipe_id']}"
        )
        for slot, meal in zip(meal_schedule, best_plan["meals"], strict=False)
        if original_meals.get(slot["type"]) != str(meal["recipe_id"])
    ]
    if normalized_plan["total_calories"] != best_plan["total_calories"]:
        applied_fixes.append(
            f"totals: {normalized_plan['total_calories']:.0f} -> {best_plan['total_calories']:.0f} kcal"
        )
    if avoid_recipe_base_ids:
        reused = [
            meal["title"]
            for meal in best_plan["meals"]
            if _meal_base_id(meal) in avoid_recipe_base_ids
        ]
        if reused:
            applied_fixes.append(
                f"repeat-aware fallback kept: {', '.join(reused)}"
            )

    return best_plan, applied_fixes, None
