"""document chunk embedding

Revision ID: 0003_document_chunk_embedding
Revises: 0002_ai_job_contract
Create Date: 2026-05-02 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "0003_document_chunk_embedding"
down_revision = "0002_ai_job_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column("embedding", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document_chunks", "embedding")
