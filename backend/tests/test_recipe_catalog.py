"""Tests for recipe catalog normalization and portion scaling guardrails."""

import pytest

from app.core.recipe_catalog import RecipeCatalogError, normalize_recipe_payload, scale_recipe_payload


def test_normalize_recipe_payload_builds_ingredients_short_and_normalizes_lists():
    payload = {
        "title": "  Chicken   Rice Bowl  ",
        "description": "Simple meal",
        "ingredients": [
            {"name": "Chicken breast", "amount": 200, "unit": "g"},
            {"name": "Rice", "amount": 180, "unit": "g"},
        ],
        "calories": 520,
        "protein": 45,
        "fat": 6,
        "carbs": 70,
        "tags": ["High Protein", "High Protein", "Quick"],
        "allergens": ["Milk", "milk"],
        "meal_type": "Lunch",
    }

    normalized = normalize_recipe_payload(payload)

    assert normalized["title"] == "Chicken Rice Bowl"
    assert normalized["meal_type"] == "lunch"
    assert normalized["tags"] == ["high protein", "quick"]
    assert normalized["allergens"] == ["milk"]
    assert normalized["ingredients_short"] == "Chicken breast, Rice"


def test_normalize_recipe_payload_rejects_banned_or_absurd_ingredient():
    payload = {
        "title": "Weird soup",
        "ingredients": [
            {"name": "penis кита", "amount": 1, "unit": "piece"},
        ],
        "calories": 100,
        "protein": 10,
        "fat": 2,
        "carbs": 5,
    }

    with pytest.raises(RecipeCatalogError, match="Banned ingredient term"):
        normalize_recipe_payload(payload)


def test_normalize_recipe_payload_accepts_russian_piece_unit_alias():
    payload = {
        "title": "Омлет",
        "ingredients": [
            {"name": "Яйцо", "amount": 2, "unit": "шт"},
            {"name": "Молоко", "amount": 50, "unit": "ml"},
        ],
        "calories": 220,
        "protein": 16,
        "fat": 15,
        "carbs": 3,
        "meal_type": "breakfast",
    }

    normalized = normalize_recipe_payload(payload)

    assert normalized["ingredients"][0]["unit"] == "piece"


def test_normalize_recipe_payload_maps_dessert_meal_type_to_snack():
    payload = {
        "title": "Брауни",
        "ingredients": [
            {"name": "Шоколад", "amount": 100, "unit": "g"},
            {"name": "Мука", "amount": 80, "unit": "g"},
        ],
        "calories": 676,
        "protein": 10,
        "fat": 46,
        "carbs": 55,
        "meal_type": "dessert",
    }

    normalized = normalize_recipe_payload(payload)

    assert normalized["meal_type"] == "snack"


def test_normalize_recipe_payload_rejects_unsafe_dairy_with_pickles():
    payload = {
        "title": "Окрошка на молоке",
        "ingredients": [
            {"name": "Молоко", "amount": 500, "unit": "ml"},
            {"name": "Огурцы солёные", "amount": 150, "unit": "g"},
            {"name": "Колбаса докторская", "amount": 200, "unit": "g"},
        ],
        "calories": 620,
        "protein": 28,
        "fat": 42,
        "carbs": 24,
        "meal_type": "lunch",
    }

    with pytest.raises(RecipeCatalogError, match="Unsafe ingredient combination"):
        normalize_recipe_payload(payload)


def test_normalize_recipe_payload_rejects_implausible_pairing():
    payload = {
        "title": "Шпроты с шоколадом",
        "ingredients": [
            {"name": "Шпроты", "amount": 120, "unit": "g"},
            {"name": "Шоколад", "amount": 40, "unit": "g"},
        ],
        "calories": 540,
        "protein": 22,
        "fat": 42,
        "carbs": 18,
        "meal_type": "snack",
    }

    with pytest.raises(RecipeCatalogError, match="Implausible ingredient combination"):
        normalize_recipe_payload(payload)


def test_scale_recipe_payload_rejects_absurd_scaled_portion():
    recipe = normalize_recipe_payload(
        {
            "title": "Cabbage stew",
            "ingredients": [
                {"name": "Cabbage", "amount": 1200, "unit": "g"},
                {"name": "Chicken", "amount": 300, "unit": "g"},
            ],
            "calories": 700,
            "protein": 55,
            "fat": 20,
            "carbs": 40,
            "meal_type": "dinner",
        }
    )

    with pytest.raises(RecipeCatalogError, match="Recipe portion mass is unrealistic"):
        scale_recipe_payload(recipe, factor=2.0)


def test_scale_recipe_payload_scales_within_guardrails():
    recipe = normalize_recipe_payload(
        {
            "title": "Chicken bowl",
            "ingredients": [
                {"name": "Chicken", "amount": 200, "unit": "g"},
                {"name": "Rice", "amount": 150, "unit": "g"},
            ],
            "calories": 520,
            "protein": 45,
            "fat": 6,
            "carbs": 70,
            "meal_type": "lunch",
        }
    )

    scaled = scale_recipe_payload(recipe, factor=1.5)

    assert scaled["calories"] == 780.0
    assert scaled["protein"] == 67.5
    assert scaled["ingredients"][0]["amount"] == 300.0
