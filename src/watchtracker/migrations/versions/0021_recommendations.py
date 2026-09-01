"""Add tenant-owned Standard recommendation state and refinement policy versioning.

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def upgrade() -> None:
    op.add_column(
        "rating_assessments",
        sa.Column("question_order", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "rating_refinement_runs",
        sa.Column(
            "session_policy_version",
            sa.String(40),
            nullable=False,
            server_default="comparisons-first-v1",
        ),
    )
    op.add_column(
        "rating_refinement_runs",
        sa.Column(
            "skipped_entry_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
    )

    op.create_table(
        "user_recommendation_preferences",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("engine", sa.String(30), nullable=False, server_default="scalar"),
        sa.Column("use_ratings", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("use_favorites", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("use_refinement", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("use_rewatches", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("use_live_discovery", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("local_llm_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "excluded_media_types", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("excluded_genres", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="365"),
        sa.Column("consent_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.CheckConstraint(
            "engine IN ('scalar', 'advanced_hybrid')", name="ck_recommendation_engine"
        ),
        sa.CheckConstraint("version >= 1", name="ck_recommendation_preference_version"),
        sa.CheckConstraint(
            "retention_days >= 30 AND retention_days <= 3650",
            name="ck_recommendation_retention_days",
        ),
        sa.CheckConstraint("consent_revision >= 1", name="ck_recommendation_consent_revision"),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "recommendation_signal_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("source_revision", sa.BigInteger(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("signal_contract_version", sa.String(40), nullable=False),
        sa.Column("evidence_counts", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("signals", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column(
            "evidence_anchors", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column(
            "evidence_sufficient", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.CheckConstraint("source_revision >= 1", name="ck_recommendation_signal_revision"),
        sa.UniqueConstraint("user_id", "source_hash", name="uq_recommendation_signal_hash"),
    )
    op.create_index(
        "ix_recommendation_signal_user_created",
        "recommendation_signal_snapshots",
        ["user_id", "created_at"],
    )

    op.create_table(
        "recommendation_catalog_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("catalog_item_id", sa.String(36), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=False),
        sa.Column("source_score", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("region", sa.String(30)),
        sa.Column("language", sa.String(30)),
        sa.Column("provenance", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.ForeignKeyConstraint(["catalog_item_id"], ["catalog_items.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "source_score >= 0 AND source_score <= 1", name="ck_recommendation_candidate_score"
        ),
        sa.UniqueConstraint("catalog_item_id", name="uq_recommendation_candidate_catalog"),
    )
    op.create_index(
        "ix_recommendation_candidate_freshness",
        "recommendation_catalog_candidates",
        ["source", "expires_at"],
    )

    op.create_table(
        "recommendation_candidate_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("preference_revision", sa.Integer(), nullable=False),
        sa.Column("signal_snapshot_id", sa.String(36), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("coverage", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("warning_codes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["signal_snapshot_id"], ["recommendation_signal_snapshots.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "preference_revision >= 1", name="ck_recommendation_snapshot_preference_revision"
        ),
    )
    op.create_index(
        "ix_recommendation_candidate_snapshot_user",
        "recommendation_candidate_snapshots",
        ["user_id", "created_at"],
    )

    op.create_table(
        "recommendation_candidate_snapshot_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("identity_quality", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("metadata_quality", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("artwork_available", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("eligibility", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("scoring_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "provenance_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["recommendation_candidate_snapshots.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["recommendation_catalog_candidates.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "snapshot_id", "candidate_id", name="uq_recommendation_snapshot_item"
        ),
        sa.UniqueConstraint(
            "snapshot_id", "position", name="uq_recommendation_snapshot_position"
        ),
        sa.CheckConstraint("position >= 1", name="ck_recommendation_snapshot_position"),
        sa.CheckConstraint(
            "identity_quality >= 0 AND identity_quality <= 1",
            name="ck_recommendation_identity_quality",
        ),
        sa.CheckConstraint(
            "metadata_quality >= 0 AND metadata_quality <= 1",
            name="ck_recommendation_metadata_quality",
        ),
    )

    op.create_table(
        "recommendation_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("distribution_flavor", sa.String(40), nullable=False),
        sa.Column("engine", sa.String(30), nullable=False, server_default="scalar"),
        sa.Column("engine_version", sa.String(40), nullable=False),
        sa.Column("signal_contract_version", sa.String(40), nullable=False),
        sa.Column("score_scale_version", sa.String(40), nullable=False),
        sa.Column("model_versions", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("signal_snapshot_id", sa.String(36)),
        sa.Column("candidate_snapshot_id", sa.String(36)),
        sa.Column("input_revision", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("deterministic_seed", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("phase", sa.String(40), nullable=False, server_default="checking_readiness"),
        sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "progress_indeterminate", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("completed_units", sa.Integer()),
        sa.Column("total_units", sa.Integer()),
        sa.Column(
            "message_key",
            sa.String(100),
            nullable=False,
            server_default="recommendations.progress.checking_readiness",
        ),
        sa.Column("warning_codes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("failure_code", sa.String(80)),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("safe_failure_detail", sa.String(300)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_recommendation_run_state",
        ),
        sa.CheckConstraint("input_revision >= 1", name="ck_recommendation_run_revision"),
        sa.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_recommendation_run_progress",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["signal_snapshot_id"], ["recommendation_signal_snapshots.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_snapshot_id"],
            ["recommendation_candidate_snapshots.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "user_id", "idempotency_key", name="uq_recommendation_run_idempotency"
        ),
    )
    op.create_index(
        "ix_recommendation_run_user_state",
        "recommendation_runs",
        ["user_id", "state", "created_at"],
    )
    op.create_index(
        "uq_recommendation_run_active_user",
        "recommendation_runs",
        ["user_id"],
        unique=True,
        sqlite_where=sa.text("state IN ('queued', 'running')"),
        postgresql_where=sa.text("state IN ('queued', 'running')"),
    )

    op.create_table(
        "recommendation_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("catalog_item_id", sa.String(36), nullable=False),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("final_match", sa.Float(), nullable=False),
        sa.Column("display_match", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("baseline_contribution", sa.Float(), nullable=False),
        sa.Column("tower_contribution", sa.Float()),
        sa.Column("llm_contribution", sa.Float()),
        sa.Column("reason_codes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("risk_codes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column(
            "anchor_catalog_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column(
            "eligibility_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("provenance", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["recommendation_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["catalog_item_id"], ["catalog_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["recommendation_catalog_candidates.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("run_id", "rank", name="uq_recommendation_result_rank"),
        sa.UniqueConstraint(
            "run_id", "catalog_item_id", name="uq_recommendation_result_catalog"
        ),
        sa.CheckConstraint("rank >= 1", name="ck_recommendation_result_rank"),
        sa.CheckConstraint(
            "final_match >= 0 AND final_match <= 1", name="ck_recommendation_result_match"
        ),
        sa.CheckConstraint(
            "display_match >= 0 AND display_match <= 100",
            name="ck_recommendation_result_display",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_recommendation_result_confidence",
        ),
        sa.CheckConstraint(
            "baseline_contribution >= 0 AND baseline_contribution <= 1",
            name="ck_recommendation_result_baseline",
        ),
        sa.CheckConstraint(
            "tower_contribution IS NULL OR (tower_contribution >= 0 AND tower_contribution <= 1)",
            name="ck_recommendation_result_tower",
        ),
        sa.CheckConstraint(
            "llm_contribution IS NULL OR (llm_contribution >= 0 AND llm_contribution <= 1)",
            name="ck_recommendation_result_llm",
        ),
    )
    op.create_index(
        "ix_recommendation_result_run", "recommendation_results", ["run_id", "rank"]
    )

    op.create_table(
        "recommendation_feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("result_id", sa.String(36), nullable=False),
        sa.Column("feedback", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "feedback IN ('useful', 'not_interested', 'already_seen', 'wrong_mood')",
            name="ck_recommendation_feedback_value",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["result_id"], ["recommendation_results.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("user_id", "result_id", name="uq_recommendation_feedback_result"),
    )
    op.create_index(
        "ix_recommendation_feedback_user",
        "recommendation_feedback",
        ["user_id", "created_at"],
    )

    op.create_table(
        "recommendation_preference_claims",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("dimension", sa.String(80), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("model_id", sa.String(160)),
        sa.Column("source_revision", sa.BigInteger(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_recommendation_claim_confidence"
        ),
        sa.CheckConstraint("source_revision >= 1", name="ck_recommendation_claim_revision"),
    )
    op.create_index(
        "ix_recommendation_claim_user_active",
        "recommendation_preference_claims",
        ["user_id", "revoked_at"],
    )

    op.create_table(
        "recommendation_model_qualifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("adapter_id", sa.String(80), nullable=False),
        sa.Column("model_id", sa.String(160), nullable=False),
        sa.Column("qualification_version", sa.String(40), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column(
            "capability_results", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("safe_timings", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "stability_metrics", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_recommendation_qualification_user",
        "recommendation_model_qualifications",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if (
        bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM rating_assessments "
                "WHERE rubric_version = 'guided-rubric-v4'"
            )
        ).scalar_one()
        or bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM rating_refinement_runs "
                "WHERE session_policy_version != 'comparisons-first-v1'"
            )
        ).scalar_one()
    ):
        raise RuntimeError(
            "Direct-first refinement data exists. Export or remove it before downgrading below 0021."
        )
    for table in (
        "recommendation_results",
        "recommendation_feedback",
        "recommendation_runs",
        "recommendation_candidate_snapshots",
        "recommendation_signal_snapshots",
        "recommendation_preference_claims",
        "recommendation_model_qualifications",
        "user_recommendation_preferences",
    ):
        if bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one():
            raise RuntimeError(
                "Recommendation data exists. Export or delete it before downgrading below 0021."
            )
    op.drop_index(
        "ix_recommendation_qualification_user", table_name="recommendation_model_qualifications"
    )
    op.drop_table("recommendation_model_qualifications")
    op.drop_index(
        "ix_recommendation_claim_user_active", table_name="recommendation_preference_claims"
    )
    op.drop_table("recommendation_preference_claims")
    op.drop_index("ix_recommendation_feedback_user", table_name="recommendation_feedback")
    op.drop_table("recommendation_feedback")
    op.drop_index("ix_recommendation_result_run", table_name="recommendation_results")
    op.drop_table("recommendation_results")
    op.drop_index("uq_recommendation_run_active_user", table_name="recommendation_runs")
    op.drop_index("ix_recommendation_run_user_state", table_name="recommendation_runs")
    op.drop_table("recommendation_runs")
    op.drop_table("recommendation_candidate_snapshot_items")
    op.drop_index(
        "ix_recommendation_candidate_snapshot_user",
        table_name="recommendation_candidate_snapshots",
    )
    op.drop_table("recommendation_candidate_snapshots")
    op.drop_index(
        "ix_recommendation_candidate_freshness",
        table_name="recommendation_catalog_candidates",
    )
    op.drop_table("recommendation_catalog_candidates")
    op.drop_index(
        "ix_recommendation_signal_user_created",
        table_name="recommendation_signal_snapshots",
    )
    op.drop_table("recommendation_signal_snapshots")
    op.drop_table("user_recommendation_preferences")
    op.drop_column("rating_refinement_runs", "skipped_entry_ids")
    op.drop_column("rating_refinement_runs", "session_policy_version")
    op.drop_column("rating_assessments", "question_order")
