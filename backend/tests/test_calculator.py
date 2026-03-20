"""Unit-тесты для Calculator Skill (задача 1.7)."""

import pytest

from app.core.skills.calculator import (
    calculate_bmr,
    calculate_target_calories,
    validate_meal_calories,
)
from app.db.models import ActivityLevel, Gender, Goal


class TestCalculateBMR:
    def test_male_standard(self):
        # 10*80 + 6.25*180 - 5*25 + 5 = 800 + 1125 - 125 + 5 = 1805
        bmr = calculate_bmr(weight_kg=80, height_cm=180, age=25, gender=Gender.male)
        assert bmr == 1805.0

    def test_female_standard(self):
        # 10*60 + 6.25*165 - 5*30 - 161 = 600 + 1031.25 - 150 - 161 = 1320.25
        bmr = calculate_bmr(weight_kg=60, height_cm=165, age=30, gender=Gender.female)
        assert bmr == 1320.25


class TestCalculateTargetCalories:
    def test_male_moderate_maintain(self):
        """Мужчина, 25 лет, 80 кг, 180 см, moderate, maintain → ~2798."""
        cal = calculate_target_calories(
            weight_kg=80,
            height_cm=180,
            age=25,
            gender=Gender.male,
            activity_level=ActivityLevel.moderate,
            goal=Goal.maintain,
        )
        assert 2700 <= cal <= 2900

    def test_female_sedentary_lose(self):
        """Женщина, 30 лет, 60 кг, 165 см, sedentary, lose."""
        cal = calculate_target_calories(
            weight_kg=60,
            height_cm=165,
            age=30,
            gender=Gender.female,
            activity_level=ActivityLevel.sedentary,
            goal=Goal.lose,
        )
        assert 1200 <= cal <= 1500

    def test_male_active_gain(self):
        """Мужчина, 20 лет, 75 кг, 175 см, active, gain."""
        cal = calculate_target_calories(
            weight_kg=75,
            height_cm=175,
            age=20,
            gender=Gender.male,
            activity_level=ActivityLevel.active,
            goal=Goal.gain,
        )
        assert 3200 <= cal <= 3700

    def test_returns_integer(self):
        cal = calculate_target_calories(
            weight_kg=70,
            height_cm=170,
            age=25,
            gender=Gender.male,
            activity_level=ActivityLevel.light,
            goal=Goal.maintain,
        )
        assert isinstance(cal, int)


class TestValidateMealCalories:
    def test_valid_within_tolerance(self):
        ingredients = [
            {"name": "Овсянка", "calories": 200},
            {"name": "Ягоды", "calories": 50},
        ]
        is_valid, actual = validate_meal_calories(ingredients, declared_calories=250)
        assert is_valid is True
        assert actual == 250

    def test_invalid_exceeds_tolerance(self):
        ingredients = [
            {"name": "Овсянка", "calories": 200},
            {"name": "Ягоды", "calories": 50},
        ]
        is_valid, actual = validate_meal_calories(ingredients, declared_calories=400)
        assert is_valid is False
        assert actual == 250

    def test_empty_ingredients_passes(self):
        is_valid, _ = validate_meal_calories([], declared_calories=500)
        assert is_valid is True
