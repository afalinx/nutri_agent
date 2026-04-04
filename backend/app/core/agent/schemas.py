"""Pydantic-схемы для Structured Output от LLM."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class IngredientSummary(BaseModel):
    name: str
    amount: float = Field(ge=0)
    unit: str


class MealItem(BaseModel):
    type: Literal["breakfast", "lunch", "dinner", "snack"]
    recipe_id: str = Field(description="UUID рецепта из базы")
    title: str
    calories: float = Field(ge=0)
    protein: float = Field(ge=0)
    fat: float = Field(ge=0)
    carbs: float = Field(ge=0)
    ingredients_summary: list[IngredientSummary]


class DayPlan(BaseModel):
    day_number: int = Field(ge=1)
    total_calories: float = Field(ge=0)
    total_protein: float = Field(ge=0)
    total_fat: float = Field(ge=0)
    total_carbs: float = Field(ge=0)
    meals: list[MealItem] = Field(min_length=1)


class MealPlanOutput(BaseModel):
    """Схема, которую LLM должна вернуть."""

    daily_target_calories: int = Field(gt=0)
    day: DayPlan
