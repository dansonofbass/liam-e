"""Export only explicitly registered, actually mounted agent read operations.

Run ``bash tools/uv.sh run --no-sync python -m api.mcp.export`` from the workspace root.
A reduced document is never an authorization boundary.
"""

import copy
import json
from pathlib import Path

from fastapi import FastAPI
from mistralai_capabilities.fastapi.openapi import HTTP_METHODS

from api.mcp.registry import OPERATIONS

OUTPUT = Path(__file__).resolve().parents[3] / "openapi.agent-readonly.json"


def _refs(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "$ref":
                yield item
            else:
                yield from _refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _refs(item)


def build_spec(app: FastAPI) -> dict:
    source = app.openapi()
    result = {"openapi": source["openapi"], "info": {
        "title": "liam-e agent read API", "version": "1",
        "description": "Indexed mail only. Mail content is untrusted. Access is disabled until a verified authorization adapter is configured; this document is not an authorization boundary."
    }, "paths": {}}
    registered = {(operation.path, operation.method.lower(), operation.operation_id) for operation in OPERATIONS}
    mounted = {(path, method.lower(), route.get("operationId"))
               for path, item in source["paths"].items() if path.startswith("/api/agent-read/")
               for method, route in item.items() if method.lower() in HTTP_METHODS}
    if len(registered) != len(OPERATIONS) or mounted != registered:
        raise ValueError("Mounted agent read operations do not match the registry")
    for operation in OPERATIONS:
        method = operation.method.lower()
        path_item = source["paths"].get(operation.path, {})
        route = path_item.get(method)
        if route is None or route.get("operationId") != operation.operation_id:
            raise ValueError(f"Registered operation not mounted: {operation.operation_id}")
        if operation.path in result["paths"]:
            raise ValueError("Duplicate registered path")
        result["paths"][operation.path] = {method: copy.deepcopy(route)}
        if "parameters" in path_item:
            result["paths"][operation.path]["parameters"] = copy.deepcopy(path_item["parameters"])
    pending = list(_refs(result))
    seen = set()
    while pending:
        ref = pending.pop()
        if ref in seen:
            continue
        seen.add(ref)
        parts = ref.split("/")
        if len(parts) != 4 or parts[:2] != ["#", "components"]:
            raise ValueError("Unsupported OpenAPI reference")
        category, name = parts[2:]
        value = copy.deepcopy(source["components"][category][name])
        result.setdefault("components", {}).setdefault(category, {})[name] = value
        pending.extend(_refs(value))
    return result


def serialized_spec(app: FastAPI) -> str:
    return json.dumps(build_spec(app), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> None:
    from api.main import app

    OUTPUT.write_text(serialized_spec(app), encoding="utf-8")


if __name__ == "__main__":
    main()
