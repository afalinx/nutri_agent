"""Shared metadata helpers for generation pipelines."""

from __future__ import annotations

from typing import Any

PIPELINE_STEPS = ["context", "generate", "validate", "auto-fix", "save", "shopping-list"]


def build_generation_meta(
    *,
    mode: str,
    quality_status: str,
    warnings: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "pipeline_version": "canonical_v1",
        "mode": mode,
        "quality_status": quality_status,
        "warnings": warnings or [],
    }
    if extra:
        payload.update(extra)
    return payload
