"""merge comments trades referrals with is_admin

Revision ID: 83ff3dfd8ae2
Revises: c1794894c63a, 3dc7b1990350
Create Date: 2026-07-25 14:16:32.221271

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '83ff3dfd8ae2'
down_revision: Union[str, None] = ('c1794894c63a', '3dc7b1990350')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
