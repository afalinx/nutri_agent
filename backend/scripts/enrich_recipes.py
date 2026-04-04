"""One-time script to enrich recipes.json with new fields.

Adds: meal_type, allergens, ingredients_short, prep_time_min, category.
"""

import json
import re
from pathlib import Path

DATA_PATH = Path(__file__).parent.parent / "data" / "recipes.json"

ALLERGEN_ALIASES: dict[str, list[str]] = {
    "nuts": ["орех", "миндал", "фундук", "кешью", "фисташ", "пекан", "арахис"],
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
        "фета",
        "пармезан",
    ],
    "gluten": [
        "пшениц",
        "мука",
        "хлеб",
        "макарон",
        "спагетти",
        "лапша",
        "паста",
        "панировоч",
        "сухар",
        "тортилья",
        "гренк",
        "блин",
        "манка",
        "булгур",
        "кускус",
        "гранол",
    ],
    "eggs": ["яйц", "яичн"],
    "soy": ["соев", "тофу"],
    "fish": ["рыб", "лосос", "тунец", "треск", "сёмг", "минтай"],
    "shellfish": ["креветк", "краб", "мидии", "устриц"],
    "lactose": ["молок", "молоч", "сливк", "кефир", "йогурт"],
    "honey": ["мёд", "мед"],
    "peanuts": ["арахис"],
}

TAG_TO_MEAL_TYPE = {
    "завтрак": "breakfast",
    "обед": "lunch",
    "ужин": "dinner",
    "перекус": "snack",
}

CATEGORY_RULES: list[tuple[list[str], str]] = [
    (["каша", "овсян", "гречнев"], "каша"),
    (["суп", "борщ"], "суп"),
    (["салат", "цезарь", "греческ"], "салат"),
    (["смузи", "коктейль"], "напиток"),
    (["блины", "сырник", "запеканка", "шакшука", "омлет", "яичниц"], "блюдо из яиц/теста"),
    (["тост"], "бутерброд"),
    (["сэндвич"], "бутерброд"),
    (["паста", "болоньезе", "спагетти"], "паста"),
    (["плов"], "плов"),
    (["бурито"], "бурито"),
    (["рагу"], "рагу"),
    (["наггетс", "котлет"], "котлеты"),
    (["стейк"], "стейк"),
    (["батончик"], "батончик"),
    (["палочки", "хумус"], "закуска"),
    (["миндал", "орех"], "орехи"),
    (["йогурт", "кефир", "отруб"], "молочное"),
]


def detect_allergens(recipe: dict) -> list[str]:
    text = (
        " ".join(ing["name"].lower() for ing in recipe["ingredients"])
        + " "
        + recipe["title"].lower()
    )

    found: set[str] = set()
    for allergen, keywords in ALLERGEN_ALIASES.items():
        for kw in keywords:
            if kw in text:
                found.add(allergen)
                break
    return sorted(found)


def detect_meal_type(recipe: dict) -> str:
    tags = [t.lower() for t in recipe.get("tags", [])]
    types = []
    for tag, mt in TAG_TO_MEAL_TYPE.items():
        if tag in tags:
            types.append(mt)

    if not types:
        return "universal"
    if len(types) == 1:
        return types[0]
    # Multi-tag: prefer lunch/dinner for combined recipes
    if "lunch" in types and "dinner" in types:
        return "lunch/dinner"
    if "breakfast" in types and "snack" in types:
        return "breakfast"
    return types[0]


def build_ingredients_short(recipe: dict) -> str:
    names = [ing["name"] for ing in recipe["ingredients"]]
    return ", ".join(names)


def estimate_prep_time(recipe: dict) -> int:
    desc = recipe.get("description", "").lower()

    # Extract explicit times from description
    times = re.findall(r"(\d+)\s*(?:минут|мин)", desc)
    total = sum(int(t) for t in times)

    # Add base prep time
    if "нарез" in desc or "смешат" in desc:
        total += 5

    if total == 0:
        # Default estimates based on complexity
        n_ingredients = len(recipe.get("ingredients", []))
        if n_ingredients <= 2:
            return 5
        elif n_ingredients <= 3:
            return 10
        return 15

    return max(5, total)


def detect_category(recipe: dict) -> str:
    title_lower = recipe["title"].lower()
    for keywords, category in CATEGORY_RULES:
        for kw in keywords:
            if kw in title_lower:
                return category

    # Fallback based on main protein/grain
    ingredients_text = " ".join(ing["name"].lower() for ing in recipe["ingredients"])
    if any(w in ingredients_text for w in ["курин", "куриц", "индейк"]):
        return "птица с гарниром"
    if any(w in ingredients_text for w in ["говяд", "свинин", "фарш"]):
        return "мясо с гарниром"
    if any(w in ingredients_text for w in ["лосос", "треск", "тунец", "минтай", "рыб"]):
        return "рыба с гарниром"
    if any(w in ingredients_text for w in ["тофу", "чечевиц", "фасол", "горох"]):
        return "бобовые/тофу"

    return "другое"


def enrich_recipes():
    with open(DATA_PATH, encoding="utf-8") as f:
        recipes = json.load(f)

    for recipe in recipes:
        recipe["meal_type"] = detect_meal_type(recipe)
        recipe["allergens"] = detect_allergens(recipe)
        recipe["ingredients_short"] = build_ingredients_short(recipe)
        recipe["prep_time_min"] = estimate_prep_time(recipe)
        recipe["category"] = detect_category(recipe)

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(recipes, f, ensure_ascii=False, indent=2)

    print(f"Enriched {len(recipes)} recipes")

    # Summary
    meal_types = {}
    categories = {}
    all_allergens = set()
    for r in recipes:
        mt = r["meal_type"]
        meal_types[mt] = meal_types.get(mt, 0) + 1
        cat = r["category"]
        categories[cat] = categories.get(cat, 0) + 1
        all_allergens.update(r["allergens"])

    print(f"\nMeal types: {dict(sorted(meal_types.items()))}")
    print(f"Categories: {dict(sorted(categories.items()))}")
    print(f"Allergens found: {sorted(all_allergens)}")


if __name__ == "__main__":
    enrich_recipes()
