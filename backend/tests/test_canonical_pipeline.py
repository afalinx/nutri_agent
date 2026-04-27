"""Tests for canonical pipeline recipe selection and scaling."""

from __future__ import annotations

import pytest

from app.core import canonical_pipeline


@pytest.mark.asyncio
async def test_load_candidate_recipes_adds_scaled_variants_for_high_targets(monkeypatch):
    async def fake_search_recipes(session, **kwargs):
        return [
            {
                "id": "breakfast-1",
                "title": "Breakfast Base",
                "description": "",
                "ingredients": [{"name": "Oats", "amount": 100, "unit": "g"}],
                "calories": 350,
                "protein": 15,
                "fat": 8,
                "carbs": 55,
                "tags": [],
                "meal_type": "breakfast",
                "allergens": [],
                "ingredients_short": "Oats",
                "prep_time_min": 10,
                "category": "Breakfast",
            },
            {
                "id": "lunch-1",
                "title": "Lunch Base",
                "description": "",
                "ingredients": [{"name": "Rice", "amount": 200, "unit": "g"}],
                "calories": 700,
                "protein": 30,
                "fat": 15,
                "carbs": 95,
                "tags": [],
                "meal_type": "lunch",
                "allergens": [],
                "ingredients_short": "Rice",
                "prep_time_min": 20,
                "category": "Lunch",
            },
        ]

    monkeypatch.setattr(canonical_pipeline, "search_recipes", fake_search_recipes)

    user_profile = {
        "target_calories": 2600,
        "meal_schedule": [
            {"type": "breakfast", "time": "08:00", "calories_pct": 25},
            {"type": "lunch", "time": "13:00", "calories_pct": 75},
        ],
        "allergies": [],
        "disliked_ingredients": [],
        "preferences": [],
        "diseases": [],
    }

    recipes = await canonical_pipeline.load_candidate_recipes(
        session=None,
        user_profile=user_profile,
        limit=10,
    )

    ids = {str(recipe["id"]) for recipe in recipes}
    assert any("::x" in recipe_id for recipe_id in ids)


def test_assess_recipe_pool_uses_scaled_variants_when_present():
    user_profile = {
        "target_calories": 2600,
        "meal_schedule": [
            {"type": "breakfast", "time": "08:00", "calories_pct": 25},
            {"type": "lunch", "time": "13:00", "calories_pct": 35},
            {"type": "dinner", "time": "19:00", "calories_pct": 30},
            {"type": "snack", "time": "16:00", "calories_pct": 10},
        ],
    }
    recipes = [
        {"id": "b1", "title": "B", "meal_type": "breakfast", "calories": 500},
        {"id": "b1::x1.50", "title": "B x1.50", "meal_type": "breakfast", "calories": 750},
        {"id": "l1", "title": "L", "meal_type": "lunch", "calories": 700},
        {"id": "l1::x1.50", "title": "L x1.50", "meal_type": "lunch", "calories": 1050},
        {"id": "d1", "title": "D", "meal_type": "dinner", "calories": 650},
        {"id": "d1::x1.50", "title": "D x1.50", "meal_type": "dinner", "calories": 975},
        {"id": "s1", "title": "S", "meal_type": "snack", "calories": 220},
    ]

    diagnostics = canonical_pipeline.assess_recipe_pool(recipes, user_profile=user_profile)

    assert diagnostics["feasible"] is True
    assert diagnostics["max_achievable_calories"] >= 2600 * 0.95
