# adk-agentic-coding-kit

Google ADK (`google-adk` Python) development knowledge and tooling, packaged
as a Kilo Code / Claude Code plugin marketplace. One plugin today:
**`adk-tools`**.

## What's in `adk-tools`

- **11 reference skills** — `adk-agent-architecture`, `adk-function-tools`,
  `adk-structured-output`, `adk-artifacts-and-files`, `adk-tool-auth`,
  `adk-memory-and-retrieval`, `adk-app-and-plugins`, `adk-service-backends`,
  `adk-eval-harness`, `adk-observability`, `adk-conformance-review`. Each is
  grounded in the actual `google-adk` source (not the docs alone) — every
  claim cites `path::symbol`, not a guessed API.
- **`adk-version-upgrade`** — a 12th skill, the procedure for moving a
  project between `google-adk` releases: detect the version gap, diff only
  what matters, re-verify the other 11 skills against the new version, emit
  a migration spec. Ships with two bundled scripts
  (`get_adk_tree.py`, `check_citations.py`) and a migration-spec template.
- **`adk-diff-auditor`** subagent — read-only, dispatched by
  `adk-version-upgrade` to audit one subpackage of an ADK version diff in
  isolation.
- **`/adk-upgrade`** command — the entry point that drives the above end to
  end for the current project (two confirmation gates, never edits pins or
  application code itself — it produces analysis + an updated skill set +
  a migration spec, execution is a separate step).

## Install

### Claude Code (native plugin support)

```text
claude plugin marketplace add <git-url-of-this-repo>
/plugin install adk-tools@adk-agentic-coding-kit
```

### Kilo Code (and any other tool, via `kilo-plugin-manager`)

```bash
python3 ~/.kilo/skills/kilo-plugin-manager/scripts/plugin_manager.py add <git-url-of-this-repo> --name adk-agentic-coding-kit
python3 ~/.kilo/skills/kilo-plugin-manager/scripts/plugin_manager.py install adk-tools@adk-agentic-coding-kit
# or, into one project only:
python3 ~/.kilo/skills/kilo-plugin-manager/scripts/plugin_manager.py install adk-tools --project /path/to/repo
```

`update` (no args) later pulls this marketplace and refreshes every install.

## Status

Extracted from a real ADK upgrade + conformance-review pass on a production
multi-agent project (`dave_agent`), then generalized. Currently vendored as
a local copy inside that project's own repo while this package is being
stood up and tested end to end from a fresh workspace; once verified, that
project switches to installing from here instead.
