"""Оркестратор генерации плана питания.

Пайплайн: Профиль → RAG → LLM (Structured Output) → Валидация → [Рефлексия] → Результат.
Ингредиенты подставляются post-hoc из данных рецепта, не от LLM.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import yaml
from jinja2 import Template
from loguru import logger
from pydantic import ValidationError

from app.config import settings
from app.core.agent.schemas import DayPlan, DayPlanFull, MealItemFull, MealPlanOutput
from app.core.skills.validator import validate_day_plan

PROMPTS_DIR = Path(__file__).parent / "prompts"
MAX_RETRIES = 3


def _load_prompt() -> dict[str, Template]:
    with open(PROMPTS_DIR / "meal_plan.yml", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return {key: Template(val) for key, val in raw.items()}


def _build_system_prompt(
    templates: dict[str, Template],
    user_profile: dict,
    recipes: list[dict],
) -> str:
    recipe_dicts = [
        {
            "id": r["id"] if isinstance(r, dict) else str(r.id),
            "title": r["title"] if isinstance(r, dict) else r.title,
            "calories": r["calories"] if isinstance(r, dict) else r.calories,
            "protein": r["protein"] if isinstance(r, dict) else r.protein,
            "fat": r["fat"] if isinstance(r, dict) else r.fat,
            "carbs": r["carbs"] if isinstance(r, dict) else r.carbs,
            "tags": (r.get("tags") if isinstance(r, dict) else r.tags) or [],
            "meal_type": (
                r.get("meal_type") if isinstance(r, dict) else getattr(r, "meal_type", None)
            )
            or "universal",
            "ingredients_short": (
                r.get("ingredients_short")
                if isinstance(r, dict)
                else getattr(r, "ingredients_short", None)
            )
            or "",
        }
        for r in recipes
    ]
    return templates["system"].render(
        **user_profile,
        recipes=recipe_dicts,
    )


async def _call_llm(messages: list[dict]) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.LLM_MODEL_NAME,
                "messages": messages,
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


def _append_retry_feedback(
    messages: list[dict[str, Any]], assistant_raw: str, feedback: str
) -> None:
    messages.append({"role": "assistant", "content": assistant_raw})
    messages.append({"role": "user", "content": feedback})


def _parse_response(raw: str) -> MealPlanOutput:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        cleaned = "\n".join(lines)
    return MealPlanOutput.model_validate_json(cleaned)


def _enrich_day_plan(plan: DayPlan, recipes: list[dict]) -> DayPlanFull:
    """Post-hoc: подставляет ингредиенты из рецептов вместо LLM-генерации."""
    recipes_by_id = {r["id"] if isinstance(r, dict) else str(r.id): r for r in recipes}

    enriched_meals = []
    for meal in plan.meals:
        recipe = recipes_by_id.get(meal.recipe_id)
        ingredients = []
        if recipe:
            raw_ingredients = (
                recipe["ingredients"] if isinstance(recipe, dict) else recipe.ingredients
            )
            ingredients = [
                {"name": ing["name"], "amount": ing["amount"], "unit": ing["unit"]}
                for ing in (raw_ingredients or [])
            ]

        enriched_meals.append(
            MealItemFull(
                type=meal.type,
                time=meal.time,
                recipe_id=meal.recipe_id,
                title=meal.title,
                calories=meal.calories,
                protein=meal.protein,
                fat=meal.fat,
                carbs=meal.carbs,
                ingredients_summary=ingredients,
            )
        )

    return DayPlanFull(
        day_number=plan.day_number,
        total_calories=plan.total_calories,
        total_protein=plan.total_protein,
        total_fat=plan.total_fat,
        total_carbs=plan.total_carbs,
        meals=enriched_meals,
    )


async def generate_day_plan(
    user_profile: dict,
    recipes: list[dict],
    day_number: int = 1,
) -> DayPlanFull:
    """Генерирует план на 1 день с циклом рефлексии.

    Args:
        user_profile: dict с полями gender, age, weight_kg, height_cm, goal,
                      target_calories, allergies, preferences,
                      disliked_ingredients, diseases
        recipes: список рецептов из RAG (dict или ORM-объекты)
        day_number: номер дня

    Returns:
        DayPlanFull с ингредиентами из рецептов (не от LLM)
    """
    if not recipes:
        raise RuntimeError("No recipes available for generation after profile filters")

    templates = _load_prompt()
    system_prompt = _build_system_prompt(templates, user_profile, recipes)
    target_cal = user_profile["target_calories"]

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Составь план питания на день {day_number}. Верни JSON."},
    ]

    best_plan: DayPlan | None = None
    best_deviation = float("inf")

    for attempt in range(1, MAX_RETRIES + 1):
        logger.info("Generation attempt {}/{} for day {}", attempt, MAX_RETRIES, day_number)

        raw_response = ""
        try:
            raw_response = await _call_llm(messages)
            logger.debug("LLM raw response (attempt {}): {}", attempt, raw_response[:500])

            output = _parse_response(raw_response)
            plan = output.day
            plan.day_number = day_number

        except httpx.HTTPError as e:
            logger.error("LLM request failed on attempt {}: {}", attempt, e)
            _append_retry_feedback(
                messages,
                raw_response,
                "Ошибка запроса к LLM. Повтори генерацию в корректном JSON по заданной схеме.",
            )
            continue
        except (ValidationError, json.JSONDecodeError, KeyError) as e:
            logger.error("Parse error on attempt {}: {}", attempt, e)
            _append_retry_feedback(
                messages,
                raw_response,
                f"Ошибка парсинга: {e}. Верни корректный JSON согласно схеме.",
            )
            continue

        meal_schedule = user_profile.get("meal_schedule")
        is_valid, error_msg = validate_day_plan(plan, target_cal, meal_schedule=meal_schedule)
        current_deviation = abs(plan.total_calories - target_cal)

        if current_deviation < best_deviation:
            best_plan = plan
            best_deviation = current_deviation

        if is_valid:
            logger.info("Day {} generated successfully on attempt {}", day_number, attempt)
            return _enrich_day_plan(plan, recipes)

        logger.warning("Validation failed on attempt {}: {}", attempt, error_msg)

        retry_prompt = templates["retry"].render(
            validation_error=error_msg,
            target_calories=target_cal,
        )
        _append_retry_feedback(messages, raw_response, retry_prompt)

    if best_plan:
        logger.warning(
            "Returning best plan after {} attempts (deviation: {:.0f} kcal)",
            MAX_RETRIES,
            best_deviation,
        )
        return _enrich_day_plan(best_plan, recipes)

    raise RuntimeError(f"Failed to generate valid plan after {MAX_RETRIES} attempts")
