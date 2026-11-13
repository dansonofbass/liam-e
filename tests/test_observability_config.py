import importlib


def test_observability_runtime_is_installed() -> None:
    from mistralai.extra.observability import get_telemetry_tracer

    importlib.import_module("mistralai_capabilities.observability")
    importlib.import_module("opentelemetry.sdk.trace")
    assert callable(get_telemetry_tracer)
