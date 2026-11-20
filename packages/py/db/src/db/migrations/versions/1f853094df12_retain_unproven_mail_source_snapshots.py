"""retain unproven mail source snapshots

Revision ID: 1f853094df12
Revises: 5841a5030b92
Create Date: 2026-11-20 18:18:41.034360

"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op


revision: str = '1f853094df12'
down_revision: str | Sequence[str] | None = '5841a5030b92'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'mail_reference_snapshot',
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), primary_key=True),
        sa.Column('account_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('content_json', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['mail_account.id'], ondelete='CASCADE'),
    )
    op.create_index(op.f('ix_mail_reference_snapshot_account_id'), 'mail_reference_snapshot', ['account_id'], unique=False)


def downgrade() -> None:
    op.drop_table('mail_reference_snapshot')
