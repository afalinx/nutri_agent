"""Загрузка рецептов из JSON в БД (без эмбеддингов — они будут добавлены отдельно)."""

import asyncio
import json
import uuid
from pathlib import Path

from sqlalchemy import select, text

from app.core.recipe_catalog import RecipeCatalogError, normalize_recipe_payload
from app.db.models import Recipe
from app.db.session import async_session, engine

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "recipes.json"


async def seed():
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    async with async_session() as session:
        existing = await session.execute(select(Recipe.id).limit(1))
        if existing.scalar_one_or_none():
            print("Recipes already seeded, skipping.")
            return

        with open(DATA_PATH, encoding="utf-8") as f:
            recipes_data = json.load(f)

        count = 0
        skipped = 0
        for r in recipes_data:
            try:
                normalized = normalize_recipe_payload(r)
            except RecipeCatalogError as exc:
                skipped += 1
                print(f"Skip invalid recipe '{r.get('title', 'unknown')}': {exc}")
                continue

            recipe = Recipe(
                id=uuid.uuid4(),
                title=normalized["title"],
                description=normalized.get("description", ""),
                ingredients=normalized["ingredients"],
                calories=normalized["calories"],
                protein=normalized["protein"],
                fat=normalized["fat"],
                carbs=normalized["carbs"],
                tags=normalized.get("tags", []),
                meal_type=normalized.get("meal_type"),
                allergens=normalized.get("allergens", []),
                ingredients_short=normalized.get("ingredients_short"),
                prep_time_min=normalized.get("prep_time_min"),
                category=normalized.get("category"),
                embedding=None,
            )
            session.add(recipe)
            count += 1

        await session.commit()
        print(f"Seeded {count} recipes, skipped {skipped} invalid entries.")


if __name__ == "__main__":
    asyncio.run(seed())
