"""add recipe enrichment fields

Revision ID: a3b5c7d9e1f2
Revises: 4f1df7d14a20
Create Date: 2026-04-04 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3b5c7d9e1f2"
down_revision: Union[str, None] = "4f1df7d14a20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("recipes", sa.Column("meal_type", sa.String(50), nullable=True))
    op.add_column(
        "recipes",
        sa.Column("allergens", postgresql.ARRAY(sa.String()), server_default="{}", nullable=True),
    )
    op.add_column("recipes", sa.Column("ingredients_short", sa.String(500), nullable=True))
    op.add_column("recipes", sa.Column("prep_time_min", sa.Integer(), nullable=True))
    op.add_column("recipes", sa.Column("category", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("recipes", "category")
    op.drop_column("recipes", "prep_time_min")
    op.drop_column("recipes", "ingredients_short")
    op.drop_column("recipes", "allergens")
    op.drop_column("recipes", "meal_type")
