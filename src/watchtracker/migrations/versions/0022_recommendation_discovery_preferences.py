"""Explicit discovery consent and local recommendation feedback preferences."""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_recommendation_preferences",
        sa.Column(
            "use_taste_discovery", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "user_recommendation_preferences",
        sa.Column("use_feedback", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "user_recommendation_preferences",
        sa.Column("discovery_language", sa.String(10), nullable=False, server_default=""),
    )


def downgrade() -> None:
    with op.batch_alter_table("user_recommendation_preferences") as batch:
        batch.drop_column("discovery_language")
        batch.drop_column("use_feedback")
        batch.drop_column("use_taste_discovery")
