"""Source resolution and snapshotting for recipe catalog research."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from typing import Any

import httpx

from app.config import settings

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_DESC_RE = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
    re.IGNORECASE | re.DOTALL,
)
_RECIPE_INGREDIENT_RE = re.compile(
    r'itemProp="recipeIngredient">\s*(.*?)\s*</span>.*?<span[^>]*class="css-bsdd3p"[^>]*>\s*(.*?)\s*</span>',
    re.IGNORECASE | re.DOTALL,
)
_NUTRITION_RE = {
    "calories": re.compile(r'itemProp="calories">\s*([0-9]+(?:[.,][0-9]+)?)\s*</span>', re.IGNORECASE),
    "protein": re.compile(r'itemProp="proteinContent">\s*([0-9]+(?:[.,][0-9]+)?)\s*</span>', re.IGNORECASE),
    "fat": re.compile(r'itemProp="fatContent">\s*([0-9]+(?:[.,][0-9]+)?)\s*</span>', re.IGNORECASE),
    "carbs": re.compile(r'itemProp="carbohydrateContent">\s*([0-9]+(?:[.,][0-9]+)?)\s*</span>', re.IGNORECASE),
}
_RECIPE_YIELD_RE = re.compile(r'itemProp="recipeYield"[^>]*>\s*<span>\s*([0-9]+)\s*</span>', re.IGNORECASE)
_PREP_TIME_RE = re.compile(r"ГОТОВИТЬ:\s*</span><i[^>]*></i><div[^>]*>\s*([0-9]+)\s*минут", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_AMOUNT_RE = re.compile(r"^\s*([0-9]+(?:[.,][0-9]+)?)\s*(.*?)\s*$")
_UNIT_ALIASES = {
    "г": "g",
    "гр": "g",
    "грамм": "g",
    "грамма": "g",
    "граммов": "g",
    "кг": "kg",
    "мл": "ml",
    "л": "l",
    "штука": "piece",
    "штуки": "piece",
    "штук": "piece",
    "шт": "piece",
    "столовая ложка": "tbsp",
    "столовые ложки": "tbsp",
    "столовых ложек": "tbsp",
    "чайная ложка": "tsp",
    "чайные ложки": "tsp",
    "чайных ложек": "tsp",
    "ломтик": "slice",
    "ломтика": "slice",
    "ломтиков": "slice",
}


@dataclass
class ResolvedCatalogSource:
    source_url: str | None
    source_type: str
    source_snapshot: dict[str, Any]
    provenance: dict[str, Any]
    research_input: dict[str, Any]


def _clean_text(value: str, *, limit: int | None = None) -> str:
    text = unescape(_TAG_RE.sub(" ", value))
    text = _WS_RE.sub(" ", text).strip()
    if limit is not None and len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def _normalize_amount_unit(amount_text: str) -> tuple[float, str] | None:
    text = _clean_text(amount_text)
    match = _AMOUNT_RE.match(text)
    if not match:
        return None
    amount = float(match.group(1).replace(",", "."))
    raw_unit = match.group(2).strip().lower()
    unit = _UNIT_ALIASES.get(raw_unit)
    if unit is None and raw_unit.endswith("."):
        unit = _UNIT_ALIASES.get(raw_unit.rstrip("."))
    if unit is None:
        return None
    return amount, unit


def _extract_structured_recipe(html: str) -> dict[str, Any]:
    ingredients: list[dict[str, Any]] = []
    for raw_name, raw_amount in _RECIPE_INGREDIENT_RE.findall(html):
        name = _clean_text(raw_name)
        amount_unit = _normalize_amount_unit(raw_amount)
        if not name or amount_unit is None:
            continue
        amount, unit = amount_unit
        ingredients.append({"name": name, "amount": amount, "unit": unit, "amount_text": _clean_text(raw_amount)})

    nutrition: dict[str, float] = {}
    for key, pattern in _NUTRITION_RE.items():
        match = pattern.search(html)
        if match:
            nutrition[key] = float(match.group(1).replace(",", "."))

    structured: dict[str, Any] = {
        "ingredients": ingredients,
        "nutrition": nutrition,
    }
    yield_match = _RECIPE_YIELD_RE.search(html)
    if yield_match:
        structured["servings"] = int(yield_match.group(1))
    prep_match = _PREP_TIME_RE.search(html)
    if prep_match:
        structured["prep_time_min"] = int(prep_match.group(1))
    return structured


def _build_html_snapshot(url: str, html: str) -> ResolvedCatalogSource:
    title_match = _TITLE_RE.search(html)
    meta_match = _META_DESC_RE.search(html)
    title = _clean_text(title_match.group(1), limit=200) if title_match else None
    description = _clean_text(meta_match.group(1), limit=400) if meta_match else None
    excerpt = _clean_text(html, limit=settings.CATALOG_SOURCE_TEXT_CHAR_LIMIT)
    structured_recipe = _extract_structured_recipe(html)
    snapshot = {
        "title": title,
        "description": description,
        "html_excerpt": excerpt,
        "structured_recipe": structured_recipe,
    }
    provenance = {
        "resolver": "http_fetch",
        "content_type": "text/html",
        "source_url": url,
    }
    return ResolvedCatalogSource(
        source_url=url,
        source_type="web",
        source_snapshot=snapshot,
        provenance=provenance,
        research_input={
            "source_url": url,
            "source_type": "web",
            "source_snapshot": snapshot,
        },
    )


async def fetch_source_url(url: str) -> ResolvedCatalogSource:
    async with httpx.AsyncClient(timeout=settings.CATALOG_SOURCE_FETCH_TIMEOUT_SEC, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        full_body = response.text
        body_excerpt = full_body[: settings.CATALOG_SOURCE_MAX_BYTES]
        if "html" in content_type or "<html" in body_excerpt.lower():
            resolved = _build_html_snapshot(str(response.url), full_body)
            resolved.provenance["http_status"] = response.status_code
            return resolved
        excerpt = _clean_text(body_excerpt, limit=settings.CATALOG_SOURCE_TEXT_CHAR_LIMIT)
        return ResolvedCatalogSource(
            source_url=str(response.url),
            source_type="web",
            source_snapshot={"text_excerpt": excerpt},
            provenance={
                "resolver": "http_fetch",
                "content_type": content_type or "text/plain",
                "http_status": response.status_code,
                "source_url": str(response.url),
            },
            research_input={
                "source_url": str(response.url),
                "source_type": "web",
                "source_snapshot": {"text_excerpt": excerpt},
            },
        )


async def resolve_catalog_source(seed_input: dict[str, Any]) -> ResolvedCatalogSource:
    if seed_input.get("source_url"):
        resolved = await fetch_source_url(str(seed_input["source_url"]))
        merged_provenance = {**resolved.provenance, **(seed_input.get("provenance") or {})}
        research_input = {**seed_input, **resolved.research_input, "provenance": merged_provenance}
        return ResolvedCatalogSource(
            source_url=resolved.source_url,
            source_type=resolved.source_type,
            source_snapshot=resolved.source_snapshot,
            provenance=merged_provenance,
            research_input=research_input,
        )

    if seed_input.get("payload"):
        payload = seed_input["payload"]
        snapshot = {
            "title": payload.get("title"),
            "description": payload.get("description"),
            "payload_excerpt": {
                "title": payload.get("title"),
                "meal_type": payload.get("meal_type"),
                "ingredients": payload.get("ingredients", [])[:8],
            },
        }
        provenance = {
            "resolver": "inline_payload",
            "source_name": seed_input.get("source_name") or "inline_payload",
            **(seed_input.get("provenance") or {}),
        }
        return ResolvedCatalogSource(
            source_url=seed_input.get("source_url"),
            source_type=seed_input.get("source_type") or "payload",
            source_snapshot=snapshot,
            provenance=provenance,
            research_input={
                **seed_input,
                "source_snapshot": snapshot,
                "provenance": provenance,
            },
        )

    if seed_input.get("source_snapshot"):
        provenance = {
            "resolver": "provided_source_snapshot",
            **(seed_input.get("provenance") or {}),
        }
        return ResolvedCatalogSource(
            source_url=seed_input.get("source_url"),
            source_type=seed_input.get("source_type") or "web",
            source_snapshot=seed_input["source_snapshot"],
            provenance=provenance,
            research_input={
                **seed_input,
                "provenance": provenance,
            },
        )

    if seed_input.get("raw_text"):
        excerpt = _clean_text(str(seed_input["raw_text"]), limit=settings.CATALOG_SOURCE_TEXT_CHAR_LIMIT)
        provenance = {
            "resolver": "raw_text",
            **(seed_input.get("provenance") or {}),
        }
        return ResolvedCatalogSource(
            source_url=seed_input.get("source_url"),
            source_type=seed_input.get("source_type") or "raw_text",
            source_snapshot={"text_excerpt": excerpt},
            provenance=provenance,
            research_input={
                **seed_input,
                "source_snapshot": {"text_excerpt": excerpt},
                "provenance": provenance,
            },
        )

    provenance = {
        "resolver": "seed_input_fallback",
        **(seed_input.get("provenance") or {}),
    }
    return ResolvedCatalogSource(
        source_url=seed_input.get("source_url"),
        source_type=seed_input.get("source_type") or "seed_input",
        source_snapshot={"seed_input": seed_input},
        provenance=provenance,
        research_input={
            **seed_input,
            "source_snapshot": {"seed_input": seed_input},
            "provenance": provenance,
        },
    )
