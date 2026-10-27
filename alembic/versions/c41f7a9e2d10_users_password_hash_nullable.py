"""users password_hash nullable

Revision ID: c41f7a9e2d10
Revises: 6b3190bdf5ea
Create Date: 2026-10-27 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c41f7a9e2d10'
down_revision: Union[str, Sequence[str], None] = '6b3190bdf5ea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('users', 'password_hash', existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    raise NotImplementedError(
        "users created by email code have no password_hash; NOT NULL cannot be restored"
    )
