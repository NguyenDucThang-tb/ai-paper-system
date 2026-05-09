"""google auth provider

Revision ID: 0005_google_auth_provider
Revises: 0004_workspaces
Create Date: 2026-05-05 00:00:01
"""
from alembic import op
import sqlalchemy as sa


revision = "0005_google_auth_provider"
down_revision = "0004_workspaces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("auth_provider", sa.String(), nullable=True, server_default="local"))
    op.add_column("users", sa.Column("google_sub", sa.String(), nullable=True))
    op.create_unique_constraint("uq_users_google_sub", "users", ["google_sub"])
    op.alter_column("users", "auth_provider", server_default=None)


def downgrade() -> None:
    op.drop_constraint("uq_users_google_sub", "users", type_="unique")
    op.drop_column("users", "google_sub")
    op.drop_column("users", "auth_provider")
