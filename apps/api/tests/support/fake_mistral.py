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
        for chunk in self.streams.pop(0):
            if isinstance(chunk, str):
                chunk = SimpleNamespace(data=SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=chunk, tool_calls=None))]))
            yield chunk

    async def list_async(self, **kwargs):
        self.requests.append(kwargs)
        return self.model_lists.pop(0)
