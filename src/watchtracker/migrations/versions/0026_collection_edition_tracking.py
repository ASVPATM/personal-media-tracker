"""Keep exact edition facts, explicit counts and personal taxonomy overrides."""

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("music_albums", "book_records"):
        op.add_column(name, sa.Column("completion_count", sa.Integer(), nullable=True))
        op.add_column(
            name, sa.Column("edition_info", sa.JSON(), server_default="{}", nullable=False)
        )
        for field in (
            "genre_additions",
            "genre_removals",
            "subgenre_additions",
            "subgenre_removals",
        ):
            op.add_column(
                name, sa.Column(field, sa.JSON(), server_default="[]", nullable=False)
            )


def downgrade() -> None:
    for name in ("music_albums", "book_records"):
        if op.get_bind().scalar(sa.select(sa.func.count()).select_from(sa.table(name))):
            raise RuntimeError("Collection data exists. Preserve it before downgrading.")
    for name in ("music_albums", "book_records"):
        for field in (
            "completion_count",
            "edition_info",
            "genre_additions",
            "genre_removals",
            "subgenre_additions",
            "subgenre_removals",
        ):
            op.drop_column(name, field)
