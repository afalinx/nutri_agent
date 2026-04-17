"""LLM-backed research and verification agents for recipe catalog ingest."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import yaml
from jinja2 import Template
from pydantic import BaseModel, Field, ValidationError

from app.config import settings
from app.core.catalog_ingest import ResearchOutput, VerificationOutput
from app.core.catalog_sources import resolve_catalog_source
from app.db.models import RecipeCandidate, RecipeReviewVerdict

PROMPTS_DIR = Path(__file__).parent / "agent" / "prompts"


class CatalogResearchLLMOutput(BaseModel):
    payload: dict[str, Any]
    source_url: str | None = None
    source_type: str | None = None
    source_snapshot: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None
    submitted_by: str | None = None


class CatalogVerificationLLMOutput(BaseModel):
    verdict: RecipeReviewVerdict
    reason_codes: list[str] = Field(default_factory=list)
    notes: str | None = None
    review_payload: dict[str, Any] | None = None
    reviewer: str | None = None


def _coerce_recipe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return payload
    nested_recipe = payload.get("recipe")
    if isinstance(nested_recipe, dict):
        return nested_recipe
    return payload


def _merge_source_snapshots(
    base_snapshot: dict[str, Any] | None,
    llm_snapshot: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if base_snapshot is None:
        return llm_snapshot
    if llm_snapshot is None:
        return base_snapshot
    return {**base_snapshot, **llm_snapshot}


def _ingredient_mass_grams(ingredients: list[dict[str, Any]]) -> float:
    total = 0.0
    for ingredient in ingredients:
        amount = float(ingredient.get("amount") or 0)
        unit = str(ingredient.get("unit") or "").lower()
        if unit == "g":
            total += amount
        elif unit == "kg":
            total += amount * 1000
        elif unit == "ml":
            total += amount
        elif unit == "l":
            total += amount * 1000
    return total


def _repair_recipe_payload_from_snapshot(payload: dict[str, Any], source_snapshot: dict[str, Any] | None) -> dict[str, Any]:
    repaired = dict(payload)
    structured = ((source_snapshot or {}).get("structured_recipe") or {})
    structured_ingredients = structured.get("ingredients") or []
    if structured_ingredients and (
        not repaired.get("ingredients")
        or all(isinstance(item, str) for item in repaired.get("ingredients", []))
    ):
        repaired["ingredients"] = [
            {"name": item["name"], "amount": item["amount"], "unit": item["unit"]}
            for item in structured_ingredients
            if isinstance(item, dict) and item.get("name") and item.get("amount") and item.get("unit")
        ]

    nutrition = structured.get("nutrition") or {}
    for key in ("calories", "protein", "fat", "carbs"):
        if repaired.get(key) in (None, "", 0) and nutrition.get(key) is not None:
            repaired[key] = nutrition[key]

    if repaired.get("prep_time_min") in (None, "", 0) and structured.get("prep_time_min") is not None:
        repaired["prep_time_min"] = structured["prep_time_min"]

    ingredients_short = repaired.get("ingredients_short")
    if isinstance(ingredients_short, list):
        repaired["ingredients_short"] = ", ".join(
            str(item).strip() for item in ingredients_short if str(item).strip()
        ) or None

    servings = structured.get("servings")
    ingredients = repaired.get("ingredients") or []
    if (
        isinstance(servings, int)
        and servings > 1
        and ingredients
        and all(isinstance(item, dict) for item in ingredients)
        and _ingredient_mass_grams(ingredients) > 2300
    ):
        repaired["ingredients"] = [
            {
                **item,
                "amount": round(float(item["amount"]) / servings, 1),
            }
            for item in ingredients
        ]
    return repaired


def _load_prompt_templates() -> dict[str, Template]:
    with open(PROMPTS_DIR / "catalog_ingest.yml", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return {key: Template(value) for key, value in raw.items()}


async def _call_llm(messages: list[dict[str, str]]) -> str:
    async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SEC) as client:
        response = await client.post(
            f"{settings.OPENROUTER_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.LLM_MODEL_NAME,
                "messages": messages,
                "temperature": 0,
                "max_tokens": settings.LLM_MAX_OUTPUT_TOKENS,
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


async def _call_llm_json(messages: list[dict[str, str]], output_model: type[BaseModel]) -> BaseModel:
    last_error: Exception | None = None
    attempt_messages = list(messages)
    max_attempts = 2
    for attempt in range(max_attempts):
        raw = await _call_llm(attempt_messages)
        try:
            return output_model.model_validate_json(raw)
        except ValidationError as exc:
            last_error = exc
            if attempt == max_attempts - 1:
                break
            attempt_messages = [
                *messages,
                {
                    "role": "assistant",
                    "content": raw[: max(200, settings.LLM_RETRY_RESPONSE_PREVIEW_CHARS)],
                },
                {
                    "role": "user",
                    "content": (
                        "Your previous answer was invalid or truncated JSON. "
                        "Return one complete valid JSON object only, with all required fields."
                    ),
                },
            ]
    assert last_error is not None
    raise last_error


def build_research_agent():
    templates = _load_prompt_templates()
    system_prompt = templates["research_system"].render()

    async def research_agent(seed_input: dict[str, Any]) -> ResearchOutput:
        resolved_source = await resolve_catalog_source(seed_input)
        user_prompt = templates["research_user"].render(
            seed_input_json=json.dumps(resolved_source.research_input, ensure_ascii=False, indent=2)
        )
        parsed = await _call_llm_json(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            CatalogResearchLLMOutput,
        )
        merged_snapshot = _merge_source_snapshots(
            resolved_source.source_snapshot,
            parsed.source_snapshot,
        )
        payload = _repair_recipe_payload_from_snapshot(
            _coerce_recipe_payload(parsed.payload),
            merged_snapshot,
        )
        return ResearchOutput(
            payload=payload,
            source_url=parsed.source_url or resolved_source.source_url,
            source_type=parsed.source_type or resolved_source.source_type,
            source_snapshot=merged_snapshot,
            provenance={**resolved_source.provenance, **(parsed.provenance or {})},
            submitted_by=parsed.submitted_by or "catalog_research_llm",
        )

    return research_agent


def build_verification_agent():
    templates = _load_prompt_templates()
    system_prompt = templates["verify_system"].render()

    async def verification_agent(candidate: RecipeCandidate) -> VerificationOutput:
        user_prompt = templates["verify_user"].render(
            candidate_json=json.dumps(
                {
                    "id": str(candidate.id),
                    "source_url": candidate.source_url,
                    "source_type": candidate.source_type,
                    "source_snapshot": candidate.source_snapshot,
                    "provenance": candidate.provenance,
                    "payload": candidate.payload,
                    "normalized_payload": candidate.normalized_payload,
                    "validation_report": candidate.validation_report,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        parsed = await _call_llm_json(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            CatalogVerificationLLMOutput,
        )
        return VerificationOutput(
            verdict=parsed.verdict,
            reviewer=parsed.reviewer or "catalog_verifier_llm",
            reason_codes=parsed.reason_codes,
            notes=parsed.notes,
            review_payload=parsed.review_payload,
        )

    return verification_agent
