"""workspaces

Revision ID: 0004_workspaces
Revises: 0003_document_chunk_embedding
Create Date: 2026-05-05 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "0004_workspaces"
down_revision = "0003_document_chunk_embedding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False, server_default="Untitled notebook"),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=True, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
    )
    op.create_index("ix_workspaces_id", "workspaces", ["id"], unique=False)
    op.add_column("documents", sa.Column("workspace_id", sa.Integer(), nullable=True))
    op.create_index("ix_documents_workspace_id", "documents", ["workspace_id"], unique=False)
    op.create_foreign_key(
        "fk_documents_workspace_id_workspaces",
        "documents",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_documents_workspace_id_workspaces", "documents", type_="foreignkey")
    op.drop_index("ix_documents_workspace_id", table_name="documents")
    op.drop_column("documents", "workspace_id")
    op.drop_index("ix_workspaces_id", table_name="workspaces")
    op.drop_table("workspaces")
