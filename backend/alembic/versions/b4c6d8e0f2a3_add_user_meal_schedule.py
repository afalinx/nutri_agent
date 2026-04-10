"""add user meal_schedule

Revision ID: b4c6d8e0f2a3
Revises: a3b5c7d9e1f2
Create Date: 2026-04-04 14:00:00.000000
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b4c6d8e0f2a3"
down_revision: Union[str, None] = "a3b5c7d9e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_SCHEDULE = [
    {"type": "breakfast", "time": "08:00", "calories_pct": 25},
    {"type": "lunch", "time": "13:00", "calories_pct": 35},
    {"type": "dinner", "time": "19:00", "calories_pct": 30},
    {"type": "snack", "time": "16:00", "calories_pct": 10},
]


def upgrade() -> None:
    default_schedule_json = json.dumps(DEFAULT_SCHEDULE)
    op.add_column(
        "users",
        sa.Column(
            "meal_schedule",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text(f"'{default_schedule_json}'::jsonb"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "meal_schedule")
