"""Тесты retriever cache recovery."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ["DEBUG"] = "true"

import pytest

from app.core.rag import retriever


def test_infer_meal_type_from_tags_for_cached_recipe():
    recipe = {
        "title": "Овсяная каша с ягодами",
        "tags": ["завтрак", "быстро"],
        "meal_type": None,
    }

    normalized = retriever._normalize_cached_recipe(recipe)

    assert normalized["meal_type"] == "breakfast"


@pytest.mark.asyncio
async def test_get_all_recipes_normalizes_cache_without_rebuild_when_possible(monkeypatch):
    stale_cache = [{"title": "Паста", "tags": [], "meal_type": None}]

    get_json = AsyncMock(return_value=stale_cache)
    delete = AsyncMock()
    load_all = AsyncMock()

    monkeypatch.setattr(retriever.cache, "get_json", get_json)
    monkeypatch.setattr(retriever.cache, "delete", delete)
    monkeypatch.setattr(retriever, "_load_all_recipes", load_all)

    result = await retriever._get_all_recipes(SimpleNamespace())

    assert result == [{"title": "Паста", "tags": [], "meal_type": "universal"}]
    delete.assert_not_awaited()
    load_all.assert_not_awaited()
