---
name: adk-observability
description: Use when instrumenting or debugging a Google ADK (google-adk Python) agent — setting up OpenTelemetry tracing to a self-hosted backend (Jaeger, Grafana Tempo, an OTLP collector), understanding which spans ADK emits, debugging multi-agent routing from traces, metrics, or deciding whether trace_to_cloud / openinference instrumentation is needed.
---

# Tracing and observability in ADK

Citations are `<source-repo>: <path>::<symbol>` against the ADK 2.x source
tree (`google/adk-python`), `google/adk-docs` and `google/adk-samples`.

## 1. Vendor-neutral OTLP is the default path, not a workaround

`trace_to_cloud` and `otel_to_cloud` on `get_fast_api_app` are **Google Cloud
shortcuts only**. Telemetry setup runs regardless of them:

`get_fast_api_app` (`src/google/adk/cli/fast_api.py`) forwards `otel_to_cloud`
to `ApiServer.get_fast_api_app`, which **always** calls `_setup_telemetry(...)`
(`src/google/adk/cli/api_server.py`). Inside:

1. `otel_to_cloud` → `_setup_gcp_telemetry` (needs `google.auth`, GCP creds).
2. else if the standard `OTEL_EXPORTER_OTLP_*` env vars are set
   (`_otel_env_vars_enabled`) → `_setup_telemetry_from_env` →
   `maybe_set_otel_providers` (`src/google/adk/telemetry/setup.py`) →
   a **generic** `BatchSpanProcessor(OTLPSpanExporter())`. No `google.auth`,
   no `CloudTraceSpanExporter` in this branch.
3. else → a `TracerProvider` with no external exporter (spans exist, nothing
   ships them; only the dev UI's in-memory trace viewer shows them).

adk-docs (`docs/observability/traces.md`) states it: ADK emits OTLP, usable by
*"any OTel-compatible backend (e.g. Google Cloud Trace, Jaeger, Grafana Tempo,
Datadog)"*, and shows the self-hosted setup as a first-class path.

**So: not passing the cloud flags does not disable tracing — it leaves it in
the env-var branch. Setting the env var is the whole fix; no server code
change.**

## 2. Minimal self-hosted setup

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318   # or your collector
OTEL_SERVICE_NAME=my-agent
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=production
```

Use `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` for traces only.

```yaml
jaeger:
  image: jaegertracing/all-in-one:1.60
  ports:
    - "16686:16686"   # UI
    - "4318:4318"     # OTLP HTTP — the default OTLPSpanExporter transport
  restart: unless-stopped
```

Grafana Tempo is identical in shape; only the image and collector port change.

Dependencies: `opentelemetry-sdk` and
`opentelemetry-exporter-otlp-proto-http` come in as base dependencies of
`google-adk` — verify in your own venv rather than assuming.

Optional: `opentelemetry-instrumentation-google-genai` (shipped via the
`google-adk[otel-gcp]` extra — the name is misleading, it adds no functional
GCP dependency; it only enriches `generate_content` span attributes with
Gemini SDK detail). Without it,
`_setup_instrumentation_lib_if_installed` (`cli/api_server.py`) logs a warning
and ADK falls back to its own native spans
(`src/google/adk/telemetry/tracing.py`). Not blocking.

For purely local debugging there is also a SQLite span exporter:
`src/google/adk/telemetry/sqlite_span_exporter.py`.

## 3. What ADK emits by default

Hierarchy (adk-docs `docs/observability/traces.md`; implementation in
`src/google/adk/telemetry/tracing.py`, `src/google/adk/runners.py`,
`src/google/adk/flows/llm_flows/base_llm_flow.py`,
`src/google/adk/flows/llm_flows/functions.py`):

- `invocation` — root, one per turn.
- `invoke_agent` — one per agent node traversed; attributes
  `gen_ai.agent.name`, `gen_ai.conversation.id`.
- `call_llm` / `generate_content {model}` — attributes `gen_ai.request.model`,
  invocation id, full `llm_request`/`llm_response` payload if content capture
  is enabled, token usage.
- `execute_tool` — one per tool call, **including `transfer_to_agent`**, which
  is an ordinary `FunctionTool`
  (`src/google/adk/tools/transfer_to_agent_tool.py`). It goes through
  `trace_tool_call` with `gen_ai.tool.name=transfer_to_agent` and
  `tool_call_args` containing `{"agent_name": "..."}`.

That last point is the useful one: **routing decisions are visible span
arguments, not invisible side effects.** The waterfall
`invoke_agent(root)` → `call_llm` → `execute_tool(transfer_to_agent, {...})` →
`invoke_agent(child)` tells you which agent decided what, with no extra code.

Prompt/response payloads are gated by
`ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS` /
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`
(`src/google/adk/telemetry/tracing.py`) — limited by default for PII reasons.
Enable explicitly for deep debugging, and think about where those spans land.

Metrics exist too: `src/google/adk/telemetry/_metrics.py` records agent
invocation duration, request/response size, workflow step count, tool
execution duration and client operation duration
(adk-docs: `docs/observability/metrics.md`). Logging guidance:
`docs/observability/logging.md`.

## 4. The blind spot: LLM calls made outside the Runner

Any `google.genai.client.Client(...).generate_content(...)` invoked directly
from inside a tool bypasses the ADK flow and produces **no ADK span**.
Switching to `google.adk.models.Gemini` does not fix this — spans come from the
`Runner`/flow, not from the model object (see `adk-structured-output` §5). The
only ways to get such a call traced are to bring it into the ADK loop (a leaf
agent + `AgentTool`) or to instrument the Gemini SDK itself with
`GoogleGenAiSdkInstrumentor`, which should be verified empirically rather than
assumed.

Audit for this pattern before concluding "we have full tracing".

## 5. `openinference` / Arize — generic, but usually redundant

`adk-samples/python/agents/RAG/rag/tracing.py`:

```python
from openinference.instrumentation.google_adk import GoogleADKInstrumentor
tracer_provider = register(space_id=..., api_key=..., project_name=...)  # Arize-specific
GoogleADKInstrumentor().instrument(tracer_provider=tracer_provider)      # vendor-neutral
```

`GoogleADKInstrumentor` is an **OpenInference** component (also used by
Phoenix), not Arize-specific; it accepts any OTel `TracerProvider`, so
`register(...)` can be swapped 1:1 for a local
`TracerProvider()` + `BatchSpanProcessor(OTLPSpanExporter(endpoint="http://jaeger:4318/v1/traces"))`.

But it largely duplicates what `telemetry/tracing.py` already emits under the
same GenAI semantic conventions. Adopt it only if you specifically want the
OpenInference span format for LLM/RAG evaluation tooling; for debugging
routing and latency, the native path in §1–§3 is enough.

## Review checklist

- [ ] `OTEL_EXPORTER_OTLP_ENDPOINT` set in every non-dev environment.
- [ ] A collector/backend actually exists in the deployment stack.
- [ ] Content capture flags set deliberately, with PII considered.
- [ ] Out-of-band LLM calls inventoried and known to be untraced.
- [ ] No cloud-only flags used in a self-hosted deployment.

## Related skills

`adk-structured-output`, `adk-app-and-plugins`, `adk-eval-harness`,
`adk-service-backends`.
