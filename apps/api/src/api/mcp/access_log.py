"""Prevent the ASGI server's access log from recording read-facade query strings.

Gateway and reverse-proxy logging must independently apply the same policy before exposure.
"""

import logging
import re

PREFIX = "/api/agent-read/"
_QUERY = re.compile(r"(/api/agent-read/[^\s?\"']*)\?[^\s\"']*")


class RedactAgentReadQuery(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        # Uvicorn supplies (client, method, full_path, http_version, status) to its access log.
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            path = args[2]
            if path.split("?", 1)[0].startswith(PREFIX):
                record.args = (*args[:2], path.split("?", 1)[0], *args[3:])
            return True
        # Any other shape (a changed format or a custom log config): redact the rendered line
        # instead of letting a facade query string through unchanged.
        try:
            message = record.getMessage()
        except Exception:
            return True
        if PREFIX in message:
            record.msg, record.args = _QUERY.sub(r"\1", message), None
        return True


def install() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, RedactAgentReadQuery) for item in logger.filters):
        logger.addFilter(RedactAgentReadQuery())
