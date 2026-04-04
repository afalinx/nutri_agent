from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.db.models import ActivityLevel, Gender, Goal


class MealSlot(BaseModel):
    """Один слот расписания: тип приёма, время, % калорий."""

    type: str = Field(description="breakfast, lunch, dinner, snack, second_snack")
    time: str = Field(pattern=r"^\d{2}:\d{2}$", description="HH:MM")
    calories_pct: int = Field(ge=5, le=50)


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    age: int = Field(ge=10, le=120)
    weight_kg: float = Field(gt=20, le=300)
    height_cm: float = Field(gt=80, le=260)
    gender: Gender
    activity_level: ActivityLevel
    goal: Goal
    allergies: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    disliked_ingredients: list[str] = Field(default_factory=list)
    diseases: list[str] = Field(default_factory=list)
    meal_schedule: list[MealSlot] | None = None

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.meal_schedule is not None:
            total = sum(s.calories_pct for s in self.meal_schedule)
            if total != 100:
                msg = f"Сумма calories_pct должна быть 100, получено {total}"
                raise ValueError(msg)
        return self


class UserUpdate(BaseModel):
    age: int | None = Field(default=None, ge=10, le=120)
    weight_kg: float | None = Field(default=None, gt=20, le=300)
    height_cm: float | None = Field(default=None, gt=80, le=260)
    gender: Gender | None = None
    activity_level: ActivityLevel | None = None
    goal: Goal | None = None
    allergies: list[str] | None = None
    preferences: list[str] | None = None
    disliked_ingredients: list[str] | None = None
    diseases: list[str] | None = None
    meal_schedule: list[MealSlot] | None = None

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.meal_schedule is not None:
            total = sum(s.calories_pct for s in self.meal_schedule)
            if total != 100:
                msg = f"Сумма calories_pct должна быть 100, получено {total}"
                raise ValueError(msg)
        return self


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    age: int
    weight_kg: float
    height_cm: float
    gender: Gender
    activity_level: ActivityLevel
    goal: Goal
    allergies: list[str]
    preferences: list[str]
    disliked_ingredients: list[str]
    diseases: list[str]
    target_calories: int | None
    meal_schedule: list[MealSlot] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
