"""An isolated, user-owned music collection. No changes to existing media rows."""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "music_albums",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("identity_key", sa.String(64), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("artist", sa.String(500), nullable=False),
        sa.Column("year", sa.Integer()),
        sa.Column("release_type", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("rating", sa.Float()),
        sa.Column("favorite", sa.Boolean(), nullable=False),
        sa.Column("genres", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("artwork_url", sa.Text()),
        sa.Column("artwork_data", sa.Text()),
        sa.Column("provider_id", sa.String(36)),
        sa.Column("release_group_id", sa.String(36)),
        sa.Column("tracks", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "identity_key", name="uq_music_album_identity"),
        sa.CheckConstraint(
            "rating IS NULL OR (rating >= 1 AND rating <= 10)", name="ck_music_rating"
        ),
    )
    op.create_index("ix_music_owner_deleted", "music_albums", ["user_id", "deleted_at"])
    op.create_table(
        "music_lists",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("album_ids", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_music_lists_user_id", "music_lists", ["user_id"])


def downgrade() -> None:
    connection = op.get_bind()
    for table in ("music_albums", "music_lists"):
        if connection.scalar(sa.text(f"SELECT count(*) FROM {table}")):
            raise RuntimeError("Music data exists. Export and preserve it before downgrading.")
    op.drop_table("music_lists")
    op.drop_table("music_albums")
