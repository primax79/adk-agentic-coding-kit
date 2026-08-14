# Agent operating instructions

`INSTRUCTIONS.md` in this folder is not a skill and not a plugin - skills and
subagents (see `plugins/`) are loaded *on demand*, when their description
matches the task at hand. This file is different: it's meant to be loaded
into **every** conversation/session unconditionally, as a standing set of
behavioral rules, regardless of what the task is.

It's framework-agnostic on purpose - nothing in it is specific to Google ADK
or to any single project. It covers three things learned the hard way across
real delegated coding sessions:

1. **Git safety** - don't treat unpushed work or shared branches as
   disposable.
2. **Third-party API verification** - don't guess a library's method names,
   constructor kwargs, or field aliases; grep the real installed source
   before using it. Written after a real, reproducible case of an agent
   inventing a plausible-looking `getattr(item, "is_folder", False)` check
   against a library that has no such attribute - silently misclassifying
   every folder as a file instead of erroring.
3. **Care and scope discipline** - stay inside the requested scope, treat
   hard-to-reverse actions carefully, don't touch unfamiliar existing state
   without checking it first, and verify before claiming success instead of
   reporting an expectation as a fact.

None of this is ADK-specific, or even Kilo/Claude-specific in principle -
it's the standing contract any coding agent should operate under. What *is*
tool-specific is how you wire an always-on instructions file into a given
coding assistant. That's covered per tool below.

## How to use it

### Kilo Code

Kilo loads instruction files listed under **Agent Behaviour → Rules →
Additional Instruction Files** (same UI that already lists `./AGENTS.md` and
`~/.config/kilo/INSTRUCTIONS.md` by default) into the system prompt of every
conversation. Point it at this file, or copy its content into whichever path
you already have configured there:

- **Global** (every project on the machine): copy/symlink this file to
  `~/.config/kilo/INSTRUCTIONS.md`, or add its path directly in the Rules UI,
  or add it to the `instructions` array in `~/.config/kilo/kilo.jsonc`.
- **Per project**: copy/symlink it to `<repo>/AGENTS.md` (or any path) and
  add that path in the same Rules UI, scoped to that project's `kilo.jsonc`
  (`.kilo/kilo.jsonc`) instead of the global one.

Either way this also reaches headless delegation through `kilo-mcp`
(`kilo_implement`), since that runs through the same Kilo CLI and picks up
the same `instructions` configuration - no separate wiring needed for
orchestrated vs. interactive use.

### Claude Code

The equivalent always-on mechanism is `CLAUDE.md` - global
(`~/.claude/CLAUDE.md`) or per-project (`<repo>/CLAUDE.md`), loaded into
every session automatically. Copy this file's content in (or append it,
alongside whatever project- or user-specific instructions already live
there).

### Other frameworks

Not covered yet - this kit currently targets Kilo Code and Claude Code only.
If/when another coding-agent framework is added here, document its
equivalent "always-on instructions" mechanism (every framework with a
persistent-agent story has one, under some name) as a new subsection above,
following the same pattern: where the file goes, global vs. per-project
scope, and whether headless/orchestrated runs pick it up automatically or
need separate wiring.

## Keeping this in sync

This file is a checked-in copy, not a symlink - the actual deployed instance
lives wherever you wired it per the section above (e.g.
`~/.config/kilo/INSTRUCTIONS.md`). If you improve the deployed copy during a
session, port the change back here so it isn't lost to a single machine's
`~/.config`.
