# Migration spec template

Two files, written into the project's task area (e.g. `tasks/adk-upgrade/`):
an index that carries the *analysis*, and one task that carries the
*executable change*. Keep them separate — the index is read by a human
deciding whether to do the upgrade, the task is read by an agent doing it.

Delete every bracketed placeholder. Nothing may remain unresolved: an
unverified claim in a spec becomes an unverified change in the codebase.

---

## File 1 — `README.md` (index / analysis)

````markdown
# ADK upgrade — index

Upgrade of `google-adk` from the currently pinned `<OLD>` to `<NEW>`, plus the
dependency issues that block a clean environment resolution today.

## Why now

<How the comparison was made: local checkout of `google/adk-python` at tags
`v<OLD>`/`v<NEW>`, or PyPI wheels; the changelog range read; the docs
migration page consulted for a major bump.>

Symbols this project imports from `google.adk.*`, all checked:

- `google.adk.<module>`: `<Symbol>`, `<Symbol>`
- ...

<Produce this list mechanically, do not hand-wave it:
`grep -rhoE 'from google\.adk[a-z_0-9.]* import [A-Za-z0-9_, ]+|import google\.adk[a-z_0-9.]*' <src> | sort -u`
— digits matter (`OAuth2Auth`), and parenthesized multi-line imports need a
second pass: `grep -rn -A5 'from google\.adk.* import ($' <src>`>

**Result of the comparison: <no breaking change for any of these symbols |
N breaking changes, listed below>.**

<Per changed symbol, one paragraph: what changed, evidence as ADK
`path::symbol`, and whether this project is affected. Include the negative
results too — "`AuthenticatedFunctionTool` is byte-identical" is load-bearing
information for the reviewer.>

Dependency floors that moved between `<OLD>` and `<NEW>`:

| requirement | `<OLD>` | `<NEW>` | impact here |
|---|---|---|---|
| `requires-python` | | | |
| `pydantic` | | | |
| `google-genai` | | | |

## Constraints

<Every project-level constraint discovered in phase 7 of the
`adk-version-upgrade` skill. The one that matters most:>

### Do not clobber the manual editable install of `<PACKAGE>`

`<PACKAGE>` is **not** declared as a path/editable dependency in
`pyproject.toml` (no `[tool.uv.sources]`): the dev `.venv` has it installed
editable by hand against the local checkout `<ABS PATH>` (branch `<BRANCH>`,
version `<X.Y.Z>`). Any command that reinstalls dependencies must not replace
it with a PyPI wheel. See the task file for the exact sequence.

## Tasks

- **00 — <title>** (`00-<slug>.md`)

## Out of scope

- Adopting new ADK features not currently used (<name them>).
- <Anything else deliberately excluded.>
````

---

## File 2 — `00-<slug>.md` (executable task)

````markdown
# Task 00 — Bump `google-adk` to `<NEW>`

## Target repo

`<repo>` (this repo), root `pyproject.toml` + the dev `.venv`.

## Depends on

<Nothing / task refs.>

## Result

- `pyproject.toml` pins `google-adk[<extras>]==<NEW>` (was `==<OLD>`).
- <Other dependency-hygiene outcomes.>
- A clean environment resolves and installs with nothing patched by hand.
- The whole module tree imports cleanly against `google-adk==<NEW>` with
  identical behaviour. This is a dependency bump, not a refactor: do not
  change application code unless the verification below surfaces a real
  incompatibility.

## Why

See `README.md` for the source-level comparison. Summary: <one paragraph>.

## Current on-disk state (verified <date>)

```toml
<paste the exact current dependency blocks — an agent that cannot match the
text it is told to change will improvise>
```

<Lockfile status: `uv.lock` present/absent, and what that implies.>

## Exact changes

1. In `dependencies`, change `"google-adk[<extras>]==<OLD>"` to
   `"google-adk[<extras>]==<NEW>"`.
2. <Each further edit as before/after, with the reason. Say explicitly when an
   alternative fix is wrong and why — e.g. "remove the pin, do not narrow it".>

## Constraint — the local editable install of `<PACKAGE>`

1. Install the project's own dependencies first, mirroring how the
   `Dockerfile` does it: `uv pip install -e ".[<extras>]"`.
2. Then, separately, reinstall the local library editable:
   `uv pip install -e <path to sibling checkout>`.
3. Verify with `uv pip show <PACKAGE>` that `Editable project location:`
   points at that checkout and the version is `<X.Y.Z>` — not a PyPI wheel.
   If step 1 downgraded it, redo step 2; do not proceed.

<If work happens in a git worktree, state that the sibling checkout keeps its
own absolute path and is not inside the worktree.>

## Verification (in order)

1. `uv pip install --dry-run -e ".[<extras>]"` resolves with no conflict, then
   the real `uv pip install -e ".[<extras>]"` exits 0.
2. `uv pip show google-adk` reports `<NEW>`.
3. `uv pip show <PACKAGE>` still reports the editable checkout.
4. Every module imports with zero errors:
   ```
   <explicit module list — generate it, do not approximate:
   find src -name '*.py' | sed 's|^src/||; s|\.py$||; s|/|.|g; s|\.__init__$||'>
   ```
5. `python -c "from <pkg>.server import app"` succeeds — this constructs the
   real ADK app wiring, which plain imports do not exercise.
6. <Any behaviour specific to the breaking changes found in the analysis:
   the smallest script that proves the changed API still does what the code
   assumes.>
7. Report the exact install command used, the resolved versions, and the
   pass/fail of each check above.

## Out of scope

- Do not upgrade reference checkouts under `<external tools dir>` — read-only
  material, not part of this repo's dependency graph.
- Do not adopt new ADK features in application code.
- Do not run a bare `uv sync` <when it would regenerate a lockfile or replace
  the editable install — state the actual reason for this repo>.
- <Unrelated in-flight work that must not be touched.>
````

---

## Rules that make these specs work

- **Every breaking-change claim carries ADK `path::symbol` evidence.** No
  evidence, no claim.
- **Negative findings are stated, not omitted.** "Checked, unchanged" prevents
  the next reader from redoing the comparison.
- **Verification is ordered and mechanical**, and includes at least one step
  that constructs the real ADK objects rather than importing modules.
- **Constraints name paths and versions**, never "the local library".
- **Out of scope is explicit**, because a bump task is the single most common
  place where unrelated refactors get smuggled in.
