"""Tests for LLM-backed catalog agent adapters."""

from __future__ import annotations

import json
import uuid

import pytest

from app.core import catalog_agents
from app.db.models import RecipeReviewVerdict


class _FakeCandidate:
    def __init__(self):
        self.id = uuid.UUID("22222222-2222-2222-2222-222222222222")
        self.source_url = "https://example.com/recipe"
        self.source_type = "web"
        self.source_snapshot = {"title": "Chicken bowl"}
        self.provenance = {"trace": ["research-agent"]}
        self.payload = {"title": "Chicken bowl"}
        self.normalized_payload = {"title": "Chicken bowl", "meal_type": "lunch"}
        self.validation_report = {"ok": True}


@pytest.mark.asyncio
async def test_build_research_agent_maps_llm_json(monkeypatch):
    async def fake_call_llm(messages):
        assert messages[0]["role"] == "system"
        assert "JSON" in messages[1]["content"]
        return json.dumps(
            {
                "payload": {
                    "title": "Chicken bowl",
                    "ingredients": [
                        {"name": "Chicken", "amount": 200, "unit": "g"},
                        {"name": "Rice", "amount": 150, "unit": "g"},
                    ],
                    "calories": 520,
                    "protein": 45,
                    "fat": 6,
                    "carbs": 70,
                    "meal_type": "lunch",
                },
                "source_url": "https://example.com/recipe",
                "source_type": "web",
                "source_snapshot": {"title": "Chicken bowl"},
                "provenance": {"trace": ["research-agent"]},
                "submitted_by": "catalog_research_llm",
            }
        )

    monkeypatch.setattr(catalog_agents, "_call_llm", fake_call_llm)

    agent = catalog_agents.build_research_agent()
    result = await agent({"query": "high protein lunch"})

    assert result.payload["title"] == "Chicken bowl"
    assert result.source_snapshot["title"] == "Chicken bowl"
    assert result.submitted_by == "catalog_research_llm"


@pytest.mark.asyncio
async def test_build_research_agent_unwraps_nested_recipe_payload(monkeypatch):
    async def fake_call_llm(messages):
        return json.dumps(
            {
                "payload": {
                    "recipe": {
                        "title": "Chicken bowl",
                        "ingredients": [
                            {"name": "Chicken", "amount": 200, "unit": "g"},
                            {"name": "Rice", "amount": 150, "unit": "g"},
                        ],
                        "calories": 520,
                        "protein": 45,
                        "fat": 6,
                        "carbs": 70,
                        "meal_type": "lunch",
                    }
                },
                "source_url": "https://example.com/recipe",
                "source_type": "web",
            }
        )

    monkeypatch.setattr(catalog_agents, "_call_llm", fake_call_llm)

    agent = catalog_agents.build_research_agent()
    result = await agent({"query": "high protein lunch"})

    assert result.payload["title"] == "Chicken bowl"
    assert "recipe" not in result.payload


@pytest.mark.asyncio
async def test_build_research_agent_repairs_ingredients_from_structured_snapshot(monkeypatch):
    async def fake_call_llm(messages):
        return json.dumps(
            {
                "payload": {
                    "title": "Chicken bowl",
                    "ingredients": ["Chicken", "Rice"],
                    "calories": None,
                    "protein": None,
                    "fat": None,
                    "carbs": None,
                    "meal_type": "lunch",
                },
                "source_url": "https://example.com/recipe",
                "source_type": "web",
            }
        )

    monkeypatch.setattr(catalog_agents, "_call_llm", fake_call_llm)

    agent = catalog_agents.build_research_agent()
    result = await agent(
        {
            "query": "high protein lunch",
            "source_snapshot": {
                "structured_recipe": {
                    "ingredients": [
                        {"name": "Chicken", "amount": 200, "unit": "g"},
                        {"name": "Rice", "amount": 150, "unit": "g"},
                    ],
                    "nutrition": {"calories": 520, "protein": 45, "fat": 6, "carbs": 70},
                    "prep_time_min": 25,
                }
            },
        }
    )

    assert result.payload["ingredients"] == [
        {"name": "Chicken", "amount": 200, "unit": "g"},
        {"name": "Rice", "amount": 150, "unit": "g"},
    ]
    assert result.payload["calories"] == 520
    assert result.payload["prep_time_min"] == 25


@pytest.mark.asyncio
async def test_build_research_agent_joins_ingredients_short_list(monkeypatch):
    async def fake_call_llm(messages):
        return json.dumps(
            {
                "payload": {
                    "title": "Chicken bowl",
                    "ingredients": [
                        {"name": "Chicken", "amount": 200, "unit": "g"},
                        {"name": "Rice", "amount": 150, "unit": "g"},
                    ],
                    "calories": 520,
                    "protein": 45,
                    "fat": 6,
                    "carbs": 70,
                    "meal_type": "lunch",
                    "ingredients_short": ["Chicken", "Rice"],
                },
                "source_url": "https://example.com/recipe",
                "source_type": "web",
            }
        )

    monkeypatch.setattr(catalog_agents, "_call_llm", fake_call_llm)

    agent = catalog_agents.build_research_agent()
    result = await agent({"query": "high protein lunch"})

    assert result.payload["ingredients_short"] == "Chicken, Rice"


@pytest.mark.asyncio
async def test_build_research_agent_preserves_structured_snapshot_and_scales_per_serving(monkeypatch):
    async def fake_call_llm(messages):
        return json.dumps(
            {
                "payload": {
                    "title": "Lasagna",
                    "ingredients": [
                        {"name": "Milk", "amount": 750, "unit": "ml"},
                        {"name": "Cheese", "amount": 500, "unit": "g"},
                        {"name": "Meat", "amount": 600, "unit": "g"},
                        {"name": "Sauce", "amount": 600, "unit": "g"},
                    ],
                    "calories": 965,
                    "protein": 50,
                    "fat": 73,
                    "carbs": 24,
                    "meal_type": "dinner",
                },
                "source_url": "https://example.com/recipe",
                "source_type": "web",
                "source_snapshot": {"title": "Lasagna page"},
            }
        )

    monkeypatch.setattr(catalog_agents, "_call_llm", fake_call_llm)

    agent = catalog_agents.build_research_agent()
    result = await agent(
        {
            "query": "lasagna",
            "source_snapshot": {
                "structured_recipe": {
                    "servings": 6,
                }
            },
        }
    )

    assert result.source_snapshot["title"] == "Lasagna page"
    assert result.source_snapshot["structured_recipe"]["servings"] == 6
    assert result.payload["ingredients"][0]["amount"] == 125.0


@pytest.mark.asyncio
async def test_build_verification_agent_maps_llm_json(monkeypatch):
    async def fake_call_llm(messages):
        assert messages[0]["role"] == "system"
        assert "Review this recipe candidate" in messages[1]["content"]
        return json.dumps(
            {
                "verdict": "REVIEW",
                "reason_codes": ["uncertain_source"],
                "notes": "Source support is weak",
                "review_payload": {"confidence": "low"},
                "reviewer": "catalog_verifier_llm",
            }
        )

    monkeypatch.setattr(catalog_agents, "_call_llm", fake_call_llm)

    agent = catalog_agents.build_verification_agent()
    result = await agent(_FakeCandidate())

    assert result.verdict == RecipeReviewVerdict.review
    assert result.reason_codes == ["uncertain_source"]
    assert result.review_payload == {"confidence": "low"}


@pytest.mark.asyncio
async def test_call_llm_json_retries_on_invalid_json(monkeypatch):
    responses = iter([
        '{"payload": {"title": "Broken"',
        json.dumps(
            {
                "payload": {
                    "title": "Chicken bowl",
                    "ingredients": [
                        {"name": "Chicken", "amount": 200, "unit": "g"},
                        {"name": "Rice", "amount": 150, "unit": "g"},
                    ],
                    "calories": 520,
                    "protein": 45,
                    "fat": 6,
                    "carbs": 70,
                    "meal_type": "lunch",
                }
            }
        ),
    ])

    async def fake_call_llm(messages):
        return next(responses)

    monkeypatch.setattr(catalog_agents, "_call_llm", fake_call_llm)

    parsed = await catalog_agents._call_llm_json(
        [{"role": "system", "content": "Return JSON only"}],
        catalog_agents.CatalogResearchLLMOutput,
    )

    assert parsed.payload["title"] == "Chicken bowl"
