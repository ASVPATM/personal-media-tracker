"""Isolated manual books; no conversions or changes to screen/music records."""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "book_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("identity_key", sa.String(64), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("author", sa.String(500), nullable=False),
        sa.Column("year", sa.Integer()),
        sa.Column("book_format", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("rating", sa.Float()),
        sa.Column("favorite", sa.Boolean(), nullable=False),
        sa.Column("genres", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("publisher", sa.String(500), nullable=False),
        sa.Column("isbn", sa.String(13)),
        sa.Column("page_count", sa.Integer()),
        sa.Column("current_page", sa.Integer()),
        sa.Column("artwork_url", sa.Text()),
        sa.Column("artwork_data", sa.Text()),
        sa.Column("provider_id", sa.String(30)),
        sa.Column("work_id", sa.String(30)),
        sa.Column("chapters", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "identity_key", name="uq_book_identity"),
        sa.CheckConstraint(
            "rating IS NULL OR (rating >= 1 AND rating <= 10)", name="ck_book_rating"
        ),
    )
    op.create_index("ix_book_owner_deleted", "book_records", ["user_id", "deleted_at"])
    op.create_table(
        "book_lists",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("book_ids", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_book_lists_user_id", "book_lists", ["user_id"])


def downgrade() -> None:
    for table in ("book_records", "book_lists"):
        if op.get_bind().scalar(sa.text(f"SELECT count(*) FROM {table}")):
            raise RuntimeError("Book data exists. Export and preserve it before downgrading.")
    op.drop_table("book_lists")
    op.drop_table("book_records")
