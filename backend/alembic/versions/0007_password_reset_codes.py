"""add password reset codes table

Revision ID: 0007_password_reset_codes
Revises: 0006_user_management_hardening
Create Date: 2026-05-07 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "0007_password_reset_codes"
down_revision = "0006_user_management_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "password_reset_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
    )
    op.create_index("ix_password_reset_codes_id", "password_reset_codes", ["id"], unique=False)
    op.create_index("ix_password_reset_codes_email", "password_reset_codes", ["email"], unique=False)
    op.create_index("ix_password_reset_codes_code_hash", "password_reset_codes", ["code_hash"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_password_reset_codes_code_hash", table_name="password_reset_codes")
    op.drop_index("ix_password_reset_codes_email", table_name="password_reset_codes")
    op.drop_index("ix_password_reset_codes_id", table_name="password_reset_codes")
    op.drop_table("password_reset_codes")
