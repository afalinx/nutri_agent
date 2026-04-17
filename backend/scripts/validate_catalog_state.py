"""Validate the current catalog and staging state in PostgreSQL."""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import func, select, tuple_

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.recipe_catalog import RecipeCatalogError, normalize_recipe_payload
from app.db.models import Recipe, RecipeCandidate, RecipeCandidateStatus, SourceCandidate
from app.db.session import async_session


async def main() -> None:
    async with async_session() as session:
        recipes = list((await session.execute(select(Recipe))).scalars().all())
        candidates = list((await session.execute(select(RecipeCandidate))).scalars().all())
        sources = list((await session.execute(select(SourceCandidate))).scalars().all())

        invalid_recipes: list[dict] = []
        for recipe in recipes:
            payload = {
                "title": recipe.title,
                "description": recipe.description or "",
                "ingredients": recipe.ingredients,
                "calories": recipe.calories,
                "protein": recipe.protein,
                "fat": recipe.fat,
                "carbs": recipe.carbs,
                "tags": recipe.tags or [],
                "meal_type": recipe.meal_type,
                "allergens": recipe.allergens or [],
                "ingredients_short": recipe.ingredients_short,
                "prep_time_min": recipe.prep_time_min,
                "category": recipe.category,
            }
            try:
                normalize_recipe_payload(payload)
            except RecipeCatalogError as exc:
                invalid_recipes.append(
                    {"id": str(recipe.id), "title": recipe.title, "reason_code": exc.reason_code, "error": str(exc)}
                )

        duplicate_rows = await session.execute(
            select(Recipe.title, Recipe.ingredients_short, func.count())
            .group_by(Recipe.title, Recipe.ingredients_short)
            .having(func.count() > 1)
        )
        duplicate_recipe_groups = [
            {"title": title, "ingredients_short": ingredients_short, "count": count}
            for title, ingredients_short, count in duplicate_rows.all()
        ]

        candidate_status_counts = Counter(candidate.status.value for candidate in candidates)
        source_status_counts = Counter(source.status.value for source in sources)
        accepted_without_admission = [
            str(candidate.id)
            for candidate in candidates
            if candidate.status == RecipeCandidateStatus.accepted and candidate.admitted_recipe_id is None
        ]
        accepted_sources_without_link = [
            str(source.id)
            for source in sources
            if source.status.value == "ACCEPTED" and source.linked_candidate_id is None
        ]

        print(
            json.dumps(
                {
                    "recipes_total": len(recipes),
                    "recipes_invalid": len(invalid_recipes),
                    "invalid_recipes": invalid_recipes[:20],
                    "duplicate_recipe_groups": duplicate_recipe_groups,
                    "candidate_status_counts": candidate_status_counts,
                    "source_status_counts": source_status_counts,
                    "accepted_candidates_without_admission": accepted_without_admission[:20],
                    "accepted_sources_without_link": accepted_sources_without_link[:20],
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
