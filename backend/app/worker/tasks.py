"""Celery-задачи для фоновой генерации планов питания."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Literal

from loguru import logger

from app.core.agent_cli_runtime import run_agent_cli_pipeline
from app.core.catalog_agent_runtime import run_catalog_agent_pipeline
from app.core.catalog_agents import build_research_agent, build_verification_agent
from app.core.source_discovery import DiscoverySourceOutput
from app.core.source_harvester import discover_source_urls
from app.core.source_discovery_runtime import run_source_discovery_pipeline
from app.core.canonical_pipeline import (
    create_plan_record,
    finalize_plan_record,
    load_candidate_recipes,
    load_user_profile,
)
from app.core.generation_meta import PIPELINE_STEPS, build_generation_meta
from app.worker import celery_app

_worker_loop: asyncio.AbstractEventLoop | None = None


def _run_async(coro):
    """Helper to run async code inside sync Celery task.

    Celery tasks in this worker share module-level async resources such as the
    SQLAlchemy async engine and Redis clients. Recreating and closing a brand
    new event loop for every task makes those resources cross loop boundaries,
    which triggers "Future attached to a different loop" / "Event loop is
    closed" errors on later tasks. Keep one stable loop per worker process.
    """
    global _worker_loop

    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()

    asyncio.set_event_loop(_worker_loop)
    return _worker_loop.run_until_complete(coro)


def _empty_steps() -> list[dict]:
    return [{"key": step, "status": "pending", "message": ""} for step in PIPELINE_STEPS]


def _set_step(
    state: dict,
    key: str,
    *,
    status: str,
    message: str,
    activate: bool = True,
) -> None:
    if activate:
        state["current_step"] = key
    for step in state["steps"]:
        if step["key"] == key:
            step["status"] = status
            step["message"] = message
            break


def _publish_progress(task, state: dict, *, celery_state: str = "GENERATING") -> None:
    task.update_state(state=celery_state, meta=deepcopy(state))


def _empty_catalog_steps() -> list[dict]:
    return [
        {"key": "research", "status": "pending", "message": ""},
        {"key": "candidate", "status": "pending", "message": ""},
        {"key": "verify", "status": "pending", "message": ""},
        {"key": "admit", "status": "pending", "message": ""},
    ]


def _empty_discovery_steps() -> list[dict]:
    return [
        {"key": "discover", "status": "pending", "message": ""},
        {"key": "source", "status": "pending", "message": ""},
        {"key": "research", "status": "pending", "message": ""},
        {"key": "candidate", "status": "pending", "message": ""},
        {"key": "verify", "status": "pending", "message": ""},
        {"key": "admit", "status": "pending", "message": ""},
    ]


def _build_discovery_agent():
    async def discovery_agent(seed_input: dict) -> list[DiscoverySourceOutput]:
        urls = seed_input.get("source_urls") or []
        if seed_input.get("source_url"):
            urls = [seed_input["source_url"], *urls]
        if urls:
            outputs: list[DiscoverySourceOutput] = []
            for url in urls:
                outputs.append(
                    DiscoverySourceOutput(
                        url=url,
                        source_type="web",
                        discovery_query=seed_input.get("query"),
                        discovery_payload={"seed_input": seed_input},
                        provenance=seed_input.get("provenance") or {},
                        discovered_by="source_discovery_seed",
                    )
                )
            return outputs
        return await discover_source_urls(
            query=seed_input.get("query"),
            domains=seed_input.get("domains"),
        )

    return discovery_agent


async def _generate(user_id: str, days: int, task=None) -> dict:
    from app.core.agent.orchestrator import generate_day_plan
    from app.core.skills.aggregator import aggregate_shopping_list
    from app.db.models import MealPlanStatus
    from app.db.session import async_session

    progress_state = {
        "mode": "llm_direct",
        "quality_status": "valid",
        "current_step": None,
        "steps": _empty_steps(),
        "warnings": [],
    }

    async with async_session() as session:
        _set_step(
            progress_state,
            "context",
            status="running",
            message="Загружаем профиль и каталог рецептов.",
        )
        if task is not None:
            _publish_progress(task, progress_state)
        user_profile = await load_user_profile(session, user_id)
        recipes = await load_candidate_recipes(session, user_profile, limit=30)
        if not recipes:
            raise RuntimeError("No recipes found for this profile after applying filters")
        _set_step(
            progress_state,
            "context",
            status="completed",
            message=f"Контекст готов: {len(recipes)} рецептов после фильтрации.",
        )

        plan_record = await create_plan_record(
            session,
            user_id=user_id,
            days=days,
            status=MealPlanStatus.generating,
        )
        plan_id = str(plan_record.id)
        progress_state["plan_id"] = plan_id

        try:
            _set_step(
                progress_state,
                "generate",
                status="running",
                message=f"Генерируем план на {days} дн.",
            )
            if task is not None:
                _publish_progress(task, progress_state)
            all_days = []
            quality_status = "valid"
            generation_warnings: list[str] = []
            day_generation_meta: list[dict] = []
            for day_num in range(1, days + 1):
                logger.info("Generating day {}/{} for user {}", day_num, days, user_id)
                day_result = await generate_day_plan(user_profile, recipes, day_number=day_num)
                all_days.append(day_result.plan.model_dump())
                day_generation_meta.append(
                    {
                        "day_number": day_num,
                        "quality_status": day_result.quality_status,
                        "attempts_used": day_result.attempts_used,
                        "validation_error": day_result.validation_error,
                    }
                )
                if day_result.quality_status != "valid":
                    quality_status = "partially_valid"
                if day_result.validation_error:
                    generation_warnings.append(
                        f"Day {day_num}: {day_result.validation_error}"
                    )
            progress_state["quality_status"] = quality_status
            progress_state["warnings"] = generation_warnings
            _set_step(
                progress_state,
                "generate",
                status="completed",
                message=f"План по дням собран: {len(all_days)} дн.",
            )
            _set_step(
                progress_state,
                "validate",
                status="completed",
                message=(
                    "Все дни прошли валидацию."
                    if quality_status == "valid"
                    else "Часть дней сохранена как partially_valid."
                ),
            )
            _set_step(
                progress_state,
                "auto-fix",
                status="completed" if quality_status != "valid" else "skipped",
                message=(
                    "Использован fallback после исчерпания retry."
                    if quality_status != "valid"
                    else "Исправления не потребовались."
                ),
                activate=False,
            )
            if task is not None:
                _publish_progress(task, progress_state)

            plan_data = {
                "user_profile": user_profile,
                "total_days": days,
                "daily_target_calories": user_profile["target_calories"],
                "days": all_days,
                "generation_meta": build_generation_meta(
                    mode="llm_direct",
                    quality_status=quality_status,
                    warnings=generation_warnings,
                    extra={"days": day_generation_meta},
                ),
            }

            _set_step(
                progress_state,
                "shopping-list",
                status="running",
                message="Проверяем агрегацию списка покупок.",
            )
            shopping_list = aggregate_shopping_list(plan_data)
            _set_step(
                progress_state,
                "shopping-list",
                status="completed",
                message=f"Список покупок собран: {len(shopping_list)} позиций.",
            )
            _set_step(
                progress_state,
                "save",
                status="running",
                message="Сохраняем план в базу.",
            )
            if task is not None:
                _publish_progress(task, progress_state)
            await finalize_plan_record(
                session,
                plan_record=plan_record,
                plan_data=plan_data,
                status=MealPlanStatus.ready,
            )
            _set_step(
                progress_state,
                "save",
                status="completed",
                message=f"План сохранён: {plan_id}.",
            )

            logger.info("Plan {} generated successfully ({} days)", plan_id, days)
            if task is not None:
                _publish_progress(task, progress_state, celery_state="SUCCESS")
            return {
                "plan_id": plan_id,
                "status": "READY",
                "mode": "llm_direct",
                "quality_status": quality_status,
                "warnings": generation_warnings,
                "steps": deepcopy(progress_state["steps"]),
                "current_step": progress_state["current_step"],
            }

        except Exception as e:
            logger.error("Plan generation failed: {}", e)
            progress_state["quality_status"] = "failed"
            progress_state["warnings"] = [str(e)]
            for step in reversed(progress_state["steps"]):
                if step["status"] == "running":
                    step["status"] = "failed"
                    if not step["message"]:
                        step["message"] = str(e)
                    break
            failed_plan_data = {
                "error": str(e),
                "generation_meta": build_generation_meta(
                    mode="llm_direct",
                    quality_status="failed",
                    warnings=[str(e)],
                ),
            }
            await finalize_plan_record(
                session,
                plan_record=plan_record,
                plan_data=failed_plan_data,
                status=MealPlanStatus.failed,
            )
            if task is not None:
                _publish_progress(task, progress_state)
            return {
                "plan_id": plan_id,
                "status": "FAILED",
                "mode": "llm_direct",
                "quality_status": "failed",
                "warnings": [str(e)],
                "error": str(e),
                "steps": deepcopy(progress_state["steps"]),
                "current_step": progress_state["current_step"],
            }


async def _generate_by_mode(
    user_id: str,
    days: int,
    *,
    mode: Literal["agent_cli", "llm_direct"],
    task=None,
    progress_state_holder: dict | None = None,
) -> dict:
    if mode == "agent_cli":
        return await run_agent_cli_pipeline(
            user_id=user_id,
            days=days,
            progress_callback=(
                lambda state, celery_state="GENERATING": (
                    progress_state_holder.__setitem__("state", deepcopy(state))
                    if progress_state_holder is not None
                    else None,
                    _publish_progress(task, state, celery_state=celery_state),
                )[-1]
            )
            if task is not None
            else None,
        )
    return await _generate(user_id, days, task=task)


async def _run_catalog_ingest(seed_input: dict, task=None, progress_state_holder: dict | None = None) -> dict:
    from app.db.session import async_session

    progress_state = {
        "mode": "catalog_llm_pair",
        "status": "RUNNING",
        "current_step": None,
        "steps": _empty_catalog_steps(),
        "candidate_id": None,
        "review_id": None,
        "recipe_id": None,
        "reason_codes": [],
        "error": None,
    }

    def _on_progress(state: dict[str, object]) -> None:
        merged = {**progress_state, **deepcopy(state)}
        if progress_state_holder is not None:
            progress_state_holder["state"] = deepcopy(merged)
        if task is not None:
            _publish_progress(task, merged)

    async with async_session() as session:
        result = await run_catalog_agent_pipeline(
            session,
            seed_input=seed_input,
            research_agent=build_research_agent(),
            verification_agent=build_verification_agent(),
            progress_callback=_on_progress if task is not None else None,
        )

    payload = {
        "status": result.status,
        "mode": "catalog_llm_pair",
        "candidate_id": result.candidate_id,
        "review_id": result.review_id,
        "recipe_id": result.recipe_id,
        "reason_codes": result.reason_codes or [],
        "error": result.error,
        "steps": result.steps or _empty_catalog_steps(),
        "current_step": result.current_step,
    }
    if progress_state_holder is not None:
        progress_state_holder["state"] = deepcopy(payload)
    if task is not None:
        _publish_progress(task, payload, celery_state="SUCCESS" if result.status == "ACCEPTED" else "GENERATING")
    return payload


async def _run_source_discovery_ingest(seed_input: dict, task=None, progress_state_holder: dict | None = None) -> dict:
    from app.db.session import async_session

    progress_state = {
        "mode": "source_discovery_ingest",
        "status": "RUNNING",
        "current_step": None,
        "steps": _empty_discovery_steps(),
        "source_candidate_id": None,
        "candidate_id": None,
        "review_id": None,
        "recipe_id": None,
        "reason_codes": [],
        "error": None,
    }

    def _on_progress(state: dict[str, object]) -> None:
        merged = {**progress_state, **deepcopy(state)}
        if progress_state_holder is not None:
            progress_state_holder["state"] = deepcopy(merged)
        if task is not None:
            _publish_progress(task, merged)

    async with async_session() as session:
        result = await run_source_discovery_pipeline(
            session,
            seed_input=seed_input,
            discovery_agent=_build_discovery_agent(),
            research_agent=build_research_agent(),
            verification_agent=build_verification_agent(),
            progress_callback=_on_progress if task is not None else None,
        )

    payload = {
        "status": result.status,
        "mode": "source_discovery_ingest",
        "source_candidate_id": result.source_candidate_id,
        "candidate_id": result.candidate_id,
        "review_id": result.review_id,
        "recipe_id": result.recipe_id,
        "reason_codes": result.reason_codes or [],
        "error": result.error,
        "steps": result.steps or _empty_discovery_steps(),
        "current_step": result.current_step,
    }
    if progress_state_holder is not None:
        progress_state_holder["state"] = deepcopy(payload)
    if task is not None:
        _publish_progress(task, payload, celery_state="SUCCESS" if result.status == "ACCEPTED" else "GENERATING")
    return payload


@celery_app.task(name="generate_meal_plan", bind=True)
def generate_meal_plan(self, user_id: str, days: int = 7, mode: str = "agent_cli"):
    logger.info(
        "Task started: generate_meal_plan user={} days={} mode={}",
        user_id,
        days,
        mode,
    )
    self.update_state(state="GENERATING")
    progress_state_holder: dict[str, dict] = {}
    try:
        return _run_async(
            _generate_by_mode(
                user_id,
                days,
                mode=mode,
                task=self,
                progress_state_holder=progress_state_holder,
            )
        )
    except Exception as exc:
        logger.exception("Task failed: generate_meal_plan user={} days={} mode={}", user_id, days, mode)
        last_state = progress_state_holder.get("state") or {}
        return {
            "status": "FAILED",
            "mode": mode,
            "quality_status": "failed",
            "warnings": last_state.get("warnings") or [str(exc)],
            "error": str(exc),
            "steps": last_state.get("steps") or [],
            "current_step": last_state.get("current_step"),
        }


@celery_app.task(name="run_catalog_ingest", bind=True)
def run_catalog_ingest(self, seed_input: dict):
    logger.info("Task started: run_catalog_ingest")
    self.update_state(state="GENERATING")
    progress_state_holder: dict[str, dict] = {}
    try:
        return _run_async(
            _run_catalog_ingest(
                seed_input,
                task=self,
                progress_state_holder=progress_state_holder,
            )
        )
    except Exception as exc:
        logger.exception("Task failed: run_catalog_ingest")
        last_state = progress_state_holder.get("state") or {}
        return {
            "status": "FAILED",
            "mode": "catalog_llm_pair",
            "candidate_id": last_state.get("candidate_id"),
            "review_id": last_state.get("review_id"),
            "recipe_id": last_state.get("recipe_id"),
            "reason_codes": last_state.get("reason_codes") or [],
            "error": str(exc),
            "steps": last_state.get("steps") or _empty_catalog_steps(),
            "current_step": last_state.get("current_step"),
        }


@celery_app.task(name="run_source_discovery_ingest", bind=True)
def run_source_discovery_ingest(self, seed_input: dict):
    logger.info("Task started: run_source_discovery_ingest")
    self.update_state(state="GENERATING")
    progress_state_holder: dict[str, dict] = {}
    try:
        return _run_async(
            _run_source_discovery_ingest(
                seed_input,
                task=self,
                progress_state_holder=progress_state_holder,
            )
        )
    except Exception as exc:
        logger.exception("Task failed: run_source_discovery_ingest")
        last_state = progress_state_holder.get("state") or {}
        return {
            "status": "FAILED",
            "mode": "source_discovery_ingest",
            "source_candidate_id": last_state.get("source_candidate_id"),
            "candidate_id": last_state.get("candidate_id"),
            "review_id": last_state.get("review_id"),
            "recipe_id": last_state.get("recipe_id"),
            "reason_codes": last_state.get("reason_codes") or [],
            "error": str(exc),
            "steps": last_state.get("steps") or _empty_discovery_steps(),
            "current_step": last_state.get("current_step"),
        }
