"""Unit tests for catalog routes without live DB access."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes import catalog
from app.db.models import RecipeCandidateStatus, RecipeReviewVerdict


class _FakeAsyncResult:
    def __init__(self, state: str, result=None, info=None):
        self.state = state
        self.result = result
        self.info = info


@pytest.mark.asyncio
async def test_create_candidate_route_uses_ingest_service(monkeypatch):
    candidate_id = uuid.uuid4()

    async def fake_create_recipe_candidate(db, **kwargs):
        return SimpleNamespace(
            id=candidate_id,
            source_url=kwargs["source_url"],
            source_type=kwargs["source_type"],
            source_snapshot=kwargs["source_snapshot"],
            provenance=kwargs["provenance"],
            payload=kwargs["payload"],
            normalized_payload={"title": "Chicken bowl"},
            validation_report={"ok": True},
            status="PENDING",
            admitted_recipe_id=None,
        )

    monkeypatch.setattr(catalog, "create_recipe_candidate", fake_create_recipe_candidate)

    response = await catalog.create_candidate(
        catalog.CandidateCreateRequest(
            payload={"title": "Chicken bowl"},
            source_url="https://example.com/recipe",
            source_type="web",
            source_snapshot={"title": "Chicken bowl"},
            provenance={"trace": ["research-agent"]},
            submitted_by="research-agent",
        ),
        db=object(),
    )

    assert response.id == candidate_id
    assert response.validation_report == {"ok": True}
    assert response.source_snapshot == {"title": "Chicken bowl"}
    assert response.provenance == {"trace": ["research-agent"]}


@pytest.mark.asyncio
async def test_create_review_route_maps_missing_candidate(monkeypatch):
    async def fake_add_candidate_review(*args, **kwargs):
        raise ValueError("RecipeCandidate not found")

    monkeypatch.setattr(catalog, "add_candidate_review", fake_add_candidate_review)

    with pytest.raises(HTTPException, match="RecipeCandidate not found"):
        await catalog.create_review(
            uuid.uuid4(),
            catalog.ReviewCreateRequest(verdict=RecipeReviewVerdict.accept),
            db=object(),
        )


@pytest.mark.asyncio
async def test_admit_candidate_route_returns_recipe_id(monkeypatch):
    recipe_id = uuid.uuid4()

    async def fake_admit_recipe_candidate(db, *, candidate_id: str):
        return SimpleNamespace(id=recipe_id)

    monkeypatch.setattr(catalog, "admit_recipe_candidate", fake_admit_recipe_candidate)

    response = await catalog.admit_candidate(uuid.uuid4(), db=object())

    assert response.recipe_id == recipe_id


@pytest.mark.asyncio
async def test_queue_catalog_ingest_job_sends_celery_task(monkeypatch):
    monkeypatch.setattr(
        catalog.celery_app,
        "send_task",
        lambda name, args: SimpleNamespace(id="task-123", name=name, args=args),
    )

    response = await catalog.queue_catalog_ingest_job(
        catalog.CatalogIngestJobRequest(seed_input={"query": "high protein lunch"})
    )

    assert response.task_id == "task-123"


@pytest.mark.asyncio
async def test_get_catalog_task_status_uses_progress_meta(monkeypatch):
    monkeypatch.setattr(
        catalog,
        "AsyncResult",
        lambda task_id, app=None: _FakeAsyncResult(
            "GENERATING",
            info={
                "mode": "catalog_llm_pair",
                "candidate_id": "cand-1",
                "current_step": "verify",
                "steps": [{"key": "verify", "status": "running", "message": "Checking"}],
                "reason_codes": ["needs_more_source_support"],
            },
        ),
    )

    response = await catalog.get_catalog_task_status("task-1")

    assert response.status == "GENERATING"
    assert response.mode == "catalog_llm_pair"
    assert response.candidate_id == "cand-1"
    assert response.current_step == "verify"
    assert response.reason_codes == ["needs_more_source_support"]


@pytest.mark.asyncio
async def test_get_catalog_task_status_maps_success_result(monkeypatch):
    monkeypatch.setattr(
        catalog,
        "AsyncResult",
        lambda task_id, app=None: _FakeAsyncResult(
            "SUCCESS",
            result={
                "status": RecipeCandidateStatus.review.value,
                "mode": "catalog_llm_pair",
                "candidate_id": "cand-1",
                "review_id": "rev-1",
                "reason_codes": ["uncertain_source"],
                "steps": [{"key": "verify", "status": "completed", "message": "Needs review"}],
                "current_step": "verify",
                "error": "Needs review",
            },
        ),
    )

    response = await catalog.get_catalog_task_status("task-1")

    assert response.status == "REVIEW"
    assert response.review_id == "rev-1"
    assert response.error == "Needs review"
    assert response.steps[0]["key"] == "verify"
