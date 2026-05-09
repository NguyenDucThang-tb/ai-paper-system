"""user management hardening

Revision ID: 0006_user_management_hardening
Revises: 0005_google_auth_provider
Create Date: 2026-05-06 00:00:01
"""
from alembic import op
import sqlalchemy as sa


revision = "0006_user_management_hardening"
down_revision = "0005_google_auth_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))

    op.execute("UPDATE users SET role = 'user' WHERE role IS NULL")
    op.execute("UPDATE users SET is_active = TRUE WHERE is_active IS NULL")
    op.execute("UPDATE users SET auth_provider = 'local' WHERE auth_provider IS NULL")

    op.alter_column("users", "role", existing_type=sa.String(), nullable=False, server_default="user")
    op.alter_column("users", "is_active", existing_type=sa.Boolean(), nullable=False, server_default=sa.true())
    op.alter_column("users", "auth_provider", existing_type=sa.String(), nullable=False, server_default="local")

    op.create_check_constraint(
        "ck_users_role_valid",
        "users",
        "role IN ('user', 'admin')",
    )
    op.create_check_constraint(
        "ck_users_auth_provider_valid",
        "users",
        "auth_provider IN ('local', 'google')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_auth_provider_valid", "users", type_="check")
    op.drop_constraint("ck_users_role_valid", "users", type_="check")

    op.alter_column("users", "auth_provider", existing_type=sa.String(), nullable=True, server_default=None)
    op.alter_column("users", "is_active", existing_type=sa.Boolean(), nullable=True, server_default=None)
    op.alter_column("users", "role", existing_type=sa.String(), nullable=True, server_default=None)

    op.drop_column("users", "last_login_at")
    op.drop_column("users", "updated_at")
