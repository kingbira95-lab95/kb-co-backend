"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-06-22
"""
from alembic import op
import sqlalchemy as sa

revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # All tables are created by SQLAlchemy's create_all in database.py on startup.
    # This migration is a placeholder; add custom migrations here as the schema evolves.
    pass


def downgrade() -> None:
    pass
