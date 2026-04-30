"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-04-29 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("user_email", sa.String(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("device_id", sa.String(), nullable=False),
    )
    op.create_index("ix_refresh_tokens_id", "refresh_tokens", ["id"], unique=False)
    op.create_index("ix_refresh_tokens_token", "refresh_tokens", ["token"], unique=True)
    op.create_index("ix_refresh_tokens_user_email", "refresh_tokens", ["user_email"], unique=False)
    op.create_index("ix_refresh_tokens_device_id", "refresh_tokens", ["device_id"], unique=False)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
    )
    op.create_index("ix_users_id", "users", ["id"], unique=False)
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "worker_status",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("worker_name", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("current_job_id", sa.Integer(), nullable=True),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
    )
    op.create_index("ix_worker_status_id", "worker_status", ["id"], unique=False)
    op.create_unique_constraint("uq_worker_status_worker_name", "worker_status", ["worker_name"])

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("file_type", sa.String(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=True),
    )
    op.create_index("ix_documents_id", "documents", ["id"], unique=False)

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
    )
    op.create_index("ix_document_chunks_id", "document_chunks", ["id"], unique=False)

    op.create_table(
        "document_graphs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("nodes", sa.JSON(), nullable=True),
        sa.Column("edges", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
    )
    op.create_index("ix_document_graphs_id", "document_graphs", ["id"], unique=False)
    op.create_unique_constraint("uq_document_graphs_document_id", "document_graphs", ["document_id"])

    op.create_table(
        "document_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=True),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_document_jobs_id", "document_jobs", ["id"], unique=False)

    op.create_table(
        "document_metadata",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("publication_year", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("authors", sa.JSON(), nullable=True),
        sa.Column("keywords", sa.JSON(), nullable=True),
        sa.Column("topics", sa.JSON(), nullable=True),
        sa.Column("methods", sa.JSON(), nullable=True),
        sa.Column("doi", sa.String(), nullable=True),
        sa.Column("external_url", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
    )
    op.create_index("ix_document_metadata_id", "document_metadata", ["id"], unique=False)
    op.create_unique_constraint("uq_document_metadata_document_id", "document_metadata", ["document_id"])

    op.create_table(
        "document_recommendations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recommended_document_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("external_url", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
    )
    op.create_index("ix_document_recommendations_id", "document_recommendations", ["id"], unique=False)

    op.create_table(
        "document_summaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("summary_short", sa.Text(), nullable=True),
        sa.Column("summary_medium", sa.Text(), nullable=True),
        sa.Column("summary_long", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
    )
    op.create_index("ix_document_summaries_id", "document_summaries", ["id"], unique=False)

    op.create_table(
        "qa_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("sources", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
    )
    op.create_index("ix_qa_history_id", "qa_history", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_qa_history_id", table_name="qa_history")
    op.drop_table("qa_history")

    op.drop_index("ix_document_summaries_id", table_name="document_summaries")
    op.drop_table("document_summaries")

    op.drop_index("ix_document_recommendations_id", table_name="document_recommendations")
    op.drop_table("document_recommendations")

    op.drop_constraint("uq_document_metadata_document_id", "document_metadata", type_="unique")
    op.drop_index("ix_document_metadata_id", table_name="document_metadata")
    op.drop_table("document_metadata")

    op.drop_index("ix_document_jobs_id", table_name="document_jobs")
    op.drop_table("document_jobs")

    op.drop_constraint("uq_document_graphs_document_id", "document_graphs", type_="unique")
    op.drop_index("ix_document_graphs_id", table_name="document_graphs")
    op.drop_table("document_graphs")

    op.drop_index("ix_document_chunks_id", table_name="document_chunks")
    op.drop_table("document_chunks")

    op.drop_index("ix_documents_id", table_name="documents")
    op.drop_table("documents")

    op.drop_constraint("uq_worker_status_worker_name", "worker_status", type_="unique")
    op.drop_index("ix_worker_status_id", table_name="worker_status")
    op.drop_table("worker_status")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_id", table_name="users")
    op.drop_table("users")

    op.drop_index("ix_refresh_tokens_device_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_email", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_token", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
