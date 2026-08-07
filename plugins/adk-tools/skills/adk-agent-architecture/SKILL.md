---
name: adk-agent-architecture
description: "Use when designing, reviewing or refactoring the agent tree of a Google ADK (google-adk Python) project — choosing between sub_agents and AgentTool, hitting "already has a parent agent", deciding how many coordinator layers to have, picking SequentialAgent/ParallelAgent/LoopAgent versus the graph Workflow engine, building retry/refinement loops, or plugging in non-Gemini models."
---

# ADK agent architecture

Citations are `<source-repo>: <path>::<symbol>` against the ADK 2.x source
tree (`google/adk-python`) and `google/adk-docs`. Line numbers drift between
patch releases — grep the symbol, do not trust a line number blindly.

## 1. The two composition primitives are not interchangeable

| | `sub_agents=[child]` | `tools=[AgentTool(agent=child)]` |
|---|---|---|
| Semantics | **Transfer of control**: the child continues the conversation | **Call and return**: the child runs in an isolated `Runner`, its output comes back as a tool result |
| Parent link | Sets `child.parent_agent` — **one parent only** | Does not touch `parent_agent`; the same instance can be referenced from anywhere |
| Input | Full conversation context | Text only — `args['request']` |
| Output | Free-form conversational turn | Validated against the child's `output_schema` if it has one |
| State | Same session | `state_delta` of the child Runner is propagated back to the caller's `tool_context` |

- Transfer is implemented as a normal tool call named `transfer_to_agent`
  (adk-python: `src/google/adk/tools/transfer_to_agent_tool.py`). It is not a
  special event type — which is why it shows up in traces and in eval
  trajectories for free.
- `AgentTool` builds its own `Runner` and validates the final text against the
  agent's schema (adk-python: `src/google/adk/tools/agent_tool.py`, see
  `_get_output_schema` and the `validate_schema(output_schema, merged_text)`
  call in `run_async`).

**When you convert `sub_agents` → `AgentTool`, re-read the parent's
instruction.** Prompts written for transfer semantics ("hand the user over
to X") are wrong for call-and-return semantics.

## 2. The single-parent constraint, and the wrong way around it

`BaseAgent.__set_parent_agent_for_sub_agents` raises
`ValueError: Agent '<name>' already has a parent agent ...`
(adk-python: `src/google/adk/agents/base_agent.py`).

Do **not** work around it with `copy.copy(agent)` / `copy.deepcopy(agent)`.
A shallow copy shares mutable members (`tools`, `sub_agents`) with the
original, so a later mutation silently affects both. `AgentTool` is the
supported mechanism for reusing one agent instance from several call sites
(adk-docs: `docs/tools/limitations.md`, "Workaround #1: AgentTool"; used
throughout `adk-samples/python/agents/financial-advisor`).

## 3. Do not add hops that only re-classify

Every intermediate agent that has no tools of its own and only re-routes
costs one extra LLM turn per request, in latency and tokens.

- The sanctioned pattern for "which specialist handles this request" is
  **Coordinator/Dispatcher**: one `LlmAgent` with `sub_agents` (or
  `AgentTool`s) and an instruction that describes each specialist
  (adk-docs: `docs/workflows/patterns.md`).
- `adk-samples/python/agents/financial-advisor` uses a **flat** coordinator
  over four specialists exposed as `AgentTool`s — no dispatcher tier.
- Add a tier only when it does real work: an authorization guard, state
  enrichment before transfer, a deterministic pipeline.

Routing by prompt is correct when the decision depends on the *meaning* of
the request. It is wrong for rules that are deterministic.

## 4. Deterministic rules belong in code, not in the instruction

"Always call `initialize_session` first" written only in an instruction is a
hope, not a constraint. Move it to one of:

- `before_agent_callback` that inspects `callback_context.state` and blocks /
  redirects when the precondition is missing;
- an explicit edge in a graph `Workflow` (§5);
- a `BasePlugin` hook if the rule is app-wide (see the `adk-app-and-plugins`
  skill — a plugin callback that returns non-`None` short-circuits).

## 5. Template workflow agents vs the graph Workflow engine

Two distinct layers exist in ADK 2.x:

- **Template workflow agents** — `SequentialAgent`, `ParallelAgent`,
  `LoopAgent` (adk-python: `src/google/adk/agents/{sequential,parallel,loop}_agent.py`).
  Simple, composable, still fine for linear or fan-out pipelines.
- **Graph engine** — `google.adk.Workflow`, exported at top level
  (adk-python: `src/google/adk/__init__.py` → `from .workflow import Workflow`;
  implementation in `src/google/adk/workflow/_workflow.py` and `_graph.py`).
  Provides nodes/edges, conditional routing (`RoutingMap`), unconditioned-cycle
  detection, static schema validation, join nodes (`_join_node.py`), dynamic
  node scheduling (`_dynamic_node_scheduler.py`) and **per-node
  `RetryConfig`** (`workflow/_retry_config.py`).

adk-docs (`docs/graphs/index.md`, `docs/agents/workflow-agents/index.md`)
positions the graph engine as the answer when you need deterministic control;
the templates are the prebuilt higher-level alternative.

**Graph known limitations** (adk-docs: `docs/graphs/index.md`,
"Known limitations"): not compatible with live streaming, and some
third-party integrations do not work inside graph workflows. Check before
committing to it in a streaming app.

## 6. Iterative refinement (generate → check → retry)

Canonical shape (adk-docs: `docs/workflows/patterns.md`):

```python
LoopAgent(
    max_iterations=N,
    sub_agents=[generator_agent, checker_agent],
)
```

The loop ends when a sub-agent emits `EventActions(escalate=True)`. You can
get that from a small custom `BaseAgent`, or from the built-in tool
`google.adk.tools.exit_loop` (adk-python:
`src/google/adk/tools/exit_loop_tool.py` — sets `tool_context.actions.escalate = True`
and `skip_summarization = True`).

Two failure modes to check for in any existing loop:

- **Double cap.** `max_iterations` on the `LoopAgent` and a second retry
  counter inside the checker will silently take the minimum. Keep exactly one
  source of truth (e.g. `max_iterations = MAX_RETRY + 1`).
- **Wrong retry primitive.** `RetryConfig` in the graph engine retries a node
  on **raised exceptions**. It is not a substitute for "an LLM judges whether
  the output is good enough" — that needs the loop + checker shape above.

Every loop iteration is at least one extra LLM call. Justify it with evidence
that plain tool-level error handling does not already cover the failure.

## 7. Models: ADK is not Gemini-only

`src/google/adk/models/` ships `google_llm.py` (`Gemini`), `anthropic_llm.py`,
`gemma_llm.py`, `apigee_llm.py` and `lite_llm.py` (`LiteLlm`, the LiteLLM
bridge to OpenAI / Ollama / vLLM / etc.), resolved through
`registry.py::LLMRegistry` (`new_llm`, `register`, `resolve`).

If you need retry / rate-limit handling, configure it on the model, not around
it: `Gemini(retry_options=types.HttpRetryOptions(initial_delay=1, attempts=2))`
(adk-python: `src/google/adk/models/google_llm.py`, field `retry_options`).

## 8. One-tool-per-agent limitation

Some tools cannot coexist with any other tool in the same agent — Google
Search, code execution and Agent Search with the Gemini API (adk-docs:
`docs/tools/limitations.md`, "One tool per agent limitation"; the note says
this applies to Search in ADK Python ≤ 1.15.0, with a built-in workaround from
1.16.0). **Verify against your installed version.** The general escape hatch
is the same as §2: isolate the restricted tool in a leaf agent and expose that
agent with `AgentTool`.

## Review checklist

- [ ] No `copy.copy` / `deepcopy` of agents anywhere.
- [ ] Every intermediate agent does work beyond re-classifying.
- [ ] Deterministic preconditions enforced by callback/graph, not by prompt text.
- [ ] `AgentTool` vs `sub_agents` choice matches the wording of the parent instruction.
- [ ] Loops have exactly one iteration cap and a real escalation path.
- [ ] Model retry configured on the `BaseLlm` instance.
- [ ] Restricted tools isolated behind `AgentTool`.

## Related skills

`adk-function-tools`, `adk-structured-output`, `adk-app-and-plugins`,
`adk-eval-harness` (trajectory evals verify routing for free),
`adk-conformance-review`.
