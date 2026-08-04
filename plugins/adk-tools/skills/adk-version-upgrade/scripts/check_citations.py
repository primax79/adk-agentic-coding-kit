#!/usr/bin/env python3
"""Re-verify the citations of the ADK skill family against a new ADK version.

Every `adk-*` skill cites ADK source files (``src/google/adk/...``, optionally
``::symbol``), dotted module paths (``google.adk.tools.exit_loop``) and bare
identifiers in backticks or code fences. This script diffs those citations
between two materialized ADK source trees so that a version bump only requires
reading the diffs that actually touch something a skill claims.

Trees are directories that contain ``google/adk`` (a wheel/site-packages
layout) or ``src/google/adk`` (a repo layout). Produce them with
``get_adk_tree.py`` or point at an installed package::

    python3 -c "import google.adk,pathlib;print(pathlib.Path(google.adk.__file__).parents[2])"

``--old``/``--new`` are repeatable: pass the ``google-adk`` tree and the
``google-adk-community`` tree together to also check ``google.adk_community``
citations, otherwise those are reported as ``NO_TREE`` (not checked) instead of
being mistaken for removals.

Classification (the ``--old`` tree is what the skills were written against):

  files    UNCHANGED | CHANGED | MOVED_OR_DELETED | ADDED_AFTER | BROKEN | NO_TREE
  symbols  OK | MOVED | REMOVED | ADDED_AFTER | UNKNOWN

``BROKEN`` (cited path in neither tree) and ``UNKNOWN`` (identifier defined in
neither tree) are pre-existing citation errors, not upgrade fallout — fix them
regardless of the version bump. ``UNKNOWN`` also collects ordinary English
words and project-side identifiers, so it is reported only with ``--strict``.

Usage::

    check_citations.py --old /tmp/adk-2.1.0 --new /tmp/adk-2.6.1
    check_citations.py --old /tmp/adk-2.1.0 --old /tmp/adkc-0.3.0 \\
                       --new /tmp/adk-2.6.1 --new /tmp/adkc-0.4.0
    check_citations.py --old ... --new ... --skill adk-function-tools --json
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path

DEFAULT_SKILLS_DIR = Path(__file__).resolve().parents[2]

FILE_RE = re.compile(
    r"(?:src/)?(google/(?:adk|adk_community)(?:/[A-Za-z0-9_]+)*\.py)"
    r"(?:::([A-Za-z_][A-Za-z0-9_.]*))?"
)
MODULE_RE = re.compile(r"\bgoogle\.(?:adk|adk_community)(?:\.[a-z_][a-z0-9_]*)+\b")
BACKTICK_RE = re.compile(r"`([^`\n]{2,80})`")
FENCE_RE = re.compile(r"```[a-zA-Z]*\n(.*?)```", re.DOTALL)
IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
DEF_RE = re.compile(
    r"^[ \t]*(?:async[ \t]+)?def[ \t]+(\w+)"
    r"|^[ \t]*class[ \t]+(\w+)"
    r"|^[ \t]*(\w+)[ \t]*(?::[^=\n]+)?=[^=]",
    re.MULTILINE,
)
# Identifiers that are too generic to carry signal even when ADK defines them.
STOPWORDS = {
    "self", "cls", "args", "kwargs", "None", "True", "False", "return", "import",
    "from", "class", "def", "async", "await", "type", "id", "name", "value",
    "key", "data", "result", "error", "status", "message", "content", "text",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def defined_names(text: str) -> set[str]:
    """Every name a module makes available: classes, functions, assignment
    targets (including Pydantic fields), function parameters and import
    aliases (``from .x import y as z`` — how ADK re-exports most tools)."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {m for groups in DEF_RE.findall(text) for m in groups if m}
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return names


def resolve_tree(path: Path) -> Path:
    """Return the directory that directly contains ``google/``."""
    path = path.expanduser().resolve()
    for candidate in (path, path / "src"):
        if (candidate / "google" / "adk").is_dir() or (candidate / "google" / "adk_community").is_dir():
            return candidate
    if path.name == "adk" and path.parent.name == "google":
        return path.parents[1]
    raise SystemExit(f"error: {path} contains neither google/adk nor src/google/adk")


class Tree:
    def __init__(self, roots: list[Path], label: str):
        self.roots = [resolve_tree(r) for r in roots]
        self.label = label
        self.files: dict[str, str] = {}
        self.defs: set[str] = set()
        self.tokens: set[str] = set()
        self.defs_by_file: dict[str, set[str]] = {}
        self.packages: set[str] = set()
        for root in self.roots:
            self._index(root)

    def _index(self, root: Path) -> None:
        for pkg in ("adk", "adk_community"):
            if (root / "google" / pkg).is_dir():
                self.packages.add(pkg)
        for py in sorted((root / "google").rglob("*.py")):
            rel = py.relative_to(root).as_posix()
            self.files[rel] = sha(py)
            text = py.read_text(encoding="utf-8", errors="replace")
            names = defined_names(text)
            self.defs_by_file[rel] = names
            self.defs |= names
            self.tokens |= set(IDENT_RE.findall(text))

    def covers(self, rel_or_dotted: str) -> bool:
        """True when the package a citation belongs to is present in this tree."""
        pkg = "adk_community" if "adk_community" in rel_or_dotted else "adk"
        return pkg in self.packages

    def basenames(self, name: str) -> list[str]:
        return [rel for rel in self.files if rel.rsplit("/", 1)[-1] == name]

    def module_targets(self, dotted: str) -> list[str]:
        """Candidate on-disk targets for a dotted module path."""
        rel = dotted.replace(".", "/")
        out = [f"{rel}.py", f"{rel}/__init__.py"]
        return [p for p in out if p in self.files]


def extract(skill_md: Path) -> dict:
    text = skill_md.read_text(encoding="utf-8")
    files: dict[str, set[str]] = {}
    for path, symbol in FILE_RE.findall(text):
        files.setdefault(path, set())
        if symbol:
            files[path].add(symbol.split(".")[-1])
    modules = set(MODULE_RE.findall(text))

    idents: set[str] = set()
    for raw in BACKTICK_RE.findall(text):
        token = raw.strip().rstrip("()")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token):
            idents.add(token)
        elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", token):
            idents.add(token.rsplit(".", 1)[-1])
    for fence in FENCE_RE.findall(text):
        idents |= set(IDENT_RE.findall(fence))

    idents = {
        i for i in idents
        if i not in STOPWORDS
        and len(i) >= 4
        and ("_" in i or (i[:1].isupper() and any(c.islower() for c in i)))
    }
    return {"files": files, "modules": modules, "idents": idents}


def audit(skill_md: Path, old: Tree, new: Tree) -> dict:
    cited = extract(skill_md)
    report: dict = {
        "skill": skill_md.parent.name,
        "files": [],
        "modules": [],
        "symbols": [],
        "unknown": [],
    }

    for path, symbols in sorted(cited["files"].items()):
        if not (old.covers(path) and new.covers(path)):
            report["files"].append({
                "path": path, "state": "NO_TREE",
                "hint": "package not present in both trees — pass its tree with a second --old/--new to check it",
            })
            continue
        in_old, in_new = path in old.files, path in new.files
        if in_old and in_new:
            state = "UNCHANGED" if old.files[path] == new.files[path] else "CHANGED"
            hint = ""
        elif in_old and not in_new:
            moved = new.basenames(path.rsplit("/", 1)[-1])
            state = "MOVED_OR_DELETED"
            hint = f"same basename now at: {', '.join(moved)}" if moved else "no file with that basename in the new tree"
        elif not in_old and in_new:
            state = "ADDED_AFTER"
            hint = "path exists only in the new tree — the citation predates it or was written against another version"
        else:
            state = "BROKEN"
            hint = "path in neither tree — pre-existing bad citation"
        report["files"].append({"path": path, "state": state, "hint": hint})

        for sym in sorted(symbols):
            report["symbols"].append(classify_symbol(sym, path, old, new))

    for dotted in sorted(cited["modules"]):
        leaf = dotted.rsplit(".", 1)[-1]
        if leaf.startswith("__") and leaf.endswith("__"):
            continue  # `google.adk.__file__` and friends are snippets, not modules
        if not (old.covers(dotted) and new.covers(dotted)):
            report["modules"].append({"module": dotted, "state": "NO_TREE", "targets": []})
            continue
        o, n = old.module_targets(dotted), new.module_targets(dotted)
        if not o and not n:
            # Not a module: most likely a symbol re-exported from the parent
            # package, e.g. `google.adk.tools.exit_loop`.
            parent = dotted.rsplit(".", 1)[0]
            entry = classify_symbol(leaf, None, old, new)
            entry["hint"] = f"resolved as a symbol re-exported from {parent}; {entry['hint']}".strip("; ")
            report["symbols"].append(entry)
            continue
        if o and n:
            changed = any(old.files[p] != new.files[p] for p in n if p in old.files)
            state = "CHANGED" if changed else "UNCHANGED"
        elif o and not n:
            state = "MOVED_OR_DELETED"
        else:
            state = "ADDED_AFTER"
        report["modules"].append({"module": dotted, "state": state, "targets": n or o})

    cited_syms = {s["symbol"] for s in report["symbols"]}
    unknown: list[str] = []
    for ident in sorted(cited["idents"]):
        if ident in cited_syms:
            continue
        entry = classify_symbol(ident, None, old, new)
        if entry["state"] == "UNKNOWN":
            unknown.append(ident)
        else:
            report["symbols"].append(entry)
    report["unknown"] = unknown
    report["symbols"].sort(key=lambda s: (s["state"], s["symbol"]))
    return report


def classify_symbol(sym: str, path: str | None, old: Tree, new: Tree) -> dict:
    in_old, in_new = sym in old.defs, sym in new.defs
    if not in_old and not in_new:
        return {"symbol": sym, "path": path, "state": "UNKNOWN",
                "hint": "not defined in either ADK tree — not an ADK symbol, or a bad citation"}
    if not in_old and in_new:
        return {"symbol": sym, "path": path, "state": "ADDED_AFTER",
                "hint": "new in the target version"}
    if in_old and not in_new:
        state = "REMOVED" if sym not in new.tokens else "MOVED"
        hint = ("no definition and no textual occurrence left in the new tree"
                if state == "REMOVED" else "definition gone but the name still occurs — renamed, re-exported or now imported")
        return {"symbol": sym, "path": path, "state": state, "hint": hint}
    if path and path in new.files and path in old.files:
        if sym in old.defs_by_file.get(path, set()) and sym not in new.defs_by_file.get(path, set()):
            where = [p for p, names in new.defs_by_file.items() if sym in names]
            return {"symbol": sym, "path": path, "state": "MOVED",
                    "hint": f"no longer defined in the cited file; now in: {', '.join(where[:5]) or 'unknown'}"}
    return {"symbol": sym, "path": path, "state": "OK", "hint": ""}


def render(reports: list[dict], old: Tree, new: Tree, strict: bool) -> str:
    out: list[str] = [f"# ADK citation audit — {old.label} -> {new.label}", ""]
    interesting_files: set[str] = set()
    problems = 0

    for rep in reports:
        rows_f = [f for f in rep["files"] if f["state"] != "UNCHANGED"]
        rows_m = [m for m in rep["modules"] if m["state"] != "UNCHANGED"]
        rows_s = [s for s in rep["symbols"] if s["state"] != "OK"]
        clean = not rows_f and not rows_m and not rows_s and not (strict and rep["unknown"])
        out.append(f"## {rep['skill']} — {'clean' if clean else 'needs review'}")
        out.append("")
        if clean:
            out.append(f"{len(rep['files'])} cited files, {len(rep['symbols'])} checked symbols: no change.")
            out.append("")
            continue
        if rows_f:
            out.append("| cited file | state | note |")
            out.append("|---|---|---|")
            for f in rows_f:
                out.append(f"| `{f['path']}` | {f['state']} | {f['hint']} |")
                if f["state"] == "CHANGED":
                    interesting_files.add(f["path"])
                elif f["state"] != "NO_TREE":
                    problems += 1
            out.append("")
        if rows_m:
            out.append("| cited module | state | resolves to |")
            out.append("|---|---|---|")
            for m in rows_m:
                out.append(f"| `{m['module']}` | {m['state']} | {', '.join(m['targets']) or '-'} |")
                interesting_files.update(m["targets"])
                if m["state"] not in {"CHANGED", "NO_TREE"}:
                    problems += 1
            out.append("")
        if rows_s:
            out.append("| symbol | cited in | state | note |")
            out.append("|---|---|---|---|")
            for s in rows_s:
                out.append(f"| `{s['symbol']}` | {s['path'] or '-'} | {s['state']} | {s['hint']} |")
                problems += 1
            out.append("")
        if strict and rep["unknown"]:
            out.append(f"Unverifiable identifiers (not ADK-defined in either tree): {', '.join('`%s`' % u for u in rep['unknown'])}")
            out.append("")

    out.append("## Diffs to read")
    out.append("")
    if interesting_files:
        out.append("Cited files whose content changed — read these diffs before touching the skills:")
        out.append("")
        for path in sorted(interesting_files):
            out.append(f"- `{path}`")
    else:
        out.append("No cited file changed between the two trees.")
    out.append("")
    out.append(f"**{problems} finding(s) beyond plain content changes; {len(interesting_files)} changed cited file(s).**")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--old", required=True, type=Path, action="append",
                    help="tree of the version the skills were written against (repeatable)")
    ap.add_argument("--new", required=True, type=Path, action="append",
                    help="tree of the target version (repeatable)")
    ap.add_argument("--skills-dir", type=Path, default=DEFAULT_SKILLS_DIR,
                    help=f"directory holding the adk-* skill folders (default: {DEFAULT_SKILLS_DIR})")
    ap.add_argument("--skill", action="append", default=[], help="restrict to these skill names (repeatable)")
    ap.add_argument("--pattern", default="adk-*", help="glob for skill folders (default: adk-*)")
    ap.add_argument("--strict", action="store_true", help="also list identifiers not defined in either tree")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of markdown")
    args = ap.parse_args()

    old = Tree(args.old, ", ".join(p.name for p in args.old))
    new = Tree(args.new, ", ".join(p.name for p in args.new))

    skills_dir = args.skills_dir.expanduser().resolve()
    folders = sorted(p for p in skills_dir.glob(args.pattern) if (p / "SKILL.md").is_file())
    if args.skill:
        wanted = set(args.skill)
        folders = [p for p in folders if p.name in wanted]
    if not folders:
        raise SystemExit(f"error: no SKILL.md found under {skills_dir}/{args.pattern}")

    reports = [audit(p / "SKILL.md", old, new) for p in folders]
    if args.json:
        json.dump(
            {"old": [str(r) for r in old.roots], "new": [str(r) for r in new.roots], "reports": reports},
            sys.stdout, indent=2,
        )
        print()
    else:
        print(render(reports, old, new, args.strict))


if __name__ == "__main__":
    main()
