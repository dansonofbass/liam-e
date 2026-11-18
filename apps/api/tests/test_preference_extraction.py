"""Model behavior is mocked; no historical conversations or external calls."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from api.preferences import extraction as ex

CASES = json.loads((Path(__file__).parent / 'fixtures/preference_extraction.json').read_text())


def client(monkeypatch, output):
    complete = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=output))]))
    monkeypatch.setattr(ex, 'mistral_client', lambda: SimpleNamespace(chat=SimpleNamespace(complete_async=complete)))
    return complete


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['id'])
def test_synthetic_corpus_through_prompt_and_validation(monkeypatch, case):
    call = client(monkeypatch, json.dumps({'candidates': case['candidates']}))
    result = asyncio.run(ex.extract(case['text'], 'test-model'))
    assert len(result) == case['expected']
    args = call.call_args.kwargs
    assert args['messages'] == [{'role': 'system', 'content': ex.SYSTEM}, {'role': 'user', 'content': case['text']}]
    assert args['response_format'] == {'type': 'json_object'}
    assert 'tools' not in args


@pytest.mark.parametrize('output', ['not json', '{"candidates": [{"key":"other"}]}',
    json.dumps({'candidates': CASES[0]['candidates'] * 4})])
def test_invalid_output_is_rejected(monkeypatch, output):
    client(monkeypatch, output)
    with pytest.raises(ValueError):
        asyncio.run(ex.extract(CASES[0]['text'], 'test-model'))


@pytest.mark.parametrize('case', CASES[4:], ids=lambda c: c['id'])
def test_model_cannot_bypass_durability_and_quote_gate(case):
    item = dict(CASES[0]['candidates'][0], evidence=case['text'])
    with pytest.raises(ValueError):
        ex.validate_output(json.dumps({'candidates': [item]}), case['text'])


def test_long_input_is_not_sent(monkeypatch):
    call = client(monkeypatch, '{}')
    assert asyncio.run(ex.extract('x' * 2001, 'test-model')) == []
    call.assert_not_awaited()


@pytest.mark.parametrize('mode', ['timeout', 'model', 'json'])
def test_failures_are_detached_and_never_persist(monkeypatch, mode):
    client(monkeypatch, 'invalid')
    monkeypatch.setattr(ex.records, 'claim', AsyncMock(return_value=('activation', CASES[0]['text'])))
    store = AsyncMock()
    monkeypatch.setattr(ex.records, 'store', store)
    if mode != 'json':
        async def fail(*args, **kwargs):
            if mode == 'timeout':
                await asyncio.sleep(10)
            raise RuntimeError('test-only')
        complete = AsyncMock(side_effect=fail)
        monkeypatch.setattr(ex, 'mistral_client', lambda: SimpleNamespace(chat=SimpleNamespace(complete_async=complete)))
        monkeypatch.setattr(ex, 'TIMEOUT_SECONDS', .001)
    async def turn():
        ex.schedule('conversation', 'message', 'test-model')
        assert ex._tasks
        # The answer can complete without awaiting the extractor.
        answer = 'answer'
        await asyncio.gather(*ex._tasks)
        return answer
    assert asyncio.run(turn()) == 'answer'
    store.assert_not_awaited()


def test_claim_rejection_never_calls_model(monkeypatch):
    monkeypatch.setattr(ex.records, 'claim', AsyncMock(return_value=None))
    call = client(monkeypatch, '{}')
    asyncio.run(ex.run('conversation', 'message', 'test-model'))
    call.assert_not_awaited()
