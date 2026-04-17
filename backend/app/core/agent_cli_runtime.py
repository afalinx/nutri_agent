"""Server-side agent_cli runtime built around the shared CLI contract."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from loguru import logger

from app.core.agent.orchestrator import generate_day_plan
from app.core.cli_contract import (
    build_context_payload,
    build_shopping_list_payload,
    save_plan_payload,
    validate_plan_payload,
)
from app.core.day_plan_repair import repair_day_plan
from app.core.generation_meta import PIPELINE_STEPS, build_generation_meta

ProgressCallback = Callable[[dict[str, Any], str], None]


def _empty_steps() -> list[dict[str, Any]]:
    return [{"key": step, "status": "pending", "message": ""} for step in PIPELINE_STEPS]


def _set_step(
    state: dict[str, Any],
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


def _emit_progress(
    progress_callback: ProgressCallback | None,
    state: dict[str, Any],
    *,
    celery_state: str = "GENERATING",
) -> None:
    if progress_callback is not None:
        progress_callback(deepcopy(state), celery_state)


async def run_agent_cli_pipeline(
    *,
    user_id: str,
    days: int,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Run the canonical context->generate->validate->auto-fix->save pipeline."""
    state: dict[str, Any] = {
        "mode": "agent_cli",
        "quality_status": "valid",
        "current_step": None,
        "steps": _empty_steps(),
        "warnings": [],
    }
    warnings: list[str] = []
    generated_days: list[dict[str, Any]] = []
    day_generation_meta: list[dict[str, Any]] = []
    shared_user: dict[str, Any] | None = None
    current_recipes: list[dict[str, Any]] = []
    recipes_by_day: dict[int, list[dict[str, Any]]] = {}
    catalog_diagnostics_by_day: dict[int, dict[str, Any]] = {}

    try:
        _set_step(state, "context", status="running", message="Готовим CLI-контекст для агента.")
        _emit_progress(progress_callback, state)

        for day_number in range(1, days + 1):
            context = await build_context_payload(user_id, day=day_number)
            shared_user = context["user"]
            current_recipes = context["available_recipes"]
            recipes_by_day[day_number] = current_recipes
            catalog_diagnostics_by_day[day_number] = context.get("catalog_diagnostics") or {}
            if not current_recipes:
                raise RuntimeError(f"No recipes available for day {day_number} after filters")
            diagnostics = catalog_diagnostics_by_day[day_number]
            if diagnostics and not diagnostics.get("feasible", True):
                slot_counts = diagnostics.get("slot_counts") or {}
                raise RuntimeError(
                    "catalog_insufficient: "
                    f"target={diagnostics.get('target_calories')} "
                    f"max_achievable={diagnostics.get('max_achievable_calories')} "
                    f"slot_counts={slot_counts}"
                )

        _set_step(
            state,
            "context",
            status="completed",
            message=f"CLI-контекст готов: {len(current_recipes)} рецептов, {days} дн.",
        )
        _set_step(state, "generate", status="running", message=f"Агент собирает план на {days} дн.")
        _emit_progress(progress_callback, state)

        for day_number in range(1, days + 1):
            context = await build_context_payload(user_id, day=day_number)
            shared_user = context["user"]
            recipes_by_day[day_number] = context["available_recipes"]
            catalog_diagnostics_by_day[day_number] = context.get("catalog_diagnostics") or {}
            day_result = await generate_day_plan(
                context["user"],
                context["available_recipes"],
                day_number=day_number,
            )
            generated_days.append(day_result.plan.model_dump())
            day_generation_meta.append(
                {
                    "day_number": day_number,
                    "quality_status": day_result.quality_status,
                    "attempts_used": day_result.attempts_used,
                    "validation_error": day_result.validation_error,
                }
            )
            if day_result.quality_status != "valid":
                state["quality_status"] = "partially_valid"
            if day_result.validation_error:
                warnings.append(f"Day {day_number}: {day_result.validation_error}")

        _set_step(
            state,
            "generate",
            status="completed",
            message=f"План агентом собран: {len(generated_days)} дн.",
        )
        _set_step(
            state,
            "validate",
            status="running",
            message="Проверяем итоговые day-планы через CLI contract.",
        )
        _emit_progress(progress_callback, state)

        validation_errors: list[str] = []
        days_to_repair: list[tuple[int, str]] = []
        for day in generated_days:
            validation_payload = {
                "daily_target_calories": shared_user["target_calories"],
                "day": day,
            }
            result, exit_code = validate_plan_payload(
                validation_payload,
                target_calories=shared_user["target_calories"],
                meal_schedule=shared_user.get("meal_schedule"),
            )
            if exit_code != 0:
                error = f"Day {day['day_number']}: {result.get('error', 'validation failed')}"
                validation_errors.append(error)
                days_to_repair.append((day["day_number"], result.get("error", "validation failed")))

        if validation_errors:
            _set_step(
                state,
                "validate",
                status="completed",
                message=f"Найдены ошибки: {len(validation_errors)} дн.",
            )
            _set_step(
                state,
                "auto-fix",
                status="running",
                message="Восстанавливаем day-plans по расписанию и recipe pool.",
            )
            _emit_progress(progress_callback, state)

            repair_notes: list[str] = []
            for day_number, initial_error in days_to_repair:
                repaired_day, applied_fixes, repair_error = repair_day_plan(
                    day_plan=generated_days[day_number - 1],
                    recipes=recipes_by_day.get(day_number, current_recipes),
                    meal_schedule=shared_user.get("meal_schedule") or [],
                    target_calories=shared_user["target_calories"],
                )
                if repaired_day is None:
                    _set_step(
                        state,
                        "auto-fix",
                        status="failed",
                        message=repair_error or validation_errors[0],
                    )
                    raise RuntimeError(f"Day {day_number}: {repair_error or initial_error}")

                generated_days[day_number - 1] = repaired_day
                state["quality_status"] = "partially_valid"
                note = (
                    f"Day {day_number}: auto-fix after '{initial_error}'. "
                    f"Applied: {', '.join(applied_fixes) if applied_fixes else 'totals normalization'}"
                )
                repair_notes.append(note)
                warnings.append(note)

                validation_payload = {
                    "daily_target_calories": shared_user["target_calories"],
                    "day": repaired_day,
                }
                result, exit_code = validate_plan_payload(
                    validation_payload,
                    target_calories=shared_user["target_calories"],
                    meal_schedule=shared_user.get("meal_schedule"),
                )
                if exit_code != 0:
                    _set_step(
                        state,
                        "auto-fix",
                        status="failed",
                        message=result.get("error", validation_errors[0]),
                    )
                    raise RuntimeError(
                        f"Day {day_number}: {result.get('error', 'validation failed after auto-fix')}"
                    )

            _set_step(
                state,
                "auto-fix",
                status="completed",
                message=f"Auto-fix применён: {len(repair_notes)} дн.",
            )

        _set_step(
            state,
            "validate",
            status="completed",
            message="Итоговый план прошёл валидацию.",
        )
        if not validation_errors:
            _set_step(
                state,
                "auto-fix",
                status="completed" if state["quality_status"] != "valid" else "skipped",
                message=(
                    "Во время генерации использовался встроенный retry/reflection."
                    if state["quality_status"] != "valid"
                    else "Исправления не потребовались."
                ),
                activate=False,
            )

        state["warnings"] = warnings
        plan_data = {
            "user_profile": shared_user,
            "total_days": days,
            "daily_target_calories": shared_user["target_calories"],
            "days": generated_days,
            "generation_meta": build_generation_meta(
                mode="agent_cli",
                quality_status=state["quality_status"],
                warnings=warnings,
                extra={
                    "steps": PIPELINE_STEPS,
                    "days": day_generation_meta,
                },
            ),
        }

        _set_step(state, "save", status="running", message="Сохраняем агентный результат в БД.")
        _emit_progress(progress_callback, state)
        save_result = await save_plan_payload(user_id, plan_data, days_count=days)
        plan_id = save_result["plan_id"]

        _set_step(state, "save", status="completed", message=f"План сохранён: {plan_id}.")
        _set_step(state, "shopping-list", status="running", message="Строим shopping list из плана.")
        shopping_list = build_shopping_list_payload(plan_data, input_format="week")
        _set_step(
            state,
            "shopping-list",
            status="completed",
            message=f"Список покупок собран: {len(shopping_list)} позиций.",
        )
        _emit_progress(progress_callback, state, celery_state="SUCCESS")

        logger.info(
            "Agent CLI pipeline completed: user_id={} plan_id={} days={}",
            user_id,
            plan_id,
            days,
        )
        return {
            "plan_id": plan_id,
            "status": "READY",
            "mode": "agent_cli",
            "quality_status": state["quality_status"],
            "warnings": warnings,
            "steps": deepcopy(state["steps"]),
            "current_step": state["current_step"],
            "shopping_list": shopping_list,
        }
    except Exception:
        state["quality_status"] = "failed"
        for step in reversed(state["steps"]):
            if step["status"] == "running":
                step["status"] = "failed"
                break
        state["warnings"] = warnings
        _emit_progress(progress_callback, state)
        raise
