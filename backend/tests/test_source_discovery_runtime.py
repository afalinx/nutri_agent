"""Tests for source discovery runtime harness."""

from __future__ import annotations

import uuid

import pytest

from app.core import source_discovery_runtime
from app.core.catalog_agent_runtime import CatalogAgentRuntimeResult
from app.core.source_discovery import DiscoverySourceOutput
from app.db.models import SourceCandidateStatus


class _FakeSourceCandidate:
    def __init__(self, *, status=SourceCandidateStatus.pending):
        self.id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        self.url = "https://example.com/recipe"
        self.source_type = "web"
        self.source_snapshot = {"title": "Recipe"}
        self.provenance = {"resolver": "http_fetch"}
        self.validation_report = {"ok": True, "reason_codes": [], "notes": []}
        self.status = status


@pytest.mark.asyncio
async def test_run_source_discovery_pipeline_success(monkeypatch):
    progress = []

    async def fake_discovery(seed_input):
        return [DiscoverySourceOutput(url="https://example.com/recipe", discovered_by="discovery-agent")]

    async def fake_create_source_candidate(*args, **kwargs):
        return _FakeSourceCandidate()

    async def fake_catalog_pipeline(*args, **kwargs):
        kwargs["progress_callback"](
            {
                "current_step": "verify",
                "steps": [
                    {"key": "research", "status": "completed", "message": "done"},
                    {"key": "candidate", "status": "completed", "message": "done"},
                    {"key": "verify", "status": "running", "message": "checking"},
                    {"key": "admit", "status": "pending", "message": ""},
                ],
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
            steps=[],
            current_step="admit",
        )

    async def fake_attach(*args, **kwargs):
        return _FakeSourceCandidate(status=SourceCandidateStatus.accepted)

    monkeypatch.setattr(source_discovery_runtime, "create_source_candidate", fake_create_source_candidate)
    monkeypatch.setattr(source_discovery_runtime, "run_catalog_agent_pipeline", fake_catalog_pipeline)
    monkeypatch.setattr(source_discovery_runtime, "attach_source_candidate_to_recipe_candidate", fake_attach)

    result = await source_discovery_runtime.run_source_discovery_pipeline(
        session=object(),
        seed_input={"query": "borsch"},
        discovery_agent=fake_discovery,
        research_agent=object(),
        verification_agent=object(),
        progress_callback=lambda state: progress.append(state),
    )

    assert result.status == "ACCEPTED"
    assert result.source_candidate_id == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert result.recipe_id == "recipe-1"
    assert any(step["key"] == "source" and step["status"] == "completed" for step in progress[-1]["steps"])


@pytest.mark.asyncio
async def test_run_source_discovery_pipeline_fails_on_rejected_source(monkeypatch):
    async def fake_discovery(seed_input):
        return [DiscoverySourceOutput(url="https://example.com/recipe", discovered_by="discovery-agent")]

    async def fake_create_source_candidate(*args, **kwargs):
        source = _FakeSourceCandidate(status=SourceCandidateStatus.rejected)
        source.validation_report = {"ok": False, "reason_codes": ["source_domain_not_allowed"], "notes": ["bad"]}
        return source

    monkeypatch.setattr(source_discovery_runtime, "create_source_candidate", fake_create_source_candidate)

    result = await source_discovery_runtime.run_source_discovery_pipeline(
        session=object(),
        seed_input={"query": "borsch"},
        discovery_agent=fake_discovery,
        research_agent=object(),
        verification_agent=object(),
    )

    assert result.status == "FAILED"
    assert result.reason_codes == ["source_domain_not_allowed"]
    assert result.current_step == "source"
