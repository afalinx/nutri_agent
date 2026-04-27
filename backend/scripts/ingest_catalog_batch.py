"""Run the catalog agent pipeline over a batch of recipe sources."""

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

from app.core.catalog_agent_runtime import run_catalog_agent_pipeline
from app.core.catalog_agents import build_research_agent, build_verification_agent
from app.db.models import Recipe, RecipeCandidate, RecipeCandidateStatus
from app.db.session import async_session, engine

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "recipes.json"


def _load_inline_recipe_sources(*, limit: int | None = None, offset: int = 0) -> list[dict]:
    recipes = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    sliced = recipes[offset : offset + limit if limit is not None else None]
    result = []
    for idx, recipe in enumerate(sliced, start=offset):
        result.append(
            {
                "payload": recipe,
                "source_type": "local_seed_json",
                "source_name": "data/recipes.json",
                "provenance": {
                    "dataset": "data/recipes.json",
                    "index": idx,
                    "trust_level": "internal_curated_seed",
                },
            }
        )
    return result


async def _print_db_summary() -> None:
    async with async_session() as session:
        recipe_count = await session.execute(select(func.count()).select_from(Recipe))
        candidate_count = await session.execute(select(func.count()).select_from(RecipeCandidate))
        accepted_count = await session.execute(
            select(func.count()).select_from(RecipeCandidate).where(
                RecipeCandidate.status == RecipeCandidateStatus.accepted
            )
        )
        review_count = await session.execute(
            select(func.count()).select_from(RecipeCandidate).where(
                RecipeCandidate.status == RecipeCandidateStatus.review
            )
        )
        rejected_count = await session.execute(
            select(func.count()).select_from(RecipeCandidate).where(
                RecipeCandidate.status == RecipeCandidateStatus.rejected
            )
        )

        print(
            json.dumps(
                {
                    "recipes": recipe_count.scalar_one(),
                    "candidates": candidate_count.scalar_one(),
                    "accepted_candidates": accepted_count.scalar_one(),
                    "review_candidates": review_count.scalar_one(),
                    "rejected_candidates": rejected_count.scalar_one(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )


async def main(limit: int | None, offset: int) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    research_agent = build_research_agent()
    verification_agent = build_verification_agent()
    sources = _load_inline_recipe_sources(limit=limit, offset=offset)

    summary = {"ACCEPTED": 0, "REVIEW": 0, "REJECTED": 0, "FAILED": 0}
    async with async_session() as session:
        for idx, seed_input in enumerate(sources, start=1):
            result = await run_catalog_agent_pipeline(
                session,
                seed_input=seed_input,
                research_agent=research_agent,
                verification_agent=verification_agent,
            )
            summary[result.status] = summary.get(result.status, 0) + 1
            if result.status == "FAILED":
                await session.rollback()
            print(
                json.dumps(
                    {
                        "batch_index": idx + offset,
                        "status": result.status,
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
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()
    asyncio.run(main(limit=args.limit, offset=args.offset))
