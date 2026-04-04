import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.base import Base

DEFAULT_MEAL_SCHEDULE = [
    {"type": "breakfast", "time": "08:00", "calories_pct": 25},
    {"type": "lunch", "time": "13:00", "calories_pct": 35},
    {"type": "dinner", "time": "19:00", "calories_pct": 30},
    {"type": "snack", "time": "16:00", "calories_pct": 10},
]


class Gender(str, enum.Enum):
    male = "male"
    female = "female"


class ActivityLevel(str, enum.Enum):
    sedentary = "sedentary"
    light = "light"
    moderate = "moderate"
    active = "active"
    very_active = "very_active"


class Goal(str, enum.Enum):
    lose = "lose"
    maintain = "maintain"
    gain = "gain"


class MealPlanStatus(str, enum.Enum):
    pending = "PENDING"
    generating = "GENERATING"
    ready = "READY"
    failed = "FAILED"


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)

    age = Column(Integer, nullable=False)
    weight_kg = Column(Float, nullable=False)
    height_cm = Column(Float, nullable=False)
    gender = Column(Enum(Gender), nullable=False)
    activity_level = Column(Enum(ActivityLevel), nullable=False)
    goal = Column(Enum(Goal), nullable=False)

    allergies = Column(JSONB, default=list)
    preferences = Column(JSONB, default=list)
    disliked_ingredients = Column(JSONB, default=list)
    diseases = Column(JSONB, default=list)
    target_calories = Column(Integer, nullable=True)
    meal_schedule = Column(JSONB, default=lambda: DEFAULT_MEAL_SCHEDULE)

    created_at = Column(DateTime, default=datetime.utcnow)

    meal_plans = relationship("MealPlan", back_populates="user")


class Recipe(Base):
    __tablename__ = "recipes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    ingredients = Column(JSONB, nullable=False)

    calories = Column(Float, nullable=False)
    protein = Column(Float, nullable=False)
    fat = Column(Float, nullable=False)
    carbs = Column(Float, nullable=False)

    embedding = Column(Vector(1536), nullable=True)
    tags = Column(ARRAY(String), default=list)

    meal_type = Column(String(50), nullable=True)
    allergens = Column(ARRAY(String), default=list)
    ingredients_short = Column(String(500), nullable=True)
    prep_time_min = Column(Integer, nullable=True)
    category = Column(String(100), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


class MealPlan(Base):
    __tablename__ = "meal_plans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    status = Column(Enum(MealPlanStatus), default=MealPlanStatus.pending, nullable=False)

    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    plan_data = Column(JSONB, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="meal_plans")
