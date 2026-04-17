"""Tests for catalog source resolution and snapshotting."""

from __future__ import annotations

import pytest

from app.core import catalog_sources


@pytest.mark.asyncio
async def test_resolve_catalog_source_from_payload():
    resolved = await catalog_sources.resolve_catalog_source(
        {
            "payload": {
                "title": "Chicken bowl",
                "description": "Simple lunch",
                "ingredients": [{"name": "Chicken", "amount": 200, "unit": "g"}],
                "meal_type": "lunch",
            },
            "source_name": "seed.json",
            "provenance": {"dataset": "seed.json"},
        }
    )

    assert resolved.source_type == "payload"
    assert resolved.source_snapshot["title"] == "Chicken bowl"
    assert resolved.provenance["dataset"] == "seed.json"
    assert resolved.research_input["source_snapshot"]["payload_excerpt"]["meal_type"] == "lunch"


@pytest.mark.asyncio
async def test_resolve_catalog_source_fetches_url(monkeypatch):
    class _FakeResponse:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}
        text = "<html><head><title>Chicken Bowl</title><meta name='description' content='Tasty lunch'></head><body>Recipe text</body></html>"
        url = "https://example.com/recipe"

        def raise_for_status(self):
            return None

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            assert url == "https://example.com/recipe"
            return _FakeResponse()

    monkeypatch.setattr(catalog_sources.httpx, "AsyncClient", lambda **kwargs: _FakeClient())

    resolved = await catalog_sources.resolve_catalog_source({"source_url": "https://example.com/recipe"})

    assert resolved.source_type == "web"
    assert resolved.source_snapshot["title"] == "Chicken Bowl"
    assert "Recipe text" in resolved.source_snapshot["html_excerpt"]
    assert resolved.provenance["resolver"] == "http_fetch"
