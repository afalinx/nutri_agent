"""Discovery staging for external recipe source URLs."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.catalog_sources import fetch_source_url
from app.core.source_policy import validate_url_against_policy
from app.db.models import SourceCandidate, SourceCandidateStatus

DiscoveryStep = Callable[[dict[str, Any]], Awaitable[list["DiscoverySourceOutput"]]]


@dataclass
class DiscoverySourceOutput:
    url: str
    source_type: str = "web"
    discovery_query: str | None = None
    discovery_payload: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None
    discovered_by: str | None = None


def validate_source_url(url: str) -> tuple[bool, dict[str, Any]]:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, {"reason_codes": ["invalid_url"], "notes": ["Malformed source URL"]}
    domain = (parsed.hostname or "").lower()
    if not domain:
        return False, {"reason_codes": ["invalid_url"], "notes": ["Source URL has no hostname"]}
    ok, report = validate_url_against_policy(url)
    report["domain"] = report.get("domain") or domain
    return ok, report


async def _find_existing_source_candidate(session: AsyncSession, *, url: str) -> SourceCandidate | None:
    result = await session.execute(select(SourceCandidate).where(SourceCandidate.url == url))
    return result.scalar_one_or_none()


async def create_source_candidate(
    session: AsyncSession,
    *,
    url: str,
    source_type: str,
    discovery_query: str | None = None,
    discovery_payload: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    discovered_by: str | None = None,
) -> SourceCandidate:
    ok, report = validate_source_url(url)
    domain = report.get("domain") or (urlparse(url).hostname or "").lower()
    existing = await _find_existing_source_candidate(session, url=url)
    if existing is not None:
        return existing

    snapshot = None
    merged_provenance = {**(provenance or {}), "discovery_stage": "source_candidate"}
    if ok:
        resolved = await fetch_source_url(url)
        snapshot = resolved.source_snapshot
        merged_provenance = {**resolved.provenance, **merged_provenance}

    source_candidate = SourceCandidate(
        url=url,
        domain=domain,
        source_type=source_type,
        discovery_query=discovery_query,
        discovery_payload=discovery_payload,
        source_snapshot=snapshot,
        provenance=merged_provenance,
        validation_report={
            "ok": ok,
            "reason_codes": report.get("reason_codes") or [],
            "notes": report.get("notes") or [],
        },
        status=SourceCandidateStatus.pending if ok else SourceCandidateStatus.rejected,
        discovered_by=discovered_by,
    )
    session.add(source_candidate)
    await session.commit()
    await session.refresh(source_candidate)
    return source_candidate


async def attach_source_candidate_to_recipe_candidate(
    session: AsyncSession,
    *,
    source_candidate_id: str,
    recipe_candidate_id: str,
) -> SourceCandidate:
    source_candidate = await session.get(SourceCandidate, uuid.UUID(source_candidate_id))
    if source_candidate is None:
        raise ValueError(f"SourceCandidate {source_candidate_id} not found")
    source_candidate.linked_candidate_id = uuid.UUID(recipe_candidate_id)
    source_candidate.status = SourceCandidateStatus.accepted
    await session.commit()
    await session.refresh(source_candidate)
    return source_candidate
