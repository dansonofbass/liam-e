"""allow calendar point occurrences

Revision ID: 9f00f591b515
Revises: 9c420cfdeeb6
Create Date: 2026-11-17 15:13:14.110567

"""
from collections.abc import Sequence

from alembic import op


revision: str = '9f00f591b515'
down_revision: str | Sequence[str] | None = '9c420cfdeeb6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NAME = 'ck_calendar_occurrence_interval'
_ALL_DAY = '(start_date IS NOT NULL AND end_date IS NOT NULL AND start_date < end_date AND start_at IS NULL AND end_at IS NULL AND timezone IS NULL)'
_TIMED = '(start_date IS NULL AND end_date IS NULL AND start_at IS NOT NULL AND end_at IS NOT NULL AND start_at {operator} end_at AND timezone IS NOT NULL)'


def _constraint(operator: str) -> None:
    op.create_check_constraint(_NAME, 'calendar_occurrence', _ALL_DAY + ' OR ' + _TIMED.format(operator=operator))


def upgrade() -> None:
    op.drop_constraint(_NAME, 'calendar_occurrence', type_='check')
    _constraint('<=')


def downgrade() -> None:
    op.execute('UPDATE calendar_sync_state SET incomplete = true WHERE source_id IN '
               '(SELECT source_id FROM calendar_occurrence WHERE start_at = end_at)')
    op.execute('DELETE FROM calendar_occurrence WHERE start_at = end_at')
    op.drop_constraint(_NAME, 'calendar_occurrence', type_='check')
    _constraint('<')
