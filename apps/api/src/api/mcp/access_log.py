"""Prevent the ASGI server's access log from recording read-facade query strings.

Gateway and reverse-proxy logging must independently apply the same policy before exposure.
"""

import logging
import re

PREFIX = "/api/agent-read/"
# Everything from the "?" up to the next whitespace: a request target never contains raw
# whitespace, and quotes inside the query must not end the redaction early.
_QUERY = re.compile(r"(/api/agent-read/[^\s?]*)\?\S*")


def _redact(text: str) -> str:
    return _QUERY.sub(r"\1", text)


class RedactAgentReadQuery(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple):
            # Keep the argument shape (uvicorn's formatter unpacks its 5-tuple) and redact every
            # facade path among the arguments, wherever a format puts it.
            record.args = tuple(_redact(item) if isinstance(item, str) and PREFIX in item else item for item in args)
            return True
        # Any other shape (a mapping, or a message without arguments): redact the rendered line
        # instead of letting a facade query string through unchanged.
        try:
            message = record.getMessage()
        except Exception:
            return True
        if PREFIX in message:
            record.msg, record.args = _redact(message), None
        return True


def install() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, RedactAgentReadQuery) for item in logger.filters):
        logger.addFilter(RedactAgentReadQuery())
