---
name: adk-eval-harness
description: "Use when testing a Google ADK (google-adk Python) agent - writing evalsets, running AgentEvaluator from pytest or the adk eval CLI, choosing metrics (tool_trajectory_avg_score, response_match_score, LLM-as-judge), verifying that multi-agent routing is correct, asserting on session state with a custom metric, or simulating users."
---

# The ADK eval framework

Citations are `<source-repo>: <path>::<symbol>` against the ADK 2.x source
tree (`google/adk-python`), `google/adk-docs` and `google/adk-samples`.

## 1. An eval measures the final response **and** the tool trajectory

An eval compares two lists of `Invocation`
(adk-python: `src/google/adk/evaluation/eval_case.py`): each has
`user_content`, `final_response` and `intermediate_data`
(`IntermediateData.tool_uses` / `tool_responses`).

The consequence that makes this worth adopting in any multi-agent project:
**transfer of control is itself a tool call**. A routing decision appears in
the trajectory as `transfer_to_agent(agent_name="...")`, so
`TrajectoryEvaluator` (`src/google/adk/evaluation/trajectory_evaluator.py`)
verifies your routing for free - no extra assertions, no instrumentation. For
a system that routes purely by prompt, this is often the only automated way to
notice that an instruction edit broke the dispatcher.

## 2. Metrics

`PrebuiltMetrics` (adk-python: `src/google/adk/evaluation/eval_metrics.py`):

| Metric | LLM needed? |
|---|---|
| `tool_trajectory_avg_score` | no - deterministic match |
| `response_match_score` | no - ROUGE-1 |
| `response_evaluation_score` | yes |
| `final_response_match_v2` | yes (judge model) |
| `rubric_based_final_response_quality_v1`, `rubric_based_tool_use_quality_v1` | yes |
| `hallucinations_v1`, `safety_v1` | yes |
| `multi_turn_task_success_v1`, `multi_turn_trajectory_quality_v1`, `multi_turn_tool_use_quality_v1` | yes |
| `per_turn_user_simulator_quality_v1` | yes |

Defaults when no criteria are given (`src/google/adk/evaluation/eval_config.py`):
`{"tool_trajectory_avg_score": 1.0, "response_match_score": 0.8}`.

`ToolTrajectoryCriterion.MatchType` (same file, implemented in
`trajectory_evaluator.py`):

- `EXACT` (default) - no extra and no missing tool calls.
- `IN_ORDER` - expected calls must appear in order; extras tolerated.
- `ANY_ORDER` - same calls, order free.

`IN_ORDER` is usually the right default for real agents: it lets you assert
"authentication first, then the domain tool" without breaking every time the
model also calls a harmless accessory tool.

Per-metric documentation: `adk-docs: docs/evaluate/criteria.md`.

## 3. Evalset format

`EvalSet` (`src/google/adk/evaluation/eval_set.py`) → `EvalCase`
(`eval_case.py`, `conversation: list[Invocation]` + `session_input`) →
`Invocation`.

```json
{
  "eval_set_id": "workspace_list_folder_routing",
  "eval_cases": [
    {
      "eval_id": "list_papers_folder",
      "conversation": [
        {
          "invocation_id": "inv-1",
          "user_content": { "role": "user", "parts": [{ "text": "list the files in /papers" }] },
          "final_response": { "parts": [{ "text": "Here are the files in /papers: ..." }] },
          "intermediate_data": {
            "tool_uses": [
              { "name": "transfer_to_agent", "args": { "agent_name": "WorkspaceAgent" } },
              { "name": "list_folder", "args": { "path_or_id": "/papers" } }
            ]
          }
        }
      ],
      "session_input": {
        "app_name": "my_app",
        "user_id": "test_user",
        "state": { "user_profile": { "...": "..." } }
      }
    }
  ]
}
```

`session_input.state` is the escape hatch for preconditions you cannot
reproduce locally - pre-inject the post-login profile instead of driving a
real OAuth redirect in every case.

An older flat format also exists (`*.test.json`, a list of
`{query, expected_tool_use, reference}`; see
`adk-samples/python/agents/RAG/eval/data/conversation.test.json`). It is
easier to hand-write but limited to one session per file. ADK migrates it
automatically:
`AgentEvaluator.migrate_eval_data_to_new_schema`
(`src/google/adk/evaluation/agent_evaluator.py`).

**Free starting material:** the `adk web` UI has an "Add current session"
button that writes a real `.evalset.json` from a session you just drove by
hand. Check whether the repo already has committed `*.evalset.json` files
nobody wired to a test - curating a captured real conversation beats writing
one from scratch.

## 4. Running it - three paths, one of which matters for CI

1. **pytest** - `AgentEvaluator.evaluate(...)` or
   `AgentEvaluator.evaluate_eval_set(...)`
   (`src/google/adk/evaluation/agent_evaluator.py`). A normal async test.
   Real example: `adk-samples/python/agents/RAG/eval/test_eval.py`.
2. **CLI** - `adk eval <agent_module_path> <eval_set.json> [--config_file_path=...]`
   (adk-docs: `docs/evaluate/index.md`). Same engine, for non-pytest CI.
3. **Web UI** - `adk web`, Eval + Trace tabs. Authoring and debugging only.

Under the hood `AgentEvaluator` builds a `LocalEvalService`
(`src/google/adk/evaluation/local_eval_service.py`) with
`InMemorySessionService` and `InMemoryArtifactService`: **the eval
orchestration runs entirely in-process with no Vertex AI or GCP dependency.**
Google services are needed only for the LLM-as-judge metrics, which use a
judge model (default `gemini-2.5-flash`, see `eval_metrics.py`) reachable with
a plain `GOOGLE_API_KEY`.

`tool_trajectory_avg_score` and `response_match_score` call no LLM at all -
they run offline, in a container, with no API key. Start there.

## 5. Custom metrics - the only way to assert on state

No built-in evaluator reads `final_session_state`, even though the field
exists on `EvalCase`. If you need to assert "the tool wrote
`visibility=public`", write a custom metric:
`src/google/adk/evaluation/custom_metric_evaluator.py` (a Python function
resolved by path, receiving the actual `list[Invocation]`), documented in
`adk-docs: docs/evaluate/custom_metrics.md`.

The practical trick is to inspect `tool_responses` (not `tool_uses`) of the
relevant call and assert on the serialized payload your tool returned - which
is another reason to keep a single, stable tool result shape
(`adk-function-tools` §1).

## 6. Beyond static evalsets

- **User simulation** - `src/google/adk/evaluation/simulation/`
  (`llm_backed_user_simulator.py`, `static_user_simulator.py`,
  `pre_built_personas.py`, `user_simulator_provider.py`); docs
  `docs/evaluate/user-sim.md`. Drives multi-turn conversations against your
  agent instead of replaying a fixed script.
- **Conversation scenarios** - `evaluation/conversation_scenarios.py`
  (`ConversationScenario`, `ConversationGenerationConfig`) for generating
  cases.
- **Environment / agent simulation** - `src/google/adk/tools/environment_simulation/`
  and `src/google/adk/tools/agent_simulator/`, each shipping a plugin and a
  tool-connection analyzer; docs `docs/evaluate/environment_simulation.md`.
  Lets you evaluate without hitting real external systems.
- **Optimization** - `docs/optimize/index.md`.

## 7. Picking the first five cases

Prioritize flows that are **critical and unenforced in code** - rules that
live only in an instruction - and flows where several agents/tools cooperate
and a silent regression would go unnoticed:

1. A precondition ordering rule (e.g. "authenticate first"):
   `tool_trajectory_avg_score` with `IN_ORDER`.
2. Routing for deliberately ambiguous requests: assert on `transfer_to_agent`.
3. A cross-agent handoff that relies on cached/derived state.
4. A tool whose correctness is about *state written*, not text: custom metric.
5. A regression guard on a default that must never silently change (e.g.
   ingested-content visibility): same custom metric.

## Review checklist

- [ ] Evalsets live under `tests/` and are executed by pytest in CI.
- [ ] Deterministic metrics used for CI; judge metrics kept optional.
- [ ] `MatchType.IN_ORDER` where accessory tool calls are acceptable.
- [ ] `session_input.state` used to skip unreproducible preconditions.
- [ ] Any committed `*.evalset.json` is actually referenced by a test.
- [ ] State-level assertions implemented as a custom metric.

## Related skills

`adk-agent-architecture`, `adk-function-tools`, `adk-observability`,
`adk-conformance-review`.
