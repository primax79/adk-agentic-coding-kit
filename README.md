# adk-agentic-coding-kit

Google ADK (`google-adk` Python) dev skills, subagent, and upgrade tooling for
AI coding agents (Claude Code, Kilo Code) — source-verified, not guessed.

Packaged as a Kilo Code / Claude Code plugin marketplace. One plugin today:
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

Two independent install paths. `kilo-plugin-manager` is the one actually
verified end to end in this repo's history (twice, see Status below) — it
writes working files into **both** `.kilo/` and `.claude/`, so it installs
for Claude Code too, with or without Claude's own native `/plugin` command
being available in your environment (it isn't in every Claude Code build —
if `/plugin` errors with "isn't available in this environment", use
`kilo-plugin-manager` instead, it does not depend on that command at all).

### `kilo-plugin-manager` (works for Kilo Code *and* Claude Code)

One-time, per machine: register this repo as a marketplace.

```bash
python3 ~/.kilo/skills/kilo-plugin-manager/scripts/plugin_manager.py add git@github.com:primax79/adk-agentic-coding-kit.git --name adk-agentic-coding-kit
```

**Global** — available in every project on this machine, written to
`~/.kilo/skills/`, `~/.kilo/agent/`, `~/.kilo/command/` and their
`~/.claude/` counterparts:

```bash
python3 ~/.kilo/skills/kilo-plugin-manager/scripts/plugin_manager.py install adk-tools@adk-agentic-coding-kit
```

**Per project** — scoped to one repo only, written to `<repo>/.kilo/...`
and `<repo>/.claude/...` (skills are symlinks back to the marketplace
checkout; pass `--copy` instead if the install must not depend on the
local checkout staying in place):

```bash
python3 ~/.kilo/skills/kilo-plugin-manager/scripts/plugin_manager.py install adk-tools@adk-agentic-coding-kit --project /path/to/repo
```

`update` (no args, no `--project`) later pulls this marketplace and
refreshes every install it made, global and per-project alike.
`uninstall adk-tools [--project /path/to/repo]` removes them again.

### Claude Code native plugin command (if available in your environment)

```text
claude plugin marketplace add git@github.com:primax79/adk-agentic-coding-kit.git
/plugin install adk-tools@adk-agentic-coding-kit
```

This is Claude Code's own mechanism (global, user-level — Claude Code does
not have a documented per-project plugin scope the way Kilo does with
`--project`). Use it if `/plugin` works in your environment; otherwise use
`kilo-plugin-manager` above, which produces the same `.claude/agents/`,
`.claude/commands/`, `.claude/skills/` files without depending on this
command.

## Status

Extracted from a real ADK upgrade + conformance-review pass on a production
multi-agent project (`dave_agent`), then generalized. Verified end to end
twice: once installing from the local checkout, once installing from this
repo's real GitHub remote into a throwaway workspace — both times confirming
the Kilo-shaped `adk-diff-auditor` subagent keeps its read-only permissions
(`mode: subagent`, `edit: deny`) instead of losing them to a lossy
Claude→Kilo auto-translation (see `plugins/adk-tools/agents_kilo/`).

`dave_agent` currently still carries its own local copy of these skills
while this package settles; it will switch to installing from here instead.

## License

[MIT](LICENSE)
