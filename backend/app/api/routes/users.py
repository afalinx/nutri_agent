import uuid

import bcrypt as _bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import UserCreate, UserResponse, UserUpdate
from app.core import cache
from app.core.skills.calculator import calculate_target_calories
from app.db.models import DEFAULT_MEAL_SCHEDULE, User
from app.db.session import get_db

router = APIRouter(prefix="/api/users", tags=["Users"])


def _normalize_profile_lists(user: User) -> User:
    user.allergies = user.allergies or []
    user.preferences = user.preferences or []
    user.disliked_ingredients = user.disliked_ingredients or []
    user.diseases = user.diseases or []
    if user.meal_schedule is None:
        user.meal_schedule = DEFAULT_MEAL_SCHEDULE
    return user


def _build_profile_cache(user: User) -> dict:
    return {
        "gender": user.gender.value,
        "age": user.age,
        "weight_kg": user.weight_kg,
        "height_cm": user.height_cm,
        "goal": user.goal.value,
        "target_calories": user.target_calories,
        "allergies": user.allergies or [],
        "preferences": user.preferences or [],
        "disliked_ingredients": user.disliked_ingredients or [],
        "diseases": user.diseases or [],
        "meal_schedule": user.meal_schedule or DEFAULT_MEAL_SCHEDULE,
    }


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(data: UserCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    target_cal = calculate_target_calories(
        weight_kg=data.weight_kg,
        height_cm=data.height_cm,
        age=data.age,
        gender=data.gender,
        activity_level=data.activity_level,
        goal=data.goal,
    )

    schedule = (
        [s.model_dump() for s in data.meal_schedule]
        if data.meal_schedule
        else DEFAULT_MEAL_SCHEDULE
    )

    user = User(
        email=data.email,
        password_hash=_bcrypt.hashpw(data.password.encode(), _bcrypt.gensalt()).decode(),
        age=data.age,
        weight_kg=data.weight_kg,
        height_cm=data.height_cm,
        gender=data.gender,
        activity_level=data.activity_level,
        goal=data.goal,
        allergies=data.allergies,
        preferences=data.preferences,
        disliked_ingredients=data.disliked_ingredients,
        diseases=data.diseases,
        target_calories=target_cal,
        meal_schedule=schedule,
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info("User created: {} (target_calories={})", user.email, target_cal)
    await cache.set_json(f"user:{user.id}", _build_profile_cache(user), ttl=600)

    return _normalize_profile_lists(user)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _normalize_profile_lists(user)


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    data: UserUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = data.model_dump(exclude_unset=True)
    if "meal_schedule" in update_data and update_data["meal_schedule"] is not None:
        update_data["meal_schedule"] = [
            s.model_dump() if hasattr(s, "model_dump") else s for s in update_data["meal_schedule"]
        ]
    for field, value in update_data.items():
        setattr(user, field, value)

    user.target_calories = calculate_target_calories(
        weight_kg=user.weight_kg,
        height_cm=user.height_cm,
        age=user.age,
        gender=user.gender,
        activity_level=user.activity_level,
        goal=user.goal,
    )

    await db.commit()
    await db.refresh(user)

    logger.info("User updated: {} (target_calories={})", user.email, user.target_calories)
    await cache.delete(f"user:{user_id}")
    await cache.set_json(f"user:{user.id}", _build_profile_cache(user), ttl=600)

    return _normalize_profile_lists(user)
