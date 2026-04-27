"""Tests for catalog discovery routes."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.api.routes import catalog


@pytest.mark.asyncio
async def test_queue_source_discovery_ingest_job(monkeypatch):
    monkeypatch.setattr(
        catalog.celery_app,
        "send_task",
        lambda name, args: SimpleNamespace(id="task-456", name=name, args=args),
    )

    response = await catalog.queue_source_discovery_ingest_job(
        catalog.CatalogIngestJobRequest(seed_input={"query": "borsch", "source_urls": ["https://example.com/recipe"]})
    )

    assert response.task_id == "task-456"
