---
description: "Upgrade this project to a newer google-adk release - version gap, source diff, ADK skill re-verification, migration spec"
---

Run the Google ADK upgrade procedure for the current project.

Target version (optional, empty means "latest published"): $ARGUMENTS

Load the `adk-version-upgrade` skill and follow it. It owns the commands, the
scripts and the quality bar; this command only fixes the order of work and the
reporting.

## Steps

1. **Version triple** (skill §1). Report installed / declared / latest, using
   the project's own interpreter. Stop and say so if installed already equals
   the target. If the declared pin disagrees with what is installed, raise that
   first - every later conclusion depends on which one is real.

2. **Confirm the target with me** before doing any work: the version, whether
   it is a major bump, and the `requires-python` / `pydantic` / `google-genai`
   floors it brings. Wait for my go-ahead.

3. **Materialize both trees** (skill §2) with
   `~/.kilo/skills/adk-version-upgrade/scripts/get_adk_tree.py`, preferring a
   local `google/adk-python` checkout via tags. Include the
   `google-adk-community` trees only if this project imports
   `google.adk_community.*`.

4. **Release narrative** (skill §3): changelog range, plus the docs
   incompatibility page for a major bump. Produce the list of candidate
   breaking areas.

5. **Citation audit** (skill §4):
   `~/.kilo/skills/adk-version-upgrade/scripts/check_citations.py --old ... --new ...`.
   Save the report; its "Diffs to read" section drives the next step.

6. **Parallel area audits** (skill §5): group the changed files by subpackage
   and dispatch one `adk-diff-auditor` subagent per area, all at once, each
   with the two tree paths, its file list, the citing skill names and this
   project's source root. Collect their tables.

7. **Report to me before editing anything**: breaking changes that affect this
   project, breaking changes that do not, and skills that need repair. Wait for
   my go-ahead.

8. **Repair the skills** (skill §6): only the implicated ones, re-cited against
   the new tree, then the same-tree self-check, then `/reload`.

9. **Write the migration spec** (skill §7) from
   `~/.kilo/skills/adk-version-upgrade/references/migration-spec-template.md`
   into this project's task area. Discover the project's real constraints
   first - undeclared editable installs, lockfile, Dockerfile install lines,
   conflicting pins in extras - and run `uv pip install --dry-run` before
   claiming the new pin resolves.

## Rules

- Do not change the pin, the environment or any application code as part of
  this command. It produces analysis, updated skills and a spec; executing the
  spec is a separate, reviewable task.
- No claim about ADK without a `path::symbol` you actually grepped in the new
  tree.
- State negative results explicitly ("checked, unchanged") - they are what
  stops the next person from redoing the comparison.
