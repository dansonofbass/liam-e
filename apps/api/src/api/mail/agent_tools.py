"""Read-only agent tools and explicit proposal creation."""
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from db.accessors import mail_account, mail_message
from db.models.chat_message import ChatMessage
from api.mail import headers, insights, newsletters, proposals, send
from api.mail.chat_events import StatusEvent


@dataclass
class TurnContext:
    conversation_id: str
    account_id: str | None
    today: date


@dataclass
class ToolOutcome:
    content: str
    mails: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    proposal_message: ChatMessage | None = None


def result(value, **kwargs):
    return ToolOutcome(json.dumps(value, ensure_ascii=False, default=str), **kwargs)


def _schema(name, description, properties, required=()):
    return {'type': 'function', 'function': {'name': name, 'description': description, 'parameters': {'type': 'object', 'properties': properties, 'required': list(required)}}}


S = {'type': 'string'}
A = {'type': 'array', 'items': S}
TOOLS = [
    _schema('list_accounts', 'List connected accounts', {}),
    _schema('search_messages', 'Search the inbox', {'query': S, 'account_id': S, 'unread_only': {'type':'boolean'}, 'since_days': {'type':'integer'}, 'limit': {'type':'integer', 'maximum':50}}),
    _schema('get_message', 'Read a mail', {'message_id': S}, ['message_id']),
    _schema('get_insights', 'Get mail insights', {'message_ids': A}, ['message_ids']),
    _schema('find_newsletters', 'Find newsletter senders', {}),
    _schema('propose_action', 'Propose a mail action for confirmation', {'kind': {'type':'string', 'enum':['archive','trash','mark_read','unsubscribe']}, 'message_ids': A, 'sender_ids': A, 'reason': S}, ['kind','reason']),
    _schema('create_draft', 'Propose a mail to send', {'to': A, 'cc': A, 'subject': S, 'body': S, 'mode': {'type':'string', 'enum':['new','reply','reply_all','forward']}, 'reply_to_message_id': S}, ['to','subject','body']),
    _schema('show_mails', 'Display mail cards', {'message_ids': A}, ['message_ids']),
    _schema('suggest_followups', 'Suggest follow-up actions', {'texts': A}, ['texts']),
]


async def tool_status(name, arguments, ctx):
    codes = {'search_messages':'searching', 'get_message':'reading', 'get_insights':'checking_deadlines', 'find_newsletters':'finding_newsletters', 'propose_action':'preparing_proposal', 'create_draft':'preparing_proposal'}
    if name not in codes:
        return None
    count = None
    if name == 'search_messages':
        count = 1 if arguments.get('account_id') or ctx.account_id else sum(a.is_active for a in await mail_account.list_accounts())
    elif name == 'get_insights':
        count = min(len(arguments.get('message_ids', [])), 20)
    return StatusEvent(code=codes[name], count=count)


def _summary(m):
    return {'id': m.id, 'account_id': m.account_id, 'subject': m.subject, 'sender': m.sender, 'date': m.internal_date, 'snippet': m.snippet, 'is_read': m.is_read}


async def _proposal(ctx, proposal):
    row = await proposals.create_proposal(ctx.conversation_id, proposal)
    return result({'proposal_id': row.id, 'status': 'pending', 'note': 'Der Nutzer muss den Vorschlag bestätigen.'}, proposal_message=row)


def _valid_addresses(addresses):
    return all(isinstance(a, str) and '@' in a and not any(c.isspace() or c == ',' for c in a) for a in addresses)


async def execute_tool(name: str, arguments: dict, ctx: TurnContext) -> ToolOutcome:
    if name == 'list_accounts':
        return result([{'id': a.id, 'provider': a.provider, 'email_address': a.email_address, 'is_active': a.is_active} for a in await mail_account.list_accounts()])
    if name == 'search_messages':
        account_id = arguments.get('account_id') or ctx.account_id
        rows = await mail_message.list_page(folder='INBOX', account_ids=[account_id] if account_id else None, unread_only=arguments.get('unread_only', False), query=arguments.get('query', ''), limit=max(1, min(int(arguments.get('limit', 10)), 50)))
        since = arguments.get('since_days')
        if since is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=int(since))
            rows = [m for m in rows if m.internal_date and (m.internal_date.replace(tzinfo=timezone.utc) if m.internal_date.tzinfo is None else m.internal_date) >= cutoff]
        return result({'untrusted_mails': [_summary(m) for m in rows]})
    if name == 'get_message':
        m = await mail_message.get_message(arguments.get('message_id', ''))
        if not m: return result({'error':'message_not_found'})
        return result({'untrusted_mail': {'id':m.id, 'account_id':m.account_id, 'folder':m.folder, 'subject':m.subject, 'sender':m.sender, 'to':json.loads(m.recipients_json), 'cc':json.loads(m.cc_json), 'date':m.internal_date, 'body_text':m.body_text[:8000], 'has_attachments':m.has_attachments, 'is_read':m.is_read}})
    if name == 'get_insights':
        items = []
        for id in arguments.get('message_ids', [])[:20]:
            try:
                insight = await insights.get_or_compute(id)
                items.append({'message_id':id, 'points':json.loads(insight.points_json), 'deadline':insight.deadline, 'needs_reply':insight.needs_reply, 'followups':json.loads(insight.followups_json)})
            except insights.MessageNotFound:
                items.append({'message_id':id, 'error':'not_found'})
            except insights.InsightError:
                items.append({'message_id':id, 'error':'unavailable'})
        return result({'untrusted_insights':items})
    if name == 'find_newsletters':
        rows = await newsletters.find_newsletters(account_ids=[ctx.account_id] if ctx.account_id else None)
        return result({'untrusted_senders':[{k:getattr(s, k) for k in ('sender_id','address','display_name','total','unread','last_read_at','method')} for s in rows]})
    if name == 'propose_action':
        kind = arguments.get('kind')
        if kind == 'send': return result({'error':'use_create_draft'})
        if kind not in ('archive','trash','mark_read','unsubscribe'): return result({'error':'invalid_arguments'})
        items = []
        ids = list(dict.fromkeys(arguments.get('sender_ids' if kind == 'unsubscribe' else 'message_ids', [])))
        for id in ids:
            if len(items) == 50: break
            if kind == 'unsubscribe':
                s = await newsletters.sender_by_id(id)
                if not s: continue
                subtitle = f'{s.address} · {s.total} Mails'
                if s.method == 'mailto':
                    target = newsletters.parse_mailto(s.link)
                    if target: subtitle += f' · {target.recipient} · {target.subject} · {target.body}'
                items.append(proposals.ProposalItem(id=id, kind='sender', title=s.display_name, subtitle=subtitle, count=s.total, unread=s.unread, last_read_at=s.last_read_at, method=s.method))
            else:
                m = await mail_message.get_message(id)
                if not m or m.folder != 'INBOX' or (kind == 'mark_read' and m.is_read): continue
                account = await mail_account.get_account(m.account_id)
                items.append(proposals.ProposalItem(id=id, kind='mail', title=m.subject or '(ohne Betreff)', subtitle=f'{headers.sender_name(m.sender)} · {account.email_address if account else ""}'))
        if not items: return result({'error':'no_valid_items'})
        return await _proposal(ctx, proposals.Proposal(kind=kind, reason=arguments.get('reason',''), items=items))
    if name == 'create_draft':
        to, cc = arguments.get('to', []), arguments.get('cc', [])
        if not _valid_addresses(to + cc): return result({'error':'invalid_address'})
        mode = arguments.get('mode', 'new')
        if mode not in ('new','reply','reply_all','forward'): return result({'error':'invalid_arguments'})
        original = await mail_message.get_message(arguments.get('reply_to_message_id', '')) if mode != 'new' else None
        if mode != 'new' and not original: return result({'error':'message_not_found'})
        if original:
            account = await mail_account.get_account(original.account_id)
        else:
            account = await mail_account.get_account(ctx.account_id) if ctx.account_id else next((a for a in await mail_account.list_accounts() if a.is_active), None)
        if not account: return result({'error':'no_account'})
        if mode in ('reply','reply_all'):
            to, base_cc = send.reply_recipients(original, account, reply_all=mode == 'reply_all')
            seen = {address.casefold() for address in to}
            deduplicated = []
            for address in base_cc + cc:
                if address.casefold() not in seen:
                    deduplicated.append(address)
                    seen.add(address.casefold())
            cc = deduplicated
        if not to: return result({'error':'recipients_missing'})
        if not _valid_addresses(to + cc): return result({'error':'invalid_address'})
        to_text = ', '.join(to)
        reason = {'new':f'Neue Mail an {to_text}.', 'reply':f'Antwort an {to_text}.', 'reply_all':f'Antwort an alle: {to_text}.', 'forward':f'Weiterleitung an {to_text}.'}[mode]
        draft = proposals.SendDraft(account_id=account.id, mode=mode, to=to, cc=cc, subject=arguments.get('subject') or (original.subject if original else ''), body=arguments.get('body', ''), quote=send.quote_original(original) if original else '', reply_to_message_id=original.id if original else None)
        return await _proposal(ctx, proposals.Proposal(kind='send', reason=reason, items=[], draft=draft))
    if name == 'show_mails':
        ids = []
        for id in dict.fromkeys(arguments.get('message_ids', [])):
            if await mail_message.get_message(id): ids.append(id)
            if len(ids) == 10: break
        return result({'ok':True}, mails=ids)
    if name == 'suggest_followups':
        texts = [s.strip()[:120] for s in arguments.get('texts', []) if isinstance(s, str) and s.strip()][:3]
        return result({'ok':True}, suggestions=texts)
    return result({'error':'unknown_tool'})
