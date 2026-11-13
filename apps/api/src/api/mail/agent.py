"""Stream chat turns, persisting tool history and confirmation-only proposals."""
import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import date

from db.accessors import chat_conversation as conversation_access, chat_message as message_access
from db.accessors import mail_account, mail_insight, mail_message
from env.mail import env as mail_env
from utils.mistral import mistral_client
from api.mail.agent_prompt import system_prompt
from api.mail.agent_tools import TOOLS, TurnContext, execute_tool, tool_status
from api.mail.chat_events import ChatEvent, StartEvent, StatusEvent, DeltaEvent, MailsEvent, MailRefOut, ProposalEvent, SuggestionsEvent, DoneEvent, ErrorEvent
from api.mail.chat_schemas import ChatExtrasOut, to_message_out
from api.mail import headers, state

logger = logging.getLogger(__name__)


def _to_model_messages(history, *, prompt=None):
    """Repair incomplete tool exchanges before sending history to the model."""
    result = [{'role': 'system', 'content': prompt or system_prompt(today=date.today(), account_scope=None)}]
    kept = set()
    for i, row in enumerate(history):
        if row.role == 'tool':
            try: call_id = json.loads(row.tool_payload_json).get('tool_call_id')
            except (ValueError, TypeError): continue
            if call_id in kept:
                result.append({'role':'tool', 'tool_call_id':call_id, 'name':row.tool_name, 'content':row.content})
            continue
        if row.role == 'assistant' and row.tool_payload_json:
            try:
                calls = json.loads(row.tool_payload_json)
                later = set()
                for other in history[i + 1:]:
                    if other.role == 'tool':
                        try: later.add(json.loads(other.tool_payload_json).get('tool_call_id'))
                        except (ValueError, TypeError): pass
                calls = [c for c in calls if c.get('id') in later]
            except (ValueError, TypeError, AttributeError): calls = []
            if calls:
                kept.update(c['id'] for c in calls)
                result.append({'role':'assistant', 'content':row.content, 'tool_calls':calls})
            elif row.content:
                result.append({'role':'assistant', 'content':row.content})
        elif row.role in ('user', 'assistant', 'draft', 'proposal'):
            result.append({'role':'user' if row.role == 'user' else 'assistant', 'content':row.content})
    return result


def visible_messages(rows):
    return [r for r in rows if r.role != 'tool' and not (r.role == 'assistant' and r.tool_payload_json)]


async def run_turn_events(*, conversation_id: str | None, text: str, account_id: str | None = None, context_message_id: str | None = None) -> AsyncIterator[ChatEvent]:
    if conversation_id:
        conversation = await conversation_access.get_conversation(conversation_id)
        if conversation is None: raise LookupError('conversation not found')
    else:
        conversation = await conversation_access.create_conversation(title=' '.join(text.split())[:60])
    user = await message_access.add_message(conversation_id=conversation.id, role='user', content=text)
    model = conversation.model or mail_env.mail_chat_model
    all_text = ''
    mails, suggestions = [], []
    proposal_id = None
    saved = False

    async def save(stopped):
        nonlocal saved
        if saved: return None
        row = await message_access.add_message(conversation_id=conversation.id, role='assistant', content=all_text, stopped=stopped, extras_json=ChatExtrasOut(mails=mails, suggestions=suggestions, model=model).model_dump_json())
        saved = True
        return row

    try:
        yield StartEvent(conversation_id=conversation.id, user_message_id=user.id)
        yield StatusEvent(code='thinking')
        account = await mail_account.get_account(account_id) if account_id else None
        ctx = TurnContext(conversation.id, account.id if account else None, date.today())
        history = await message_access.list_messages(conversation.id)
        messages = _to_model_messages(history, prompt=system_prompt(today=ctx.today, account_scope=account.email_address if account else None))
        if context_message_id and await mail_message.get_message(context_message_id):
            messages.insert(1, {'role':'system', 'content':f'Die Bitte bezieht sich auf die Mail mit der ID {context_message_id}. Lies sie mit get_message, bevor du antwortest.'})
        client = None
        for round_index in range(max(1, mail_env.mail_chat_max_tool_rounds)):
            calls = []
            calls_by_index = {}
            round_text = ''
            try:
                kwargs = {'model':model, 'messages':messages, 'tools':TOOLS}
                last = round_index == max(1, mail_env.mail_chat_max_tool_rounds) - 1
                if last: kwargs['tool_choice'] = 'none'
                if client is None:
                    client = mistral_client()
                stream = await client.chat.stream_async(**kwargs)
                async with stream:
                    async for event in stream:
                        delta = event.data.choices[0].delta
                        content = getattr(delta, 'content', None)
                        if isinstance(content, list): content = ''.join(getattr(c, 'text', '') for c in content if isinstance(getattr(c, 'text', None), str))
                        if isinstance(content, str) and content:
                            all_text += content
                            round_text += content
                            yield DeltaEvent(text=content)
                        tool_calls = getattr(delta, 'tool_calls', None)
                        if not last and isinstance(tool_calls, list):
                            for pos, call in enumerate(tool_calls):
                                index = getattr(call, 'index', None)
                                if not isinstance(index, int): index = pos
                                id = getattr(call, 'id', None)
                                id = id if isinstance(id, str) and id not in ('', 'null') else ''
                                item = calls_by_index.get(index)
                                if not id and item is None and calls:
                                    item = calls[-1]
                                if item is None or (id and item['id'] and item['id'] != id):
                                    item = {'id':'', 'type':'function', 'function':{'name':'', 'arguments':''}}
                                    calls.append(item)
                                calls_by_index[index] = item
                                function = getattr(call, 'function', None)
                                name = getattr(function, 'name', None)
                                args = getattr(function, 'arguments', None)
                                if id: item['id'] = id
                                if isinstance(name, str) and name and not item['function']['name']: item['function']['name'] = name
                                if isinstance(args, dict): args = json.dumps(args)
                                if isinstance(args, str): item['function']['arguments'] += args
            except (asyncio.CancelledError, GeneratorExit): raise
            except Exception as error:
                logger.warning('%s', type(error).__name__)
                if all_text: await save(True)
                saved = True
                yield ErrorEvent(code='model_unavailable')
                return
            if not calls:
                answer = await save(False)
                await conversation_access.touch_conversation(conversation)
                if mails:
                    accounts = await mail_account.list_accounts()
                    colors = state.color_indexes(accounts)
                    insight_map = await mail_insight.get_for_messages(mails)
                    refs = []
                    for id in mails:
                        m = await mail_message.get_message(id)
                        if m:
                            insight = insight_map.get(id)
                            refs.append(MailRefOut(id=m.id, account_id=m.account_id, color_index=colors.get(m.account_id, 0), subject=m.subject, sender_name=headers.sender_name(m.sender), internal_date=m.internal_date, deadline=insight.deadline if insight else None))
                    if refs: yield MailsEvent(mails=refs)
                if proposal_id:
                    proposal = await message_access.get_message(proposal_id)
                    if proposal: yield ProposalEvent(message=to_message_out(proposal))
                if suggestions: yield SuggestionsEvent(items=suggestions)
                yield DoneEvent(conversation_id=conversation.id, message_id=answer.id, stopped=False)
                return
            payload = calls
            used_ids = {call['id'] for call in payload if call['id']}
            for n, call in enumerate(payload):
                if not call['id']:
                    id = f'call_{round_index}_{n}'
                    while id in used_ids: id += '_'
                    call['id'] = id
                    used_ids.add(id)
            await message_access.add_message(conversation_id=conversation.id, role='assistant', content='', tool_payload_json=json.dumps(payload))
            messages.append({'role':'assistant', 'content':round_text, 'tool_calls':payload})
            for call in payload:
                name = call['function']['name']
                try:
                    args = json.loads(call['function']['arguments'] or '{}')
                    if not isinstance(args, dict): raise ValueError
                except (ValueError, TypeError):
                    args = None
                if args is None:
                    content = json.dumps({'error':'invalid_arguments'})
                else:
                    try:
                        status = await tool_status(name, args, ctx)
                        if status: yield status
                        outcome = await execute_tool(name, args, ctx)
                        content = outcome.content
                        for id in outcome.mails:
                            if id not in mails and len(mails) < 10: mails.append(id)
                        if name == 'suggest_followups': suggestions = outcome.suggestions
                        if outcome.proposal_message: proposal_id = outcome.proposal_message.id
                    except (asyncio.CancelledError, GeneratorExit): raise
                    except Exception as error:
                        logger.warning('%s', type(error).__name__)
                        content = json.dumps({'error':'tool_failed'})
                await message_access.add_message(conversation_id=conversation.id, role='tool', tool_name=name, tool_payload_json=json.dumps({'tool_call_id':call['id']}), content=content)
                messages.append({'role':'tool', 'name':name, 'tool_call_id':call['id'], 'content':content})
            yield StatusEvent(code='thinking')
    except (asyncio.CancelledError, GeneratorExit):
        if not saved:
            task = asyncio.create_task(save(True))
            try: await asyncio.shield(task)
            except asyncio.CancelledError:
                await asyncio.shield(task)
        raise
    except Exception as error:
        logger.warning('%s', type(error).__name__)
        if all_text: await save(True)
        saved = True
        yield ErrorEvent(code='internal')
