"""Persist proposals and execute them only after an explicit, atomic confirmation."""

import json
import logging
from datetime import datetime
from typing import Literal

from db.accessors import chat_message as message_access
from db.accessors import chat_context as context_access
from db.accessors import mail_account as account_access
from db.accessors import mail_message as mail_access
from db.models.chat_message import ChatMessage
from db.engine import get_session_maker
from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.exc import IntegrityError

from api.mail import actions, netguard, newsletters, send, service, transport
from api.errors import refuse
from api.tasks import patch as task_patch
from api.tasks import proposals as task_proposals
from api.tasks import state as task_state

logger = logging.getLogger(__name__)
ProposalKind = Literal["send", "archive", "trash", "mark_read", "unsubscribe", "task"]


class ProposalItem(BaseModel):
    id: str
    kind: Literal["mail", "sender"]
    title: str
    subtitle: str
    count: int | None = None
    unread: int | None = None
    last_read_at: datetime | None = None
    method: str | None = None
    target: str | None = None
    selected: bool = True


class SendDraft(BaseModel):
    account_id: str
    mode: Literal["new", "reply", "reply_all", "forward"]
    to: list[str]
    cc: list[str]
    subject: str
    body: str
    quote: str
    reply_to_message_id: str | None


class ItemProblem(BaseModel):
    id: str
    code: str


class ManualStep(BaseModel):
    id: str
    link: str | None


class ProposalResult(BaseModel):
    done: int = 0
    failed: list[ItemProblem] = Field(default_factory=list)
    manual: list[ManualStep] = Field(default_factory=list)
    undo_action_ids: list[str] = Field(default_factory=list)
    task_series_id: str | None = None


class Proposal(BaseModel):
    kind: ProposalKind
    reason: str
    items: list[ProposalItem]
    draft: SendDraft | None = None
    task: task_proposals.TaskProposal | None = None
    irreversible: bool = False
    result: ProposalResult | None = None

    @model_validator(mode="after")
    def validate_kind(self):
        self.irreversible = self.kind in {"send", "unsubscribe"}
        if self.kind == "send" and self.draft is None:
            raise ValueError("send requires a draft")
        if (self.kind == 'task') != (self.task is not None):
            raise ValueError('task requires exactly one typed command')
        if self.kind == 'task' and (self.items or self.draft):
            raise ValueError('task commands do not select mail items')
        expected = "sender" if self.kind == "unsubscribe" else "mail"
        if self.kind != "send" and any(item.kind != expected for item in self.items):
            raise ValueError("item kind does not match proposal")
        return self


class ProposalNotFoundError(Exception):
    pass


class ProposalStateError(Exception):
    pass


class ProposalContextRevokedError(Exception):
    pass


class ProposalSelectionError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def proposal_view(message: ChatMessage) -> Proposal | None:
    if message.role == "proposal":
        return Proposal.model_validate_json(message.proposal_json)
    if message.role == "draft":
        old = json.loads(message.draft_json)
        return Proposal(kind="send", reason="", items=[], draft=SendDraft(
            account_id=old["account_id"], mode="new", to=old["to"], cc=[],
            subject=old["subject"], body=old["body"], quote="", reply_to_message_id=None,
        ))
    return None


async def create_proposal(conversation_id: str, proposal: Proposal, *, context_id: str | None = None) -> ChatMessage:
    for attempt in range(2):
        await message_access.cancel_open_proposals(conversation_id)
        try:
            return await message_access.add_message(
                conversation_id=conversation_id, role="proposal", content=proposal.reason,
                proposal_json=proposal.model_dump_json(), proposal_status="pending", context_id=context_id,
            )
        except IntegrityError:
            if attempt:
                raise
    raise AssertionError("unreachable")


async def _get_proposal(proposal_id: str) -> ChatMessage:
    message = await message_access.get_message(proposal_id)
    if message is None or message.role != "proposal":
        raise ProposalNotFoundError
    return message


async def cancel(proposal_id: str) -> ChatMessage:
    await _get_proposal(proposal_id)
    message = await message_access.cancel_proposal(proposal_id)
    if message is None:
        raise ProposalStateError
    return message


async def _send(draft: SendDraft, result: ProposalResult) -> None:
    def fail(code: str):
        result.failed.append(ItemProblem(id="draft", code=code))

    try:
        account = await account_access.get_account(draft.account_id)
        if account is None:
            fail("account_gone")
            return
        original = None
        if draft.mode != "new":
            original = await mail_access.get_message(draft.reply_to_message_id) if draft.reply_to_message_id else None
            if original is None:
                fail("item_gone")
                return
        await send.send_message(
            account, to=draft.to, cc=draft.cc, subject=draft.subject,
            body=draft.body + ("\n\n" + draft.quote if draft.quote else ""),
            reply_to=original if draft.mode in {"reply", "reply_all"} else None,
            forward_of=original if draft.mode == "forward" else None,
            reply_all=draft.mode == "reply_all",
        )
        result.done = 1
    except (transport.MailHostNotAllowedError, netguard.BlockedAddressError):
        fail("host_not_allowed")
    except service.CredentialError:
        fail("credentials_invalid")
    except send.SeedAccountError:
        fail("send_failed")
    except Exception as error:
        logger.warning("%s", type(error).__name__)
        fail("send_failed")


async def _apply(item: ProposalItem, kind: ProposalKind, result: ProposalResult) -> None:
    def fail(code: str):
        result.failed.append(ItemProblem(id=item.id, code=code))

    try:
        if kind == "unsubscribe":
            sender = await newsletters.sender_by_id(item.id)
            account = await account_access.get_account(sender.account_id) if sender else None
            if sender is None or account is None:
                fail("item_gone")
                return
            if (sender.method != item.method or (sender.link or None) != (item.target or None)
                    or (item.method != "none" and not item.target)):
                fail("item_changed")
                return
            outcome = await newsletters.unsubscribe(sender, account)
            if outcome.status == "failed":
                fail(outcome.error_code)
            else:
                result.undo_action_ids.extend(outcome.archived_action_ids)
                if outcome.status == "manual":
                    result.manual.append(ManualStep(id=item.id, link=outcome.link))
                else:
                    result.done += 1
            return
        mail = await mail_access.get_message(item.id)
        if mail is None or mail.folder != "INBOX":
            fail("item_gone")
            return
        action = await actions.apply_action(item.id, kind)
        result.undo_action_ids.append(action.id)
        result.done += 1
    except actions.ActionUnsupportedError:
        fail("action_unsupported")
    except HTTPException as error:
        if error.status_code != 404:
            logger.warning("%s", type(error).__name__)
        fail("item_gone" if error.status_code == 404 else "action_failed")
    except Exception as error:
        logger.warning("%s", type(error).__name__)
        fail("action_failed")


async def _confirm_task(message: ChatMessage, edit: task_proposals.TaskCreateCommand | None = None) -> ChatMessage:
    """One local transaction; retries use the existing not-pending conflict."""
    async with get_session_maker()() as session:
        claimed = await message_access.claim_proposal_in_session(session, message.id)
        if claimed is None:
            current = await message_access.get_message(message.id)
            if current and current.proposal_status == 'pending' and current.context_id and not await context_access.is_live(current.context_id):
                raise ProposalContextRevokedError
            raise ProposalStateError
        proposal = proposal_view(claimed)
        assert proposal is not None and proposal.task is not None
        if edit is not None:
            if not isinstance(proposal.task, task_proposals.TaskCreateCommand) or (
                edit.source_account_id, edit.source_message_id
            ) != (proposal.task.source_account_id, proposal.task.source_message_id):
                raise ProposalSelectionError('selection_invalid')
            proposal.task = edit
        context = await context_access.get_context_in_session(session, claimed.context_id) if claimed.context_id else None
        if context is None or context.revoked or context.conversation_id != claimed.conversation_id:
            raise ProposalContextRevokedError
        scope = json.loads(context.task_scope_json)
        account_scope = json.loads(context.account_scope_json)
        source = proposal.task.source_account_id
        selection = account_scope.get('selection')
        from api.tasks.chat import allowed_in_selection
        if not allowed_in_selection(scope, selection, source, proposal.task.source_message_id):
            raise refuse(403, 'task_scope_invalid', 'Die Aufgabe gehört nicht zur gewählten Auswahl.')
        try:
            series_id = await task_proposals.execute(session, proposal.task, proposal_id=claimed.id)
        except task_patch.RevisionConflict:
            raise refuse(409, 'task_revision_conflict', 'Die neue Wiederholung überschneidet sich mit einer erledigten Fälligkeit. Wähle einen anderen Zeitplan.') from None
        except task_state.StateConflict:
            raise refuse(409, 'task_version_conflict', 'Die Aufgabe wurde inzwischen geändert. Prüfe den aktuellen Stand.') from None
        except task_state.StateNotFound:
            raise refuse(404, 'task_not_found', 'Die Aufgabe ist nicht mehr verfügbar.') from None
        except task_proposals.TaskSourceGone:
            raise refuse(409, 'task_source_gone', 'Die verknüpfte Mail ist nicht mehr verfügbar.') from None
        except ValueError:
            raise refuse(422, 'task_invalid', 'Die Aufgabe konnte nicht geändert werden. Prüfe ihre Angaben.') from None
        proposal.result = ProposalResult(done=1, task_series_id=series_id)
        updated = await message_access.finish_proposal_in_session(session, claimed.id, proposal_json=proposal.model_dump_json())
        await session.commit()
        return updated


async def confirm(proposal_id: str, *, selected_ids: list[str], body: str | None = None,
                  task_edit: task_proposals.TaskCreateCommand | None = None) -> ChatMessage:
    message = await _get_proposal(proposal_id)
    proposal = proposal_view(message)
    assert proposal is not None
    if proposal.kind == 'task':
        if selected_ids or body is not None:
            raise ProposalSelectionError('selection_invalid')
        return await _confirm_task(message, task_edit)
    if task_edit is not None:
        raise ProposalSelectionError('selection_invalid')
    selected = set(selected_ids)
    if not selected.issubset({item.id for item in proposal.items}):
        raise ProposalSelectionError("selection_invalid")
    if proposal.kind != "send" and not selected:
        raise ProposalSelectionError("selection_empty")
    if await message_access.claim_proposal(proposal_id) is None:
        current = await message_access.get_message(proposal_id)
        if current and current.proposal_status == "pending" and current.context_id and not await context_access.is_live(current.context_id):
            raise ProposalContextRevokedError
        raise ProposalStateError
    result = ProposalResult()
    proposal.result = result
    status = "failed"
    try:
        for item in proposal.items:
            item.selected = item.id in selected
        if proposal.kind == "send":
            assert proposal.draft is not None
            if body is not None:
                proposal.draft.body = body
            await _send(proposal.draft, result)
        else:
            for item in proposal.items:
                if item.selected:
                    await _apply(item, proposal.kind, result)
        status = "done" if not result.failed else "partial" if result.done or result.manual else "failed"
    finally:
        updated = await message_access.set_proposal(proposal_id, proposal_json=proposal.model_dump_json(), proposal_status=status)
    assert updated is not None
    return updated
