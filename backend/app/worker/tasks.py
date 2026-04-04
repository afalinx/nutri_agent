"""Celery-задачи для фоновой генерации планов питания."""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta

from loguru import logger

from app.worker import celery_app


def _run_async(coro):
    """Helper to run async code inside sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _get_user_profile(user_id: str, session) -> dict:
    """Get user profile from Redis cache or DB."""
    from app.core import cache
    from app.db.models import User

    cached = await cache.get_json(f"user:{user_id}")
    if cached:
        logger.debug("User profile loaded from cache: {}", user_id)
        return cached

    from sqlalchemy import select

    result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError(f"User {user_id} not found")

    from app.db.models import DEFAULT_MEAL_SCHEDULE

    profile = {
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

    await cache.set_json(f"user:{user_id}", profile, ttl=600)
    return profile


async def _generate(user_id: str, days: int) -> dict:
    from app.core import cache
    from app.core.agent.orchestrator import generate_day_plan
    from app.core.rag.retriever import search_recipes
    from app.db.models import MealPlan, MealPlanStatus
    from app.db.session import async_session

    async with async_session() as session:
        user_profile = await _get_user_profile(user_id, session)

        recipes = await search_recipes(
            session,
            allergies=user_profile.get("allergies"),
            dislikes=user_profile.get("disliked_ingredients"),
            preferred_tags=user_profile.get("preferences"),
            diseases=user_profile.get("diseases"),
            limit=30,
        )
        if not recipes:
            raise RuntimeError("No recipes found for this profile after applying filters")

        plan_record = MealPlan(
            user_id=uuid.UUID(user_id),
            status=MealPlanStatus.generating,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=days - 1),
        )
        session.add(plan_record)
        await session.commit()
        await session.refresh(plan_record)
        plan_id = str(plan_record.id)

        try:
            all_days = []
            for day_num in range(1, days + 1):
                logger.info("Generating day {}/{} for user {}", day_num, days, user_id)
                day_plan = await generate_day_plan(user_profile, recipes, day_number=day_num)
                all_days.append(day_plan.model_dump())

            plan_data = {
                "user_profile": user_profile,
                "total_days": days,
                "daily_target_calories": user_profile["target_calories"],
                "days": all_days,
            }

            plan_record.plan_data = plan_data
            plan_record.status = MealPlanStatus.ready
            await session.commit()

            # Cache the completed plan
            await cache.set_json(f"plan:{plan_id}", plan_data, ttl=3600)

            logger.info("Plan {} generated successfully ({} days)", plan_id, days)
            return {"plan_id": plan_id, "status": "READY"}

        except Exception as e:
            logger.error("Plan generation failed: {}", e)
            plan_record.status = MealPlanStatus.failed
            plan_record.plan_data = {"error": str(e)}
            await session.commit()
            return {"plan_id": plan_id, "status": "FAILED", "error": str(e)}


@celery_app.task(name="generate_meal_plan", bind=True)
def generate_meal_plan(self, user_id: str, days: int = 7):
    logger.info("Task started: generate_meal_plan user={} days={}", user_id, days)
    self.update_state(state="GENERATING")
    return _run_async(_generate(user_id, days))
