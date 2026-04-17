"""API-эндпоинты для генерации и получения планов питания."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from celery.result import AsyncResult
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import Response
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.core.demo_pipeline import create_demo_task, get_demo_task, schedule_demo_pipeline
from app.core.skills.aggregator import aggregate_shopping_list
from app.core.skills.ics_export import generate_ics
from app.db.models import MealPlan, MealPlanStatus
from app.db.session import get_db
from app.worker import celery_app

router = APIRouter(prefix="/api", tags=["Plans"])


class GeneratePlanRequest(BaseModel):
    user_id: uuid.UUID
    days: int = Field(default=7, ge=1, le=14)
    mode: Literal["agent_cli", "llm_direct"] = "agent_cli"


class GeneratePlanResponse(BaseModel):
    task_id: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    plan_id: str | None = None
    mode: str | None = None
    quality_status: str | None = None
    current_step: str | None = None
    steps: list[DemoStepResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class DemoStepResponse(BaseModel):
    key: str
    status: str
    message: str = ""


class DemoTaskStatusResponse(TaskStatusResponse):
    current_step: str | None = None
    steps: list[DemoStepResponse] = Field(default_factory=list)
    shopping_list: list[dict] | None = None


class PlanResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    status: str
    start_date: date | None
    end_date: date | None
    plan_data: dict | None
    mode: str | None = None
    quality_status: str | None = None
    warnings: list[str] = Field(default_factory=list)
    model_config = {"from_attributes": True}


@router.post("/generate-plan", response_model=GeneratePlanResponse)
async def generate_plan(data: GeneratePlanRequest):
    task = celery_app.send_task(
        "generate_meal_plan",
        args=[str(data.user_id), data.days, data.mode],
    )
    logger.info(
        "Plan generation queued: task_id={} user_id={} mode={}",
        task.id,
        data.user_id,
        data.mode,
    )
    return GeneratePlanResponse(task_id=task.id)


@router.post("/demo/generate-plan", response_model=GeneratePlanResponse)
async def generate_demo_plan(data: GeneratePlanRequest, background_tasks: BackgroundTasks):
    task = create_demo_task(str(data.user_id), data.days)
    background_tasks.add_task(schedule_demo_pipeline, task)
    logger.info("Demo plan generation queued: task_id={} user_id={}", task.task_id, data.user_id)
    return GeneratePlanResponse(task_id=task.task_id)


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    result = AsyncResult(task_id, app=celery_app)

    status_map = {
        "PENDING": "PENDING",
        "STARTED": "GENERATING",
        "GENERATING": "GENERATING",
        "SUCCESS": "READY",
        "FAILURE": "FAILED",
    }

    status = status_map.get(result.state, result.state)

    response = TaskStatusResponse(task_id=task_id, status=status)
    progress_meta = result.info if isinstance(result.info, dict) else {}
    response.mode = progress_meta.get("mode")
    response.quality_status = progress_meta.get("quality_status")
    response.current_step = progress_meta.get("current_step")
    response.steps = progress_meta.get("steps") or []
    response.warnings = progress_meta.get("warnings") or []

    if result.state == "SUCCESS" and result.result:
        response.plan_id = result.result.get("plan_id")
        response.mode = result.result.get("mode") or response.mode
        response.quality_status = result.result.get("quality_status") or response.quality_status
        response.current_step = result.result.get("current_step") or response.current_step
        response.steps = result.result.get("steps") or response.steps
        response.warnings = result.result.get("warnings") or response.warnings
        if result.result.get("status") == "FAILED":
            response.status = "FAILED"
            response.error = result.result.get("error")
    elif result.state == "FAILURE":
        response.error = str(result.result)

    return response


@router.get("/demo/tasks/{task_id}", response_model=DemoTaskStatusResponse)
async def get_demo_task_status(task_id: str):
    task = get_demo_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Demo task not found")
    return DemoTaskStatusResponse(**task.payload())


@router.get("/plans/{plan_id}", response_model=PlanResponse)
async def get_plan(plan_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    # Try cache first
    cached_plan_data = await cache.get_json(f"plan:{plan_id}")

    result = await db.execute(select(MealPlan).where(MealPlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    plan_data = cached_plan_data if cached_plan_data else plan.plan_data

    generation_meta = (plan_data or {}).get("generation_meta") or {}

    return PlanResponse(
        id=plan.id,
        user_id=plan.user_id,
        status=plan.status.value,
        start_date=plan.start_date,
        end_date=plan.end_date,
        plan_data=plan_data,
        mode=generation_meta.get("mode"),
        quality_status=generation_meta.get("quality_status"),
        warnings=generation_meta.get("warnings") or [],
    )


@router.get("/plans/{plan_id}/shopping-list")
async def get_shopping_list(plan_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MealPlan).where(MealPlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    if plan.status != MealPlanStatus.ready or not plan.plan_data:
        raise HTTPException(status_code=400, detail="Plan is not ready yet")

    shopping_list = aggregate_shopping_list(plan.plan_data)
    return {"plan_id": str(plan_id), "items": shopping_list}


@router.get("/plans/{plan_id}/calendar.ics")
async def export_calendar(plan_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Экспорт плана питания в формат iCalendar (.ics)."""
    result = await db.execute(select(MealPlan).where(MealPlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    if plan.status != MealPlanStatus.ready or not plan.plan_data:
        raise HTTPException(status_code=400, detail="Plan is not ready yet")

    ics_content = generate_ics(
        plan_data=plan.plan_data,
        plan_id=str(plan_id),
        start_date=plan.start_date,
    )

    return Response(
        content=ics_content,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="nutriagent-plan-{plan_id}.ics"'},
    )


# ── Swap / Cancel ──────────────────────────────────


class SwapMealRequest(BaseModel):
    day_number: int = Field(ge=1)
    meal_type: str
    new_recipe_id: uuid.UUID | None = None


class CancelMealRequest(BaseModel):
    day_number: int = Field(ge=1)
    meal_type: str


async def _load_ready_plan(plan_id: uuid.UUID, db: AsyncSession) -> MealPlan:
    result = await db.execute(select(MealPlan).where(MealPlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    if plan.status != MealPlanStatus.ready or not plan.plan_data:
        raise HTTPException(status_code=400, detail="Plan is not ready yet")
    return plan


def _find_day_and_meal(plan_data: dict, day_number: int, meal_type: str) -> tuple[dict, dict, int]:
    """Find day dict, meal dict, and meal index in the day."""
    for day in plan_data.get("days", []):
        if day.get("day_number") == day_number:
            for idx, meal in enumerate(day.get("meals", [])):
                if meal.get("type") == meal_type:
                    return day, meal, idx
            raise HTTPException(
                status_code=404,
                detail=f"Meal type '{meal_type}' not found in day {day_number}",
            )
    raise HTTPException(status_code=404, detail=f"Day {day_number} not found in plan")


def _recalc_day_totals(day: dict) -> None:
    """Recalculate day totals from meals."""
    meals = day.get("meals", [])
    day["total_calories"] = sum(m.get("calories", 0) for m in meals)
    day["total_protein"] = sum(m.get("protein", 0) for m in meals)
    day["total_fat"] = sum(m.get("fat", 0) for m in meals)
    day["total_carbs"] = sum(m.get("carbs", 0) for m in meals)


@router.get("/plans/{plan_id}/alternatives")
async def get_alternatives(
    plan_id: uuid.UUID,
    day_number: int,
    meal_type: str,
    db: AsyncSession = Depends(get_db),
):
    """Получить альтернативные рецепты для замены блюда."""
    plan = await _load_ready_plan(plan_id, db)
    _, current_meal, _ = _find_day_and_meal(plan.plan_data, day_number, meal_type)

    current_calories = current_meal.get("calories", 0)
    current_recipe_id = current_meal.get("recipe_id")

    # Get IDs of all recipes used in this day (to avoid duplicates)
    day_data = next(
        (d for d in plan.plan_data.get("days", []) if d.get("day_number") == day_number), {}
    )
    used_ids = {m.get("recipe_id") for m in day_data.get("meals", [])}

    # Load user profile for allergy filtering
    from app.core.rag.retriever import _get_all_recipes

    all_recipes = await _get_all_recipes(db)

    # Filter: same meal_type, similar calories ±30%, not current, not used today
    user_profile = plan.plan_data.get("user_profile", {})
    user_allergens = set(user_profile.get("allergies", []))

    alternatives = []
    for r in all_recipes:
        r_type = (r.get("meal_type") or "").strip()
        # Match meal_type (including universal types like "lunch/dinner")
        if meal_type not in r_type and r_type != meal_type:
            continue
        if r["id"] == current_recipe_id or r["id"] in used_ids:
            continue
        # Allergen check
        if user_allergens & set(r.get("allergens", [])):
            continue
        # Calorie range ±30%
        if current_calories > 0:
            r_cal = r.get("calories", 0)
            if abs(r_cal - current_calories) / current_calories > 0.3:
                continue
        alternatives.append(
            {
                "id": r["id"],
                "title": r["title"],
                "calories": r["calories"],
                "protein": r["protein"],
                "fat": r["fat"],
                "carbs": r["carbs"],
                "meal_type": r.get("meal_type"),
                "prep_time_min": r.get("prep_time_min"),
                "category": r.get("category"),
            }
        )

    return {"alternatives": alternatives[:5]}


@router.post("/plans/{plan_id}/swap-meal")
async def swap_meal(
    plan_id: uuid.UUID,
    data: SwapMealRequest,
    db: AsyncSession = Depends(get_db),
):
    """Заменить одно блюдо в плане."""
    plan = await _load_ready_plan(plan_id, db)
    day, old_meal, meal_idx = _find_day_and_meal(plan.plan_data, data.day_number, data.meal_type)

    # Find the new recipe
    from app.core.rag.retriever import _get_all_recipes

    all_recipes = await _get_all_recipes(db)

    if data.new_recipe_id:
        new_recipe = next((r for r in all_recipes if r["id"] == str(data.new_recipe_id)), None)
        if not new_recipe:
            raise HTTPException(status_code=404, detail="Recipe not found")
    else:
        # Auto-select: same meal_type, closest calories, not current
        current_cal = old_meal.get("calories", 0)
        current_id = old_meal.get("recipe_id")
        used_ids = {m.get("recipe_id") for m in day.get("meals", [])}

        candidates = [
            r
            for r in all_recipes
            if data.meal_type in ((r.get("meal_type") or "").strip())
            and r["id"] != current_id
            and r["id"] not in used_ids
        ]
        if not candidates:
            raise HTTPException(status_code=404, detail="No alternative recipes available")

        candidates.sort(key=lambda r: abs(r["calories"] - current_cal))
        new_recipe = candidates[0]

    # Build new meal entry
    new_meal = {
        "type": data.meal_type,
        "time": old_meal.get("time", "12:00"),
        "recipe_id": new_recipe["id"],
        "title": new_recipe["title"],
        "calories": new_recipe["calories"],
        "protein": new_recipe["protein"],
        "fat": new_recipe["fat"],
        "carbs": new_recipe["carbs"],
        "ingredients_summary": new_recipe.get("ingredients", []),
    }

    day["meals"][meal_idx] = new_meal
    _recalc_day_totals(day)

    # Persist
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(plan, "plan_data")
    await db.commit()
    await cache.delete(f"plan:{plan_id}")

    logger.info(
        "Swapped meal: plan={} day={} type={} → {}",
        plan_id,
        data.day_number,
        data.meal_type,
        new_recipe["title"],
    )

    return {"day": day}


@router.post("/plans/{plan_id}/cancel-meal")
async def cancel_meal(
    plan_id: uuid.UUID,
    data: CancelMealRequest,
    db: AsyncSession = Depends(get_db),
):
    """Убрать блюдо из плана (пересчитать итоги дня)."""
    plan = await _load_ready_plan(plan_id, db)
    day, _, meal_idx = _find_day_and_meal(plan.plan_data, data.day_number, data.meal_type)

    day["meals"].pop(meal_idx)
    _recalc_day_totals(day)

    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(plan, "plan_data")
    await db.commit()
    await cache.delete(f"plan:{plan_id}")

    logger.info("Cancelled meal: plan={} day={} type={}", plan_id, data.day_number, data.meal_type)

    return {"day": day}
