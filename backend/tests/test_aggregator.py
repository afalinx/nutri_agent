"""Unit-тесты агрегатора списка покупок."""

from app.core.skills.aggregator import aggregate_shopping_list


def test_aggregator_sums_items_by_name_and_unit():
    plan_data = {
        "days": [
            {
                "meals": [
                    {
                        "ingredients_summary": [
                            {"name": "Рис", "amount": 80, "unit": "g"},
                            {"name": "Курица", "amount": 200, "unit": "g"},
                        ]
                    }
                ]
            },
            {
                "meals": [
                    {
                        "ingredients_summary": [
                            {"name": "рис", "amount": 90, "unit": "g"},
                            {"name": "Курица", "amount": 150, "unit": "g"},
                        ]
                    }
                ]
            },
        ]
    }

    result = aggregate_shopping_list(plan_data)
    assert result == [
        {"name": "Курица", "amount": 350.0, "unit": "g"},
        {"name": "Рис", "amount": 170.0, "unit": "g"},
    ]


def test_aggregator_skips_empty_ingredient_names():
    plan_data = {
        "days": [
            {
                "meals": [
                    {
                        "ingredients_summary": [
                            {"name": "", "amount": 10, "unit": "g"},
                            {"name": "  ", "amount": 20, "unit": "g"},
                            {"name": "Тофу", "amount": 120, "unit": "g"},
                        ]
                    }
                ]
            }
        ]
    }

    result = aggregate_shopping_list(plan_data)
    assert result == [{"name": "Тофу", "amount": 120.0, "unit": "g"}]
