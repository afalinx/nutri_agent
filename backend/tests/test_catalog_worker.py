"""Tests for catalog ingest worker helpers."""

from __future__ import annotations

import pytest

from app.core.catalog_agent_runtime import CatalogAgentRuntimeResult
from app.db import session as db_session
from app.worker import tasks


class _FakeSessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_run_catalog_ingest_returns_runtime_payload(monkeypatch):
    progress_events: list[tuple[str, dict]] = []

    monkeypatch.setattr(tasks, "build_research_agent", lambda: "research-agent")
    monkeypatch.setattr(tasks, "build_verification_agent", lambda: "verification-agent")
    monkeypatch.setattr(db_session, "async_session", lambda: _FakeSessionContext())

    async def fake_runtime(session, **kwargs):
        kwargs["progress_callback"](
            {
                "status": "RUNNING",
                "current_step": "verify",
                "steps": [{"key": "verify", "status": "running", "message": "Checking"}],
                "candidate_id": "cand-1",
                "review_id": None,
                "recipe_id": None,
                "reason_codes": [],
                "error": None,
            }
        )
        return CatalogAgentRuntimeResult(
            status="ACCEPTED",
            candidate_id="cand-1",
            review_id="rev-1",
            recipe_id="recipe-1",
            reason_codes=[],
            error=None,
            steps=[{"key": "admit", "status": "completed", "message": "Done"}],
            current_step="admit",
        )

    monkeypatch.setattr(tasks, "run_catalog_agent_pipeline", fake_runtime)
    monkeypatch.setattr(
        tasks,
        "_publish_progress",
        lambda task, state, celery_state="GENERATING": progress_events.append((celery_state, state)),
    )

    result = await tasks._run_catalog_ingest(
        {"query": "high protein lunch"},
        task=object(),
        progress_state_holder={},
    )

    assert result["status"] == "ACCEPTED"
    assert result["recipe_id"] == "recipe-1"
    assert progress_events[-1][0] == "SUCCESS"
