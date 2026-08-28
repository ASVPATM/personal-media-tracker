"""Retain bounded provider values used during normalized account imports.

Revision ID: 0019a
Revises: 0019
"""

import sqlalchemy as sa
from alembic import op

revision = "0019a"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "integration_events",
        sa.Column("source_values", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    op.drop_column("integration_events", "source_values")
