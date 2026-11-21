"""Local-only API fixture: real HTTP/DB routes, synthetic chat and audio providers."""
import asyncio
import math
import os
import struct
import sys
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

db = urlsplit(os.environ['DATABASE_URL'])
if db.hostname != '127.0.0.1' or db.path != '/liam_e_voice_e2e' or db.query:
    raise SystemExit('A disposable loopback voice database is required')
os.environ.update(TELEMETRY_ENABLED='false', MISTRAL_SECRETS_ENABLED='false', MAIL_WORKER_ENABLED='false')

import uvicorn
from mistralai_capabilities.fastapi.hooks import FastAPIHooks
from db.accessors import chat_conversation, chat_message
from api.audio.access import get_audio_owner_verifier
from api.mail.chat_events import StartEvent, DeltaEvent, DoneEvent, ProposalEvent
from api.mail import proposals
from api.mail.chat_schemas import to_message_out, ContextOut
from api.mail.dev_seed import seed
from api.mail.models_catalog import ChatModelOut
from api.main import create_app
from api.routers.api.v1.audio.live import speech, status, transcription
from api.routers.api.v1.chat import models, stream

TRANSCRIPTS = ['Merk dir: Die Testente ist gelb.', 'Welche Farbe hat die Testente?', 'Ja, mach das']

class Transcription:
    def __init__(self):
        self.count = 0
        self.events = asyncio.Queue()
    async def append(self, frame):
        assert frame and len(frame) % 2 == 0
        self.count += 1
        if self.count in (4, 35, 70):
            text = TRANSCRIPTS[(4, 35, 70).index(self.count)]
            await self.events.put({'type': 'turn.start', 'time_s': self.count})
            await self.events.put({'type': 'transcription.text.delta', 'text': text})
            await self.events.put({'type': 'turn.end', 'time_s': self.count + 0.1})
    async def receive(self): return await self.events.get()

class Speech:
    def __init__(self): self.done = False
    async def append(self, text): assert text
    async def finish(self): pass
    async def receive(self):
        if self.done: return None
        self.done = True
        return b''.join(struct.pack('<h', int(4000 * math.sin(2 * math.pi * 440 * n / 24000))) for n in range(144000))

@asynccontextmanager
async def fixture_live(kind):
    yield Transcription() if kind == 'transcription' else Speech()

async def loopback_owner(connection):
    return connection.client is not None and connection.client.host == '127.0.0.1'

async def fixture_models():
    return [ChatModelOut(id='mistral-medium-latest', label='Mistral Medium', description='', is_default=True)]

async def fixture_turn(*, text, resolved_context, **unused):
    conversation, snapshot, _ = resolved_context
    user = await chat_message.add_message(conversation_id=conversation.id, role='user', content=text, context_id=snapshot.id)
    yield StartEvent(conversation_id=conversation.id, user_message_id=user.id, model='mistral-medium-latest')
    answer = 'Die Testente ist gelb.' if 'Farbe' in text else 'Verstanden.'
    yield DeltaEvent(text=answer)
    reply = await chat_message.add_message(conversation_id=conversation.id, role='assistant', content=answer, context_id=snapshot.id)
    if text.startswith('Merk dir'):
        card = await proposals.create_proposal(conversation.id, proposals.Proposal(kind='mark_read', reason='Synthetischer Vorschlag', items=[proposals.ProposalItem(id='synthetic-mail', kind='mail', title='Synthetische Mail', subtitle='Test')]), context_id=snapshot.id)
        card_out = to_message_out(card)
        card_out.context = ContextOut.model_validate(snapshot, from_attributes=True)
        yield ProposalEvent(message=card_out)
    yield DoneEvent(conversation_id=conversation.id, message_id=reply.id, stopped=False)

async def main(port):
    await seed()
    await chat_conversation.create_conversation(title='Synthetic voice test', model='mistral-medium-latest')
    models.list_chat_models = fixture_models
    stream.run_turn_events = fixture_turn
    transcription.mistral_live = speech.mistral_live = fixture_live
    transcription.live_remaining = speech.live_remaining = lambda _: 600
    status.live_allowed = lambda _: True
    app = create_app(hooks=FastAPIHooks.empty())
    app.dependency_overrides[get_audio_owner_verifier] = lambda: loopback_owner
    await uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, access_log=False, proxy_headers=False)).serve()

asyncio.run(main(int(sys.argv[1])))
