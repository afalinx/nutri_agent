"""add source candidate workflow

Revision ID: d2e4f6a8b0c1
Revises: f1a2b3c4d5e6
Create Date: 2026-04-13 15:58:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2e4f6a8b0c1"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


source_candidate_status = postgresql.ENUM(
    "pending",
    "accepted",
    "rejected",
    name="sourcecandidatestatus",
    create_type=False,
)


def upgrade() -> None:
    source_candidate_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "source_candidates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=100), nullable=False),
        sa.Column("discovery_query", sa.String(length=255), nullable=True),
        sa.Column("discovery_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("validation_report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", source_candidate_status, nullable=False),
        sa.Column("discovered_by", sa.String(length=100), nullable=True),
        sa.Column("linked_candidate_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["linked_candidate_id"], ["recipe_candidates.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url", name="uq_source_candidates_url"),
    )
    op.create_index("ix_source_candidates_domain", "source_candidates", ["domain"])
    op.create_index("ix_source_candidates_status", "source_candidates", ["status"])


def downgrade() -> None:
    op.drop_index("ix_source_candidates_status", table_name="source_candidates")
    op.drop_index("ix_source_candidates_domain", table_name="source_candidates")
    op.drop_table("source_candidates")
    source_candidate_status.drop(op.get_bind(), checkfirst=True)
