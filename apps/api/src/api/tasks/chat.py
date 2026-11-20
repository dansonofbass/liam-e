"""Bounded, read-only task index tools and immutable proposal preparation.

The turn supplies ownership and source scope. Tool arguments never expand it.
Reading never calls reconcile; incomplete coverage is returned explicitly.
"""

from datetime import date, timedelta
import json

from db.accessors import mail_message, task_occurrence, task_schedule_revision, task_series
from db.engine import get_session_maker
from pydantic import TypeAdapter

from api.tasks.proposals import TaskProposal
from api.tasks.reading import complete_in_window, validate_window


def allowed(scope: dict, account_ids: list[str], account_id: str | None, message_id: str | None = None) -> bool:
    if account_id not in account_ids and (account_id is not None or message_id is not None):
        return False
    source = scope.get('source')
    # In an account-limited chat, personal tasks are those without any account binding; a task that
    # names another account stays excluded even when it has no source mail.
    return (source == 'all' or
            (source == 'unlinked' and message_id is None) or
            (source == 'account_and_unlinked' and account_id is None and message_id is None) or
            (source in {'account', 'account_and_unlinked'} and account_id is not None and scope.get('account_id') == account_id))


def allowed_in_selection(scope: dict, selection: str | None, account_ids: list[str], account_id: str | None, message_id: str | None) -> bool:
    """Apply the persisted task boundary and the mail selection together."""
    if not allowed(scope, account_ids, account_id, message_id):
        return False
    if selection is None:
        return True
    return scope.get('account_id') == selection and scope.get('source') in {'account', 'account_and_unlinked'} and (
        account_id == selection or (scope['source'] == 'account_and_unlinked' and account_id is None and message_id is None)
    )


async def series_data(session, row, start, end, cursor=None, limit=5, status=None):
    revisions = await task_schedule_revision.list_for_series(session, row.id)
    occurrences = await task_occurrence.list_page(session, scope='app', status=status,
        due_from=start.isoformat(), due_to=(end + timedelta(days=1)).isoformat(),
        after=cursor, limit=limit + 1, series_id=row.id)
    return {
        'series_id': row.id, 'title': row.title, 'version': row.version, 'archived': row.archived,
        'source_account_id': row.source_account_id, 'source_message_id': row.source_message_id,
        'schedule': revisions[-1].model_dump() if revisions else None,
        'complete': bool(revisions) and complete_in_window(revisions, start, end),
        'occurrences': [o.model_dump() for o in occurrences[:limit]],
        'next_occurrence_cursor': json.dumps([occurrences[limit - 1].due_local, occurrences[limit - 1].id]) if len(occurrences) > limit else None,
    }


async def read(name, args, scope, account_ids):
    if scope.get('source') == 'none':
        return {'error': 'task_out_of_scope'}
    if 'source' in args or 'source_account_id' in args:
        return {'error': 'task_out_of_scope'}
    try:
        start, end = date.fromisoformat(args['from']), date.fromisoformat(args['to'])
        validate_window(start, end)
        status = args.get('status', 'open' if name == 'search_tasks' else None)
        if status not in {None, 'open', 'completed', 'skipped', 'cancelled'}:
            raise ValueError
        if (end - start).days > 89:
            raise ValueError
        async with get_session_maker()() as session:
            if name == 'get_task':
                row = await task_series.get(session, 'app', args['series_id'])
                if row is None or not allowed(scope, account_ids, row.source_account_id, row.source_message_id):
                    return {'error': 'task_not_found'}
                rows, cursor = [row], None
            else:
                rows = await task_series.list_page(session, scope='app', due_from=start.isoformat(),
                    due_to=(end + timedelta(days=1)).isoformat(), archived=None,
                    source=scope['source'], source_account_id=scope.get('account_id'),
                    after=args.get('cursor'), limit=21, allowed_account_ids=account_ids)
                cursor = rows[19].id if len(rows) > 20 else None
                rows = rows[:20]
            occurrence_cursor = None
            if name == 'get_task' and args.get('occurrence_cursor'):
                occurrence_cursor = json.loads(args['occurrence_cursor'])
                if not isinstance(occurrence_cursor, list) or len(occurrence_cursor) != 2 or not all(isinstance(v, str) and len(v) <= 200 for v in occurrence_cursor):
                    raise ValueError
                occurrence_cursor = tuple(occurrence_cursor)
            items = [await series_data(session, row, start, end, occurrence_cursor, 50 if name == 'get_task' else 5, status) for row in rows]
            return {'read_only': True, 'window': {'from': start.isoformat(), 'to': end.isoformat()},
                    'source': scope, 'next_cursor': cursor,
                    'untrusted_task_data': {'series': items},
                    'note': 'Coverage is per series and window. Follow series and occurrence cursors before claiming that no tasks exist.'}
    except (ValueError, KeyError, TypeError):
        return {'error': 'task_window_invalid'}


async def prepare(args, ctx):
    """Derive source references from trusted rows, not model-supplied account IDs."""
    command = dict(args)
    command.pop('reason', None)
    if any(key in command for key in ('source_account_id', 'payload_version', 'creation_key')):
        raise ValueError('task_scope_invalid')
    async with get_session_maker()() as session:
        if command.get('action') == 'create':
            source_id = command.get('source_message_id')
            if source_id:
                source = await mail_message.get_message(source_id, session)
                if source is None or source.unverified_connector or source.account_id not in ctx.account_ids:
                    raise ValueError('task_scope_invalid')
                command['source_account_id'] = source.account_id
        else:
            row = await task_series.get(session, 'app', command.get('series_id', ''))
            if row is None:
                raise ValueError('task_not_found')
            if not allowed(ctx.task_scope, ctx.account_ids, row.source_account_id, row.source_message_id):
                raise ValueError('task_scope_invalid')
            if 'source_message_id' in command and command['source_message_id'] != row.source_message_id:
                raise ValueError('task_scope_invalid')
            command['source_account_id'], command['source_message_id'] = row.source_account_id, row.source_message_id
            command['title'] = row.title
            revision = await task_schedule_revision.current(session, row.id)
            occurrence = await task_occurrence.get(session, command['occurrence_id']) if command.get('occurrence_id') else None
            if command.get('occurrence_id') and (occurrence is None or occurrence.series_id != row.id):
                raise ValueError('task_not_found')
            if occurrence:
                revision = await task_schedule_revision.get(session, occurrence.revision_id)
            command['due_local'] = occurrence.due_local if occurrence else revision.start_local if revision else None
            command['occurrence_key'] = occurrence.occurrence_key if occurrence else None
            command['display_timezone'] = revision.timezone if revision else None
            command['display_rrule'] = revision.rrule if revision else None
            upcoming = await task_occurrence.list_page(session, scope='app', status='open',
                due_from=ctx.today.isoformat(), due_to=None, after=None, limit=5, series_id=row.id)
            command['next_due'] = [item.due_local for item in upcoming]
            if command.get('expected_version') != row.version or (occurrence and command.get('expected_occurrence_version') != occurrence.version):
                raise ValueError('task_version_conflict')
        if not allowed_in_selection(ctx.task_scope, ctx.account_id, ctx.account_ids, command.get('source_account_id'), command.get('source_message_id')):
            raise ValueError('task_scope_invalid')
        return TypeAdapter(TaskProposal).validate_python(command)
