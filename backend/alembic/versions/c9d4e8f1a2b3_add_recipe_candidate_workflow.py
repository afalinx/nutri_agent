"""add recipe candidate workflow

Revision ID: c9d4e8f1a2b3
Revises: a3b5c7d9e1f2
Create Date: 2026-04-11 16:45:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9d4e8f1a2b3"
down_revision: Union[str, None] = "a3b5c7d9e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


recipe_candidate_status = postgresql.ENUM(
    "pending",
    "review",
    "accepted",
    "rejected",
    name="recipecandidatestatus",
    create_type=False,
)
recipe_review_verdict = postgresql.ENUM(
    "accept",
    "review",
    "reject",
    name="recipereviewverdict",
    create_type=False,
)


def upgrade() -> None:
    recipe_candidate_status.create(op.get_bind(), checkfirst=True)
    recipe_review_verdict.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "recipe_candidates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("source_type", sa.String(length=100), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("normalized_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("validation_report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", recipe_candidate_status, nullable=False),
        sa.Column("submitted_by", sa.String(length=100), nullable=True),
        sa.Column("admitted_recipe_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["admitted_recipe_id"], ["recipes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "recipe_candidate_reviews",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("candidate_id", sa.UUID(), nullable=False),
        sa.Column("reviewer", sa.String(length=100), nullable=True),
        sa.Column("verdict", recipe_review_verdict, nullable=False),
        sa.Column("reason_codes", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("review_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["candidate_id"], ["recipe_candidates.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("recipe_candidate_reviews")
    op.drop_table("recipe_candidates")
    recipe_review_verdict.drop(op.get_bind(), checkfirst=True)
    recipe_candidate_status.drop(op.get_bind(), checkfirst=True)
