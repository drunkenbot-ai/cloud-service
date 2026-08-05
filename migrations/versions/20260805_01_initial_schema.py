"""Create the initial cloud-service schema.

Revision ID: 20260805_01
Revises: None
"""
from alembic import op

from app import models  # noqa: F401 -- register models before metadata access
from app.db import Base

revision = "20260805_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create all current tables for a newly provisioned deployment."""
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """Drop the baseline schema (development use only)."""
    Base.metadata.drop_all(bind=op.get_bind())
