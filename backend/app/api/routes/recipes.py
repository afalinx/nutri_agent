import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.db.models import Recipe
from app.db.session import get_db

router = APIRouter(prefix="/api/recipes", tags=["Recipes"])


class RecipeResponse(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    ingredients: list[dict]
    calories: float
    protein: float
    fat: float
    carbs: float
    tags: list[str] | None = None
    meal_type: str | None = None
    allergens: list[str] | None = None
    ingredients_short: str | None = None
    prep_time_min: int | None = None
    category: str | None = None

    model_config = {"from_attributes": True}


class BatchRequest(BaseModel):
    recipe_ids: list[uuid.UUID] = Field(max_length=50)


@router.get("/{recipe_id}", response_model=RecipeResponse)
async def get_recipe(recipe_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Recipe).where(Recipe.id == recipe_id))
    recipe = result.scalar_one_or_none()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe


@router.post("/batch", response_model=list[RecipeResponse])
async def get_recipes_batch(data: BatchRequest, db: AsyncSession = Depends(get_db)):
    """Получить рецепты пачкой по списку ID (решает N+1)."""
    if not data.recipe_ids:
        return []

    # Try from cached recipe catalog first
    cached_all = await cache.get_json("recipes:all")
    if cached_all:
        cached_by_id = {r["id"]: r for r in cached_all}
        results = []
        for rid in data.recipe_ids:
            r = cached_by_id.get(str(rid))
            if r:
                results.append(
                    RecipeResponse(
                        id=uuid.UUID(r["id"]),
                        title=r["title"],
                        description=r.get("description"),
                        ingredients=r["ingredients"],
                        calories=r["calories"],
                        protein=r["protein"],
                        fat=r["fat"],
                        carbs=r["carbs"],
                        tags=r.get("tags"),
                        meal_type=r.get("meal_type"),
                        allergens=r.get("allergens"),
                        ingredients_short=r.get("ingredients_short"),
                        prep_time_min=r.get("prep_time_min"),
                        category=r.get("category"),
                    )
                )
        return results

    # Fallback: single DB query with IN clause
    result = await db.execute(select(Recipe).where(Recipe.id.in_(data.recipe_ids)))
    return list(result.scalars().all())
