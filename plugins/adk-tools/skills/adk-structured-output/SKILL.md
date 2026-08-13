---
name: adk-structured-output
description: "Use when a Google ADK (google-adk Python) agent or tool needs reliable JSON or typed output from an LLM - choosing between output_schema, response_schema/response_mime_type and manual parsing, stripping ```json fences by hand, calling google.genai directly from inside a tool, or sending a PDF/image to a model from within an ADK tool."
---

# Structured output and direct LLM calls in ADK

Citations are `<source-repo>: <path>::<symbol>` against the ADK 2.x source
tree (`google/adk-python`), `google/adk-docs` and `google/adk-samples`.

## 1. Never hand-parse model JSON

If you see `.replace("```json", "").replace("```", "")` followed by
`json.loads(...)` in an ADK codebase, that is a bug waiting for a model that
prefixes one sentence. The generic `except` that catches the resulting
`JSONDecodeError` usually collapses two different failures into one opaque
error: "the analysis genuinely failed" and "the output was malformed and a
retry would have worked".

Three supported alternatives, in increasing order of integration:

| Approach | Where | What you get |
|---|---|---|
| `response_mime_type` + `response_schema` on the `GenerateContentConfig` | any direct `google.genai` call | schema-constrained decoding, no fences |
| `output_schema` on an `LlmAgent` | inside the ADK loop | same, plus post-hoc validation |
| `AgentTool` over that agent | called from another agent | the above, plus events/tracing and state propagation |

## 2. Minimal fix: constrain the generation config

```python
from google.genai import types

generation_config = types.GenerateContentConfig(
    temperature=0.1,
    response_mime_type="application/json",
    response_schema=list[MyItemModel],
)
```

This is a one-line-per-call change and does not touch your architecture. If
your project has a central config builder for `GenerateContentConfig`, check
whether it sets only `temperature`/`top_p`/`top_k`/`safety_settings` - that is
the common case, and it means no call in the app is schema-constrained.

## 3. Structural fix: a leaf agent + `AgentTool`

```python
analyzer = LlmAgent(
    name="post_analyzer",
    model=...,
    instruction=ANALYSIS_PROMPT,          # drop "VALID JSON IS MANDATORY" - the schema does that
    output_schema=list[PostAnalysis],
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)

parent = LlmAgent(..., tools=[AgentTool(agent=analyzer)])
```

`AgentTool` extracts the schema (`_get_output_schema`, which also walks into
the last sub-agent of a workflow agent) and validates the merged final text
with `validate_schema(...)` before returning
(adk-python: `src/google/adk/tools/agent_tool.py`; helper in
`src/google/adk/utils/_schema_utils.py`).

Two constraints that come with `output_schema`:

- The agent's final text must *be* the JSON. It cannot also produce the rich
  formatted prose (bullet lists, emoji) your presentation prompt asks for. If
  an agent is conditionally given an `output_schema`, check the instruction
  does not contradict it in that branch.
- Set `disallow_transfer_to_parent` / `disallow_transfer_to_peers` on schema
  leaves so the model cannot escape by transferring instead of answering.

## 4. `AgentTool` does not forward multimodal input

`AgentTool.run_async` builds the sub-agent's input from **text only** -
`types.Part.from_text(text=args['request'])`
(adk-python: `src/google/adk/tools/agent_tool.py`). A PDF or image `Part`
held by the caller is not forwarded.

The official workaround, with a complete precedent in
`adk-samples/python/agents/small-business-loan-agent/.../sub_agents/document_extraction/`:

1. `models.py` - a Pydantic model for the extraction result.
2. `agent.py` - `LlmAgent(output_schema=..., before_model_callback=inject_document_into_request, disallow_transfer_to_parent=True, disallow_transfer_to_peers=True)`.
3. `tools.py::inject_document_into_request` - resolves the document (state →
   artifact service → fallback) and appends it to `llm_request.contents` as a
   `Part` with `inline_data`. The sample's own comment states the caveat:
   *"When ... called as a sub-agent via AgentTool, the original multimodal
   content (PDF/image) is not forwarded."*
4. Wire with `AgentTool(document_extraction_agent)`.

Budget ~40 lines for the callback. If you only have one fixed prompt and do
not need the call traced, a direct `generate_content` side-channel is simpler
at equal functionality - make that trade-off explicitly (see §5).

## 5. Use `google.adk.models.Gemini`, not a raw `google.genai.Client`

Instantiating `google.genai.client.Client(api_key=...)` inside a helper class
gives up things the ADK model layer already implements:

- **Retry / rate limiting** - `Gemini.retry_options: Optional[types.HttpRetryOptions]`
  and dedicated 429 / resource-exhausted handling
  (adk-python: `src/google/adk/models/google_llm.py`). A real example is
  `adk-samples/.../document_extraction/agent.py` with
  `HttpRetryOptions(initial_delay=1, attempts=2)`. With a raw client a 429
  propagates as an unhandled exception into your tool's `except`.
- **Context caching** - `src/google/adk/models/cache_metadata.py` and
  `gemini_context_cache_manager.py`, driven by `App.context_cache_config`.
- **Vertex / custom endpoint configuration** - documented in the `Gemini`
  docstring via `api_client` substitution.

`Gemini` is a standalone `BaseLlm` (`src/google/adk/models/base_llm.py`); you
can call `generate_content_async` with a minimal `LlmRequest` without a
`Runner`.

**What swapping the client does not buy you: tracing.** Spans are produced by
the `Runner`/flow, not by the model object. A model call made outside a
`Runner` stays invisible to ADK tracing regardless of which client you use -
only going through `AgentTool` (§3) or a normal agent turn puts it in the
trace. See `adk-observability`.

## Review checklist

- [ ] No manual fence-stripping / `json.loads` on model output.
- [ ] Every direct `generate_content` call that expects JSON sets
      `response_mime_type` + `response_schema`.
- [ ] Agents with `output_schema` have transfer disallowed and no conflicting
      formatting instructions.
- [ ] Multimodal sub-tasks use a `before_model_callback` injector, not
      `AgentTool`'s text argument.
- [ ] Model objects come from `google.adk.models`, with `retry_options` set.
- [ ] Any deliberate out-of-band LLM call is documented as untraced.

## Related skills

`adk-agent-architecture`, `adk-function-tools`, `adk-artifacts-and-files`,
`adk-observability`.
