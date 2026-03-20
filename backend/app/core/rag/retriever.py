"""RAG Retriever — поиск рецептов с фильтрацией аллергенов."""

from __future__ import annotations

from sqlalchemy import select, not_, cast, String
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.db.models import Recipe

_ALLERGEN_ALIASES: dict[str, list[str]] = {
    "nuts": ["орех", "миндал", "фундук", "кешью", "фисташ", "пекан", "арахис", "nuts", "nut"],
    "milk": ["молок", "молоч", "сливк", "сливоч", "сметан", "творог", "кефир", "йогурт", "сыр", "milk"],
    "gluten": ["пшениц", "мука", "хлеб", "макарон", "спагетти", "лапша", "gluten"],
    "eggs": ["яйц", "яичн", "egg"],
    "soy": ["соев", "тофу", "soy"],
    "fish": ["рыб", "лосос", "тунец", "треск", "сёмг", "fish"],
    "shellfish": ["креветк", "краб", "мидии", "устриц", "shellfish"],
    "lactose": ["молок", "молоч", "сливк", "кефир", "йогурт", "lactose"],
}


def _expand_allergens(allergies: list[str]) -> list[str]:
    """Раскрывает аллерген в список ключевых слов для фильтрации."""
    keywords: list[str] = []
    for allergen in allergies:
        key = allergen.lower().strip()
        if key in _ALLERGEN_ALIASES:
            keywords.extend(_ALLERGEN_ALIASES[key])
        else:
            keywords.append(key)
    return keywords


async def search_recipes(
    session: AsyncSession,
    allergies: list[str] | None = None,
    tags: list[str] | None = None,
    limit: int = 20,
) -> list[Recipe]:
    """Поиск рецептов с жёсткой фильтрацией аллергенов.

    Пока эмбеддинги не загружены — простой SQL-поиск по тегам.
    При наличии эмбеддингов — будет векторный поиск.
    """
    stmt = select(Recipe)

    if allergies:
        keywords = _expand_allergens(allergies)
        for kw in keywords:
            stmt = stmt.where(
                not_(
                    Recipe.ingredients.cast(String).ilike(f"%{kw}%")
                )
            )
            stmt = stmt.where(
                not_(
                    Recipe.title.ilike(f"%{kw}%")
                )
            )

    if tags:
        for tag in tags:
            stmt = stmt.where(Recipe.tags.any(tag))

    stmt = stmt.limit(limit)

    result = await session.execute(stmt)
    recipes = list(result.scalars().all())

    logger.debug(
        "RAG search: found {} recipes (allergies={}, tags={})",
        len(recipes), allergies, tags,
    )
    return recipes
