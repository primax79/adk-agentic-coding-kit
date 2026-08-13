---
name: adk-app-and-plugins
description: "Use when configuring the application layer of a Google ADK (google-adk Python) project - the App container, writing or registering a BasePlugin, intercepting every tool or model call globally, the built-in plugins (logging, retry, context filter, global instruction, artifacts), context caching, context compaction for long conversations, or agent resumability."
---

# The App container and plugins

Citations are `<source-repo>: <path>::<symbol>` against the ADK 2.x source
tree (`google/adk-python`) and `google/adk-docs`.

## 1. `App` is the deployable unit

adk-python: `src/google/adk/apps/app.py::App`

```python
name: str
root_agent: Union[BaseAgent, Any, None]
plugins: list[BasePlugin]
events_compaction_config: Optional[EventsCompactionConfig]
context_cache_config: Optional[ContextCacheConfig]
resumability_config: Optional[ResumabilityConfig]
```

adk-docs (`docs/apps/index.md`) frames it as: centralized configuration,
startup/shutdown lifecycle hooks for persistent resources, an explicit
boundary for `app:`-prefixed state, and a formal deployable unit. Defining an
`App` is optional - but four features (plugins, context caching, compaction,
resume) are only reachable through it.

Discovery: `AgentLoader` prefers a module-level `app` object over `root_agent`
(adk-python: `src/google/adk/cli/utils/agent_loader.py`), so adding

```python
app = App(name="my_app", root_agent=root_agent, plugins=[...])
```

at the bottom of your agent module is enough - no change to your
`get_fast_api_app(...)` call. `get_fast_api_app` also accepts
`extra_plugins: list[str]` if you prefer configuring them at the server layer
(`src/google/adk/cli/fast_api.py`).

## 2. Plugin callback surface

`adk-python: src/google/adk/plugins/base_plugin.py::BasePlugin` - 14 hooks,
all `async`:

| Stage | Hooks |
|---|---|
| Turn | `on_user_message_callback`, `before_run_callback`, `on_event_callback`, `after_run_callback` |
| Agent | `before_agent_callback`, `after_agent_callback` |
| Model | `before_model_callback`, `after_model_callback`, `on_model_error_callback` |
| Tool | `before_tool_callback`, `after_tool_callback`, `on_tool_error_callback` |

A plugin sees **every** agent, model and tool in the app - that is the point.
Use a plugin for cross-cutting concerns (policy, logging, retry, redaction,
upload handling) and an agent-level callback for something specific to one
agent.

## 3. The return-value contract (this is the part people get wrong)

adk-docs (`docs/plugins/index.md`):

- Return `None` → **observe**. Execution proceeds normally.
- Return anything non-`None` → **short-circuit**. The `Runner` uses your
  return value as the result and skips the underlying operation.
- Additionally: when a plugin callback returns non-`None`, the corresponding
  **agent-/model-/tool-level callback is skipped entirely**.

That last clause is the subtle one. A plugin that returns a value "just to be
explicit" will silently disable per-agent callbacks you rely on. Return `None`
unless you mean to take over.

Practical uses of the short-circuit: a policy denial that returns a refusal
dict instead of running the tool; a cache that returns a stored model response
without calling the model; an error hook that returns a fallback result
instead of re-raising (`on_model_error_callback` / `on_tool_error_callback`
return `None` to let the original exception propagate).

## 4. Built-in plugins - read before writing your own

All in `adk-python: src/google/adk/plugins/`:

| Plugin | What it does |
|---|---|
| `SaveFilesAsArtifactsPlugin` | Saves user-attached `inline_data` parts to the artifact service (see `adk-artifacts-and-files`) |
| `ReflectAndRetryToolPlugin` | Self-healing tool errors: structured guidance back to the model + retry up to a limit, concurrency-safe, configurable `TrackingScope` |
| `ContextFilterPlugin` | Trims the LLM context, keeping function call/response pairs intact |
| `GlobalInstructionPlugin` | App-wide instruction/identity. **Replaces the deprecated `LlmAgent.global_instruction` field** |
| `LoggingPlugin` | Prints every critical event to the console; also the reference example for writing a plugin |
| `DebugLoggingPlugin` | Full interaction dump to a file (requests, responses, function calls, events, end-of-invocation state) |
| `MultimodalToolResultsPlugin` | Lets function tools return a list of `Part`s (stopgap, see its docstring) |
| `BigQueryAgentAnalyticsPlugin` | Ships analytics to BigQuery, with its own `RetryConfig`/`BigQueryLoggerConfig` |

From `google-adk-community` (`src/google/adk_community/plugins/`):

- `AgentGovernancePlugin` - evaluates YAML/OPA/Cedar policies before tool
  execution and returns a dict that short-circuits denied calls (exactly the
  §3 contract). Requires the external `agentmesh-platform`; has a `fail_open`
  switch.
- `TaxonomyPlugin` (+ `taxonomy/policy.py`, `taxonomy_config.py`) - pluggable
  taxonomy/skill policy enforcement.

## 5. Context compaction (long conversations)

`EventsCompactionConfig` (adk-python: `src/google/adk/apps/_configs.py`):

- `summarizer: Optional[BaseEventsSummarizer]` - default implementation
  `src/google/adk/apps/llm_event_summarizer.py`.
- `compaction_interval: int` - number of *new user-initiated invocations*
  that, once fully represented in the session events, triggers a compaction.
- `overlap_size: int` - how many preceding invocations to include for
  continuity.

Machinery in `src/google/adk/apps/compaction.py`; docs in
`adk-docs: docs/context/compaction.md` (token-based strategy and sliding
window). This is the supported answer to "my sessions get too long", not
manual event truncation - and note the compaction code goes to some trouble to
keep function call/response pairs and HITL positions consistent, which a
naive truncation would break.

## 6. Context caching

`ContextCacheConfig` (adk-python: `src/google/adk/agents/context_cache_config.py`):
`cache_intervals`, `ttl_seconds`, `min_tokens`. Applies to all LLM agents in
the app. Docs: `adk-docs: docs/context/caching.md`. Implementation lives in
the model layer (`src/google/adk/models/cache_metadata.py`,
`gemini_context_cache_manager.py`) - a model instantiated outside the ADK
model layer gets none of it (see `adk-structured-output` §5).

## 7. Resumability

`ResumabilityConfig` (adk-python: `src/google/adk/apps/_configs.py`) enables
pausing an invocation on a long-running function call and resuming from the
last event after a pause or a mid-way failure. Its own docstring states the
guarantees plainly:

> ADK resumes the invocation in a best-effort manner: 1. Tool call to resume
> needs to be idempotent because we only guarantee an at-least-once behavior
> once resumed. 2. Any temporary / in-memory state will be lost upon
> resumption.

So: **make resumable tools idempotent**, and do not rely on `temp:` state or
in-process caches surviving. Docs: `adk-docs: docs/runtime/resume.md`
(including how to extend `BaseAgentState` for custom agents).

## Review checklist

- [ ] An `App` object exists if you need plugins/caching/compaction/resume.
- [ ] Plugin hooks return `None` unless a short-circuit is intended.
- [ ] Cross-cutting logic lives in a plugin, not copy-pasted per agent.
- [ ] `global_instruction` migrated to `GlobalInstructionPlugin`.
- [ ] Long-running deployments have a compaction strategy.
- [ ] Resumable tools are idempotent.

## Related skills

`adk-artifacts-and-files`, `adk-agent-architecture`, `adk-service-backends`,
`adk-observability`.
