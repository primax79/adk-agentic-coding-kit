---
name: adk-function-tools
description: "Use when writing or reviewing tools for a Google ADK (google-adk Python) agent — choosing the return type of a FunctionTool, writing tool docstrings the model can actually use, reading and writing session state from a tool and its app/user/temp key prefixes, using ToolContext (artifacts, memory, confirmation, actions), long-running and human-in-the-loop tools, or toolsets."
---

# Writing ADK function tools

Citations are `<source-repo>: <path>::<symbol>` against the ADK 2.x source
tree (`google/adk-python`) and `google/adk-docs`. Grep the symbol; line
numbers drift between patch releases.

## 1. Return a plain `dict`. Nothing else.

ADK wraps any non-dict return value in `{"result": <value>}` before it reaches
the model:

```python
# adk-python: src/google/adk/flows/llm_flows/functions.py::__build_response_event
# Specs requires the result to be a dict.
if not isinstance(function_result, dict):
    function_result = {'result': function_result}
```

adk-docs (`docs/tools-custom/function-tools.md`) states it directly: *"The
preferred return type for a Function Tool is a dictionary... If your function
returns a type other than a dictionary or map, the framework automatically
wraps it into a dictionary with a single key named 'result'."*

Consequences:

- Returning a **Pydantic model** (a `BaseModel` is not a `dict`) produces
  double nesting. A model with its own `result` field gives the model
  `{"result": {"status": ..., "result": ..., ...}}`. Not a crash — an extra
  indirection level the instruction now has to explain.
- Returning a **str** gives `{"result": "..."}`.
- If you use a Pydantic envelope for internal typing, unwrap it on the way
  out: `return tool_result.model_dump(exclude_none=True)`.

**Use one result shape across every tool in the app.** Mixed conventions
(`ToolResult` envelope here, bare dict there, bare str elsewhere) mean the
instruction has to teach the model two or three ways to read an error, and it
will get one of them wrong. Pick a shape, e.g.
`{"status": "ok"|"error", "error": str|None, "data": ..., "message": str}`,
and apply it including in your error decorator.

## 2. The docstring is the whole description — there is no Args parsing

In both declaration paths, the function-level `description` is the raw
docstring:

- adk-python: `src/google/adk/tools/_automatic_function_calling_util.py`
  → `description=func.__doc__`
- adk-python: `src/google/adk/tools/_function_tool_declarations.py`
  → `description = inspect.cleandoc(func.__doc__) if func.__doc__ else None`

Per-parameter descriptions in the JSON schema are **not** populated from an
`Args:` section. The code says so:
`# 3. Do not support parameter description for now.`
(`_automatic_function_calling_util.py::_get_fields_dict`).

So `Args:` / `Returns:` text is useful only as free prose inside the single
description blob the model reads holistically. Write the docstring to cover:

1. **When to use this tool** (helps routing).
2. **Where each input comes from** — an explicit parameter, or session state
   written by an earlier tool. State-sourced inputs are invisible in the
   schema; if you do not say it, the model cannot know.
3. **The shape of the return value** — key names and what is in the lists.
4. **Side effects on `tool_context.state`** — which keys are written.

Type hints still matter: they generate the parameter schema. Keep them
JSON-schema-able (`str`, `int`, `bool`, `list[str]`, defaults) and avoid exotic
generics.

## 3. Session state prefixes

`adk-python: src/google/adk/sessions/state.py::State` defines three:

```python
APP_PREFIX  = "app:"
USER_PREFIX = "user:"
TEMP_PREFIX = "temp:"
```

| Key form | Scope | Persisted |
|---|---|---|
| `foo` | this session | yes (in a persistent SessionService) |
| `app:foo` | whole app, all users | yes |
| `user:foo` | this user, across sessions | yes |
| `temp:foo` | current invocation only | **never** |

`temp:` is stripped before persistence — see
`src/google/adk/sessions/base_session_service.py::_trim_temp_delta_state`.
adk-docs (`docs/tools-custom/function-tools.md`) calls `temp:` *"the
recommended way"* to pass data between tools within one turn.

Practical rule: **any key that is intermediate scratch data for a
retrieve → transform → store chain must be `temp:`**. Without the prefix it
persists, accumulates, and a later unrelated turn can read stale data as if it
were current. There is no automatic cleanup.

Caveat before promoting a key to `user:`: it becomes long-lived in your
session backend. Never put raw tokens or secrets there (see `adk-tool-auth`).

## 4. `ToolContext` — what is available

From `adk-python: src/google/adk/agents/context.py` (inherited by
`ToolContext`, `src/google/adk/tools/tool_context.py`):

- `state` — dict-like, prefix-aware.
- `load_artifact(filename, version=None)`, `save_artifact(filename, artifact)`,
  **`list_artifacts()`** — the last one lets a tool discover what already
  exists instead of you tracking filenames by hand in state.
- `add_memory(...)`, `search_memory(query)` — the native memory path.
- `request_confirmation(...)` — native human-in-the-loop gate; see §5.
- `actions` — `escalate`, `skip_summarization`, `transfer_to_agent`,
  `artifact_delta`.
- auth helpers — `get_auth_response`, `request_credential` (see `adk-tool-auth`).

Do not reach into `tool_context._invocation_context.*`. It is private and it
will break on upgrade. If you need something only available there (e.g. the
session id), isolate the access in one accessor function so a version bump is
a one-line fix, and re-verify on every ADK upgrade.

## 5. Long-running and human-in-the-loop tools

- `LongRunningFunctionTool` (adk-python: `src/google/adk/tools/long_running_tool.py`)
  — the framework calls the function, and the real result comes back
  asynchronously keyed by `function_call_id`. This is the base for anything
  that waits on a human or an external system.
- `ToolConfirmation` + `ToolContext.request_confirmation`
  (adk-python: `src/google/adk/tools/tool_confirmation.py`; adk-docs:
  `docs/tools-custom/confirmation.md`) — the native gate for destructive tools
  (delete, upload, spend). A textual "ask the user first" in the instruction is
  not a gate.
- `get_user_choice_tool` (`src/google/adk/tools/get_user_choice_tool.py`) —
  a `LongRunningFunctionTool` that presents options and sets
  `skip_summarization`.
- `_request_input_tool.py` — "ask the user a question and wait" primitive.
- Community: `google-adk-community` ships an approval gateway with a
  `hitl_tool` decorator, an `ApprovalRequest`/`ApprovalDecision` model with
  risk levels, a pluggable store and FastAPI routes
  (`src/google/adk_community/tools/hitl/{gateway,models}.py`,
  `services/hitl_approval/{api,routes,store}.py`) — worth reading before
  building an approval queue yourself.

## 6. Built-in tools you may be reimplementing

Before writing a custom tool, check `src/google/adk/tools/`:

- `exit_loop_tool.py` — end a `LoopAgent`.
- `load_artifacts_tool.py` — expose the list of available artifact names to
  the model so it can name one.
- `load_memory_tool.py` / `preload_memory_tool.py` — query memory on demand,
  or inject it automatically into every request.
- `google_search_tool.py`, `url_context_tool.py`, `load_web_page.py`,
  `bash_tool.py`, `example_tool.py`.
- Adapters: `langchain_tool.py`, `crewai_tool.py`, `mcp_tool/`, `openapi_tool/`.

## 7. Toolsets, not just tools

`BaseToolset` (`src/google/adk/tools/base_toolset.py`) lets you supply a
dynamic, filterable group of tools to an agent instead of a static list —
used by `mcp_tool`, `openapi_tool`, `skill_toolset.py`. Most toolsets accept a
`tool_filter` (a predicate or a name list), which is the clean way to expose a
subset of a large API to one agent.

`SkillToolset` (`src/google/adk/tools/skill_toolset.py`, with
`google.adk.skills.{Skill, SkillRegistry, load_skill_from_dir,
list_skills_in_dir}`) implements the agentskills.io Skill spec inside ADK:
progressive-disclosure units of instructions + resources + scripts, plus
`additional_tools` activated with the skill. Marked experimental in adk-docs
(`docs/skills/index.md`). Consider it before hand-rolling a
"load extra instructions on demand" mechanism.

## 8. Tool errors

Wrap tool bodies so a raised exception becomes your standard error dict
instead of an unhandled exception, and apply the wrapper **everywhere** — a
half-covered surface is worse than none, because the model learns a contract
that half your tools break.

App-wide alternative/complement: `ReflectAndRetryToolPlugin`
(adk-python: `src/google/adk/plugins/reflect_retry_tool_plugin.py`) intercepts
tool failures, feeds structured guidance back to the model and retries up to a
limit, with a configurable `TrackingScope`. See `adk-app-and-plugins`.

## Review checklist

- [ ] Every tool returns a `dict`, and all tools return the *same* shape.
- [ ] Docstrings state: when to use, input source (param vs state), output
      keys, state side effects.
- [ ] Intra-turn scratch keys use `temp:`.
- [ ] No secrets under `user:` / persisted state.
- [ ] Destructive tools use `request_confirmation`, not prompt text.
- [ ] No `_invocation_context` access outside a single isolated accessor.
- [ ] Checked `src/google/adk/tools/` for an existing built-in first.

## Related skills

`adk-structured-output`, `adk-artifacts-and-files`, `adk-tool-auth`,
`adk-app-and-plugins`, `adk-conformance-review`.
