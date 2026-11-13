"""A queued, recording stand-in for the Mistral SDK."""

from types import SimpleNamespace


class FakeMistral:
    def __init__(self, responses=(), streams=(), models=()):
        self.responses = list(responses)
        self.streams = list(streams)
        self.model_lists = list(models)
        self.requests = []
        self.chat = self
        self.models = self

    async def complete_async(self, **kwargs):
        self.requests.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, str):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=response, tool_calls=None))])
        return response

    async def stream_async(self, **kwargs):
        self.requests.append(kwargs)
        chunks = self.streams.pop(0)
        if isinstance(chunks, Exception):
            raise chunks
        return FakeStream(chunks)

    async def list_async(self, **kwargs):
        self.requests.append(kwargs)
        result = self.model_lists.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeStream:
    def __init__(self, chunks):
        self.chunks = iter(chunks)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            chunk = next(self.chunks)
        except StopIteration:
            raise StopAsyncIteration from None
        if isinstance(chunk, Exception):
            raise chunk
        if isinstance(chunk, str):
            chunk = SimpleNamespace(data=SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=chunk, tool_calls=None))]))
        return chunk

    async def aclose(self):
        pass

    async def close(self):
        await self.aclose()
