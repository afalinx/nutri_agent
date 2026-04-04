import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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

    model_config = {"from_attributes": True}


@router.get("/{recipe_id}", response_model=RecipeResponse)
async def get_recipe(recipe_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Recipe).where(Recipe.id == recipe_id))
    recipe = result.scalar_one_or_none()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe
