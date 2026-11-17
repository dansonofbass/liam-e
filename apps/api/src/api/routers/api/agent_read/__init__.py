"""Separately authorized, fail-closed agent read facade."""

from fastapi import Depends

from api.mcp.access import require_read_access
from api.mcp.access_log import install

install()

segment = "agent-read"
dependencies = (Depends(require_read_access),)
