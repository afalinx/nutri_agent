"""RAG Retriever — поиск рецептов с фильтрацией по аллергенам, предпочтениям и заболеваниям.

Рецепты загружаются из Redis-кеша (или БД при промахе) и фильтруются in-memory.
Это быстрее SQL ILIKE для малого каталога (48 рецептов) и использует обогащённые поля.
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.db.models import Recipe

CACHE_KEY = "recipes:all"
CACHE_TTL = 86400  # 24 hours
_TAG_TO_MEAL_TYPE = {
    "завтрак": "breakfast",
    "обед": "lunch",
    "ужин": "dinner",
    "перекус": "snack",
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


def _infer_meal_type(tags: list[str] | None, meal_type: str | None) -> str:
    if meal_type and meal_type.strip():
        return meal_type.strip().lower()

    normalized_tags = [tag.lower().strip() for tag in (tags or []) if tag.strip()]
    detected = [_TAG_TO_MEAL_TYPE[tag] for tag in normalized_tags if tag in _TAG_TO_MEAL_TYPE]

    if not detected:
        return "universal"
    if len(detected) == 1:
        return detected[0]
    if "lunch" in detected and "dinner" in detected:
        return "lunch/dinner"
    if "breakfast" in detected and "snack" in detected:
        return "breakfast"
    return detected[0]


async def _load_all_recipes(session: AsyncSession) -> list[dict]:
    """Load all recipes from DB and cache them."""
    result = await session.execute(select(Recipe))
    recipes = list(result.scalars().all())

    recipe_dicts = [
        {
            "id": str(r.id),
            "title": r.title,
            "description": r.description,
            "ingredients": r.ingredients,
            "calories": r.calories,
            "protein": r.protein,
            "fat": r.fat,
            "carbs": r.carbs,
            "tags": r.tags or [],
            "meal_type": _infer_meal_type(r.tags or [], r.meal_type),
            "allergens": r.allergens or [],
            "ingredients_short": r.ingredients_short or "",
            "prep_time_min": r.prep_time_min,
            "category": r.category,
        }
        for r in recipes
    ]

    await cache.set_json(CACHE_KEY, recipe_dicts, ttl=CACHE_TTL)
    logger.debug("Cached {} recipes in Redis", len(recipe_dicts))
    return recipe_dicts


def _normalize_cached_recipe(recipe: dict) -> dict:
    normalized = dict(recipe)
    normalized["meal_type"] = _infer_meal_type(
        normalized.get("tags") or [],
        normalized.get("meal_type"),
    )
    return normalized


def _is_cache_healthy(recipes: list[dict]) -> bool:
    if not recipes:
        return True
    return all(bool((recipe.get("meal_type") or "").strip()) for recipe in recipes)


async def _get_all_recipes(session: AsyncSession) -> list[dict]:
    """Get all recipes from cache, falling back to DB."""
    cached = await cache.get_json(CACHE_KEY)
    if cached:
        normalized_cached = [_normalize_cached_recipe(recipe) for recipe in cached]
        if _is_cache_healthy(normalized_cached):
            return normalized_cached
        logger.warning("Recipe cache is stale or incomplete; rebuilding from database")
        await cache.delete(CACHE_KEY)
    return await _load_all_recipes(session)


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


def _recipe_matches_keyword(recipe: dict, keyword: str) -> bool:
    """Check if a recipe contains a keyword in ingredients or title."""
    kw = keyword.lower()
    if kw in recipe["title"].lower():
        return True
    return kw in recipe.get("ingredients_short", "").lower()


async def search_recipes(
    session: AsyncSession,
    allergies: list[str] | None = None,
    dislikes: list[str] | None = None,
    preferred_tags: list[str] | None = None,
    diseases: list[str] | None = None,
    limit: int = 30,
) -> list[dict]:
    """Поиск рецептов с in-memory фильтрацией по кешированным данным.

    Использует обогащённое поле `allergens` для точной фильтрации аллергенов,
    и `ingredients_short` для фильтрации нелюбимых ингредиентов.
    """
    all_recipes = await _get_all_recipes(session)

    # --- Hard exclusion: allergens (exact match on enriched field) ---
    user_allergens = set()
    if allergies:
        for a in allergies:
            user_allergens.add(a.lower().strip())

    # --- Hard exclusion: disease rules ---
    disease_exclude_keywords: list[str] = []
    disease_preferred_tags: list[str] = []
    if diseases:
        disease_exclude_keywords, disease_preferred_tags = _expand_disease_rules(diseases)

    # --- Hard exclusion: dislikes ---
    dislike_keywords = [d.lower().strip() for d in (dislikes or []) if d.strip()]

    # Apply hard filters
    safe_recipes: list[dict] = []
    for r in all_recipes:
        # Filter by allergens (exact set intersection)
        recipe_allergens = {a.lower().strip() for a in (r.get("allergens", []) or [])}
        if user_allergens & recipe_allergens:
            continue

        # Filter by disease-excluded keywords
        if any(_recipe_matches_keyword(r, kw) for kw in disease_exclude_keywords):
            continue

        # Filter by dislikes
        if any(_recipe_matches_keyword(r, kw) for kw in dislike_keywords):
            continue

        safe_recipes.append(r)

    # --- Soft filter: prefer recipes with matching tags ---
    all_preferred_tags = list(
        dict.fromkeys(
            [
                *[t.strip() for t in (preferred_tags or []) if t.strip()],
                *disease_preferred_tags,
            ]
        )
    )

    if all_preferred_tags:
        preferred = [
            r
            for r in safe_recipes
            if any(tag in (r.get("tags") or []) for tag in all_preferred_tags)
        ]
        if preferred:
            logger.debug(
                "RAG: {} recipes match preferred_tags {}",
                len(preferred),
                all_preferred_tags,
            )
            return preferred[:limit]
        logger.debug("RAG: no preferred tag matches, using all {} safe recipes", len(safe_recipes))

    logger.debug(
        "RAG: {} recipes after filtering (allergies={}, dislikes={}, diseases={})",
        len(safe_recipes),
        allergies,
        dislikes,
        diseases,
    )
    return safe_recipes[:limit]
