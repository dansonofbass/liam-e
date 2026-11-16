"""Fail-closed lookup for future structured source references and write proposals."""

import json

from db.accessors import calendar_source


async def permits(source_id: str, capability: str) -> bool:
    source = await calendar_source.get(source_id)
    if source is None or not source.is_active:
        return False
    try:
        capabilities = json.loads(source.capabilities_json)
    except (ValueError, TypeError):
        return False
    return isinstance(capabilities, list) and capability in capabilities
