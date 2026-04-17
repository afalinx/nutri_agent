"""Tests for source discovery staging."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.core import source_discovery
from app.db.models import SourceCandidateStatus


class _FakeSourceCandidate:
    def __init__(self, *, status=SourceCandidateStatus.pending):
        self.id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        self.url = "https://example.com/recipe"
        self.domain = "example.com"
        self.source_type = "web"
        self.discovery_query = "borsch"
        self.discovery_payload = {"page": 1}
        self.source_snapshot = {"title": "Recipe"}
        self.provenance = {"resolver": "http_fetch"}
        self.validation_report = {"ok": True, "reason_codes": [], "notes": []}
        self.status = status
        self.linked_candidate_id = None


@pytest.mark.asyncio
async def test_validate_source_url_rejects_non_https(monkeypatch):
    monkeypatch.setattr(
        source_discovery,
        "validate_url_against_policy",
        lambda url: (False, {"reason_codes": ["source_url_not_https"], "notes": ["Only https source URLs are allowed"]}),
    )
    ok, report = source_discovery.validate_source_url("http://example.com/recipe")
    assert ok is False
    assert report["reason_codes"] == ["source_url_not_https"]


@pytest.mark.asyncio
async def test_validate_source_url_rejects_non_allowlisted_domain(monkeypatch):
    monkeypatch.setattr(
        source_discovery,
        "validate_url_against_policy",
        lambda url: (
            False,
            {"reason_codes": ["source_domain_not_allowed"], "notes": ["Source domain is not allowlisted: evil.com"]},
        ),
    )
    ok, report = source_discovery.validate_source_url("https://evil.com/recipe")
    assert ok is False
    assert report["reason_codes"] == ["source_domain_not_allowed"]


@pytest.mark.asyncio
async def test_create_source_candidate_fetches_snapshot(monkeypatch):
    monkeypatch.setattr(
        source_discovery,
        "validate_url_against_policy",
        lambda url: (
            True,
            {
                "reason_codes": [],
                "notes": [],
                "domain": "example.com",
                "trust_level": "trusted_editorial",
            },
        ),
    )

    async def fake_find_existing(*args, **kwargs):
        return None

    monkeypatch.setattr(source_discovery, "_find_existing_source_candidate", fake_find_existing)

    async def fake_fetch(url: str):
        return SimpleNamespace(
            source_url=url,
            source_type="web",
            source_snapshot={"title": "Recipe"},
            provenance={"resolver": "http_fetch", "source_url": url},
            research_input={"source_url": url},
        )

    monkeypatch.setattr(source_discovery, "fetch_source_url", fake_fetch)

    class _Session:
        def __init__(self):
            self.added = None

        def add(self, obj):
            self.added = obj

        async def commit(self):
            return None

        async def refresh(self, obj):
            return None

    session = _Session()
    candidate = await source_discovery.create_source_candidate(
        session,
        url="https://example.com/recipe",
        source_type="web",
        discovery_query="borsch",
        provenance={"trace": ["discovery"]},
        discovered_by="agent",
    )

    assert candidate.status == SourceCandidateStatus.pending
    assert candidate.source_snapshot == {"title": "Recipe"}
