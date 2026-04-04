#!/usr/bin/env python3
"""
CLI для NutriAgent — работает без внешнего LLM API.

Команды:
  context   — подготовить контекст (профиль + рецепты + промпт) для агента
  validate  — провалидировать сгенерированный JSON плана
  save      — сохранить валидный план в БД
  user      — показать профиль пользователя
  users     — список всех пользователей
"""

import argparse
import asyncio
import json
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

# Ensure app is importable
sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger  # noqa: E402

logger.remove()

from app.db.session import async_session, engine  # noqa: E402

engine.echo = False


def _run(coro):
    return asyncio.run(coro)


# ──────────────────── context ────────────────────


async def _context(user_id: str, day: int):
    from sqlalchemy import select

    from app.core.rag.retriever import search_recipes
    from app.db.models import User

    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
        user = result.scalar_one_or_none()
        if not user:
            print(f"Error: user {user_id} not found", file=sys.stderr)
            sys.exit(1)

        recipes = await search_recipes(
            session,
            allergies=user.allergies,
            dislikes=user.disliked_ingredients,
            preferred_tags=user.preferences,
            diseases=user.diseases,
            limit=30,
        )

        recipe_list = []
        for r in recipes:
            recipe_list.append(
                {
                    "id": str(r.id),
                    "title": r.title,
                    "calories": r.calories,
                    "protein": r.protein,
                    "fat": r.fat,
                    "carbs": r.carbs,
                    "tags": r.tags or [],
                    "ingredients": r.ingredients,
                }
            )

        context = {
            "user": {
                "id": str(user.id),
                "gender": user.gender.value,
                "age": user.age,
                "weight_kg": user.weight_kg,
                "height_cm": user.height_cm,
                "goal": user.goal.value,
                "target_calories": user.target_calories,
                "allergies": user.allergies or [],
                "preferences": user.preferences or [],
                "disliked_ingredients": user.disliked_ingredients or [],
                "diseases": user.diseases or [],
            },
            "day_number": day,
            "available_recipes": recipe_list,
            "output_schema": {
                "daily_target_calories": "int",
                "day": {
                    "day_number": "int",
                    "total_calories": "float",
                    "total_protein": "float",
                    "total_fat": "float",
                    "total_carbs": "float",
                    "meals": [
                        {
                            "type": "breakfast|lunch|dinner|snack",
                            "recipe_id": "uuid из available_recipes",
                            "title": "str",
                            "calories": "float",
                            "protein": "float",
                            "fat": "float",
                            "carbs": "float",
                            "ingredients_summary": [
                                {"name": "str", "amount": "float", "unit": "str"}
                            ],
                        }
                    ],
                },
            },
        }

        print(json.dumps(context, ensure_ascii=False, indent=2))


def cmd_context(args):
    _run(_context(args.user_id, args.day))


# ──────────────────── validate ────────────────────


def cmd_validate(args):
    from app.core.agent.schemas import MealPlanOutput
    from app.core.skills.validator import validate_day_plan

    raw = sys.stdin.read() if args.file == "-" else Path(args.file).read_text()

    try:
        output = MealPlanOutput.model_validate_json(raw)
    except Exception as e:
        print(json.dumps({"valid": False, "error": f"Parse error: {e}"}))
        sys.exit(1)

    target = args.target_calories or output.daily_target_calories
    is_valid, error = validate_day_plan(output.day, target)
    deviation_pct = (
        round(abs(output.day.total_calories - target) / target * 100, 1) if target > 0 else None
    )

    result = {
        "valid": is_valid,
        "total_calories": output.day.total_calories,
        "target_calories": target,
        "deviation_pct": deviation_pct,
        "meals_count": len(output.day.meals),
    }
    if error:
        result["error"] = error

    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if is_valid else 1)


# ──────────────────── save ────────────────────


async def _save(user_id: str, plan_file: str, days_count: int):
    from app.db.models import MealPlan, MealPlanStatus

    raw = sys.stdin.read() if plan_file == "-" else Path(plan_file).read_text()
    plan_data = json.loads(raw)

    async with async_session() as session:
        plan = MealPlan(
            user_id=uuid.UUID(user_id),
            status=MealPlanStatus.ready,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=days_count - 1),
            plan_data=plan_data,
        )
        session.add(plan)
        await session.commit()
        await session.refresh(plan)

        print(
            json.dumps(
                {
                    "plan_id": str(plan.id),
                    "status": "READY",
                    "days": days_count,
                }
            )
        )


def cmd_save(args):
    _run(_save(args.user_id, args.file, args.days))


# ──────────────────── users ────────────────────


async def _users():
    from sqlalchemy import select

    from app.db.models import User

    async with async_session() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()
        for u in users:
            print(f"  {u.id}  {u.email}  {u.target_calories} ккал  ({u.goal.value})")


def cmd_users(args):
    print("Users:")
    _run(_users())


# ──────────────────── shopping-list ────────────────────


def cmd_shopping(args):
    from app.core.skills.aggregator import aggregate_shopping_list

    raw = sys.stdin.read() if args.file == "-" else Path(args.file).read_text()
    plan_data = json.loads(raw)
    items = aggregate_shopping_list(plan_data)
    print(json.dumps(items, ensure_ascii=False, indent=2))


# ──────────────────── main ────────────────────


def main():
    parser = argparse.ArgumentParser(description="NutriAgent CLI")
    sub = parser.add_subparsers(dest="command")

    p_ctx = sub.add_parser("context", help="Prepare context for agent")
    p_ctx.add_argument("--user-id", required=True)
    p_ctx.add_argument("--day", type=int, default=1)
    p_ctx.set_defaults(func=cmd_context)

    p_val = sub.add_parser("validate", help="Validate generated plan JSON")
    p_val.add_argument("--file", default="-", help="JSON file or - for stdin")
    p_val.add_argument("--target-calories", type=int, default=None)
    p_val.set_defaults(func=cmd_validate)

    p_save = sub.add_parser("save", help="Save plan to database")
    p_save.add_argument("--user-id", required=True)
    p_save.add_argument("--file", default="-", help="JSON file or - for stdin")
    p_save.add_argument("--days", type=int, default=1)
    p_save.set_defaults(func=cmd_save)

    p_users = sub.add_parser("users", help="List all users")
    p_users.set_defaults(func=cmd_users)

    p_shop = sub.add_parser("shopping-list", help="Aggregate shopping list from plan")
    p_shop.add_argument("--file", default="-", help="Plan JSON file or - for stdin")
    p_shop.set_defaults(func=cmd_shopping)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
