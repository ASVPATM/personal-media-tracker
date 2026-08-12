"""Preserve source-specific import context on watch entries."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("watch_entries") as batch:
        batch.add_column(
            sa.Column(
                "import_context",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("watch_entries") as batch:
        batch.drop_column("import_context")
