"""Загрузка рецептов из JSON в БД (без эмбеддингов — они будут добавлены отдельно)."""

import asyncio
import json
import uuid
from pathlib import Path

from sqlalchemy import select, text

from app.config import settings
from app.db.base import Base
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
        for r in recipes_data:
            recipe = Recipe(
                id=uuid.uuid4(),
                title=r["title"],
                description=r.get("description", ""),
                ingredients=r["ingredients"],
                calories=r["calories"],
                protein=r["protein"],
                fat=r["fat"],
                carbs=r["carbs"],
                tags=r.get("tags", []),
                embedding=None,
            )
            session.add(recipe)
            count += 1

        await session.commit()
        print(f"Seeded {count} recipes.")


if __name__ == "__main__":
    asyncio.run(seed())
