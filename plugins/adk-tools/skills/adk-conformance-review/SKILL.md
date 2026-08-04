---
name: adk-conformance-review
description: Use when auditing an existing Google ADK (google-adk Python) codebase against real ADK capabilities — "is our use of ADK idiomatic", "are we reinventing something ADK already provides", "which of our custom abstractions are genuinely necessary" — or when you need the method for verifying ADK API claims against the actual sources instead of guessing.
---

# ADK conformance review

The method for checking whether a project's use of Google ADK matches what the
framework actually offers, and for producing findings that can be acted on.
This skill is also the index of the ADK skill family (§6).

## 1. Ground truth, in priority order

1. **The installed package.** `python -c "import google.adk, pathlib;
   print(pathlib.Path(google.adk.__file__).parent)"` then read `version.py`.
   This is what runs. A pin in `pyproject.toml` that disagrees with the venv is
   itself a finding — and it invalidates any conclusion drawn from the other
   version.
2. **A source checkout of `google/adk-python`** at the same version, for
   grepping.
3. **`google/adk-docs`** — for intent, recommended patterns and deprecations.
4. **`google/adk-samples`** — for what Google actually writes, which is
   frequently simpler than what the docs describe.
5. **`google/adk-python-community`** (`google.adk_community.*`) — separate
   distribution, lighter review bar. Read the source before adopting.

## 2. Rules for claims

- **Never assert an ADK class, function, parameter or behaviour you have not
  grepped.** Inventing plausible API names is the dominant failure mode of
  this kind of review and it poisons every downstream task.
- Cite `path::symbol`. Include a line number only as a hint — line numbers
  drift across patch releases, symbol names do not.
- Distinguish *the docs say* from *the code does*. When they disagree, the
  code wins for behaviour, the docs win for intent, and the disagreement is a
  finding.
- Flag anything marked `@experimental(...)` or documented as experimental
  (e.g. `AuthenticatedFunctionTool`, ADK Skills). Using it is allowed;
  depending on it without pinning is not.
- Verify empirically when cheap. "Does a Pydantic return value get
  double-wrapped?" is a five-line script, not a debate.

## 3. Two-phase procedure

**Phase 0 — catalogue what exists.** Read the project and write down every
architectural and implementation pattern with `file:line`: agent tree and
routing, tool conventions and return shapes, auth and identity, artifact/file
handling, direct LLM calls, session-state key conventions, config management,
dead code. No judgement yet, no edits. This catalogue is the map every later
phase indexes into.

**Phase 1 — compare, theme by theme.** For each theme, answer three
questions and nothing else:

1. Is this already the idiomatic ADK pattern?
2. Is there a native ADK mechanism we are reimplementing (worse)?
3. Is this genuinely custom because ADK has no equivalent?

Answer (3) explicitly. A review that only lists defects makes the team
re-litigate its correct decisions. Writing down "ADK has no concept of
application roles, so this RBAC layer is necessarily ours" is as valuable as
any fix.

Suggested themes — one pass each, each mapping to a skill in §6:
orchestration · tools & state · auth · artifacts/files · structured output &
direct LLM calls · memory/RAG · app & plugins · service backends · eval ·
observability.

## 4. Output shape

One file per theme plus a prioritized synthesis. Each finding carries:

- verdict (aligned / to fix / necessarily custom),
- evidence: project `file:line` **and** ADK `path::symbol`,
- the concrete change, and its blast radius.

Prioritize by effort × risk:

- **P1** — low effort, no architectural risk (return-type unwrapping, adding
  `response_schema`, registering a plugin, setting an env var, wiring an
  existing evalset to pytest).
- **P2** — medium refactors with real maintainability payoff (removing a
  redundant agent tier, replacing `copy.copy` with `AgentTool`, converging tool
  result shapes).
- **P3** — needs a team decision, not just execution (security trade-offs,
  whether to revive or delete a dead branch, whether ingestion stays a
  conversational tool).

Keep P3 as *decisions with options*, never as a recommendation dressed up as a
fact.

## 5. High-yield things to grep for immediately

These recur across ADK projects and each has a dedicated skill:

- `copy.copy(` / `copy.deepcopy(` on an agent → single-parent workaround.
- Tools returning a Pydantic model or a bare `str` → auto-wrapping.
- More than one tool result shape in the same app.
- `json.loads` after `.replace("```json"` → unconstrained generation.
- `genai.Client(` or `genai.client.Client(` inside a tool → untraced,
  un-retried side-channel.
- Session-state keys with no prefix that are scratch data for one turn.
- `_invocation_context` or other private attribute access.
- Committed `*.evalset.json` referenced by nothing.
- `InMemory*Service` reachable from a production entrypoint.
- A `pyproject` ADK pin that disagrees with the venv.
- Dead branches (`if False`-style flags, agents never reachable) left in a
  system described as production-grade.

## 6. The ADK skill family

| Skill | Covers |
|---|---|
| `adk-agent-architecture` | agent tree, `sub_agents` vs `AgentTool`, single parent, graph `Workflow`, loops, models |
| `adk-function-tools` | tool return contract, docstrings, `ToolContext`, state prefixes, HITL, toolsets |
| `adk-structured-output` | `output_schema`, `response_schema`, `AgentTool` validation, multimodal injection, model layer |
| `adk-artifacts-and-files` | user uploads, `SaveFilesAsArtifactsPlugin`, artifact services |
| `adk-tool-auth` | OAuth2/OIDC in tools, credential services, what ADK does not provide |
| `adk-memory-and-retrieval` | `BaseMemoryService` vs `BaseRetrievalTool` vs your own vector store |
| `adk-app-and-plugins` | `App`, plugin hooks and short-circuit contract, compaction, caching, resume |
| `adk-service-backends` | session/artifact/memory/credential implementations, custom service registration |
| `adk-eval-harness` | evalsets, metrics, pytest, custom metrics, simulation |
| `adk-observability` | OTLP setup, span hierarchy, tracing blind spots |

Load the one matching the theme you are reviewing rather than reasoning from
memory about ADK behaviour.

These ten describe ADK at the version they were verified against. When a newer
`google-adk` release has to be adopted — or when you suspect the skills have
gone stale — use **`adk-version-upgrade`** (entry point: the `/adk-upgrade`
command): it establishes the version gap, machine-checks every citation in this
family against the new sources, and produces the project's migration spec.
