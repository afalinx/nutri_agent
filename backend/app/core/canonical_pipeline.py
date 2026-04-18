"""Shared helpers for the canonical meal generation pipeline."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.core.rag.retriever import search_recipes
from app.core.recipe_catalog import RecipeCatalogError, scale_recipe_payload
from app.db.models import DEFAULT_MEAL_SCHEDULE, MealPlan, MealPlanStatus, User

_SCALING_FACTORS = (1.25, 1.5, 2.0)


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


def _augment_recipes_with_scaled_variants(
    recipes: list[dict[str, Any]],
    *,
    user_profile: dict[str, Any],
) -> list[dict[str, Any]]:
    schedule = user_profile.get("meal_schedule") or DEFAULT_MEAL_SCHEDULE
    slot_targets = {
        slot["type"]: float(user_profile.get("target_calories") or 0) * slot["calories_pct"] / 100
        for slot in schedule
    }
    augmented: list[dict[str, Any]] = list(recipes)
    seen_ids = {str(recipe["id"]) for recipe in recipes}

    for recipe in recipes:
        recipe_id = str(recipe["id"])
        recipe_types = _normalize_meal_type(recipe.get("meal_type"))
        if not recipe_types:
            continue

        relevant_slot_targets = [
            slot_targets[slot["type"]]
            for slot in schedule
            if recipe_types & _slot_compatible_types(slot["type"])
        ]
        if not relevant_slot_targets:
            continue
        highest_target = max(relevant_slot_targets)
        base_calories = float(recipe.get("calories") or 0)
        if base_calories <= 0:
            continue

        for factor in _SCALING_FACTORS:
            if base_calories * factor < highest_target * 0.85:
                continue
            try:
                scaled = scale_recipe_payload(recipe, factor=factor)
            except RecipeCatalogError:
                continue
            scaled_id = f"{recipe_id}::x{factor:.2f}"
            if scaled_id in seen_ids:
                continue
            scaled["id"] = scaled_id
            scaled["base_recipe_id"] = recipe_id
            scaled["portion_factor"] = factor
            scaled["title"] = f"{recipe['title']} x{factor:.2f}"
            augmented.append(scaled)
            seen_ids.add(scaled_id)

    return augmented


def select_recipes_for_generation(
    recipes: list[dict[str, Any]],
    *,
    user_profile: dict[str, Any],
    limit: int,
) -> list[dict[str, Any]]:
    """Build a context set that preserves slot coverage and calorie reachability.

    `search_recipes` already applies safety filters and soft preference ranking.
    Here we reshape the final context so the model sees:
    - enough recipes per slot
    - high-calorie candidates when target is high
    - original preferred ordering as a fallback fill strategy
    """
    if len(recipes) <= limit:
        return recipes

    schedule = user_profile.get("meal_schedule") or DEFAULT_MEAL_SCHEDULE
    target_calories = int(user_profile.get("target_calories") or 0)
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    def add_recipe(recipe: dict[str, Any]) -> None:
        recipe_id = str(recipe["id"])
        if recipe_id in selected_ids or len(selected) >= limit:
            return
        selected.append(recipe)
        selected_ids.add(recipe_id)

    for slot in schedule:
        slot_target = target_calories * slot["calories_pct"] / 100
        matched = [recipe for recipe in recipes if _recipe_matches_slot(recipe, slot["type"])]
        ranked = sorted(
            matched,
            key=lambda recipe: (
                abs(float(recipe["calories"]) - slot_target),
                -float(recipe["calories"]),
                recipe["title"],
            ),
        )
        strongest = sorted(
            matched,
            key=lambda recipe: (-float(recipe["calories"]), recipe["title"]),
        )
        if ranked:
            add_recipe(ranked[0])
        if strongest:
            add_recipe(strongest[0])
    for slot in schedule:
        slot_target = target_calories * slot["calories_pct"] / 100
        matched = [recipe for recipe in recipes if _recipe_matches_slot(recipe, slot["type"])]
        ranked = sorted(
            matched,
            key=lambda recipe: (
                abs(float(recipe["calories"]) - slot_target),
                -float(recipe["calories"]),
                recipe["title"],
            ),
        )
        strongest = sorted(
            matched,
            key=lambda recipe: (-float(recipe["calories"]), recipe["title"]),
        )
        for recipe in ranked[:3]:
            add_recipe(recipe)
        for recipe in strongest[:2]:
            add_recipe(recipe)

    for recipe in recipes:
        add_recipe(recipe)

    return selected[:limit]


def assess_recipe_pool(
    recipes: list[dict[str, Any]],
    *,
    user_profile: dict[str, Any],
) -> dict[str, Any]:
    """Check whether the current recipe pool can satisfy the user's schedule/target."""
    schedule = user_profile.get("meal_schedule") or DEFAULT_MEAL_SCHEDULE
    target_calories = int(user_profile.get("target_calories") or 0)
    slot_counts: dict[str, int] = {}
    max_achievable = 0.0

    for slot in schedule:
        matched = [recipe for recipe in recipes if _recipe_matches_slot(recipe, slot["type"])]
        slot_counts[slot["type"]] = len(matched)
        if matched:
            max_achievable += max(float(recipe["calories"]) for recipe in matched)

    feasible = all(count > 0 for count in slot_counts.values()) and (
        target_calories <= 0 or max_achievable >= target_calories * 0.95
    )
    return {
        "slot_counts": slot_counts,
        "max_achievable_calories": round(max_achievable, 1),
        "target_calories": target_calories,
        "feasible": feasible,
    }


async def load_user_profile(session: AsyncSession, user_id: str) -> dict:
    """Load a user profile from cache or database in a canonical shape."""
    cached = await cache.get_json(f"user:{user_id}")
    if cached:
        if "id" not in cached:
            cached["id"] = user_id
            await cache.set_json(f"user:{user_id}", cached, ttl=600)
        return cached

    result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError(f"User {user_id} not found")

    profile = {
        "id": str(user.id),
        "email": user.email,
        "gender": user.gender.value,
        "age": user.age,
        "weight_kg": user.weight_kg,
        "height_cm": user.height_cm,
        "goal": user.goal.value,
        "target_calories": user.target_calories,
        "allergies": user.allergies or [],
        "preferences": user.preferences or [],
        "disliked_ingredients": user.disliked_ingredients or [],
        "diseases": user.diseases or [],
        "meal_schedule": user.meal_schedule or DEFAULT_MEAL_SCHEDULE,
    }
    await cache.set_json(f"user:{user_id}", profile, ttl=600)
    return profile


async def load_candidate_recipes(
    session: AsyncSession,
    user_profile: dict,
    *,
    limit: int = 30,
) -> list[dict]:
    """Load candidate recipes for a user profile using the canonical filters."""
    raw_recipes = await search_recipes(
        session,
        allergies=user_profile.get("allergies"),
        dislikes=user_profile.get("disliked_ingredients"),
        preferred_tags=user_profile.get("preferences"),
        diseases=user_profile.get("diseases"),
        limit=max(limit * 3, limit),
    )
    candidate_pool = _augment_recipes_with_scaled_variants(
        raw_recipes,
        user_profile=user_profile,
    )
    return select_recipes_for_generation(
        candidate_pool,
        user_profile=user_profile,
        limit=limit,
    )


async def create_plan_record(
    session: AsyncSession,
    *,
    user_id: str,
    days: int,
    status: MealPlanStatus = MealPlanStatus.generating,
) -> MealPlan:
    """Create an empty plan record before generation begins."""
    plan_record = MealPlan(
        user_id=uuid.UUID(user_id),
        status=status,
        start_date=date.today(),
        end_date=date.today() + timedelta(days=days - 1),
    )
    session.add(plan_record)
    await session.commit()
    await session.refresh(plan_record)
    return plan_record


async def finalize_plan_record(
    session: AsyncSession,
    *,
    plan_record: MealPlan,
    plan_data: dict,
    status: MealPlanStatus,
) -> None:
    """Persist generated plan data and cache it when ready."""
    plan_record.plan_data = plan_data
    plan_record.status = status
    await session.commit()

    if status == MealPlanStatus.ready:
        await cache.set_json(f"plan:{plan_record.id}", plan_data, ttl=3600)
