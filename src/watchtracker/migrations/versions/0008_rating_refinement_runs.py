"""Add resumable staged rating-refinement runs.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rating_refinement_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(20), nullable=False),
        sa.Column("rubric_version", sa.String(40), nullable=False),
        sa.Column("ranking_version", sa.String(40), nullable=False),
        sa.Column("target_entry_ids", sa.JSON, nullable=False),
        sa.Column("completed_entry_ids", sa.JSON, nullable=False),
        sa.Column("completed_pair_keys", sa.JSON, nullable=False),
        sa.Column("comparison_target", sa.Integer, nullable=False),
        sa.Column("comparisons_completed", sa.Integer, nullable=False),
        sa.Column("assessment_target", sa.Integer, nullable=False),
        sa.Column("assessments_completed", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("scope IN ('focused', 'full')", name="ck_rating_refinement_scope"),
        sa.CheckConstraint(
            "state IN ('active', 'completed', 'cancelled')",
            name="ck_rating_refinement_state",
        ),
        sa.CheckConstraint(
            "stage IN ('comparisons', 'assessments', 'complete')",
            name="ck_rating_refinement_stage",
        ),
        sa.CheckConstraint(
            "comparison_target >= 0 AND comparisons_completed >= 0",
            name="ck_rating_refinement_comparison_counts",
        ),
        sa.CheckConstraint(
            "assessment_target >= 0 AND assessments_completed >= 0",
            name="ck_rating_refinement_assessment_counts",
        ),
    )
    op.create_index(
        "ix_rating_refinement_state_updated",
        "rating_refinement_runs",
        ["state", "updated_at"],
    )


def downgrade() -> None:
    op.drop_table("rating_refinement_runs")
