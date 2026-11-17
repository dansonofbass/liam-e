"""Prevent the ASGI server's access log from recording read-facade query strings.

Gateway and reverse-proxy logging must independently apply the same policy before exposure.
"""

import logging


class RedactAgentReadQuery(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        # Uvicorn supplies (client, method, full_path, http_version, status) to its access log.
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            path = args[2]
            if path.split("?", 1)[0].startswith("/api/agent-read/"):
                record.args = (*args[:2], path.split("?", 1)[0], *args[3:])
        return True


def install() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, RedactAgentReadQuery) for item in logger.filters):
        logger.addFilter(RedactAgentReadQuery())
