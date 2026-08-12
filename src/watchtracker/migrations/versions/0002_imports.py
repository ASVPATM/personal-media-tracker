"""Add transactional import preview and idempotency records."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "import_previews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("import_kind", sa.String(30), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_import_previews_source_hash", "import_previews", ["source_hash"])
    op.create_table(
        "import_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("import_kind", sa.String(30), nullable=False),
        sa.Column("summary", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_hash", name="uq_import_history_hash"),
    )


def downgrade() -> None:
    op.drop_table("import_history")
    op.drop_table("import_previews")
