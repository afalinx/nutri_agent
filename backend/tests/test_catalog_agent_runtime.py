"""Tests for catalog agent runtime harness."""

from __future__ import annotations

import uuid

import pytest

from app.core import catalog_agent_runtime
from app.core.catalog_ingest import ResearchOutput, VerificationOutput
from app.db.models import RecipeCandidateStatus, RecipeReviewVerdict


class _FakeRecipe:
    def __init__(self, recipe_id: str = "recipe-1"):
        self.id = uuid.UUID("11111111-1111-1111-1111-111111111111")
        self.title = "Chicken bowl"
        self.ingredients_short = "Chicken, Rice"


class _FakeCandidate:
    def __init__(self, status=RecipeCandidateStatus.pending, validation_report=None):
        self.id = uuid.UUID("22222222-2222-2222-2222-222222222222")
        self.status = status
        self.validation_report = validation_report or {"ok": True, "reason_codes": [], "notes": []}
        self.source_snapshot = {"title": "Chicken bowl"}
        self.provenance = {"trace": ["research-agent"]}


class _FakeReview:
    def __init__(self):
        self.id = uuid.UUID("33333333-3333-3333-3333-333333333333")


@pytest.mark.asyncio
async def test_catalog_agent_runtime_success(monkeypatch):
    progress_events: list[dict] = []

    async def fake_research(seed_input: dict):
        return ResearchOutput(
            payload={
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
            source_url="https://example.com/recipe",
            source_type="web",
            source_snapshot={"title": "Chicken bowl"},
            provenance={"trace": ["research-agent"], "seed": seed_input},
            submitted_by="research-agent",
        )

    async def fake_create_candidate(*args, **kwargs):
        return _FakeCandidate()

    async def fake_verify(candidate):
        return VerificationOutput(
            verdict=RecipeReviewVerdict.accept,
            reviewer="verification-agent",
            reason_codes=[],
            notes="ok",
        )

    async def fake_add_review(*args, **kwargs):
        return _FakeReview()

    async def fake_admit(*args, **kwargs):
        return _FakeRecipe()

    monkeypatch.setattr(catalog_agent_runtime, "create_recipe_candidate", fake_create_candidate)
    monkeypatch.setattr(catalog_agent_runtime, "add_candidate_review", fake_add_review)
    monkeypatch.setattr(catalog_agent_runtime, "admit_recipe_candidate", fake_admit)

    result = await catalog_agent_runtime.run_catalog_agent_pipeline(
        session=object(),
        seed_input={"query": "high protein lunch"},
        research_agent=fake_research,
        verification_agent=fake_verify,
        progress_callback=lambda state: progress_events.append(state),
    )

    assert result.status == RecipeCandidateStatus.accepted.value
    assert result.recipe_id == "11111111-1111-1111-1111-111111111111"
    assert result.review_id == "33333333-3333-3333-3333-333333333333"
    assert progress_events[-1]["steps"][-1]["status"] == "completed"


@pytest.mark.asyncio
async def test_catalog_agent_runtime_stops_after_failed_candidate_validation(monkeypatch):
    async def fake_research(seed_input: dict):
        return ResearchOutput(payload={"title": "bad"})

    async def fake_create_candidate(*args, **kwargs):
        return _FakeCandidate(
            status=RecipeCandidateStatus.rejected,
            validation_report={
                "ok": False,
                "reason_codes": ["invalid_recipe_payload"],
                "notes": ["bad payload"],
            },
        )

    async def fake_verify(candidate):
        raise AssertionError("verify should not run after candidate rejection")

    monkeypatch.setattr(catalog_agent_runtime, "create_recipe_candidate", fake_create_candidate)

    result = await catalog_agent_runtime.run_catalog_agent_pipeline(
        session=object(),
        seed_input={"query": "bad"},
        research_agent=fake_research,
        verification_agent=fake_verify,
    )

    assert result.status == "FAILED"
    assert result.reason_codes == ["invalid_recipe_payload"]
    assert result.current_step == "candidate"


@pytest.mark.asyncio
async def test_catalog_agent_runtime_returns_review_status_without_admission(monkeypatch):
    async def fake_research(seed_input: dict):
        return ResearchOutput(payload={"title": "candidate"})

    async def fake_create_candidate(*args, **kwargs):
        return _FakeCandidate()

    async def fake_verify(candidate):
        return VerificationOutput(
            verdict=RecipeReviewVerdict.review,
            reviewer="verification-agent",
            reason_codes=["non_food_ingredient_suspected"],
            notes="needs manual review",
        )

    async def fake_add_review(*args, **kwargs):
        return _FakeReview()

    async def fake_admit(*args, **kwargs):
        raise AssertionError("admit should not run when verification returns REVIEW")

    monkeypatch.setattr(catalog_agent_runtime, "create_recipe_candidate", fake_create_candidate)
    monkeypatch.setattr(catalog_agent_runtime, "add_candidate_review", fake_add_review)
    monkeypatch.setattr(catalog_agent_runtime, "admit_recipe_candidate", fake_admit)

    result = await catalog_agent_runtime.run_catalog_agent_pipeline(
        session=object(),
        seed_input={"query": "suspicious"},
        research_agent=fake_research,
        verification_agent=fake_verify,
    )

    assert result.status == RecipeCandidateStatus.review.value
    assert result.recipe_id is None
    assert result.reason_codes == ["non_food_ingredient_suspected"]
