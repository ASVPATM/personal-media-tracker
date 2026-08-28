"""Record the selected protected backend for integration credentials.

Revision ID: 0019b
Revises: 0019a
"""

import sqlalchemy as sa
from alembic import op

revision = "0019b"
down_revision = "0019a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("integration_connections", sa.Column("credential_storage", sa.String(30)))


def downgrade() -> None:
    op.drop_column("integration_connections", "credential_storage")
