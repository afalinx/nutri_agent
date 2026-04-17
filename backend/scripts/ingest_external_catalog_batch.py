"""Run autonomous external catalog ingest over a batch of discovered source URLs."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import func, select, text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.catalog_agents import build_research_agent, build_verification_agent
from app.core.source_discovery import DiscoverySourceOutput
from app.core.source_discovery_runtime import run_source_discovery_pipeline
from app.core.source_harvester import discover_source_urls
from app.db.models import Recipe, RecipeCandidate, RecipeCandidateStatus, SourceCandidate
from app.db.session import async_session, engine


def _dedupe_sources(sources: list[DiscoverySourceOutput], *, limit: int | None = None) -> list[DiscoverySourceOutput]:
    unique: list[DiscoverySourceOutput] = []
    seen: set[str] = set()
    for source in sources:
        if source.url in seen:
            continue
        seen.add(source.url)
        unique.append(source)
        if limit is not None and len(unique) >= limit:
            break
    return unique


async def _print_db_summary() -> None:
    async with async_session() as session:
        recipe_count = await session.scalar(select(func.count()).select_from(Recipe))
        candidate_count = await session.scalar(select(func.count()).select_from(RecipeCandidate))
        source_count = await session.scalar(select(func.count()).select_from(SourceCandidate))
        accepted_count = await session.scalar(
            select(func.count()).select_from(RecipeCandidate).where(
                RecipeCandidate.status == RecipeCandidateStatus.accepted
            )
        )
        review_count = await session.scalar(
            select(func.count()).select_from(RecipeCandidate).where(
                RecipeCandidate.status == RecipeCandidateStatus.review
            )
        )
        rejected_count = await session.scalar(
            select(func.count()).select_from(RecipeCandidate).where(
                RecipeCandidate.status == RecipeCandidateStatus.rejected
            )
        )

        print(
            json.dumps(
                {
                    "recipes": recipe_count,
                    "candidates": candidate_count,
                    "sources": source_count,
                    "accepted_candidates": accepted_count,
                    "review_candidates": review_count,
                    "rejected_candidates": rejected_count,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


async def main(*, domains: list[str] | None, query: str | None, limit: int | None) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    discovered_sources = await discover_source_urls(query=query, domains=domains)
    sources = _dedupe_sources(discovered_sources, limit=limit)
    print(
        json.dumps(
            {
                "discovered_total": len(discovered_sources),
                "selected_total": len(sources),
                "domains": domains or [],
                "query": query,
            },
            ensure_ascii=False,
        )
    )

    research_agent = build_research_agent()
    verification_agent = build_verification_agent()
    summary = {"ACCEPTED": 0, "REVIEW": 0, "REJECTED": 0, "FAILED": 0}

    async with async_session() as session:
        for idx, source in enumerate(sources, start=1):
            async def single_source_discovery_agent(seed_input: dict) -> list[DiscoverySourceOutput]:
                return [source]

            result = await run_source_discovery_pipeline(
                session,
                seed_input={
                    "domains": domains or [],
                    "query": query,
                },
                discovery_agent=single_source_discovery_agent,
                research_agent=research_agent,
                verification_agent=verification_agent,
            )
            summary[result.status] = summary.get(result.status, 0) + 1
            if result.status == "FAILED":
                await session.rollback()
            print(
                json.dumps(
                    {
                        "batch_index": idx,
                        "source_url": source.url,
                        "status": result.status,
                        "source_candidate_id": result.source_candidate_id,
                        "candidate_id": result.candidate_id,
                        "review_id": result.review_id,
                        "recipe_id": result.recipe_id,
                        "reason_codes": result.reason_codes or [],
                        "error": result.error,
                    },
                    ensure_ascii=False,
                )
            )

    print(json.dumps({"summary": summary}, ensure_ascii=False))
    await _print_db_summary()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", dest="domains", action="append", default=None)
    parser.add_argument("--query", type=str, default=None)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    asyncio.run(main(domains=args.domains, query=args.query, limit=args.limit))
