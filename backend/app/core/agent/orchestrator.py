"""Оркестратор генерации плана питания.

Пайплайн: Профиль → RAG → LLM (Structured Output) → Валидация → [Рефлексия] → Результат.
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
from app.core.agent.schemas import DayPlan, MealPlanOutput
from app.core.skills.validator import validate_day_plan
from app.db.models import Recipe

PROMPTS_DIR = Path(__file__).parent / "prompts"
MAX_RETRIES = 3


def _load_prompt() -> dict[str, Template]:
    with open(PROMPTS_DIR / "meal_plan.yml", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return {key: Template(val) for key, val in raw.items()}


def _build_system_prompt(
    templates: dict[str, Template],
    user_profile: dict,
    recipes: list[Recipe],
) -> str:
    recipe_dicts = [
        {
            "id": str(r.id),
            "title": r.title,
            "calories": r.calories,
            "protein": r.protein,
            "fat": r.fat,
            "carbs": r.carbs,
            "tags": r.tags or [],
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


def _append_retry_feedback(messages: list[dict[str, Any]], assistant_raw: str, feedback: str) -> None:
    messages.append({"role": "assistant", "content": assistant_raw})
    messages.append({"role": "user", "content": feedback})


def _parse_response(raw: str) -> MealPlanOutput:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        cleaned = "\n".join(lines)
    return MealPlanOutput.model_validate_json(cleaned)


async def generate_day_plan(
    user_profile: dict,
    recipes: list[Recipe],
    day_number: int = 1,
) -> DayPlan:
    """Генерирует план на 1 день с циклом рефлексии.

    Args:
        user_profile: dict с полями gender, age, weight_kg, height_cm, goal,
                      target_calories, allergies, preferences,
                      disliked_ingredients, diseases
        recipes: список рецептов из RAG
        day_number: номер дня

    Returns:
        Валидный DayPlan
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

        is_valid, error_msg = validate_day_plan(plan, target_cal)
        current_deviation = abs(plan.total_calories - target_cal)

        if current_deviation < best_deviation:
            best_plan = plan
            best_deviation = current_deviation

        if is_valid:
            logger.info("Day {} generated successfully on attempt {}", day_number, attempt)
            return plan

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
        return best_plan

    raise RuntimeError(f"Failed to generate valid plan after {MAX_RETRIES} attempts")
