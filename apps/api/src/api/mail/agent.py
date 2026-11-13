"""The chat agent: a Mistral tool loop over the synced mail index.

Reading and searching are free. Sending only ever creates a *pending draft* (a ``chat_message``
with role ``draft``) which the user confirms explicitly through the drafts endpoint — the agent can
never send on its own (see AGENTS.md, "Beschlossene Anforderungen").
"""

from __future__ import annotations

import json
from typing import Any

from db.accessors import chat_conversation as conversation_access
from db.accessors import chat_message as message_access
from db.accessors import mail_account as account_access
from db.accessors import mail_message as mail_message_access
from db.models.chat_conversation import ChatConversation
from db.models.chat_message import ChatMessage
from db.models.mail_message import MailMessage
from env.mail import env as mail_env
from utils.mistral import mistral_client

SYSTEM_PROMPT = (
    "Du bist der Mail-Assistent der App liam-e. Der Nutzer hat mehrere Mail-Konten verbunden "
    "(z.B. Gmail, Outlook, iCloud, Yahoo), die lokal synchronisiert sind. "
    "Antworte auf Deutsch, kurz und präzise. "
    "Nutze die Tools, um Mails zu suchen und zu lesen, bevor du antwortest. "
    "Zum Versenden erstellst du ausschließlich einen Entwurf (create_draft) — die Mail wird erst "
    "nach ausdrücklicher Bestätigung des Nutzers im Chat verschickt."
)

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_accounts",
            "description": "Alle verbundenen Mail-Konten auflisten (id, Anbieter, E-Mail-Adresse).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_messages",
            "description": "Volltextsuche über alle synchronisierten Mails (Betreff, Absender, Inhalt).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Suchbegriff: Absender, Stichwort oder Betreff-Teil",
                    },
                    "account_id": {
                        "type": "string",
                        "description": "Optional: nur in diesem Konto suchen",
                    },
                    "limit": {"type": "integer", "default": 10, "maximum": 50},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_message",
            "description": "Den vollständigen Inhalt einer Mail lesen (id aus search_messages).",
            "parameters": {
                "type": "object",
                "properties": {"message_id": {"type": "string"}},
                "required": ["message_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_draft",
            "description": (
                "Entwurf für eine neue Mail oder eine Antwort erstellen. Wird NICHT automatisch "
                "gesendet — der Nutzer bestätigt den Entwurf im Chat."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Empfänger-Adressen",
                    },
                    "subject": {"type": "string"},
                    "body": {"type": "string", "description": "Text der Mail"},
                    "in_reply_to_message_id": {
                        "type": "string",
                        "description": "Optional: id der Mail, auf die geantwortet wird (legt das Absender-Konto fest)",
                    },
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
]


def _summary(message: MailMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "account_id": message.account_id,
        "folder": message.folder,
        "subject": message.subject,
        "sender": message.sender,
        "internal_date": message.internal_date.isoformat()
        if message.internal_date
        else None,
        "snippet": message.snippet,
    }


def _full(message: MailMessage) -> dict[str, Any]:
    return {
        **_summary(message),
        "recipients": json.loads(message.recipients_json),
        "body_text": message.body_text,
        "has_attachments": message.has_attachments,
        "is_read": message.is_read,
    }


async def _execute_tool(
    name: str, arguments: dict[str, Any], *, conversation_id: str
) -> str:
    if name == "list_accounts":
        accounts = await account_access.list_accounts()
        return json.dumps(
            [
                {
                    "id": a.id,
                    "provider": a.provider,
                    "email_address": a.email_address,
                    "is_active": a.is_active,
                }
                for a in accounts
            ],
            ensure_ascii=False,
        )
    if name == "search_messages":
        messages = await mail_message_access.search_messages(
            query=str(arguments.get("query", "")),
            account_id=str(arguments.get("account_id", "")),
            limit=min(int(arguments.get("limit", 10)), 50),
        )
        return json.dumps([_summary(m) for m in messages], ensure_ascii=False)
    if name == "get_message":
        message = await mail_message_access.get_message(
            str(arguments.get("message_id", ""))
        )
        if message is None:
            return json.dumps({"error": "message not found"})
        return json.dumps(_full(message), ensure_ascii=False)
    if name == "create_draft":
        to = [str(a) for a in arguments.get("to", [])]
        subject = str(arguments.get("subject", ""))
        body = str(arguments.get("body", ""))
        in_reply_to = str(arguments.get("in_reply_to_message_id", ""))
        account_id = ""
        if in_reply_to:
            replied = await mail_message_access.get_message(in_reply_to)
            if replied is not None:
                account_id = replied.account_id
        if not account_id:
            accounts = [a for a in await account_access.list_accounts() if a.is_active]
            if not accounts:
                return json.dumps({"error": "no connected mail account available"})
            account_id = accounts[0].id
        draft = {
            "status": "pending",
            "account_id": account_id,
            "to": to,
            "subject": subject,
            "body": body,
            "in_reply_to_message_id": in_reply_to,
        }
        message = await message_access.add_message(
            conversation_id=conversation_id,
            role="draft",
            content=f"Entwurf an {', '.join(to)} — Betreff: {subject}",
            draft_json=json.dumps(draft, ensure_ascii=False),
        )
        return json.dumps({"draft_id": message.id, **draft}, ensure_ascii=False)
    return json.dumps({"error": f"unknown tool {name!r}"})


def _to_model_message(message: ChatMessage) -> dict[str, Any]:
    if message.role == "tool":
        tool_call_id = ""
        if message.tool_payload_json:
            tool_call_id = json.loads(message.tool_payload_json).get("tool_call_id", "")
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": message.tool_name,
            "content": message.content,
        }
    if message.role == "assistant" and message.tool_payload_json:
        return {
            "role": "assistant",
            "content": message.content,
            "tool_calls": json.loads(message.tool_payload_json),
        }
    # user and draft messages map to plain content messages; drafts carry no model-relevant content.
    role = "assistant" if message.role == "draft" else message.role
    return {"role": role, "content": message.content}


async def run_turn(
    conversation_id: str, user_text: str
) -> tuple[ChatConversation, list[ChatMessage]]:
    """Run one chat turn: persist the user message, loop the model with tools, persist everything new."""
    conversation = await conversation_access.get_conversation(conversation_id)
    if conversation is None:
        raise LookupError(f"no chat conversation with id {conversation_id}")
    await message_access.add_message(
        conversation_id=conversation_id, role="user", content=user_text
    )
    history = await message_access.list_messages(conversation_id)
    model_messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]
    model_messages.extend(_to_model_message(m) for m in history)

    new_messages: list[ChatMessage] = []
    client = mistral_client()
    for _ in range(mail_env.mail_chat_max_tool_rounds):
        response = await client.chat.complete_async(
            model=mail_env.mail_chat_model, messages=model_messages, tools=TOOLS
        )
        message = response.choices[0].message
        tool_calls = list(message.tool_calls or [])
        if not tool_calls:
            persisted = await message_access.add_message(
                conversation_id=conversation_id,
                role="assistant",
                content=message.content or "",
            )
            new_messages.append(persisted)
            break
        calls_payload = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments
                    if isinstance(call.function.arguments, str)
                    else json.dumps(call.function.arguments),
                },
            }
            for call in tool_calls
        ]
        persisted = await message_access.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=message.content or "",
            tool_payload_json=json.dumps(calls_payload),
        )
        new_messages.append(persisted)
        model_messages.append(
            {
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": calls_payload,
            }
        )
        for call in tool_calls:
            arguments = (
                json.loads(call.function.arguments)
                if isinstance(call.function.arguments, str)
                else call.function.arguments
            )
            result = await _execute_tool(
                call.function.name, arguments, conversation_id=conversation_id
            )
            persisted_tool = await message_access.add_message(
                conversation_id=conversation_id,
                role="tool",
                content=result,
                tool_name=call.function.name,
                tool_payload_json=json.dumps({"tool_call_id": call.id}),
            )
            new_messages.append(persisted_tool)
            model_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.function.name,
                    "content": result,
                }
            )
    await conversation_access.touch_conversation(conversation)
    return conversation, new_messages
