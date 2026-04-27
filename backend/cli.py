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
import sys
from pathlib import Path

# Ensure app is importable
sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger

logger.remove()

from app.db.session import async_session, engine  # noqa: E402
from app.core.cli_contract import (  # noqa: E402
    build_context_payload,
    build_shopping_list_payload,
    dump_json,
    save_plan_payload,
    validate_plan_payload,
)

engine.echo = False


def _run(coro):
    return asyncio.run(coro)


# ──────────────────── context ────────────────────


async def _context(user_id: str, day: int):
    context = await build_context_payload(user_id, day)
    print(dump_json(context))


def cmd_context(args):
    _run(_context(args.user_id, args.day))


# ──────────────────── validate ────────────────────


def cmd_validate(args):
    raw = sys.stdin.read() if args.file == "-" else Path(args.file).read_text()
    result, exit_code = validate_plan_payload(raw, target_calories=args.target_calories)
    print(dump_json(result))
    sys.exit(exit_code)


# ──────────────────── save ────────────────────


async def _save(user_id: str, plan_file: str, days_count: int):
    import json

    raw = sys.stdin.read() if plan_file == "-" else Path(plan_file).read_text()
    plan_data = json.loads(raw)
    result = await save_plan_payload(user_id, plan_data, days_count=days_count)
    print(dump_json(result))


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
    import json

    raw = sys.stdin.read() if args.file == "-" else Path(args.file).read_text()
    plan_data = json.loads(raw)
    input_format = "day" if args.day_format else args.input_format
    try:
        items = build_shopping_list_payload(plan_data, input_format=input_format)
    except ValueError as exc:
        print(dump_json({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)
    print(dump_json(items))


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
    p_shop.add_argument(
        "--day-format",
        action="store_true",
        help="Treat input as one-day format ({daily_target_calories, day})",
    )
    p_shop.add_argument(
        "--input-format",
        choices=["auto", "day", "week"],
        default="auto",
        help="Input JSON format (default: auto)",
    )
    p_shop.set_defaults(func=cmd_shopping)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
