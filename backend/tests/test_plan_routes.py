"""Unit-тесты API-роутов планов без живых внешних зависимостей."""

from __future__ import annotations

import pytest

from app.api.routes import plans


class _FakeAsyncResult:
    def __init__(self, state: str, result=None, info=None):
        self.state = state
        self.result = result
        self.info = info


@pytest.mark.asyncio
async def test_get_task_status_uses_progress_meta(monkeypatch):
    monkeypatch.setattr(
        plans,
        "AsyncResult",
        lambda task_id, app=None: _FakeAsyncResult(
            "GENERATING",
            info={
                "mode": "agent_cli",
                "quality_status": "partially_valid",
                "current_step": "validate",
                "steps": [{"key": "validate", "status": "running", "message": "Checking"}],
                "warnings": ["Day 2 fallback"],
            },
        ),
    )

    response = await plans.get_task_status("task-1")

    assert response.status == "GENERATING"
    assert response.mode == "agent_cli"
    assert response.quality_status == "partially_valid"
    assert response.current_step == "validate"
    assert response.steps[0]["key"] == "validate"
    assert response.warnings == ["Day 2 fallback"]


@pytest.mark.asyncio
async def test_get_task_status_uses_success_result_payload(monkeypatch):
    monkeypatch.setattr(
        plans,
        "AsyncResult",
        lambda task_id, app=None: _FakeAsyncResult(
            "SUCCESS",
            result={
                "plan_id": "plan-123",
                "status": "READY",
                "mode": "agent_cli",
                "quality_status": "valid",
                "current_step": "shopping-list",
                "steps": [{"key": "shopping-list", "status": "completed", "message": "Done"}],
                "warnings": [],
            },
            info={"mode": "llm_direct"},
        ),
    )

    response = await plans.get_task_status("task-1")

    assert response.status == "READY"
    assert response.plan_id == "plan-123"
    assert response.mode == "agent_cli"
    assert response.current_step == "shopping-list"
    assert response.steps[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_get_task_status_maps_failure_error(monkeypatch):
    monkeypatch.setattr(
        plans,
        "AsyncResult",
        lambda task_id, app=None: _FakeAsyncResult(
            "FAILURE",
            result=RuntimeError("boom"),
            info={"mode": "agent_cli", "current_step": "generate"},
        ),
    )

    response = await plans.get_task_status("task-1")

    assert response.status == "FAILED"
    assert response.error == "boom"
    assert response.mode == "agent_cli"
