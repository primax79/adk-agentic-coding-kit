# Global Safety and Execution Instructions

## Safety and Git Constraints

- **NEVER run `git reset --hard` (or any destructive git command like `git checkout -- .`, `git clean -fd`) on local or shared branches** (`development`, `main`, etc.) unless explicitly instructed by the user in that exact prompt.
- **NEVER assume unpushed local commits on integration branches are disposable.** Always check `git log` and `git reflog` before resetting or switching branches.
- When creating worktrees or sub-agent tasks, ensure they branch from the intended base commit without resetting or modifying the parent working tree.

## Third-Party/External API Verification (anti-hallucination)

Before writing code that calls a method, class, constructor field, or parameter
of any external or third-party library (anything not written in this same
task's diff — installed packages, vendored/nested repos, internal but
unfamiliar modules), **verify it against the real installed/checked-out
source first.** Do not rely on the name/shape looking plausible, matching a
similar API you've seen elsewhere, or matching what a task spec/draft
sketches in pseudocode — spec text and prior drafts are frequently wrong on
exact names and get corrected during real implementation.

- Locate the real source (`grep`/`find` the installed package in the venv's
  `site-packages`, or the actual repo if it's a local/editable dependency) and
  read the actual class/function definition: exact method name, parameter
  names, defaults, return type, and any Pydantic `alias=`/field name that
  differs from the attribute name used elsewhere.
- This applies especially to: constructor kwargs on library model classes
  (aliases are a common silent-failure trap — passing the wrong kwarg name
  can pass validation-free with `None`/a default instead of erroring),
  client method names, and any field read from a client response that isn't
  backed by a typed model (raw dict responses — verify shape empirically,
  e.g. via a real call or existing test fixture, don't assume key names).
- If a library class distinguishes cases by object **type** (e.g. subclass
  hierarchy) rather than a boolean/optional attribute, use `isinstance()`
  against the real class, not `getattr(x, "some_plausible_attr", False)` or
  `hasattr(x, "some_plausible_attr")` — a guessed attribute name that doesn't
  exist silently returns the default/`False` instead of erroring, which
  hides the bug instead of surfacing it.
- If the real definition cannot be located (library not installed yet,
  genuinely not written yet), say so explicitly in code comments and/or the
  final report instead of guessing a plausible-looking signature and moving
  on silently.

## Care and Scope Discipline

Applies whether you're working interactively with a user or executing a
delegated task headlessly (background/MCP orchestration) — the framing below
covers both; in a headless run, "ask/flag" means stating it clearly in your
final report/commit message instead of prompting a person.

- **Stay in scope:** implement exactly what was asked. Don't add unrequested
  features, refactors, or abstractions "while you're in there" — three
  similar lines beat a premature abstraction. If you notice something else
  worth doing, mention it rather than doing it unasked.
- **Blast-radius awareness:** for anything hard to reverse or outside the
  explicit request (touching files/scope not mentioned, deleting data,
  force-pushing, editing real/shared config instead of a scratch copy) —
  stop and ask if you can (interactive), or clearly flag the deviation
  instead of doing it silently (headless). If the real environment forces a
  deviation the request didn't foresee (a missing dependency, a config gap),
  say so explicitly rather than quietly working around it.
- **Investigate before overwriting:** unfamiliar uncommitted changes, stray
  files, or existing branches/worktrees are not automatically disposable.
  Check what they are before touching them; leave what isn't yours alone.
- **Verify, don't just report:** run the actual test/build/import before
  claiming something works. "Should work" is not "verified" — when you
  report completion, describe what you actually ran and its real output,
  not what you expect to happen.
