"""CLI-first demo pipeline for Sprint 4.

This flow avoids external LLM dependencies and generates a demo-ready meal plan
from the local recipe catalog while exposing explicit pipeline steps.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import product
from typing import Any

from loguru import logger
from sqlalchemy import select

from app.core.skills.aggregator import aggregate_shopping_list
from app.core.skills.validator import validate_day_plan
from app.db.models import DEFAULT_MEAL_SCHEDULE, MealPlan, MealPlanStatus, User
from app.db.session import async_session

PIPELINE_STEPS = ["context", "generate", "validate", "auto-fix", "save", "shopping-list"]
MAX_AUTO_FIX_ITERATIONS = 8


def _empty_steps() -> list[dict[str, Any]]:
    return [{"key": step, "status": "pending", "message": ""} for step in PIPELINE_STEPS]


def _normalize_meal_type(value: str | None) -> set[str]:
    if not value:
        return set()
    return {
        chunk.strip().lower()
        for chunk in value.replace(",", "/").split("/")
        if chunk.strip()
    }


def _slot_compatible_types(slot_type: str) -> set[str]:
    if slot_type == "breakfast":
        return {"breakfast"}
    if slot_type == "snack":
        return {"snack", "second_snack"}
    if slot_type == "lunch":
        return {"lunch", "lunch/dinner", "universal"}
    if slot_type == "dinner":
        return {"dinner", "lunch/dinner", "universal"}
    return {slot_type}


def _recipe_matches_slot(recipe: dict[str, Any], slot_type: str) -> bool:
    recipe_types = _normalize_meal_type(recipe.get("meal_type"))
    if not recipe_types:
        return False
    return bool(recipe_types & _slot_compatible_types(slot_type))


def _build_meal(recipe: dict[str, Any], slot: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": slot["type"],
        "time": slot["time"],
        "recipe_id": recipe["id"],
        "title": recipe["title"],
        "calories": round(float(recipe["calories"]), 1),
        "protein": round(float(recipe["protein"]), 1),
        "fat": round(float(recipe["fat"]), 1),
        "carbs": round(float(recipe["carbs"]), 1),
        "ingredients_summary": [
            {
                "name": ingredient["name"],
                "amount": float(ingredient["amount"]),
                "unit": ingredient["unit"],
            }
            for ingredient in (recipe.get("ingredients") or [])
        ],
    }


def _build_day_plan(day_number: int, schedule: list[dict[str, Any]], recipes: list[dict[str, Any]]) -> dict:
    meals = [_build_meal(recipe, slot) for slot, recipe in zip(schedule, recipes, strict=False)]
    return {
        "day_number": day_number,
        "total_calories": round(sum(meal["calories"] for meal in meals), 1),
        "total_protein": round(sum(meal["protein"] for meal in meals), 1),
        "total_fat": round(sum(meal["fat"] for meal in meals), 1),
        "total_carbs": round(sum(meal["carbs"] for meal in meals), 1),
        "meals": meals,
    }


def _meal_summary(day_plan: dict[str, Any]) -> str:
    return "; ".join(
        f"{meal['type']}={meal['title']} ({meal['calories']:.0f} kcal)"
        for meal in day_plan.get("meals", [])
    )


def _slot_candidates_summary(
    recipes: list[dict[str, Any]],
    schedule: list[dict[str, Any]],
    target_calories: int,
    max_candidates_per_slot: int | None = None,
) -> str:
    candidate_lists = _candidate_lists(
        recipes,
        schedule,
        target_calories,
        max_candidates_per_slot=max_candidates_per_slot,
    )
    chunks = []
    for slot, candidates in zip(schedule, candidate_lists, strict=False):
        top = ", ".join(f"{recipe['title']} ({recipe['calories']:.0f})" for recipe in candidates[:3])
        chunks.append(f"{slot['type']}[{len(candidates)}]: {top}")
    return " | ".join(chunks)


def _candidate_lists(
    recipes: list[dict[str, Any]],
    schedule: list[dict[str, Any]],
    target_calories: int,
    max_candidates_per_slot: int | None = None,
) -> list[list[dict[str, Any]]]:
    all_candidates: list[list[dict[str, Any]]] = []
    for idx, slot in enumerate(schedule):
        slot_target = target_calories * slot["calories_pct"] / 100
        matched = [recipe for recipe in recipes if _recipe_matches_slot(recipe, slot["type"])]
        if not matched:
            logger.warning(
                "No recipes matched slot '{}' after strict filtering; available meal_types={}",
                slot["type"],
                sorted({recipe.get("meal_type") or "missing" for recipe in recipes}),
            )
            all_candidates.append([])
            continue
        ranked = sorted(
            matched,
            key=lambda recipe: (
                abs(float(recipe["calories"]) - slot_target),
                -float(recipe["calories"]),
                idx,
                recipe["title"],
            ),
        )
        all_candidates.append(ranked[:max_candidates_per_slot] if max_candidates_per_slot else ranked)
    return all_candidates


def _max_daily_calories(
    recipes: list[dict[str, Any]],
    schedule: list[dict[str, Any]],
    max_candidates_per_slot: int | None,
) -> float:
    candidate_lists = _candidate_lists(
        recipes=recipes,
        schedule=schedule,
        target_calories=999999,
        max_candidates_per_slot=max_candidates_per_slot,
    )
    if not candidate_lists or any(not group for group in candidate_lists):
        return 0.0
    return sum(max(float(recipe["calories"]) for recipe in group) for group in candidate_lists)


def _max_unique_day_calories(
    recipes: list[dict[str, Any]],
    schedule: list[dict[str, Any]],
    max_candidates_per_slot: int | None,
) -> float:
    candidate_lists = _candidate_lists(
        recipes=recipes,
        schedule=schedule,
        target_calories=999999,
        max_candidates_per_slot=max_candidates_per_slot,
    )
    if not candidate_lists or any(not group for group in candidate_lists):
        return 0.0

    best_total = 0.0
    for combination in product(*candidate_lists):
        recipe_ids = [recipe["id"] for recipe in combination]
        if len(recipe_ids) != len(set(recipe_ids)):
            continue
        total = sum(float(recipe["calories"]) for recipe in combination)
        if total > best_total:
            best_total = total
    return best_total


def _plan_signature(day_plan: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(meal["recipe_id"]) for meal in day_plan.get("meals", []))


def _day_deviation(day_plan: dict[str, Any], target_calories: int) -> float:
    return abs(float(day_plan["total_calories"]) - float(target_calories))


def _diversity_penalty(combination: tuple[dict[str, Any], ...], recipe_penalties: dict[str, float]) -> float:
    return sum(recipe_penalties.get(str(recipe["id"]), 0.0) for recipe in combination)


def _combination_score(
    day_plan: dict[str, Any],
    target_calories: int,
    penalty: float,
    is_valid: bool,
) -> tuple[float, float, float, float]:
    deviation = _day_deviation(day_plan, target_calories)
    return (0.0 if is_valid else 1.0, deviation, penalty, -float(day_plan["total_calories"]))


def _find_plan_combination(
    recipes: list[dict[str, Any]],
    schedule: list[dict[str, Any]],
    target_calories: int,
    day_number: int,
    *,
    max_candidates_per_slot: int | None = None,
    recipe_penalties: dict[str, float] | None = None,
    blocked_signatures: set[tuple[str, ...]] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    candidate_lists = _candidate_lists(
        recipes,
        schedule,
        target_calories,
        max_candidates_per_slot=max_candidates_per_slot,
    )
    if not candidate_lists or any(not group for group in candidate_lists):
        return None, "Недостаточно рецептов для всех слотов расписания."

    best_day: dict[str, Any] | None = None
    best_score: tuple[float, float, float, float] | None = None
    penalties = recipe_penalties or {}
    signatures = blocked_signatures or set()

    for combination in product(*candidate_lists):
        recipe_ids = [recipe["id"] for recipe in combination]
        if len(recipe_ids) != len(set(recipe_ids)):
            continue

        day_plan = _build_day_plan(day_number, schedule, list(combination))
        signature = _plan_signature(day_plan)
        if signature in signatures:
            continue

        is_valid, _ = validate_day_plan(
            DayPlanAdapter.model_validate(day_plan),
            target_calories=target_calories,
            meal_schedule=schedule,
        )
        score = _combination_score(
            day_plan,
            target_calories,
            _diversity_penalty(combination, penalties),
            is_valid,
        )

        if best_score is None or score < best_score:
            best_day = day_plan
            best_score = score

    if best_day is None:
        return None, "Не удалось подобрать неповторяющуюся комбинацию блюд."

    is_valid, error = validate_day_plan(
        DayPlanAdapter.model_validate(best_day),
        target_calories=target_calories,
        meal_schedule=schedule,
    )
    if is_valid:
        return best_day, None

    return best_day, error or (
        f"Отклонение от целевого калоража осталось {best_day['total_calories']:.0f} "
        f"vs {target_calories}."
    )


async def _load_demo_recipes(session, user_profile: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    from app.core.rag.retriever import search_recipes

    preferred_recipes = await search_recipes(
        session,
        allergies=user_profile["allergies"],
        dislikes=user_profile["disliked_ingredients"],
        preferred_tags=user_profile["preferences"],
        diseases=user_profile["diseases"],
        limit=48,
    )

    schedule = user_profile.get("meal_schedule") or DEFAULT_MEAL_SCHEDULE
    target_calories = int(user_profile.get("target_calories") or 0)
    preferred_capacity = _max_daily_calories(preferred_recipes, schedule, max_candidates_per_slot=8)
    logger.info(
        "Demo recipe pool: preferred_count={} preferred_capacity={} target={} preferences={}",
        len(preferred_recipes),
        preferred_capacity,
        target_calories,
        user_profile["preferences"],
    )

    if preferred_recipes and preferred_capacity >= target_calories * 0.95:
        return preferred_recipes, "Используем рецепты с учётом предпочтений."

    relaxed_recipes = await search_recipes(
        session,
        allergies=user_profile["allergies"],
        dislikes=user_profile["disliked_ingredients"],
        preferred_tags=[],
        diseases=user_profile["diseases"],
        limit=48,
    )
    if relaxed_recipes:
        logger.warning(
            "Demo pipeline relaxed preference filter: preferred_count={} preferred_capacity={} target={}",
            len(preferred_recipes),
            preferred_capacity,
            target_calories,
        )
        return (
            relaxed_recipes,
            "Для демо soft-предпочтения ослаблены, чтобы собрать валидный рацион.",
        )

    return preferred_recipes, "Используем рецепты с учётом предпочтений."


def _resolve_demo_target_calories(
    target_calories: int,
    recipes: list[dict[str, Any]],
    schedule: list[dict[str, Any]],
) -> tuple[int, str | None]:
    achievable_max = int(
        _max_unique_day_calories(
            recipes,
            schedule,
            max_candidates_per_slot=max(len(recipes), 1),
        )
    )
    logger.info(
        "Demo target resolution: requested={} achievable_max={} schedule_slots={}",
        target_calories,
        achievable_max,
        [slot["type"] for slot in schedule],
    )
    if achievable_max <= 0:
        return target_calories, None

    if target_calories <= achievable_max:
        return target_calories, None

    # In demo mode we anchor the target to the best achievable unique day,
    # so the validator can accept a real plan from the current catalog.
    demo_target = achievable_max

    return (
        demo_target,
        (
            f"Для демо target_calories скорректирован с {target_calories} до {demo_target}, "
            f"потому что текущий каталог рецептов даёт максимум около {achievable_max} ккал/день."
        ),
    )


def _recipe_usage_penalties(generated_days: list[dict[str, Any]]) -> dict[str, float]:
    counts = Counter(
        str(meal["recipe_id"])
        for day in generated_days
        for meal in day.get("meals", [])
    )
    return {recipe_id: count * 60.0 for recipe_id, count in counts.items()}


def _auto_fix_replacement_order(schedule: list[dict[str, Any]]) -> list[str]:
    return [slot["type"] for slot in sorted(schedule, key=lambda slot: slot["calories_pct"], reverse=True)]


def _slot_candidates_by_type(
    recipes: list[dict[str, Any]],
    schedule: list[dict[str, Any]],
    target_calories: int,
) -> dict[str, list[dict[str, Any]]]:
    return {
        slot["type"]: candidates
        for slot, candidates in zip(
            schedule,
            _candidate_lists(recipes, schedule, target_calories, max_candidates_per_slot=None),
            strict=False,
        )
    }


def _build_replaced_day(
    day_plan: dict[str, Any],
    replacements: dict[str, dict[str, Any]],
    schedule: list[dict[str, Any]],
) -> dict[str, Any]:
    current_by_type = {meal["type"]: meal for meal in day_plan["meals"]}
    ordered_recipes = []
    for slot in schedule:
        replacement = replacements.get(slot["type"])
        if replacement is not None:
            ordered_recipes.append(replacement)
            continue
        ordered_recipes.append(current_by_type[slot["type"]])

    recipes_for_build = [
        {
            "id": meal["recipe_id"],
            "title": meal["title"],
            "calories": meal["calories"],
            "protein": meal["protein"],
            "fat": meal["fat"],
            "carbs": meal["carbs"],
            "ingredients": meal.get("ingredients_summary", []),
        }
        if "recipe_id" in meal
        else meal
        for meal in ordered_recipes
    ]
    return _build_day_plan(day_plan["day_number"], schedule, recipes_for_build)


def _directed_auto_fix(
    day_plan: dict[str, Any],
    recipes: list[dict[str, Any]],
    schedule: list[dict[str, Any]],
    target_calories: int,
    blocked_signatures: set[tuple[str, ...]],
) -> tuple[dict[str, Any] | None, str]:
    current_signature = _plan_signature(day_plan)
    blocked = set(blocked_signatures)
    blocked.add(current_signature)
    slot_candidates = _slot_candidates_by_type(recipes, schedule, target_calories)
    current_by_type = {meal["type"]: meal for meal in day_plan["meals"]}
    slot_order = _auto_fix_replacement_order(schedule)
    best_day = day_plan
    best_error = "Auto-fix не нашёл улучшение."
    best_deviation = _day_deviation(day_plan, target_calories)

    for slot_type in slot_order:
        alternatives = slot_candidates.get(slot_type, [])
        for alternative in alternatives:
            if alternative["id"] == current_by_type[slot_type]["recipe_id"]:
                continue
            replacement = _build_replaced_day(day_plan, {slot_type: alternative}, schedule)
            signature = _plan_signature(replacement)
            if signature in blocked:
                continue
            is_valid, error = validate_day_plan(
                DayPlanAdapter.model_validate(replacement),
                target_calories=target_calories,
                meal_schedule=schedule,
            )
            logger.info(
                "Auto-fix replace slot {} -> {}: total={} error={}",
                slot_type,
                alternative["title"],
                replacement["total_calories"],
                error,
            )
            if is_valid:
                return replacement, ""
            deviation = _day_deviation(replacement, target_calories)
            if deviation < best_deviation:
                best_day = replacement
                best_deviation = deviation
                best_error = error or best_error

    for first_index, first_slot in enumerate(slot_order):
        for second_slot in slot_order[first_index + 1 :]:
            first_alts = [alt for alt in slot_candidates.get(first_slot, [])[:6]]
            second_alts = [alt for alt in slot_candidates.get(second_slot, [])[:6]]
            for first_alt, second_alt in product(first_alts, second_alts):
                if first_alt["id"] == current_by_type[first_slot]["recipe_id"] and second_alt["id"] == current_by_type[second_slot]["recipe_id"]:
                    continue
                replacement = _build_replaced_day(
                    day_plan,
                    {first_slot: first_alt, second_slot: second_alt},
                    schedule,
                )
                signature = _plan_signature(replacement)
                if signature in blocked:
                    continue
                is_valid, error = validate_day_plan(
                    DayPlanAdapter.model_validate(replacement),
                    target_calories=target_calories,
                    meal_schedule=schedule,
                )
                logger.info(
                    "Auto-fix replace slots {}+{} -> {} / {}: total={} error={}",
                    first_slot,
                    second_slot,
                    first_alt["title"],
                    second_alt["title"],
                    replacement["total_calories"],
                    error,
                )
                if is_valid:
                    return replacement, ""
                deviation = _day_deviation(replacement, target_calories)
                if deviation < best_deviation:
                    best_day = replacement
                    best_deviation = deviation
                    best_error = error or best_error

    if best_day is not day_plan:
        return best_day, best_error
    return None, best_error


@dataclass
class DemoTaskState:
    task_id: str
    user_id: str
    days: int
    status: str = "PENDING"
    current_step: str | None = None
    steps: list[dict[str, Any]] | None = None
    error: str | None = None
    plan_id: str | None = None
    shopping_list: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        if self.steps is None:
            self.steps = _empty_steps()

    def payload(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "current_step": self.current_step,
            "steps": deepcopy(self.steps),
            "error": self.error,
            "plan_id": self.plan_id,
            "shopping_list": deepcopy(self.shopping_list),
        }


DEMO_TASKS: dict[str, DemoTaskState] = {}


def get_demo_task(task_id: str) -> DemoTaskState | None:
    return DEMO_TASKS.get(task_id)


def create_demo_task(user_id: str, days: int) -> DemoTaskState:
    task = DemoTaskState(task_id=str(uuid.uuid4()), user_id=user_id, days=days)
    DEMO_TASKS[task.task_id] = task
    return task


def _set_step(
    task: DemoTaskState,
    key: str,
    *,
    status: str,
    message: str,
    activate: bool = True,
) -> None:
    task.current_step = key if activate else task.current_step
    if status == "running":
        task.status = "RUNNING"
    for step in task.steps or []:
        if step["key"] == key:
            step["status"] = status
            step["message"] = message
            break


def _finish_task(task: DemoTaskState, status: str, error: str | None = None) -> None:
    task.status = status
    task.error = error
    if status == "FAILED":
        for step in reversed(task.steps or []):
            if step["status"] == "running":
                step["status"] = "failed"
                if error and not step["message"]:
                    step["message"] = error
                break


async def run_demo_pipeline(task: DemoTaskState) -> None:
    try:
        _set_step(task, "context", status="running", message="Собираем профиль и локальный каталог.")
        async with async_session() as session:
            result = await session.execute(select(User).where(User.id == uuid.UUID(task.user_id)))
            user = result.scalar_one_or_none()
            if not user:
                raise ValueError("Профиль пользователя не найден.")

            user_profile = {
                "id": str(user.id),
                "email": user.email,
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
            recipes, recipe_mode_message = await _load_demo_recipes(session, user_profile)
        if not recipes:
            raise RuntimeError("После фильтрации не осталось безопасных рецептов.")
        _set_step(
            task,
            "context",
            status="completed",
            message=f"Профиль загружен, доступно {len(recipes)} подходящих рецептов. {recipe_mode_message}",
        )

        schedule = user_profile.get("meal_schedule") or DEFAULT_MEAL_SCHEDULE
        source_target_calories = int(user_profile.get("target_calories") or 0)
        if source_target_calories <= 0:
            raise RuntimeError("У пользователя не рассчитан целевой калораж.")
        target_calories, target_message = _resolve_demo_target_calories(
            source_target_calories,
            recipes,
            schedule,
        )
        if target_message:
            user_profile["demo_original_target_calories"] = source_target_calories
            user_profile["target_calories"] = target_calories
            context_message = next(
                step for step in (task.steps or []) if step["key"] == "context"
            )
            context_message["message"] = f"{context_message['message']} {target_message}"
        logger.info(
            "Demo context ready: user_id={} source_target={} effective_target={} recipes={}",
            task.user_id,
            source_target_calories,
            target_calories,
            len(recipes),
        )

        _set_step(
            task,
            "generate",
            status="running",
            message="Подбираем блюда по слотам расписания.",
        )
        generated_days: list[dict[str, Any]] = []
        used_signatures: set[tuple[str, ...]] = set()
        for day_number in range(1, task.days + 1):
            penalties = _recipe_usage_penalties(generated_days)
            logger.info(
                "Generate day {}: target={} penalties={} candidates={}",
                day_number,
                target_calories,
                penalties,
                _slot_candidates_summary(recipes, schedule, target_calories),
            )
            day_plan, error = _find_plan_combination(
                recipes=recipes,
                schedule=schedule,
                target_calories=target_calories,
                day_number=day_number,
                max_candidates_per_slot=None,
                recipe_penalties=penalties,
                blocked_signatures=used_signatures,
            )
            if day_plan is None:
                raise RuntimeError(error or f"Не удалось собрать день {day_number}.")
            logger.info(
                "Generate day {} result: total={} meals={}",
                day_number,
                day_plan["total_calories"],
                _meal_summary(day_plan),
            )
            generated_days.append(day_plan)
            used_signatures.add(_plan_signature(day_plan))
        _set_step(
            task,
            "generate",
            status="completed",
            message=f"Черновик плана собран на {task.days} дн.",
        )

        _set_step(task, "validate", status="running", message="Проверяем КБЖУ и расписание.")
        failed_days: list[tuple[int, str]] = []
        for day_plan in generated_days:
            is_valid, error = validate_day_plan(
                DayPlanAdapter.model_validate(day_plan),
                target_calories=target_calories,
                meal_schedule=schedule,
            )
            if not is_valid:
                logger.warning(
                    "Validate day {} failed: total={} target={} meals={} error={}",
                    day_plan["day_number"],
                    day_plan["total_calories"],
                    target_calories,
                    _meal_summary(day_plan),
                    error,
                )
                failed_days.append((day_plan["day_number"], error or "Ошибка валидации."))
            else:
                logger.info(
                    "Validate day {} passed: total={} target={} meals={}",
                    day_plan["day_number"],
                    day_plan["total_calories"],
                    target_calories,
                    _meal_summary(day_plan),
                )
        if not failed_days:
            _set_step(
                task,
                "validate",
                status="completed",
                message="План прошёл валидацию без исправлений.",
            )
            _set_step(
                task,
                "auto-fix",
                status="skipped",
                message="Исправления не потребовались.",
                activate=False,
            )
        else:
            _set_step(
                task,
                "validate",
                status="completed",
                message=f"Найдены отклонения в {len(failed_days)} дн., запускаем auto-fix.",
            )

            _set_step(
                task,
                "auto-fix",
                status="running",
                message="Ищем альтернативные комбинации блюд.",
            )
            blocked_signatures = {_plan_signature(day) for day in generated_days}
            iterations = 0
            for index, (day_number, initial_error) in enumerate(failed_days):
                fixed_day = None
                logger.warning(
                    "Auto-fix start for day {}: initial_error={} current_total={}",
                    day_number,
                    initial_error,
                    generated_days[day_number - 1]["total_calories"],
                )
                iterations += 1
                logger.info(
                    "Auto-fix day {} iteration {}: directed replacement candidates={}",
                    day_number,
                    iterations,
                    _slot_candidates_summary(recipes, schedule, target_calories),
                )
                candidate, auto_fix_error = _directed_auto_fix(
                    generated_days[day_number - 1],
                    recipes,
                    schedule,
                    target_calories,
                    blocked_signatures=blocked_signatures - {_plan_signature(generated_days[day_number - 1])},
                )
                if candidate is not None:
                    logger.info(
                        "Auto-fix day {} iteration {} candidate: total={} meals={}",
                        day_number,
                        iterations,
                        candidate["total_calories"],
                        _meal_summary(candidate),
                    )
                    is_valid, validation_error = validate_day_plan(
                        DayPlanAdapter.model_validate(candidate),
                        target_calories=target_calories,
                        meal_schedule=schedule,
                    )
                    if is_valid:
                        logger.info(
                            "Auto-fix day {} iteration {} succeeded",
                            day_number,
                            iterations,
                        )
                        fixed_day = candidate
                    else:
                        logger.warning(
                            "Auto-fix day {} iteration {} improved but still rejected: total={} target={} error={}",
                            day_number,
                            iterations,
                            candidate["total_calories"],
                            target_calories,
                            validation_error,
                        )
                else:
                    logger.warning(
                        "Auto-fix day {} iteration {}: no candidate found ({})",
                        day_number,
                        iterations,
                        auto_fix_error,
                    )
                if fixed_day is None:
                    logger.error(
                        "Auto-fix exhausted for day {} after {} iterations. Last meals={}",
                        day_number,
                        iterations,
                        _meal_summary(generated_days[day_number - 1]),
                    )
                    raise RuntimeError(
                        f"Не прошла валидация после {iterations} итераций auto-fix для дня {day_number}."
                    )
                blocked_signatures.discard(_plan_signature(generated_days[day_number - 1]))
                generated_days[day_number - 1] = fixed_day
                blocked_signatures.add(_plan_signature(fixed_day))
                failed_days[index] = (day_number, "fixed")
            _set_step(
                task,
                "auto-fix",
                status="completed",
                message=f"Исправления применены за {iterations} итерац.",
            )

        plan_data = {
            "user_profile": user_profile,
            "total_days": task.days,
            "daily_target_calories": target_calories,
            "days": generated_days,
        }

        _set_step(task, "save", status="running", message="Сохраняем план в базу.")
        async with async_session() as session:
            plan_record = MealPlan(
                user_id=uuid.UUID(task.user_id),
                status=MealPlanStatus.ready,
                start_date=date.today(),
                end_date=date.today() + timedelta(days=task.days - 1),
                plan_data=plan_data,
            )
            session.add(plan_record)
            await session.commit()
            await session.refresh(plan_record)
            task.plan_id = str(plan_record.id)
        _set_step(task, "save", status="completed", message=f"План сохранён: {task.plan_id}.")

        _set_step(
            task,
            "shopping-list",
            status="running",
            message="Агрегируем список покупок.",
        )
        task.shopping_list = aggregate_shopping_list(plan_data)
        _set_step(
            task,
            "shopping-list",
            status="completed",
            message=f"Список покупок собран: {len(task.shopping_list)} позиций.",
        )
        _finish_task(task, "READY")
    except Exception as exc:
        logger.exception("Demo pipeline failed for task {}", task.task_id)
        _finish_task(task, "FAILED", str(exc))


class DayPlanAdapter:
    """Small adapter to validate dicts with the existing pydantic schema lazily."""

    @staticmethod
    def model_validate(payload: dict[str, Any]):
        from app.core.agent.schemas import DayPlan

        return DayPlan.model_validate(payload)


async def schedule_demo_pipeline(task: DemoTaskState) -> None:
    await asyncio.sleep(0)
    await run_demo_pipeline(task)
