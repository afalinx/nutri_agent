"""Catalog candidate workflow: validation, review and admission."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.core.recipe_catalog import RecipeCatalogError, normalize_recipe_payload
from app.db.models import (
    Recipe,
    RecipeCandidate,
    RecipeCandidateReview,
    RecipeCandidateStatus,
    RecipeReviewVerdict,
)

ResearchStep = Callable[[dict[str, Any]], Awaitable["ResearchOutput"]]
VerificationStep = Callable[[RecipeCandidate], Awaitable["VerificationOutput"]]


@dataclass
class ResearchOutput:
    payload: dict[str, Any]
    source_url: str | None = None
    source_type: str | None = None
    source_snapshot: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None
    submitted_by: str | None = None


@dataclass
class VerificationOutput:
    verdict: RecipeReviewVerdict
    reviewer: str | None = None
    reason_codes: list[str] | None = None
    notes: str | None = None
    review_payload: dict[str, Any] | None = None


@dataclass
class CatalogIngestResult:
    candidate_id: str
    status: str
    review_id: str | None = None
    recipe_id: str | None = None
    reason_codes: list[str] | None = None
    error: str | None = None


async def _find_duplicate_recipe(
    session: AsyncSession,
    *,
    title: str,
    ingredients_short: str | None,
) -> Recipe | None:
    duplicate = await session.execute(
        select(Recipe).where(
            Recipe.title == title,
            Recipe.ingredients_short == ingredients_short,
        )
    )
    return duplicate.scalar_one_or_none()


def build_validation_report(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        normalized = normalize_recipe_payload(payload)
    except RecipeCatalogError as exc:
        return {
            "ok": False,
            "reason_codes": [exc.reason_code],
            "notes": [str(exc)],
            "normalized_payload": None,
        }
    return {
        "ok": True,
        "reason_codes": [],
        "notes": [],
        "normalized_payload": normalized,
    }


async def create_recipe_candidate(
    session: AsyncSession,
    *,
    payload: dict[str, Any],
    source_url: str | None,
    source_type: str | None,
    source_snapshot: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    submitted_by: str | None,
) -> RecipeCandidate:
    report = build_validation_report(payload)
    status = RecipeCandidateStatus.pending if report["ok"] else RecipeCandidateStatus.rejected
    candidate = RecipeCandidate(
        source_url=source_url,
        source_type=source_type,
        source_snapshot=source_snapshot,
        provenance=provenance,
        payload=payload,
        normalized_payload=report["normalized_payload"],
        validation_report={
            "ok": report["ok"],
            "reason_codes": report["reason_codes"],
            "notes": report["notes"],
        },
        status=status,
        submitted_by=submitted_by,
    )
    session.add(candidate)
    await session.commit()
    await session.refresh(candidate)
    return candidate


async def add_candidate_review(
    session: AsyncSession,
    *,
    candidate_id: str,
    verdict: RecipeReviewVerdict,
    reviewer: str | None,
    reason_codes: list[str],
    notes: str | None,
    review_payload: dict[str, Any] | None = None,
) -> RecipeCandidateReview:
    candidate = await session.get(RecipeCandidate, uuid.UUID(candidate_id))
    if candidate is None:
        raise ValueError(f"RecipeCandidate {candidate_id} not found")

    review = RecipeCandidateReview(
        candidate_id=candidate.id,
        reviewer=reviewer,
        verdict=verdict,
        reason_codes=reason_codes,
        notes=notes,
        review_payload=review_payload,
    )
    candidate.status = {
        RecipeReviewVerdict.accept: RecipeCandidateStatus.accepted,
        RecipeReviewVerdict.review: RecipeCandidateStatus.review,
        RecipeReviewVerdict.reject: RecipeCandidateStatus.rejected,
    }[verdict]
    session.add(review)
    await session.commit()
    await session.refresh(review)
    return review


async def admit_recipe_candidate(session: AsyncSession, *, candidate_id: str) -> Recipe:
    candidate = await session.get(RecipeCandidate, uuid.UUID(candidate_id))
    if candidate is None:
        raise ValueError(f"RecipeCandidate {candidate_id} not found")
    if candidate.status != RecipeCandidateStatus.accepted:
        raise ValueError(f"RecipeCandidate {candidate_id} is not accepted")
    if not candidate.normalized_payload:
        raise ValueError(f"RecipeCandidate {candidate_id} has no normalized payload")

    title = candidate.normalized_payload["title"]
    ingredients_short = candidate.normalized_payload.get("ingredients_short")
    existing = await _find_duplicate_recipe(
        session,
        title=title,
        ingredients_short=ingredients_short,
    )
    if existing is not None:
        candidate.admitted_recipe_id = existing.id
        await session.commit()
        await cache.delete("recipes:all")
        return existing

    recipe = Recipe(
        title=title,
        description=candidate.normalized_payload.get("description", ""),
        ingredients=candidate.normalized_payload["ingredients"],
        calories=candidate.normalized_payload["calories"],
        protein=candidate.normalized_payload["protein"],
        fat=candidate.normalized_payload["fat"],
        carbs=candidate.normalized_payload["carbs"],
        tags=candidate.normalized_payload.get("tags", []),
        meal_type=candidate.normalized_payload.get("meal_type"),
        allergens=candidate.normalized_payload.get("allergens", []),
        ingredients_short=candidate.normalized_payload.get("ingredients_short"),
        prep_time_min=candidate.normalized_payload.get("prep_time_min"),
        category=candidate.normalized_payload.get("category"),
        embedding=None,
    )
    session.add(recipe)
    await session.flush()
    candidate.admitted_recipe_id = recipe.id
    await session.commit()
    await cache.delete("recipes:all")
    await session.refresh(recipe)
    return recipe


async def run_catalog_ingest_job(
    session: AsyncSession,
    *,
    seed_input: dict[str, Any],
    research_step: ResearchStep,
    verification_step: VerificationStep,
) -> CatalogIngestResult:
    research = await research_step(seed_input)
    candidate = await create_recipe_candidate(
        session,
        payload=research.payload,
        source_url=research.source_url,
        source_type=research.source_type,
        source_snapshot=research.source_snapshot,
        provenance=research.provenance,
        submitted_by=research.submitted_by,
    )

    if candidate.status == RecipeCandidateStatus.rejected:
        return CatalogIngestResult(
            candidate_id=str(candidate.id),
            status=candidate.status.value,
            reason_codes=(candidate.validation_report or {}).get("reason_codes") or [],
            error=((candidate.validation_report or {}).get("notes") or [None])[0],
        )

    verification = await verification_step(candidate)
    review = await add_candidate_review(
        session,
        candidate_id=str(candidate.id),
        verdict=verification.verdict,
        reviewer=verification.reviewer,
        reason_codes=verification.reason_codes or [],
        notes=verification.notes,
        review_payload=verification.review_payload,
    )

    if verification.verdict != RecipeReviewVerdict.accept:
        return CatalogIngestResult(
            candidate_id=str(candidate.id),
            review_id=str(review.id),
            status=candidate.status.value,
            reason_codes=verification.reason_codes or [],
            error=verification.notes,
        )

    recipe = await admit_recipe_candidate(session, candidate_id=str(candidate.id))
    return CatalogIngestResult(
        candidate_id=str(candidate.id),
        review_id=str(review.id),
        recipe_id=str(recipe.id),
        status=RecipeCandidateStatus.accepted.value,
        reason_codes=verification.reason_codes or [],
    )
