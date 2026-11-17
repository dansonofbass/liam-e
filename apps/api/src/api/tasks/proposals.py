"""Typed local task commands; execution belongs to the caller's proposal transaction.

No provider calls, commits or model-selected ownership. Source and target versions
are immutable in a persisted command. Tools must construct these from trusted reads.
"""

from datetime import UTC, datetime
from typing import Annotated, Literal

from db.accessors import mail_message, task_occurrence, task_schedule_revision, task_series
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlmodel.ext.asyncio.session import AsyncSession

from api.tasks import create, lifecycle, patch, reconcile, state
from api.tasks.recurrence import expand_page


class TaskCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    payload_version: Literal[1] = 1
    source_account_id: str | None = Field(default=None, max_length=200)
    source_message_id: str | None = Field(default=None, max_length=200)


class TaskCreateCommand(TaskCommand):
    action: Literal['create']
    title: str = Field(min_length=1, max_length=500)
    start: str = Field(min_length=10, max_length=26)
    timezone: str = Field(min_length=1, max_length=100)
    rrule: str | None = Field(default=None, max_length=500)

    @model_validator(mode='after')
    def schedule(self):
        start = patch.parse_local(self.start)
        values, _ = expand_page(start, self.rrule or 'FREQ=DAILY;COUNT=1', start, self.timezone, limit=1)
        if values != [start]:
            raise ValueError('start must match rule')
        self.start = start.isoformat()
        if self.rrule:
            self.rrule = ';'.join(sorted(self.rrule.split(';')))
        if self.source_message_id and not self.source_account_id:
            raise ValueError('source requires account')
        return self


class TaskTargetCommand(TaskCommand):
    series_id: str = Field(min_length=1, max_length=200)
    expected_version: int = Field(ge=1)
    title: str = Field(default='', max_length=500)
    due_local: str | None = None
    occurrence_key: str | None = None
    display_timezone: str | None = None
    display_rrule: str | None = None
    next_due: list[str] = Field(default_factory=list, max_length=5)


class TaskArchiveCommand(TaskTargetCommand):
    action: Literal['archive']


class TaskOccurrenceCommand(TaskTargetCommand):
    occurrence_id: str = Field(min_length=1, max_length=200)
    expected_occurrence_version: int = Field(ge=1)


class TaskStateCommand(TaskOccurrenceCommand):
    action: Literal['complete', 'skip', 'reopen']


class TaskPatchCommand(TaskOccurrenceCommand):
    action: Literal['patch']
    scope: Literal['occurrence', 'this_and_following']
    start: str = Field(min_length=10, max_length=26)
    timezone: str | None = Field(default=None, max_length=100)
    rrule: str | None = Field(default=None, max_length=500)
    rule_supplied: bool = False

    @model_validator(mode='after')
    def schedule(self):
        start = patch.parse_local(self.start)
        zone = self.timezone or self.display_timezone or 'UTC'
        if self.rrule is not None and not self.rule_supplied:
            raise ValueError('rule must be explicitly selected')
        if self.scope == 'this_and_following' and not (self.timezone or self.display_timezone):
            raise ValueError('new revision requires timezone')
        rule = (self.rrule if self.rule_supplied else self.display_rrule) if self.scope == 'this_and_following' else None
        if self.scope == 'occurrence' and (self.timezone is not None or self.rule_supplied):
            raise ValueError('single changes retain timezone and rule')
        values, _ = expand_page(start, rule or 'FREQ=DAILY;COUNT=1', start, zone, limit=1)
        if values != [start]:
            raise ValueError('start must match rule')
        self.start = start.isoformat()
        if self.rrule:
            self.rrule = ';'.join(sorted(self.rrule.split(';')))
        return self


TaskProposal = Annotated[
    TaskCreateCommand | TaskArchiveCommand | TaskStateCommand | TaskPatchCommand,
    Field(discriminator='action'),
]


class TaskSourceGone(ValueError):
    """A bound source has disappeared; never substitute another source."""


async def execute(session: AsyncSession, command: TaskProposal, *, proposal_id: str) -> str:
    """Apply exactly the bound payload and return its series ID, without committing."""
    if command.source_message_id:
        source = await mail_message.get_message(command.source_message_id, session)
        if source is None or source.account_id != command.source_account_id:
            raise TaskSourceGone
    if isinstance(command, TaskCreateCommand):
        row, created = await create.create(
            session, creation_key=proposal_id, title=command.title, start=patch.parse_local(command.start),
            zone=command.timezone, rule=command.rrule,
            source_account_id=command.source_account_id, source_message_id=command.source_message_id,
        )
        if created:
            revision = await task_schedule_revision.get_by_version(session, row.id, 1)
            assert revision is not None
            await reconcile.reconcile_batch(session, scope='app', series_id=row.id,
                revision_id=revision.id, started_at=datetime.now(UTC), cursor=None)
        return row.id
    row = await task_series.get(session, 'app', command.series_id, lock=True)
    if row is None:
        raise state.StateNotFound
    if row.version != command.expected_version:
        raise state.StateConflict
    if (row.source_account_id, row.source_message_id) != (command.source_account_id, command.source_message_id):
        raise state.StateConflict
    if isinstance(command, TaskOccurrenceCommand):
        occurrence = await task_occurrence.get(session, command.occurrence_id)
        if occurrence is None or occurrence.series_id != row.id:
            raise state.StateNotFound
        # Direct complete is idempotent; proposals still bind the exact target version.
        if occurrence.version != command.expected_occurrence_version:
            raise state.StateConflict
    if isinstance(command, TaskPatchCommand):
        await patch.patch(session, row.id, expected_version=command.expected_version,
            occurrence_id=command.occurrence_id, expected_occurrence_version=command.expected_occurrence_version,
            scope=command.scope, start=command.start, timezone=command.timezone,
            rrule=command.rrule, rule_supplied=command.rule_supplied)
    elif isinstance(command, TaskStateCommand):
        await state.transition(session, command.occurrence_id,
            version=command.expected_occurrence_version, action=command.action)
    else:
        await lifecycle.archive(session, row.id, expected_version=command.expected_version)
    return row.id
