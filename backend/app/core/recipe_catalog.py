"""Recipe catalog normalization and safety validation.

These checks are intentionally conservative. They protect the catalog and
portion-scaling layer from obviously broken, unsafe or absurd recipe payloads.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

_ALLOWED_UNITS = {
    "g",
    "kg",
    "ml",
    "l",
    "piece",
    "pieces",
    "pcs",
    "tbsp",
    "tsp",
    "slice",
}
_UNIT_ALIASES = {
    "шт": "piece",
    "шт.": "piece",
    "pcs.": "pcs",
}
_MEAL_TYPE_ALIASES = {
    "dessert": "snack",
    "desert": "snack",
    "desserts": "snack",
    "main": "dinner",
    "main dish": "dinner",
    "main_course": "dinner",
    "main course": "dinner",
}
_BANNED_INGREDIENT_TERMS = {
    "penis",
    "penis кита",
    "whale penis",
    "human flesh",
    "человечина",
    "ртуть",
    "bleach",
    "отбеливатель",
}
_MAX_INGREDIENT_AMOUNT_BY_UNIT = {
    "g": 3000,
    "kg": 3,
    "ml": 3000,
    "l": 3,
    "piece": 20,
    "pieces": 20,
    "pcs": 20,
    "tbsp": 20,
    "tsp": 40,
    "slice": 12,
}
_MAX_TOTAL_PORTION_MASS_GRAMS = 2500
_UNSAFE_COMBINATION_RULES = [
    {
        "reason_code": "unsafe_combination",
        "message": "Unsafe ingredient combination: dairy with pickled vegetables",
        "all_groups": ["dairy", "pickled_vegetable"],
    },
]
_IMPLAUSIBLE_PAIRING_RULES = [
    {
        "reason_code": "implausible_pairing",
        "message": "Implausible ingredient combination: sprats with chocolate",
        "all_groups": ["sprats", "chocolate"],
    },
]
_INGREDIENT_GROUP_MARKERS = {
    "dairy": ("молоко", "сливки", "кефир", "йогурт", "ряженка"),
    "pickled_vegetable": ("огурцы солё", "солёные огур", "маринованн", "квашен"),
    "sprats": ("шпрот",),
    "chocolate": ("шоколад", "какао плит", "шоколадн"),
}

_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


class RecipeCatalogError(ValueError):
    """Raised when a recipe payload is not acceptable for the catalog."""

    def __init__(self, message: str, *, reason_code: str = "invalid_recipe_payload"):
        super().__init__(message)
        self.reason_code = reason_code


def _ingredient_groups(ingredients: list["IngredientPayload"]) -> set[str]:
    groups: set[str] = set()
    for ingredient in ingredients:
        lowered = ingredient.name.lower()
        for group, markers in _INGREDIENT_GROUP_MARKERS.items():
            if any(marker in lowered for marker in markers):
                groups.add(group)
    return groups


def _validate_ingredient_compatibility(ingredients: list["IngredientPayload"]) -> None:
    present_groups = _ingredient_groups(ingredients)
    for rule in _UNSAFE_COMBINATION_RULES:
        if all(group in present_groups for group in rule["all_groups"]):
            raise RecipeCatalogError(rule["message"], reason_code=rule["reason_code"])
    for rule in _IMPLAUSIBLE_PAIRING_RULES:
        if all(group in present_groups for group in rule["all_groups"]):
            raise RecipeCatalogError(rule["message"], reason_code=rule["reason_code"])


class IngredientPayload(BaseModel):
    name: str
    amount: float = Field(gt=0)
    unit: str

    @field_validator("amount", mode="before")
    @classmethod
    def _normalize_amount(cls, value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            match = _NUMBER_RE.search(value.strip())
            if match:
                return float(match.group(0).replace(",", "."))
        raise RecipeCatalogError("Input should be a valid number")

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if len(normalized) < 2:
            raise RecipeCatalogError("Ingredient name is too short")
        lowered = normalized.lower()
        if any(term in lowered for term in _BANNED_INGREDIENT_TERMS):
            raise RecipeCatalogError(f"Banned ingredient term detected: {normalized}")
        return normalized

    @field_validator("unit")
    @classmethod
    def _validate_unit(cls, value: str) -> str:
        normalized = value.strip().lower()
        normalized = _UNIT_ALIASES.get(normalized, normalized)
        if normalized not in _ALLOWED_UNITS:
            raise RecipeCatalogError(f"Unsupported ingredient unit: {value}")
        return normalized

    @model_validator(mode="after")
    def _validate_amount(self):
        limit = _MAX_INGREDIENT_AMOUNT_BY_UNIT[self.unit]
        if self.amount > limit:
            raise RecipeCatalogError(
                f"Ingredient amount is unrealistic: {self.name} {self.amount} {self.unit}"
            )
        return self


class RecipePayload(BaseModel):
    title: str
    description: str = ""
    ingredients: list[IngredientPayload] = Field(min_length=1, max_length=30)
    calories: float = Field(gt=0, le=2500)
    protein: float = Field(ge=0, le=250)
    fat: float = Field(ge=0, le=180)
    carbs: float = Field(ge=0, le=300)
    tags: list[str] = Field(default_factory=list)
    meal_type: str | None = None
    allergens: list[str] = Field(default_factory=list)
    ingredients_short: str | None = None
    prep_time_min: int | None = Field(default=None, ge=1, le=360)
    category: str | None = None

    @field_validator("calories", "protein", "fat", "carbs", mode="before")
    @classmethod
    def _normalize_macro_numbers(cls, value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            match = _NUMBER_RE.search(value.strip())
            if match:
                return float(match.group(0).replace(",", "."))
        raise RecipeCatalogError("Input should be a valid number")

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if len(normalized) < 4:
            raise RecipeCatalogError("Recipe title is too short")
        return normalized

    @field_validator("tags", "allergens")
    @classmethod
    def _normalize_string_lists(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(" ".join(v.strip().split()).lower() for v in values if v.strip()))

    @field_validator("meal_type")
    @classmethod
    def _normalize_meal_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        normalized = _MEAL_TYPE_ALIASES.get(normalized, normalized)
        if normalized not in {"breakfast", "lunch", "dinner", "snack", "second_snack", "lunch/dinner", "universal"}:
            raise RecipeCatalogError(f"Unsupported meal_type: {value}")
        return normalized

    @model_validator(mode="after")
    def _validate_macros(self):
        macro_calories = self.protein * 4 + self.carbs * 4 + self.fat * 9
        if abs(macro_calories - self.calories) > max(120, self.calories * 0.2):
            raise RecipeCatalogError(
                "Recipe calories do not roughly match macros: "
                f"{self.calories} vs {macro_calories:.1f}"
            )
        total_mass_grams = 0.0
        for ingredient in self.ingredients:
            if ingredient.unit == "g":
                total_mass_grams += ingredient.amount
            elif ingredient.unit == "kg":
                total_mass_grams += ingredient.amount * 1000
            elif ingredient.unit == "ml":
                total_mass_grams += ingredient.amount
            elif ingredient.unit == "l":
                total_mass_grams += ingredient.amount * 1000
        if total_mass_grams > _MAX_TOTAL_PORTION_MASS_GRAMS:
            raise RecipeCatalogError(
                f"Recipe portion mass is unrealistic: {total_mass_grams:.0f} g"
            )
        _validate_ingredient_compatibility(self.ingredients)
        return self


def normalize_recipe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        recipe = RecipePayload.model_validate(payload)
    except ValidationError as exc:
        first_error = exc.errors()[0]
        original = (first_error.get("ctx") or {}).get("error")
        if isinstance(original, RecipeCatalogError):
            raise original from exc
        raise RecipeCatalogError(first_error["msg"]) from exc
    data = recipe.model_dump()
    if not data.get("ingredients_short"):
        data["ingredients_short"] = ", ".join(ingredient["name"] for ingredient in data["ingredients"][:8])
    return data


def scale_recipe_payload(recipe: dict[str, Any], *, factor: float) -> dict[str, Any]:
    """Scale a catalog recipe with conservative guardrails."""
    if factor < 0.5 or factor > 2.5:
        raise RecipeCatalogError(f"Unsupported portion scaling factor: {factor}")

    scaled = deepcopy(recipe)
    scaled["calories"] = round(float(recipe["calories"]) * factor, 1)
    scaled["protein"] = round(float(recipe["protein"]) * factor, 1)
    scaled["fat"] = round(float(recipe["fat"]) * factor, 1)
    scaled["carbs"] = round(float(recipe["carbs"]) * factor, 1)

    normalized_ingredients = []
    for ingredient in recipe.get("ingredients", []):
        normalized = IngredientPayload.model_validate(ingredient).model_dump()
        scaled_amount = round(float(normalized["amount"]) * factor, 1)
        limit = _MAX_INGREDIENT_AMOUNT_BY_UNIT[normalized["unit"]]
        if scaled_amount > limit:
            raise RecipeCatalogError(
                f"Scaled ingredient is unrealistic: {normalized['name']} {scaled_amount} {normalized['unit']}"
            )
        normalized["amount"] = scaled_amount
        normalized_ingredients.append(normalized)

    scaled["ingredients"] = normalized_ingredients
    scaled["ingredients_short"] = recipe.get("ingredients_short") or ", ".join(
        ingredient["name"] for ingredient in normalized_ingredients[:8]
    )
    return normalize_recipe_payload(scaled)
