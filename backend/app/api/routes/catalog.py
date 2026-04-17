import uuid

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.catalog_ingest import add_candidate_review, admit_recipe_candidate, create_recipe_candidate
from app.db.models import (
    RecipeCandidate,
    RecipeCandidateReview,
    RecipeCandidateStatus,
    RecipeReviewVerdict,
    SourceCandidate,
    SourceCandidateStatus,
)
from app.db.session import get_db
from app.worker import celery_app

router = APIRouter(prefix="/api/catalog", tags=["Catalog"])


class CandidateCreateRequest(BaseModel):
    payload: dict
    source_url: str | None = None
    source_type: str | None = None
    source_snapshot: dict | None = None
    provenance: dict | None = None
    submitted_by: str | None = None


class CandidateResponse(BaseModel):
    id: uuid.UUID
    source_url: str | None
    source_type: str | None
    source_snapshot: dict | None = None
    provenance: dict | None = None
    payload: dict
    normalized_payload: dict | None
    validation_report: dict | None
    status: str
    admitted_recipe_id: uuid.UUID | None = None

    model_config = {"from_attributes": True}


class ReviewCreateRequest(BaseModel):
    reviewer: str | None = None
    verdict: RecipeReviewVerdict
    reason_codes: list[str] = Field(default_factory=list, max_length=20)
    notes: str | None = None
    review_payload: dict | None = None


class ReviewResponse(BaseModel):
    id: uuid.UUID
    candidate_id: uuid.UUID
    reviewer: str | None
    verdict: str
    reason_codes: list[str] = Field(default_factory=list)
    notes: str | None = None
    review_payload: dict | None = None

    model_config = {"from_attributes": True}


@router.post("/candidates", response_model=CandidateResponse)
async def create_candidate(data: CandidateCreateRequest, db: AsyncSession = Depends(get_db)):
    candidate = await create_recipe_candidate(
        db,
        payload=data.payload,
        source_url=data.source_url,
        source_type=data.source_type,
        source_snapshot=data.source_snapshot,
        provenance=data.provenance,
        submitted_by=data.submitted_by,
    )
    return candidate


@router.get("/candidates", response_model=list[CandidateResponse])
async def list_candidates(
    status: RecipeCandidateStatus | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(RecipeCandidate).order_by(RecipeCandidate.created_at.desc())
    if status is not None:
        stmt = stmt.where(RecipeCandidate.status == status)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/candidates/{candidate_id}/reviews", response_model=ReviewResponse)
async def create_review(
    candidate_id: uuid.UUID,
    data: ReviewCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        review = await add_candidate_review(
            db,
            candidate_id=str(candidate_id),
            verdict=data.verdict,
            reviewer=data.reviewer,
            reason_codes=data.reason_codes,
            notes=data.notes,
            review_payload=data.review_payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return review


@router.get("/candidates/{candidate_id}/reviews", response_model=list[ReviewResponse])
async def list_reviews(candidate_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RecipeCandidateReview)
        .where(RecipeCandidateReview.candidate_id == candidate_id)
        .order_by(RecipeCandidateReview.created_at.asc())
    )
    return list(result.scalars().all())


class AdmitResponse(BaseModel):
    candidate_id: uuid.UUID
    recipe_id: uuid.UUID


class CatalogIngestJobRequest(BaseModel):
    seed_input: dict


class CatalogIngestJobResponse(BaseModel):
    task_id: str


class CatalogTaskStepResponse(BaseModel):
    key: str
    status: str
    message: str = ""


class CatalogTaskStatusResponse(BaseModel):
    task_id: str
    status: str
    mode: str | None = None
    candidate_id: str | None = None
    review_id: str | None = None
    recipe_id: str | None = None
    current_step: str | None = None
    steps: list[CatalogTaskStepResponse] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    error: str | None = None


class SourceCandidateResponse(BaseModel):
    id: uuid.UUID
    url: str
    domain: str
    source_type: str
    discovery_query: str | None = None
    discovery_payload: dict | None = None
    source_snapshot: dict | None = None
    provenance: dict | None = None
    validation_report: dict | None = None
    status: str
    linked_candidate_id: uuid.UUID | None = None

    model_config = {"from_attributes": True}


@router.post("/candidates/{candidate_id}/admit", response_model=AdmitResponse)
async def admit_candidate(candidate_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    try:
        recipe = await admit_recipe_candidate(db, candidate_id=str(candidate_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AdmitResponse(candidate_id=candidate_id, recipe_id=recipe.id)


@router.post("/ingest-jobs", response_model=CatalogIngestJobResponse)
async def queue_catalog_ingest_job(data: CatalogIngestJobRequest):
    task = celery_app.send_task("run_catalog_ingest", args=[data.seed_input])
    return CatalogIngestJobResponse(task_id=task.id)


@router.post("/source-ingest-jobs", response_model=CatalogIngestJobResponse)
async def queue_source_discovery_ingest_job(data: CatalogIngestJobRequest):
    task = celery_app.send_task("run_source_discovery_ingest", args=[data.seed_input])
    return CatalogIngestJobResponse(task_id=task.id)


@router.get("/sources", response_model=list[SourceCandidateResponse])
async def list_source_candidates(
    status: SourceCandidateStatus | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(SourceCandidate).order_by(SourceCandidate.created_at.desc())
    if status is not None:
        stmt = stmt.where(SourceCandidate.status == status)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/tasks/{task_id}", response_model=CatalogTaskStatusResponse)
async def get_catalog_task_status(task_id: str):
    result = AsyncResult(task_id, app=celery_app)
    progress_meta = result.info if isinstance(result.info, dict) else {}

    response = CatalogTaskStatusResponse(
        task_id=task_id,
        status="PENDING" if result.state == "PENDING" else "GENERATING",
        mode=progress_meta.get("mode"),
        candidate_id=progress_meta.get("candidate_id"),
        review_id=progress_meta.get("review_id"),
        recipe_id=progress_meta.get("recipe_id"),
        current_step=progress_meta.get("current_step"),
        steps=progress_meta.get("steps") or [],
        reason_codes=progress_meta.get("reason_codes") or [],
        error=progress_meta.get("error"),
    )

    if result.state == "FAILURE":
        response.status = "FAILED"
        response.error = str(result.result)
        return response

    if result.state == "SUCCESS" and isinstance(result.result, dict):
        response.mode = result.result.get("mode") or response.mode
        response.candidate_id = result.result.get("candidate_id") or response.candidate_id
        response.review_id = result.result.get("review_id") or response.review_id
        response.recipe_id = result.result.get("recipe_id") or response.recipe_id
        response.current_step = result.result.get("current_step") or response.current_step
        response.steps = result.result.get("steps") or response.steps
        response.reason_codes = result.result.get("reason_codes") or response.reason_codes
        response.error = result.result.get("error") or response.error
        task_status = result.result.get("status")
        if task_status == RecipeCandidateStatus.accepted.value:
            response.status = "ACCEPTED"
        elif task_status == RecipeCandidateStatus.review.value:
            response.status = "REVIEW"
        elif task_status == RecipeCandidateStatus.rejected.value:
            response.status = "REJECTED"
        elif task_status == "FAILED":
            response.status = "FAILED"

    return response
