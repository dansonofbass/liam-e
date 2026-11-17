"""The import document is a closed inventory, not a filter over all GET routes."""

import json

from api.mcp.export import OUTPUT, _refs, build_spec, serialized_spec
from api.mcp.registry import OPERATIONS
from conftest import build_app


def test_export_drift_inventory_and_references():
    app = build_app()
    spec = build_spec(app)
    assert OUTPUT.read_text(encoding="utf-8") == serialized_spec(app)
    operations = {(method.upper(), path, route["operationId"]) for path, item in spec["paths"].items()
                  for method, route in item.items() if method != "parameters"}
    assert operations == {(o.method, o.path, o.operation_id) for o in OPERATIONS}
    assert len(operations) == 4
    for ref in _refs(spec):
        assert ref.startswith("#/")
        target = spec
        for part in ref[2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        assert target
    assert json.loads(serialized_spec(app)) == spec


def test_normal_route_never_enters_export():
    app = build_app()
    before = build_spec(app)

    @app.get("/api/v1/unrelated", operation_id="unrelated")
    async def unrelated():
        return {"ok": True}

    app.openapi_schema = None
    assert "/api/v1/unrelated" in app.openapi()["paths"]
    assert build_spec(app) == before
