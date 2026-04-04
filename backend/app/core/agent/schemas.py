"""Pydantic-схемы для Structured Output от LLM."""

from __future__ import annotations

from pydantic import BaseModel, Field


class IngredientSummary(BaseModel):
    name: str
    amount: float = Field(ge=0)
    unit: str


class MealItem(BaseModel):
    """Схема приёма пищи, которую возвращает LLM.

    НЕ содержит ingredients_summary — ингредиенты подставляются post-hoc
    из данных рецепта, чтобы экономить выходные токены LLM.
    """

    type: str = Field(description="breakfast, lunch, dinner, snack, second_snack")
    time: str = Field(description="HH:MM — время приёма пищи")
    recipe_id: str = Field(description="UUID рецепта из базы")
    title: str
    calories: float = Field(ge=0)
    protein: float = Field(ge=0)
    fat: float = Field(ge=0)
    carbs: float = Field(ge=0)


class MealItemFull(MealItem):
    """Расширенная схема для API-ответа — с ингредиентами из БД."""

    ingredients_summary: list[IngredientSummary] = Field(default_factory=list)


class DayPlan(BaseModel):
    day_number: int = Field(ge=1)
    total_calories: float = Field(ge=0)
    total_protein: float = Field(ge=0)
    total_fat: float = Field(ge=0)
    total_carbs: float = Field(ge=0)
    meals: list[MealItem] = Field(min_length=1)


class DayPlanFull(BaseModel):
    """DayPlan с полными данными ингредиентов для сохранения и API."""

    day_number: int = Field(ge=1)
    total_calories: float = Field(ge=0)
    total_protein: float = Field(ge=0)
    total_fat: float = Field(ge=0)
    total_carbs: float = Field(ge=0)
    meals: list[MealItemFull] = Field(min_length=1)


class MealPlanOutput(BaseModel):
    """Схема, которую LLM должна вернуть."""

    daily_target_calories: int = Field(gt=0)
    day: DayPlan
