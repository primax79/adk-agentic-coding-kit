---
name: adk-version-upgrade
description: "Use when a new Google ADK (google-adk Python) release needs to be adopted - `bump google-adk`, `upgrade ADK to X.Y.Z`, `is there a newer ADK`, `what breaks if we move to ADK 2.x`, `is our ADK knowledge still current` - to detect the version gap, diff the two source trees, re-verify the adk-* reference skills against the new version, and write the project's upgrade task spec."
---

# Upgrading Google ADK

The procedure for moving a project from one `google-adk` release to another
without guessing: establish the version gap, diff only what matters, repair the
ADK reference skills that the new version invalidates, and emit an executable
migration spec.

This skill is the *change* procedure. The *state* of ADK at the currently
documented version lives in the ten reference skills indexed by
`adk-conformance-review` §6 - read those for behaviour, edit those in phase 5.
The verification discipline (never assert a symbol you have not grepped; cite
`path::symbol`; code wins over docs for behaviour) comes from
`adk-conformance-review` §2 and applies unchanged here.

Entry point: the `/adk-upgrade` command. Heavy per-area diff reading is
delegated to the `adk-diff-auditor` subagent.

## 1. Establish the version triple

Three numbers, and they are frequently not the same one:

| | how |
|---|---|
| **installed** | `<project>/.venv/bin/python -c "import importlib.metadata as m; print(m.version('google-adk'))"` |
| **declared** | `grep -nE 'google-adk' pyproject.toml requirements*.txt uv.lock 2>/dev/null` |
| **latest** | `python3 -m pip index versions google-adk` |

- Use the **project's** interpreter, not the ambient one. Also print the import
  location - `python -c "import google.adk, pathlib; print(pathlib.Path(google.adk.__file__).parent)"` -
  because an editable/vendored ADK is a different story from a wheel.
  `google.adk.__version__` and `google.adk.version.__version__` both exist and
  agree with the distribution metadata.
- `pip index` is an *experimental* subcommand. Stable fallback:
  `curl -s https://pypi.org/pypi/google-adk/json | jq -r .info.version`.
  It reports the latest **stable** release; add `--pre` (or read
  `.releases` from the JSON) to see prereleases. There is no `uv pip index`
  subcommand - do not reach for it.
- Target metadata before committing to the bump:
  `curl -s https://pypi.org/pypi/google-adk/<version>/json | jq -r '.info.requires_python, (.info.requires_dist[]|select(startswith("pydantic")))'`.
  A raised `requires-python` floor or a moved pydantic/genai floor is usually
  the part of the upgrade that actually costs work.
- Extras matter for what gets installed, not for resolution of the version
  itself: a pin of `google-adk[eval]==X` pulls the eval dependency set too.

**Stop rules.** If installed == latest, report that and stop. If declared !=
installed, that discrepancy is itself the first finding and must be resolved
before any conclusion about the codebase is trustworthy
(`adk-conformance-review` §1) - every claim in this procedure is otherwise
drawn from a version nobody runs.

## 2. Materialize both source trees

```bash
SK=~/.kilo/skills/adk-version-upgrade/scripts
python3 $SK/get_adk_tree.py --version 2.1.0 --dest /tmp/adk-old --git-repo <adk-python-checkout>
python3 $SK/get_adk_tree.py --version 2.6.1 --dest /tmp/adk-new --git-repo <adk-python-checkout>
```

The script prefers `git archive <tag> src/google` from a local checkout and
falls back to a PyPI wheel; either way the output is normalized to
`<dest>/google/adk/...`, so trees from different sources are comparable.

- **Never read a checkout's working tree as if it were a release.** A checkout
  of `adk-python` typically sits on the default branch, whose `version.py` can
  read lower than tags that already exist in the same repo. Always go through
  a tag (`git show v2.6.1:<path>`, `git grep <pat> v2.6.1 -- src/google`).
- Tags for recent releases are often missing from a stale clone; the script
  runs `git fetch --tags` before giving up (disable with `--no-fetch`).
- If the project imports `google.adk_community.*`, materialize that
  distribution too (`--package google-adk-community`) and pass both trees in
  phase 4 - otherwise its citations are reported as unchecked, not as valid.
- An already-installed version can be used directly as a tree: pass the
  directory two levels above `google/adk` (i.e. `site-packages`).

## 3. Read the release narrative before the code

- Changelog at the target tag: `git show v<new>:CHANGELOG.md`, or
  `curl -s https://raw.githubusercontent.com/google/adk-python/v<new>/CHANGELOG.md`.
  It is release-please generated: `### Features` / `### Bug Fixes` per release,
  newest first. Read every entry from `v<old>` down to `v<new>`.
  (`CHANGELOG-v2.md` exists on the default branch but is not present at every
  tag - fetch it from `main` if you want it.)
- For a **major** bump, the incompatibility list lives in the docs, not the
  changelog: `adk-docs` → `docs/2.0/index.md`, section *"ADK Python 1.x
  compatibility"* (published as <https://google.github.io/adk-docs/2.0/>).
  It enumerates the breaking areas by name (event schema and custom session
  storage, `BaseAgent` → `BaseNode` execution, in-place context mutation,
  error handling and automatic retries).
- Commit-level view when the changelog is too coarse:
  `git -C <repo> log --oneline v<old>..v<new> -- src/google/adk/<area>`.

Write down, at this point, the candidate breaking areas. Everything after this
is confirmation or refutation against the code.

## 4. Machine-check the ADK skill family

```bash
python3 $SK/check_citations.py --old /tmp/adk-old --new /tmp/adk-new
# add: --skill adk-function-tools ... to narrow, --strict for unverifiable
#      identifiers, --json to post-process, --skills-dir for a non-default location
```

It extracts every `google/adk*/**.py` path (with optional `::symbol`), every
dotted `google.adk.*` reference and every plausible identifier from each
`adk-*/SKILL.md`, then classifies each against both trees:

| state | meaning | action |
|---|---|---|
| `UNCHANGED` | cited file byte-identical | nothing |
| `CHANGED` | cited file differs | read the diff (phase 5) |
| `MOVED_OR_DELETED` | path gone; candidate new path reported | re-cite or remove the claim |
| `MOVED` (symbol) | definition left the cited file, name still exists | re-cite the new location |
| `REMOVED` (symbol) | defined in old, absent from new entirely | the claim is dead - rewrite it |
| `ADDED_AFTER` | exists only in the new tree | the skill was written against a different version than `--old`; re-check which |
| `BROKEN` / `UNKNOWN` | in neither tree | **pre-existing bad citation**, unrelated to the bump; fix it anyway |
| `NO_TREE` | package (usually `adk_community`) not supplied | pass its tree, or state it was not checked |

Symbol resolution is AST-based, so re-exports (`from .load_artifacts_tool
import load_artifacts_tool as load_artifacts`), Pydantic fields and function
parameters all count as definitions - a symbol only reports `REMOVED` when
nothing in the new tree defines or even mentions it.

The tail of the report is a deduplicated **"Diffs to read"** list: exactly the
cited files that changed. That list, not the full release diff, is the input to
phase 5.

## 5. Read only the diffs that matter

For each changed area (group the phase-4 list by package: `tools/`, `agents/`,
`sessions/`, `plugins/`, `evaluation/`, `telemetry/`, ...), dispatch one
`adk-diff-auditor` subagent, in parallel, with: the two tree paths (or the
checkout plus both tags), the file list for that area, and the names of the
skills that cite them. Each returns API-level deltas only.

Diff commands the auditor uses:

```bash
git -C <repo> diff v<old>..v<new> -- src/google/adk/<area>     # with a checkout
diff -ru /tmp/adk-old/google/adk/<area> /tmp/adk-new/google/adk/<area>
```

Classification the auditor must apply:

- **Breaking**: public symbol removed or renamed without a re-export; a
  required parameter added, removed or renamed; return type or dict shape
  changed; a default changed such that existing behaviour changes; a module
  moved without a compatibility import; new mandatory configuration.
- **Not breaking**: new optional parameters, new symbols, docstrings,
  type-hint tightening, added null-safety, new optional Pydantic fields.
- **Private (`_`-prefixed) changes** are only breaking for *this* project if
  the project reaches into them. Grep it:
  `grep -rn "_invocation_context\|\._[a-z_]*(" <project>/src | head`.
  Reaching into ADK privates is a known pattern; a change there is a real
  finding even though ADK owes no compatibility.

## 6. Update the reference skills

Only the skills phase 4/5 actually implicated. For each:

- Re-cite against the **new** tree; verify each replacement symbol by grep
  before writing it (`git grep -n "class X" v<new> -- src/google/adk`).
- When behaviour changed, say so explicitly with both versions
  ("through 2.5.0 ... ; from 2.6.0 ..."), rather than silently overwriting - the
  reader may be on the old version.
- Fix every `BROKEN`/`UNKNOWN` citation found in phase 4, even if unrelated to
  the bump.
- Update the version reference each skill states it was verified against.
- If a skill is added, retired or renamed, update the `adk-conformance-review`
  §6 index table in the same pass.

Self-check when done - running the checker with the same tree on both sides
turns it into a pure existence check of every citation:

```bash
python3 $SK/check_citations.py --old /tmp/adk-new --new /tmp/adk-new
```

Everything must come back `UNCHANGED`/`OK`, with no `BROKEN` or `UNKNOWN`
symbols. Then `/reload` to pick the skills up mid-session.

Skills need no Claude Code sync: `~/.claude/skills` is a symlink to
`~/.kilo/skills`. Agents are separate files - if you touched
`~/.kilo/agent/*.md`, run
`python3 ~/.kilo/skills/kilo-claude-sync/scripts/sync.py --scope global`.

## 7. Write the project migration spec

Copy `references/migration-spec-template.md` into the project's task area
(e.g. `tasks/adk-upgrade/`) and fill it from what phases 1-5 established.
A spec that is not grounded in the phase-4/5 findings is worthless; every
"breaking change" line must carry its ADK `path::symbol` evidence.

Project-specific constraints that must be discovered before writing it - these
are what actually break upgrades, more often than ADK itself:

```bash
grep -nE 'google-adk|requires-python|pydantic' pyproject.toml
grep -nA5 '\[tool.uv.sources\]' pyproject.toml         # path/editable deps
uv pip list --editable                                  # editables the venv has but pyproject does not declare
uv pip show <each-editable>                             # confirm "Editable project location"
ls uv.lock poetry.lock 2>/dev/null                       # is there a lockfile to regenerate?
grep -rn 'pip install' Dockerfile* 2>/dev/null           # how CI/prod installs
```

An editable install of a sibling checkout that `pyproject.toml` does not
declare is the classic trap: any full reinstall silently replaces it with a
PyPI wheel and reintroduces bugs already fixed locally. The spec must name
that package, its checkout path, and the reinstall-and-verify step.

Check resolvability without mutating the environment first:

```bash
uv pip install --dry-run -e ".[<extras>]"
```

Conflicting pins in a test/dev extra (a stale `pydantic` ceiling is the usual
one) surface here, and are worth fixing in the same task since they block the
install regardless of the ADK version.

## 8. Done criteria

1. Version triple reported; declared == installed == target after the change.
2. Every changed cited file either reviewed or explicitly declared irrelevant.
3. `check_citations.py --old <new> --new <new>` clean.
4. Migration spec written, with per-claim ADK evidence, constraints, and an
   ordered verification section that a fresh agent can execute.
5. Application code untouched unless a real incompatibility was demonstrated -
   a version bump is not a refactor.

## Related

| Skill | Use for |
|---|---|
| `adk-conformance-review` | index of the ten ADK reference skills, and the verification method |
| `adk-agent-architecture`, `adk-function-tools`, `adk-structured-output`, `adk-artifacts-and-files`, `adk-tool-auth`, `adk-memory-and-retrieval`, `adk-app-and-plugins`, `adk-service-backends`, `adk-eval-harness`, `adk-observability` | the per-area knowledge this procedure re-verifies and edits |
| `kilo-claude-sync` | mirroring edited agents to Claude Code |
