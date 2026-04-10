"""Unit-тесты demo pipeline для Sprint 4."""

import os

os.environ["DEBUG"] = "true"

from app.core.demo_pipeline import (
    _candidate_lists,
    _find_plan_combination,
    _plan_signature,
    _recipe_matches_slot,
    _resolve_demo_target_calories,
)


def _schedule():
    return [
        {"type": "breakfast", "time": "08:00", "calories_pct": 25},
        {"type": "lunch", "time": "13:00", "calories_pct": 35},
        {"type": "dinner", "time": "19:00", "calories_pct": 30},
        {"type": "snack", "time": "16:00", "calories_pct": 10},
    ]


def _recipe(recipe_id: str, title: str, meal_type: str, calories: int) -> dict:
    return {
        "id": recipe_id,
        "title": title,
        "meal_type": meal_type,
        "calories": float(calories),
        "protein": 10.0,
        "fat": 10.0,
        "carbs": 10.0,
        "ingredients": [],
    }


def test_recipe_matches_slot_uses_strict_breakfast_rules():
    assert _recipe_matches_slot(_recipe("bf", "Omelette", "breakfast", 350), "breakfast") is True
    assert _recipe_matches_slot(_recipe("ln", "Pilaf", "lunch", 580), "breakfast") is False
    assert _recipe_matches_slot(_recipe("ld", "Pasta", "lunch/dinner", 560), "breakfast") is False
    assert _recipe_matches_slot(_recipe("un", "Universal", "universal", 400), "breakfast") is False


def test_candidate_lists_do_not_fallback_to_full_catalog_for_breakfast():
    recipes = [
        _recipe("ln1", "Pilaf", "lunch", 580),
        _recipe("dn1", "Steak", "dinner", 540),
        _recipe("sn1", "Yogurt", "snack", 280),
    ]

    candidates = _candidate_lists(recipes, _schedule(), target_calories=2200, max_candidates_per_slot=4)

    assert candidates[0] == []
    assert [recipe["title"] for recipe in candidates[1]] == ["Pilaf"]
    assert [recipe["title"] for recipe in candidates[2]] == ["Steak"]
    assert [recipe["title"] for recipe in candidates[3]] == ["Yogurt"]


def test_find_plan_combination_returns_error_when_slot_has_no_matching_recipes():
    recipes = [
        _recipe("ln1", "Pilaf", "lunch", 580),
        _recipe("dn1", "Steak", "dinner", 540),
        _recipe("sn1", "Yogurt", "snack", 280),
    ]

    day_plan, error = _find_plan_combination(
        recipes=recipes,
        schedule=_schedule(),
        target_calories=2200,
        day_number=1,
        max_candidates_per_slot=4,
    )

    assert day_plan is None
    assert error == "Недостаточно рецептов для всех слотов расписания."


def test_resolve_demo_target_calories_caps_target_to_really_achievable_day():
    recipes = [
        _recipe("bf1", "Pancakes", "breakfast", 450),
        _recipe("bf2", "Porridge", "breakfast", 350),
        _recipe("ln1", "Pasta", "lunch", 620),
        _recipe("ln2", "Pilaf", "lunch", 580),
        _recipe("dn1", "Steak", "dinner", 560),
        _recipe("dn2", "Fish", "dinner", 500),
        _recipe("sn1", "Yogurt", "snack", 280),
        _recipe("sn2", "Smoothie", "snack", 250),
    ]

    adjusted_target, message = _resolve_demo_target_calories(2633, recipes, _schedule())

    assert adjusted_target == 1910
    assert message is not None
    assert "2633" in message
    assert "1910" in message


def test_find_plan_combination_respects_blocked_signatures():
    recipes = [
        _recipe("bf1", "Pancakes", "breakfast", 450),
        _recipe("bf2", "Porridge", "breakfast", 350),
        _recipe("ln1", "Pasta", "lunch", 620),
        _recipe("ln2", "Pilaf", "lunch", 580),
        _recipe("dn1", "Steak", "dinner", 560),
        _recipe("dn2", "Fish", "dinner", 500),
        _recipe("sn1", "Yogurt", "snack", 280),
        _recipe("sn2", "Smoothie", "snack", 250),
    ]

    first_day, first_error = _find_plan_combination(
        recipes=recipes,
        schedule=_schedule(),
        target_calories=1910,
        day_number=1,
    )
    assert first_day is not None
    assert first_error is None

    second_day, _ = _find_plan_combination(
        recipes=recipes,
        schedule=_schedule(),
        target_calories=1910,
        day_number=2,
        blocked_signatures={_plan_signature(first_day)},
    )
    assert second_day is not None
    assert _plan_signature(second_day) != _plan_signature(first_day)
