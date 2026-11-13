---
name: observe
description: Add or review tracing for this Mistral App and verify traces in Mistral Studio. Use when the user asks to observe, trace, instrument, or debug the app, its Mistral calls, business operations, agents, or tool calls.
---

# Observe a Mistral App

This app is already configured to send traces to Mistral Studio:

- `MISTRAL_SDK_TELEMETRY=dedicated` enables automatic spans from Python Mistral
  clients in standalone processes. When the app's Workflow worker deployment
  sets `MISTRAL_SDK_TELEMETRY=global`, SDK spans from activities join the
  provider installed by the Workflows SDK. The SDK recognizes chat,
  embeddings, agent creation and invocation, conversations, FIM completions,
  and OCR requests as GenAI operations.
- `OTEL_ENABLED=true` enables automatic tracing in Mistral Workflows services
  when the app includes them.
- The `mistralai[telemetry]` extra supplies the OpenTelemetry SDK and exporter.

In `dedicated` mode the SDK skips automatic setup when the process already has
a global OpenTelemetry tracer provider, for example one installed by the app or
another library. Choose deliberately: set `MISTRAL_SDK_TELEMETRY=global` for
that process to join the existing provider, or call
`configure_telemetry(client, provider="dedicated")` to attach an SDK-owned
provider to that client. With `global`, SDK spans go to the existing
provider's exporter, which reaches Studio only if it targets the Mistral OTLP
endpoint, and the SDK's default secret/PII redaction does not apply; use
`provider="dedicated"` to send redacted spans to Studio.

For a dedicated Mistral Studio deployment, configure both tracing providers:

- Set `MISTRAL_OTLP_TRACES_ENDPOINT` to the full SDK OTLP/HTTP endpoint, for
  example `https://<studio-host>/telemetry/v1/traces`. If the app includes the
  Helm chart, override it once at `global.observability.mistralOtlpTracesEndpoint`.
- Set the app's `WORKFLOWS_BASE_URL` to the deployment base URL. The worker
  passes it to the Workflows SDK, which derives its authenticated telemetry
  endpoint from that URL; SDK spans emitted by activities use the same global
  provider.

Do not add setup code just to enable tracing. Existing SDK clients read
`MISTRAL_API_KEY` and lazily use the provider selected for their process.

Core's `utils.telemetry.configure_telemetry`, if the app calls it, emits
evaluation log records. It is separate from SDK tracing and should remain intact.

## Instrument what automatic tracing cannot see

Add custom spans only for meaningful application-owned operations, such as a
business workflow step or tool execution. Use the tracer attached to the same
Mistral client so custom spans and automatic SDK spans form one trace:

```python
from mistralai.extra.observability import get_telemetry_tracer

# Reuse the Mistral client the application already uses.
tracer = get_telemetry_tracer(client, __name__)

# Use the stable name from the application's registered tool catalog.
with tracer.start_as_current_span(
    f"execute_tool {tool_name}",
    attributes={
        "gen_ai.operation.name": "execute_tool",
        "gen_ai.tool.name": tool_name,
    },
):
    result = run_tool()
```

Follow these rules:

- For tool calls, use `execute_tool <registered tool name>`. Registered tool names
  are bounded and stable; never put arguments or other user values in a span name.
- Follow the [OpenTelemetry GenAI span conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/#execute-tool-span)
  for span names and attributes whenever the operation has a standard representation.
- Prompt and response content, including tool arguments and results, is useful
  observability data. Capture it using the standard GenAI fields when it helps
  debugging or evaluation.
- Never attach API keys, authorization headers, credentials, or other secrets.
  Treat captured content as application data and follow the workspace's access,
  retention, and personal-data policies.
- Let uncaught exceptions propagate through `start_as_current_span`; it records
  them and marks the span as failed. Record an exception manually only when the
  application catches and converts or suppresses it.
- Do not duplicate Mistral SDK, HTTP client/server, or Workflow spans that are
  already emitted automatically.
- Prefer a few spans at operation boundaries over tracing every helper.

Do not call `mistralai.extra.observability.configure_telemetry` unless the user
explicitly needs to replace the configured provider, or an existing global
OpenTelemetry provider prevents automatic setup (see above).

## Verify

1. Set `MISTRAL_API_KEY` to a key for the target workspace. Trace ingestion does
   not require Studio observability access.
2. Run the app and exercise the instrumented path at least once.
3. Read the traces. [Studio Trace Explorer](https://console.mistral.ai/observability/traces)
   requires Studio observability access for your workspace and an Org Admin,
   Workspace Admin, or Observability Viewer role. Workflow traces also have an
   independent Workflows read path that does not require that access. Traces
   normally appear within a few seconds.
4. If traces are not ingested, confirm the process has `MISTRAL_SDK_TELEMETRY=dedicated`
   (or `global` in a Workflow worker), no global OpenTelemetry provider was
   installed first in a `dedicated` process, the request uses a Mistral SDK
   client, and `MISTRAL_API_KEY` belongs to the target workspace.

Reference: https://docs.mistral.ai/studio/observability/traces/send-traces
