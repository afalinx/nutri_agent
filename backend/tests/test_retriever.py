"""Тесты retriever cache recovery."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ["DEBUG"] = "true"

import pytest

from app.core.rag import retriever
from app.core.canonical_pipeline import assess_recipe_pool, select_recipes_for_generation


def test_infer_meal_type_from_tags_for_cached_recipe():
    recipe = {
        "title": "Овсяная каша с ягодами",
        "tags": ["завтрак", "быстро"],
        "meal_type": None,
    }

    normalized = retriever._normalize_cached_recipe(recipe)

    assert normalized["meal_type"] == "breakfast"


@pytest.mark.asyncio
async def test_get_all_recipes_normalizes_cache_without_rebuild_when_possible(monkeypatch):
    stale_cache = [{"title": "Паста", "tags": [], "meal_type": None}]

    get_json = AsyncMock(return_value=stale_cache)
    delete = AsyncMock()
    load_all = AsyncMock()

    monkeypatch.setattr(retriever.cache, "get_json", get_json)
    monkeypatch.setattr(retriever.cache, "delete", delete)
    monkeypatch.setattr(retriever, "_load_all_recipes", load_all)

    result = await retriever._get_all_recipes(SimpleNamespace())

    assert result == [{"title": "Паста", "tags": [], "meal_type": "universal"}]
    delete.assert_not_awaited()
    load_all.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_recipes_keeps_preferred_first_but_preserves_safe_fallback(monkeypatch):
    recipes = [
        {
            "id": "1",
            "title": "Protein Lunch",
            "tags": ["высокобелковый"],
            "allergens": [],
            "ingredients_short": "",
        },
        {
            "id": "2",
            "title": "Safe Breakfast",
            "tags": ["завтрак"],
            "allergens": [],
            "ingredients_short": "",
        },
        {
            "id": "3",
            "title": "Safe Snack",
            "tags": ["перекус"],
            "allergens": [],
            "ingredients_short": "",
        },
    ]

    monkeypatch.setattr(retriever, "_get_all_recipes", AsyncMock(return_value=recipes))

    result = await retriever.search_recipes(
        SimpleNamespace(),
        preferred_tags=["высокобелковый"],
        limit=3,
    )

    assert [recipe["id"] for recipe in result] == ["1", "2", "3"]


def test_select_recipes_for_generation_preserves_slot_coverage_and_high_calorie_candidates():
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
        {"id": "b1", "title": "Breakfast 1", "meal_type": "breakfast", "calories": 300},
        {"id": "b2", "title": "Breakfast 2", "meal_type": "breakfast", "calories": 450},
        {"id": "l1", "title": "Lunch 1", "meal_type": "lunch", "calories": 400},
        {"id": "l2", "title": "Lunch 2", "meal_type": "lunch", "calories": 700},
        {"id": "d1", "title": "Dinner 1", "meal_type": "dinner", "calories": 350},
        {"id": "d2", "title": "Dinner 2", "meal_type": "dinner", "calories": 650},
        {"id": "s1", "title": "Snack 1", "meal_type": "snack", "calories": 120},
        {"id": "s2", "title": "Snack 2", "meal_type": "snack", "calories": 260},
    ]

    selected = select_recipes_for_generation(recipes, user_profile=user_profile, limit=6)
    diagnostics = assess_recipe_pool(selected, user_profile=user_profile)

    assert all(count >= 1 for count in diagnostics["slot_counts"].values())
    assert diagnostics["max_achievable_calories"] >= 2060
    assert any(recipe["id"] == "l2" for recipe in selected)
    assert any(recipe["id"] == "d2" for recipe in selected)
    assert any(recipe["id"] == "s2" for recipe in selected)
