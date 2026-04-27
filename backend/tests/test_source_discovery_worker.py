"""Tests for source discovery worker helpers."""

from __future__ import annotations

import pytest

from app.core.source_discovery_runtime import DiscoveryRuntimeResult
from app.worker import tasks


class _FakeSessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_run_source_discovery_ingest_returns_runtime_payload(monkeypatch):
    progress_events = []

    from app.db import session as db_session

    monkeypatch.setattr(db_session, "async_session", lambda: _FakeSessionContext())
    monkeypatch.setattr(tasks, "build_research_agent", lambda: "research-agent")
    monkeypatch.setattr(tasks, "build_verification_agent", lambda: "verification-agent")

    async def fake_runtime(session, **kwargs):
        kwargs["progress_callback"](
            {
                "status": "RUNNING",
                "current_step": "source",
                "steps": [{"key": "source", "status": "running", "message": "Fetching"}],
                "source_candidate_id": "src-1",
                "candidate_id": None,
                "review_id": None,
                "recipe_id": None,
                "reason_codes": [],
                "error": None,
            }
        )
        return DiscoveryRuntimeResult(
            status="ACCEPTED",
            source_candidate_id="src-1",
            candidate_id="cand-1",
            review_id="rev-1",
            recipe_id="recipe-1",
            reason_codes=[],
            steps=[{"key": "admit", "status": "completed", "message": "Done"}],
            current_step="admit",
        )

    monkeypatch.setattr(tasks, "run_source_discovery_pipeline", fake_runtime)
    monkeypatch.setattr(
        tasks,
        "_publish_progress",
        lambda task, state, celery_state="GENERATING": progress_events.append((celery_state, state)),
    )

    result = await tasks._run_source_discovery_ingest(
        {"query": "borsch", "source_urls": ["https://example.com/recipe"]},
        task=object(),
        progress_state_holder={},
    )

    assert result["status"] == "ACCEPTED"
    assert result["source_candidate_id"] == "src-1"
    assert progress_events[-1][0] == "SUCCESS"
