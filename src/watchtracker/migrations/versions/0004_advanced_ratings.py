"""Add optional guided rating assessments and pair comparisons."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rating_assessments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "entry_id",
            sa.String(36),
            sa.ForeignKey("watch_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(30), nullable=False),
        sa.Column("rubric_version", sa.String(40), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("answers", sa.JSON, nullable=False),
        sa.Column("private_reflection", sa.Text),
        sa.Column("rubric_score", sa.Float),
        sa.Column("rubric_coverage", sa.Float),
        sa.Column("suggested_rating", sa.Float),
        sa.Column("final_rating_snapshot", sa.Float),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "state IN ('draft', 'completed', 'superseded')",
            name="ck_rating_assessment_state",
        ),
        sa.CheckConstraint("version >= 1", name="ck_rating_assessment_version"),
    )
    op.create_index(
        "ix_rating_assessment_entry_state",
        "rating_assessments",
        ["entry_id", "state", "completed_at"],
    )
    op.create_index(
        "uq_rating_assessment_active_draft",
        "rating_assessments",
        ["entry_id", "rubric_version"],
        unique=True,
        sqlite_where=sa.text("state = 'draft'"),
        postgresql_where=sa.text("state = 'draft'"),
    )
    op.create_table(
        "rating_comparisons",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "entry_low_id",
            sa.String(36),
            sa.ForeignKey("watch_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "entry_high_id",
            sa.String(36),
            sa.ForeignKey("watch_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "displayed_left_entry_id",
            sa.String(36),
            sa.ForeignKey("watch_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dimension", sa.String(40), nullable=False),
        sa.Column("result", sa.String(10), nullable=False),
        sa.Column("selection_reason", sa.String(80), nullable=False),
        sa.Column("algorithm_version", sa.String(40), nullable=False),
        sa.Column("skipped_until", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("entry_low_id < entry_high_id", name="ck_rating_pair_order"),
        sa.CheckConstraint(
            "displayed_left_entry_id IN (entry_low_id, entry_high_id)",
            name="ck_rating_pair_left_member",
        ),
        sa.CheckConstraint(
            "result IN ('low', 'high', 'tie', 'skip')",
            name="ck_rating_comparison_result",
        ),
        sa.UniqueConstraint("entry_low_id", "entry_high_id", name="uq_rating_comparison_pair"),
    )
    op.create_index("ix_rating_comparison_updated", "rating_comparisons", ["updated_at"])


def downgrade() -> None:
    op.drop_table("rating_comparisons")
    op.drop_table("rating_assessments")
