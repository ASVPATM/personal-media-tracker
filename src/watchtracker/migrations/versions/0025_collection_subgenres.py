"""Preserve provider genres and add independent, editable collection subgenres."""

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("music_albums", "book_records"):
        op.add_column(
            name,
            sa.Column("subgenres", sa.JSON(), server_default="[]", nullable=False),
        )


def downgrade() -> None:
    # SQLite DDL can persist even when a later migration refuses a downgrade.
    # Match the collection-table guards before dropping *any* columns so a
    # downgrade through 0024/0023 cannot leave a partially downgraded schema.
    for name in ("music_albums", "book_records"):
        table = sa.table(name)
        if op.get_bind().scalar(sa.select(sa.func.count()).select_from(table)):
            raise RuntimeError("Collection data exists. Preserve it before downgrading.")
    for name in ("music_albums", "book_records"):
        op.drop_column(name, "subgenres")
