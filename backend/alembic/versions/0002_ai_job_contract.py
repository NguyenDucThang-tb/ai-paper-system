"""ai job contract

Revision ID: 0002_ai_job_contract
Revises: 0001_initial_schema
Create Date: 2026-04-30 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "0002_ai_job_contract"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_jobs",
        sa.Column("job_type", sa.String(), nullable=False, server_default="process_document"),
    )
    op.add_column("document_jobs", sa.Column("requested_by_user_id", sa.Integer(), nullable=True))
    op.add_column("document_jobs", sa.Column("payload", sa.JSON(), nullable=True))
    op.add_column("document_jobs", sa.Column("result", sa.JSON(), nullable=True))
    op.add_column("document_jobs", sa.Column("error_message", sa.Text(), nullable=True))
    op.add_column("document_jobs", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("document_jobs", "job_type", server_default=None)


def downgrade() -> None:
    op.drop_column("document_jobs", "completed_at")
    op.drop_column("document_jobs", "error_message")
    op.drop_column("document_jobs", "result")
    op.drop_column("document_jobs", "payload")
    op.drop_column("document_jobs", "requested_by_user_id")
    op.drop_column("document_jobs", "job_type")
