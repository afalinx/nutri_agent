"""API-эндпоинты для генерации и получения планов питания."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.skills.aggregator import aggregate_shopping_list
from app.db.models import MealPlan, MealPlanStatus
from app.db.session import get_db
from app.worker import celery_app

router = APIRouter(prefix="/api", tags=["Plans"])


class GeneratePlanRequest(BaseModel):
    user_id: uuid.UUID
    days: int = Field(default=7, ge=1, le=14)


class GeneratePlanResponse(BaseModel):
    task_id: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    plan_id: str | None = None
    error: str | None = None


class PlanResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    status: str
    start_date: date | None
    end_date: date | None
    plan_data: dict | None
    model_config = {"from_attributes": True}


@router.post("/generate-plan", response_model=GeneratePlanResponse)
async def generate_plan(data: GeneratePlanRequest):
    task = celery_app.send_task(
        "generate_meal_plan",
        args=[str(data.user_id), data.days],
    )
    logger.info("Plan generation queued: task_id={} user_id={}", task.id, data.user_id)
    return GeneratePlanResponse(task_id=task.id)


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

    if result.state == "SUCCESS" and result.result:
        response.plan_id = result.result.get("plan_id")
        if result.result.get("status") == "FAILED":
            response.status = "FAILED"
            response.error = result.result.get("error")
    elif result.state == "FAILURE":
        response.error = str(result.result)

    return response


@router.get("/plans/{plan_id}", response_model=PlanResponse)
async def get_plan(plan_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MealPlan).where(MealPlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return PlanResponse(
        id=plan.id,
        user_id=plan.user_id,
        status=plan.status.value,
        start_date=plan.start_date,
        end_date=plan.end_date,
        plan_data=plan.plan_data,
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
