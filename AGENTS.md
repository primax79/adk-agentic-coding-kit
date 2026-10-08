# AGENTS.md — adk-agentic-coding-kit

Google ADK (`google-adk` Python) dev skills, subagent, and upgrade tooling,
packaged as a Claude Code / Kilo Code plugin marketplace. Full pitch and
install paths: [`README.md`](README.md). Part of the `primax79/*` family of
AI-coding-tool repos — see the workspace root's `AGENTS.md` (one level up)
for how this repo relates to its siblings.

## Layout

- `plugins/adk-tools/` — the one plugin. `skills/` (11 reference skills +
  `adk-version-upgrade`), `agents/` + `agents_kilo/` (Claude and Kilo
  variants of `adk-diff-auditor`, kept in sync — see Agent sync rule below),
  `commands/` (`/adk-upgrade`).
- `instructions/` — framework-agnostic, always-on agent operating rules
  (not a plugin, not installed per-project). See `instructions/README.md`.
- `scripts/generate_skill_indices.py` — regenerates every `index.json` for
  the Skill-URLs install path.
- `.claude-plugin/marketplace.json` — the marketplace manifest Claude
  Code's `/plugin` reads.

## Mandatory rules

- **Source-verified claims only.** Every reference skill under
  `plugins/adk-tools/skills/` cites `path::symbol` against the real
  `google-adk` source, not the docs alone and not a guess. If you add or
  edit a claim, verify it against actual ADK source before writing it down.
- **`adk-version-upgrade` is the only sanctioned path for bumping the
  `google-adk` version** the other 11 skills are grounded against — it
  re-verifies citations (`scripts/check_citations.py`) and produces a
  migration spec rather than hand-editing skill prose in place.
- **Skill manifest.** New/changed skills need valid YAML frontmatter
  (`name`, `description`) in `SKILL.md` — Kilo's loader silently skips a
  skill without it.
- **Regenerate indices.** After adding, removing, or renaming a skill under
  `plugins/adk-tools/skills/`, run
  `python3 scripts/generate_skill_indices.py` and commit the updated
  `index.json` files alongside the skill change — they're generated, not
  hand-maintained.
- **Agent sync rule.** Claude Code and Kilo Code agent frontmatter formats
  are not compatible. `agents/` (Claude) and `agents_kilo/` (Kilo) must be
  kept in sync — same behavior, same internal `name` field — when either is
  edited. The `kilo-claude-sync` skill (in `agentic-coding-kit`'s
  `agent-tooling-meta` plugin, sibling repo) automates this.
- **`adk-diff-auditor` must stay read-only.** It's a `mode: subagent`,
  `edit: deny` agent by design (dispatched to audit an ADK diff in
  isolation) — a lossy Claude→Kilo translation has previously stripped that
  restriction; check `agents_kilo/adk-diff-auditor.md` still carries
  `edit: deny` after any sync.

## Before committing

Only when explicitly asked to commit: check `git status`/`git diff` for
scope and secrets, and if `plugins/adk-tools/skills/` changed, confirm
`index.json` was regenerated (see above).
