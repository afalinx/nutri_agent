"""Runtime harness for autonomous source discovery before catalog ingest."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from app.core.catalog_agent_runtime import CatalogAgentRuntimeResult, run_catalog_agent_pipeline
from app.core.source_discovery import (
    DiscoveryStep,
    attach_source_candidate_to_recipe_candidate,
    create_source_candidate,
)
from app.db.models import SourceCandidateStatus

DiscoveryProgressCallback = Callable[[dict[str, Any]], None]

DISCOVERY_PIPELINE_STEPS = ["discover", "source", "research", "candidate", "verify", "admit"]


@dataclass
class DiscoveryRuntimeResult:
    status: str
    source_candidate_id: str | None
    candidate_id: str | None = None
    review_id: str | None = None
    recipe_id: str | None = None
    reason_codes: list[str] | None = None
    error: str | None = None
    steps: list[dict[str, Any]] | None = None
    current_step: str | None = None


def _empty_steps() -> list[dict[str, Any]]:
    return [{"key": step, "status": "pending", "message": ""} for step in DISCOVERY_PIPELINE_STEPS]


def _set_step(state: dict[str, Any], key: str, *, status: str, message: str, activate: bool = True) -> None:
    if activate:
        state["current_step"] = key
    for step in state["steps"]:
        if step["key"] == key:
            step["status"] = status
            step["message"] = message
            break


def _emit(progress_callback: DiscoveryProgressCallback | None, state: dict[str, Any]) -> None:
    if progress_callback is not None:
        progress_callback(deepcopy(state))


async def run_source_discovery_pipeline(
    session,
    *,
    seed_input: dict[str, Any],
    discovery_agent: DiscoveryStep,
    research_agent,
    verification_agent,
    progress_callback: DiscoveryProgressCallback | None = None,
) -> DiscoveryRuntimeResult:
    state: dict[str, Any] = {
        "status": "RUNNING",
        "current_step": None,
        "steps": _empty_steps(),
        "source_candidate_id": None,
        "candidate_id": None,
        "review_id": None,
        "recipe_id": None,
        "reason_codes": [],
        "error": None,
    }

    try:
        _set_step(state, "discover", status="running", message="Discovery agent is finding source URLs.")
        _emit(progress_callback, state)
        discovered_sources = await discovery_agent(seed_input)
        if not discovered_sources:
            raise RuntimeError("Discovery returned no source URLs")
        source = discovered_sources[0]
        _set_step(state, "discover", status="completed", message="Discovery agent produced source candidates.")

        _set_step(state, "source", status="running", message="Fetching and validating discovered source URL.")
        _emit(progress_callback, state)
        source_candidate = await create_source_candidate(
            session,
            url=source.url,
            source_type=source.source_type,
            discovery_query=source.discovery_query,
            discovery_payload=source.discovery_payload,
            provenance=source.provenance,
            discovered_by=source.discovered_by,
        )
        state["source_candidate_id"] = str(source_candidate.id)
        if source_candidate.status == SourceCandidateStatus.rejected:
            _set_step(
                state,
                "source",
                status="failed",
                message=((source_candidate.validation_report or {}).get("notes") or ["Source validation failed."])[0],
            )
            state["status"] = "FAILED"
            state["reason_codes"] = (source_candidate.validation_report or {}).get("reason_codes") or []
            state["error"] = ((source_candidate.validation_report or {}).get("notes") or [None])[0]
            _emit(progress_callback, state)
            return DiscoveryRuntimeResult(
                status=state["status"],
                source_candidate_id=state["source_candidate_id"],
                reason_codes=state["reason_codes"],
                error=state["error"],
                steps=deepcopy(state["steps"]),
                current_step=state["current_step"],
            )
        _set_step(state, "source", status="completed", message="Source URL fetched and allowlist validation passed.")

        def catalog_progress(inner_state: dict[str, Any]) -> None:
            for step in state["steps"]:
                if step["key"] in {"research", "candidate", "verify", "admit"}:
                    match = next((s for s in inner_state.get("steps", []) if s["key"] == step["key"]), None)
                    if match is not None:
                        step["status"] = match["status"]
                        step["message"] = match["message"]
            state["current_step"] = inner_state.get("current_step") or state["current_step"]
            state["candidate_id"] = inner_state.get("candidate_id")
            state["review_id"] = inner_state.get("review_id")
            state["recipe_id"] = inner_state.get("recipe_id")
            state["reason_codes"] = inner_state.get("reason_codes") or []
            state["error"] = inner_state.get("error")
            _emit(progress_callback, state)

        catalog_result: CatalogAgentRuntimeResult = await run_catalog_agent_pipeline(
            session,
            seed_input={
                **seed_input,
                "source_url": source_candidate.url,
                "source_type": source_candidate.source_type,
                "source_snapshot": source_candidate.source_snapshot,
                "provenance": source_candidate.provenance,
            },
            research_agent=research_agent,
            verification_agent=verification_agent,
            progress_callback=catalog_progress,
        )
        state["status"] = catalog_result.status
        state["candidate_id"] = catalog_result.candidate_id
        state["review_id"] = catalog_result.review_id
        state["recipe_id"] = catalog_result.recipe_id
        state["reason_codes"] = catalog_result.reason_codes or []
        state["error"] = catalog_result.error
        if catalog_result.candidate_id:
            await attach_source_candidate_to_recipe_candidate(
                session,
                source_candidate_id=str(source_candidate.id),
                recipe_candidate_id=catalog_result.candidate_id,
            )
        _emit(progress_callback, state)
        return DiscoveryRuntimeResult(
            status=state["status"],
            source_candidate_id=state["source_candidate_id"],
            candidate_id=state["candidate_id"],
            review_id=state["review_id"],
            recipe_id=state["recipe_id"],
            reason_codes=state["reason_codes"],
            error=state["error"],
            steps=deepcopy(state["steps"]),
            current_step=state["current_step"],
        )
    except Exception as exc:
        state["status"] = "FAILED"
        state["error"] = str(exc)
        for step in reversed(state["steps"]):
            if step["status"] == "running":
                step["status"] = "failed"
                if not step["message"]:
                    step["message"] = str(exc)
                break
        _emit(progress_callback, state)
        return DiscoveryRuntimeResult(
            status=state["status"],
            source_candidate_id=state["source_candidate_id"],
            candidate_id=state["candidate_id"],
            review_id=state["review_id"],
            recipe_id=state["recipe_id"],
            reason_codes=state["reason_codes"],
            error=state["error"],
            steps=deepcopy(state["steps"]),
            current_step=state["current_step"],
        )
