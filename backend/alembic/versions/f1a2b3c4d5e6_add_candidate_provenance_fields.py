"""add candidate provenance fields

Revision ID: f1a2b3c4d5e6
Revises: c9d4e8f1a2b3
Create Date: 2026-04-13 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "c9d4e8f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "recipe_candidates",
        sa.Column("source_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "recipe_candidates",
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("recipe_candidates", "provenance")
    op.drop_column("recipe_candidates", "source_snapshot")
