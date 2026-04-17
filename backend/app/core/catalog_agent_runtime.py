"""Runtime harness for recipe-catalog agents.

This module coordinates the catalog ingest workflow as a strict step pipeline:
research -> candidate -> verify -> admit.
The agent implementations are pluggable; the runtime owns state transitions,
progress traces and error handling.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.core.catalog_ingest import (
    CatalogIngestResult,
    ResearchOutput,
    VerificationOutput,
    add_candidate_review,
    admit_recipe_candidate,
    create_recipe_candidate,
)
from app.db.models import RecipeCandidateStatus, RecipeReviewVerdict

CatalogProgressCallback = Callable[[dict[str, Any]], None]
ResearchAgent = Callable[[dict[str, Any]], Awaitable[ResearchOutput]]
VerificationAgent = Callable[[Any], Awaitable[VerificationOutput]]

CATALOG_PIPELINE_STEPS = ["research", "candidate", "verify", "admit"]


@dataclass
class CatalogAgentRuntimeResult:
    status: str
    candidate_id: str | None
    review_id: str | None = None
    recipe_id: str | None = None
    reason_codes: list[str] | None = None
    error: str | None = None
    steps: list[dict[str, Any]] | None = None
    current_step: str | None = None


def _empty_steps() -> list[dict[str, Any]]:
    return [{"key": step, "status": "pending", "message": ""} for step in CATALOG_PIPELINE_STEPS]


def _set_step(
    state: dict[str, Any],
    key: str,
    *,
    status: str,
    message: str,
    activate: bool = True,
) -> None:
    if activate:
        state["current_step"] = key
    for step in state["steps"]:
        if step["key"] == key:
            step["status"] = status
            step["message"] = message
            break


def _emit(progress_callback: CatalogProgressCallback | None, state: dict[str, Any]) -> None:
    if progress_callback is not None:
        progress_callback(deepcopy(state))


async def run_catalog_agent_pipeline(
    session,
    *,
    seed_input: dict[str, Any],
    research_agent: ResearchAgent,
    verification_agent: VerificationAgent,
    progress_callback: CatalogProgressCallback | None = None,
) -> CatalogAgentRuntimeResult:
    state: dict[str, Any] = {
        "status": "RUNNING",
        "current_step": None,
        "steps": _empty_steps(),
        "candidate_id": None,
        "review_id": None,
        "recipe_id": None,
        "reason_codes": [],
        "error": None,
    }

    try:
        _set_step(state, "research", status="running", message="Research agent is gathering a recipe candidate.")
        _emit(progress_callback, state)
        research = await research_agent(seed_input)
        _set_step(state, "research", status="completed", message="Research agent produced a structured candidate.")

        _set_step(state, "candidate", status="running", message="Storing candidate and running schema validation.")
        _emit(progress_callback, state)
        candidate = await create_recipe_candidate(
            session,
            payload=research.payload,
            source_url=research.source_url,
            source_type=research.source_type,
            source_snapshot=research.source_snapshot,
            provenance=research.provenance,
            submitted_by=research.submitted_by,
        )
        state["candidate_id"] = str(candidate.id)
        if candidate.status == RecipeCandidateStatus.rejected:
            _set_step(
                state,
                "candidate",
                status="failed",
                message=((candidate.validation_report or {}).get("notes") or ["Candidate validation failed."])[0],
            )
            state["status"] = "FAILED"
            state["reason_codes"] = (candidate.validation_report or {}).get("reason_codes") or []
            state["error"] = ((candidate.validation_report or {}).get("notes") or [None])[0]
            _emit(progress_callback, state)
            return CatalogAgentRuntimeResult(
                status=state["status"],
                candidate_id=state["candidate_id"],
                reason_codes=state["reason_codes"],
                error=state["error"],
                steps=deepcopy(state["steps"]),
                current_step=state["current_step"],
            )

        _set_step(state, "candidate", status="completed", message="Candidate stored and passed schema validation.")

        _set_step(state, "verify", status="running", message="Verification agent is reviewing the candidate.")
        _emit(progress_callback, state)
        verification = await verification_agent(candidate)
        review = await add_candidate_review(
            session,
            candidate_id=str(candidate.id),
            verdict=verification.verdict,
            reviewer=verification.reviewer,
            reason_codes=verification.reason_codes or [],
            notes=verification.notes,
            review_payload=verification.review_payload,
        )
        state["review_id"] = str(review.id)
        state["reason_codes"] = verification.reason_codes or []
        if verification.verdict != RecipeReviewVerdict.accept:
            review_status = {
                RecipeReviewVerdict.review: RecipeCandidateStatus.review.value,
                RecipeReviewVerdict.reject: RecipeCandidateStatus.rejected.value,
            }[verification.verdict]
            _set_step(
                state,
                "verify",
                status="completed",
                message=verification.notes or "Candidate requires review or was rejected.",
            )
            _set_step(
                state,
                "admit",
                status="skipped",
                message="Admission skipped due to verification verdict.",
                activate=False,
            )
            state["status"] = review_status
            state["error"] = verification.notes
            _emit(progress_callback, state)
            return CatalogAgentRuntimeResult(
                status=state["status"],
                candidate_id=state["candidate_id"],
                review_id=state["review_id"],
                reason_codes=state["reason_codes"],
                error=state["error"],
                steps=deepcopy(state["steps"]),
                current_step=state["current_step"],
            )

        _set_step(state, "verify", status="completed", message="Verification agent approved the candidate.")
        _set_step(state, "admit", status="running", message="Admitting candidate into canonical recipe catalog.")
        _emit(progress_callback, state)
        recipe = await admit_recipe_candidate(session, candidate_id=str(candidate.id))
        state["recipe_id"] = str(recipe.id)
        _set_step(state, "admit", status="completed", message="Candidate admitted into recipe catalog.")
        state["status"] = RecipeCandidateStatus.accepted.value
        _emit(progress_callback, state)
        return CatalogAgentRuntimeResult(
            status=state["status"],
            candidate_id=state["candidate_id"],
            review_id=state["review_id"],
            recipe_id=state["recipe_id"],
            reason_codes=state["reason_codes"],
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
        return CatalogAgentRuntimeResult(
            status=state["status"],
            candidate_id=state["candidate_id"],
            review_id=state["review_id"],
            recipe_id=state["recipe_id"],
            reason_codes=state["reason_codes"],
            error=state["error"],
            steps=deepcopy(state["steps"]),
            current_step=state["current_step"],
        )
