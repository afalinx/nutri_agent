"""RAG Retriever — поиск рецептов с фильтрацией аллергенов."""

from __future__ import annotations

from loguru import logger
from sqlalchemy import String, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Recipe

_ALLERGEN_ALIASES: dict[str, list[str]] = {
    "nuts": ["орех", "миндал", "фундук", "кешью", "фисташ", "пекан", "арахис", "nuts", "nut"],
    "milk": [
        "молок",
        "молоч",
        "сливк",
        "сливоч",
        "сметан",
        "творог",
        "кефир",
        "йогурт",
        "сыр",
        "milk",
    ],
    "gluten": ["пшениц", "мука", "хлеб", "макарон", "спагетти", "лапша", "gluten"],
    "eggs": ["яйц", "яичн", "egg"],
    "soy": ["соев", "тофу", "soy"],
    "fish": ["рыб", "лосос", "тунец", "треск", "сёмг", "fish"],
    "shellfish": ["креветк", "краб", "мидии", "устриц", "shellfish"],
    "lactose": ["молок", "молоч", "сливк", "кефир", "йогурт", "lactose"],
}

_DISEASE_RULES: dict[str, dict[str, list[str]]] = {
    "diabetes": {
        "exclude_keywords": ["сахар", "мёд", "мед", "сироп", "гранола", "батончик", "слад"],
        "preferred_tags": ["низкоуглеводный"],
    },
    "insulin_resistance": {
        "exclude_keywords": ["сахар", "мёд", "мед", "сироп", "слад"],
        "preferred_tags": ["низкоуглеводный"],
    },
    "celiac": {
        "exclude_keywords": ["глютен", "пшениц", "мука", "лапша", "хлеб", "паста"],
        "preferred_tags": ["без глютена"],
    },
    "hypertension": {
        "exclude_keywords": ["соевый соус", "солен", "соль"],
        "preferred_tags": [],
    },
    "gastritis": {
        "exclude_keywords": ["остр", "жарен", "уксус", "чили"],
        "preferred_tags": [],
    },
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
    # Дедуплицируем для меньшего SQL-условия.
    return list(dict.fromkeys(keywords))


def _expand_disease_rules(diseases: list[str]) -> tuple[list[str], list[str]]:
    exclude_keywords: list[str] = []
    preferred_tags: list[str] = []
    for disease in diseases:
        key = disease.lower().strip()
        rule = _DISEASE_RULES.get(key)
        if not rule:
            continue
        exclude_keywords.extend(rule["exclude_keywords"])
        preferred_tags.extend(rule["preferred_tags"])
    return list(dict.fromkeys(exclude_keywords)), list(dict.fromkeys(preferred_tags))


async def search_recipes(
    session: AsyncSession,
    allergies: list[str] | None = None,
    dislikes: list[str] | None = None,
    preferred_tags: list[str] | None = None,
    diseases: list[str] | None = None,
    limit: int = 20,
) -> list[Recipe]:
    """Поиск рецептов с жёсткой фильтрацией аллергенов.

    Пока эмбеддинги не загружены — простой SQL-поиск по тегам.
    При наличии эмбеддингов — будет векторный поиск.
    """
    stmt = select(Recipe)

    hard_exclude_keywords: list[str] = []
    if allergies:
        hard_exclude_keywords.extend(_expand_allergens(allergies))
    if dislikes:
        hard_exclude_keywords.extend([x.lower().strip() for x in dislikes if x.strip()])

    disease_preferred_tags: list[str] = []
    if diseases:
        disease_exclude_keywords, disease_preferred_tags = _expand_disease_rules(diseases)
        hard_exclude_keywords.extend(disease_exclude_keywords)

    hard_exclude_keywords = list(dict.fromkeys(hard_exclude_keywords))
    for kw in hard_exclude_keywords:
        stmt = stmt.where(not_(Recipe.ingredients.cast(String).ilike(f"%{kw}%")))
        stmt = stmt.where(not_(Recipe.title.ilike(f"%{kw}%")))

    all_preferred_tags = list(
        dict.fromkeys(
            [
                *[x.strip() for x in (preferred_tags or []) if x.strip()],
                *disease_preferred_tags,
            ]
        )
    )
    if all_preferred_tags:
        tag_conditions = [Recipe.tags.any(tag) for tag in all_preferred_tags]
        preferred_stmt = stmt.where(or_(*tag_conditions)).limit(limit)
        preferred_result = await session.execute(preferred_stmt)
        preferred_recipes = list(preferred_result.scalars().all())
        if preferred_recipes:
            logger.debug(
                "RAG search: found {} recipes with preferred_tags {}",
                len(preferred_recipes),
                all_preferred_tags,
            )
            return preferred_recipes
        logger.debug(
            "RAG search: no recipes for preferred_tags {}, fallback to base filter",
            all_preferred_tags,
        )

    result = await session.execute(stmt.limit(limit))
    recipes = list(result.scalars().all())

    logger.debug(
        "RAG search: found {} recipes (allergies={}, dislikes={}, preferred_tags={}, diseases={})",
        len(recipes),
        allergies,
        dislikes,
        all_preferred_tags,
        diseases,
    )
    return recipes
