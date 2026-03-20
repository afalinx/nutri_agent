"""Pydantic-схемы для Structured Output от LLM."""

from __future__ import annotations

import uuid
from pydantic import BaseModel, Field


class IngredientSummary(BaseModel):
    name: str
    amount: float
    unit: str


class MealItem(BaseModel):
    type: str = Field(description="breakfast / lunch / dinner / snack")
    recipe_id: str = Field(description="UUID рецепта из базы")
    title: str
    calories: float
    protein: float
    fat: float
    carbs: float
    ingredients_summary: list[IngredientSummary]


class DayPlan(BaseModel):
    day_number: int
    total_calories: float
    total_protein: float
    total_fat: float
    total_carbs: float
    meals: list[MealItem]


class MealPlanOutput(BaseModel):
    """Схема, которую LLM должна вернуть."""
    daily_target_calories: int
    day: DayPlan
