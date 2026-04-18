"""Tests for catalog candidate workflow."""

from __future__ import annotations

import uuid

import pytest

from app.core import catalog_ingest
from app.db.models import RecipeCandidateStatus, RecipeReviewVerdict


class _FakeRecipe:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", uuid.uuid4())
        for key, value in kwargs.items():
            setattr(self, key, value)


class _FakeCandidate:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", uuid.uuid4())
        self.source_url = kwargs.get("source_url")
        self.source_type = kwargs.get("source_type")
        self.source_snapshot = kwargs.get("source_snapshot")
        self.provenance = kwargs.get("provenance")
        self.payload = kwargs.get("payload")
        self.normalized_payload = kwargs.get("normalized_payload")
        self.validation_report = kwargs.get("validation_report")
        self.status = kwargs.get("status", RecipeCandidateStatus.pending)
        self.submitted_by = kwargs.get("submitted_by")
        self.admitted_recipe_id = kwargs.get("admitted_recipe_id")


class _FakeReview:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", uuid.uuid4())
        self.candidate_id = kwargs["candidate_id"]
        self.reviewer = kwargs.get("reviewer")
        self.verdict = kwargs["verdict"]
        self.reason_codes = kwargs.get("reason_codes", [])
        self.notes = kwargs.get("notes")
        self.review_payload = kwargs.get("review_payload")


class _FakeScalarResult:
    def __init__(self, item):
        self._item = item

    def scalar_one_or_none(self):
        return self._item


class _FakeSession:
    def __init__(self):
        self.candidates: dict[uuid.UUID, _FakeCandidate] = {}
        self.recipes: list[_FakeRecipe] = []
        self.reviews: list[_FakeReview] = []

    def add(self, obj):
        if isinstance(obj, _FakeCandidate):
            self.candidates[obj.id] = obj
        elif isinstance(obj, _FakeRecipe):
            self.recipes.append(obj)
        elif isinstance(obj, _FakeReview):
            self.reviews.append(obj)

    async def commit(self):
        return None

    async def refresh(self, obj):
        return None

    async def flush(self):
        return None

    async def get(self, model, obj_id):
        if model is catalog_ingest.RecipeCandidate:
            return self.candidates.get(obj_id)
        return None

    async def execute(self, stmt):
        title = stmt._where_criteria[0].right.value
        ingredients_short = stmt._where_criteria[1].right.value
        for recipe in self.recipes:
            if recipe.title == title and recipe.ingredients_short == ingredients_short:
                return _FakeScalarResult(recipe)
        return _FakeScalarResult(None)


@pytest.fixture(autouse=True)
def _patch_models(monkeypatch):
    monkeypatch.setattr(catalog_ingest, "RecipeCandidate", _FakeCandidate)
    monkeypatch.setattr(catalog_ingest, "RecipeCandidateReview", _FakeReview)
    monkeypatch.setattr(catalog_ingest, "Recipe", _FakeRecipe)
    async def fake_find_duplicate_recipe(session, *, title, ingredients_short):
        for recipe in session.recipes:
            if recipe.title == title and recipe.ingredients_short == ingredients_short:
                return recipe
        return None
    monkeypatch.setattr(catalog_ingest, "_find_duplicate_recipe", fake_find_duplicate_recipe)


def _payload():
    return {
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
        "tags": ["high protein"],
    }


@pytest.mark.asyncio
async def test_create_recipe_candidate_rejects_invalid_payload():
    session = _FakeSession()

    candidate = await catalog_ingest.create_recipe_candidate(
        session,
        payload={
            "title": "bad",
            "ingredients": [{"name": "penis кита", "amount": 1, "unit": "piece"}],
            "calories": 100,
            "protein": 1,
            "fat": 1,
            "carbs": 1,
        },
        source_url=None,
        source_type="agent",
        submitted_by="research-agent",
    )

    assert candidate.status == RecipeCandidateStatus.rejected
    assert candidate.validation_report["ok"] is False


@pytest.mark.asyncio
async def test_review_and_admission_flow_accepts_valid_candidate():
    session = _FakeSession()
    candidate = await catalog_ingest.create_recipe_candidate(
        session,
        payload=_payload(),
        source_url="https://example.com/recipe",
        source_type="web",
        submitted_by="research-agent",
    )

    review = await catalog_ingest.add_candidate_review(
        session,
        candidate_id=str(candidate.id),
        verdict=RecipeReviewVerdict.accept,
        reviewer="verification-agent",
        reason_codes=[],
        notes="Looks good",
    )
    recipe = await catalog_ingest.admit_recipe_candidate(session, candidate_id=str(candidate.id))

    assert review.verdict == RecipeReviewVerdict.accept
    assert candidate.status == RecipeCandidateStatus.accepted
    assert recipe.title == "Chicken bowl"
    assert candidate.admitted_recipe_id == recipe.id


@pytest.mark.asyncio
async def test_run_catalog_ingest_job_executes_research_verify_admit_flow():
    session = _FakeSession()

    async def research_step(seed_input: dict):
        return catalog_ingest.ResearchOutput(
            payload=_payload(),
            source_url="https://example.com/recipe",
            source_type="web",
            source_snapshot={"title": "Chicken bowl", "html_excerpt": "<h1>Chicken bowl</h1>"},
            provenance={"trace": ["research"], "seed": seed_input},
            submitted_by="research-agent",
        )

    async def verification_step(candidate):
        assert candidate.source_snapshot["title"] == "Chicken bowl"
        assert candidate.provenance["trace"] == ["research"]
        return catalog_ingest.VerificationOutput(
            verdict=RecipeReviewVerdict.accept,
            reviewer="verification-agent",
            reason_codes=[],
            notes="verified",
            review_payload={"checks": ["edible", "plausible_macros"]},
        )

    result = await catalog_ingest.run_catalog_ingest_job(
        session,
        seed_input={"query": "high protein chicken lunch"},
        research_step=research_step,
        verification_step=verification_step,
    )

    assert result.status == RecipeCandidateStatus.accepted.value
    assert result.recipe_id is not None
    assert result.review_id is not None


@pytest.mark.asyncio
async def test_run_catalog_ingest_job_stops_on_review_verdict():
    session = _FakeSession()

    async def research_step(seed_input: dict):
        return catalog_ingest.ResearchOutput(
            payload=_payload(),
            source_url="https://example.com/recipe",
            source_type="web",
            submitted_by="research-agent",
        )

    async def verification_step(candidate):
        return catalog_ingest.VerificationOutput(
            verdict=RecipeReviewVerdict.review,
            reviewer="verification-agent",
            reason_codes=["non_food_ingredient_suspected"],
            notes="Needs manual review",
        )

    result = await catalog_ingest.run_catalog_ingest_job(
        session,
        seed_input={"query": "weird recipe"},
        research_step=research_step,
        verification_step=verification_step,
    )

    assert result.status == RecipeCandidateStatus.review.value


def test_build_validation_report_uses_specific_reason_code_for_unsafe_combination():
    report = catalog_ingest.build_validation_report(
        {
            "title": "Окрошка на молоке",
            "ingredients": [
                {"name": "Молоко", "amount": 500, "unit": "ml"},
                {"name": "Огурцы солёные", "amount": 150, "unit": "g"},
            ],
            "calories": 280,
            "protein": 10,
            "fat": 14,
            "carbs": 22,
            "meal_type": "lunch",
        }
    )

    assert report["ok"] is False
    assert report["reason_codes"] == ["unsafe_combination"]


@pytest.mark.asyncio
async def test_admit_recipe_candidate_invalidates_recipe_cache(monkeypatch):
    session = _FakeSession()
    deleted_keys: list[str] = []

    async def fake_delete(key: str):
        deleted_keys.append(key)

    monkeypatch.setattr(catalog_ingest.cache, "delete", fake_delete)

    candidate = await catalog_ingest.create_recipe_candidate(
        session,
        payload=_payload(),
        source_url="https://example.com/recipe",
        source_type="web",
        submitted_by="research-agent",
    )
    await catalog_ingest.add_candidate_review(
        session,
        candidate_id=str(candidate.id),
        verdict=RecipeReviewVerdict.accept,
        reviewer="verification-agent",
        reason_codes=[],
        notes="Looks good",
    )

    await catalog_ingest.admit_recipe_candidate(session, candidate_id=str(candidate.id))

    assert deleted_keys == ["recipes:all"]
