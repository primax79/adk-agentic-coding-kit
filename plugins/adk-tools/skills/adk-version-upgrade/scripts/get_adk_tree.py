#!/usr/bin/env python3
"""Materialize the source tree of a specific google-adk version.

Two sources, in preference order:

1. ``--git-repo`` — a local checkout of https://github.com/google/adk-python.
   Uses ``git archive <tag> src/google``, which never touches the checkout's
   working tree or HEAD (important: the working tree of a checkout is usually
   NOT at the tag you care about).
2. PyPI — ``pip download google-adk==<version> --no-deps`` and unzip the wheel.
   Used automatically when no ``--git-repo`` is given or the tag is missing.

Both paths normalize the output to the same layout::

    <dest>/google/adk/...
    <dest>/google/adk_community/...   (only when --package google-adk-community)

so that trees coming from different sources can be diffed against each other
and against an installed site-packages directory.

Examples::

    get_adk_tree.py --version 2.1.0 --dest /tmp/adk-2.1.0 \\
        --git-repo "$HOME/works/dave_agent/external tools/adk-python"
    get_adk_tree.py --version 2.6.1 --dest /tmp/adk-2.6.1      # via PyPI
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

PYPI_JSON = "https://pypi.org/pypi/{package}/json"


def die(msg: str) -> "None":
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(1)


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def latest_version(package: str, allow_pre: bool = False) -> str:
    """Latest version on PyPI. ``info.version`` is the latest stable release."""
    with urllib.request.urlopen(PYPI_JSON.format(package=package), timeout=30) as fh:
        data = json.load(fh)
    if not allow_pre:
        return data["info"]["version"]
    from packaging.version import Version  # type: ignore

    return str(max(Version(v) for v in data["releases"] if data["releases"][v]))


def resolve_tag(repo: Path, version: str) -> str | None:
    for tag in (f"v{version}", version):
        if run(["git", "-C", str(repo), "rev-parse", "--verify", f"{tag}^{{commit}}"]).returncode == 0:
            return tag
    return None


def from_git(repo: Path, version: str, dest: Path, fetch: bool) -> bool:
    if not (repo / ".git").exists():
        print(f"note: {repo} is not a git checkout, falling back to PyPI", file=sys.stderr)
        return False
    tag = resolve_tag(repo, version)
    if tag is None and fetch:
        print(f"note: tag for {version} not present locally, running git fetch --tags", file=sys.stderr)
        run(["git", "-C", str(repo), "fetch", "--tags", "--quiet"])
        tag = resolve_tag(repo, version)
    if tag is None:
        print(f"note: no tag v{version}/{version} in {repo}, falling back to PyPI", file=sys.stderr)
        return False

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        archive = tmpdir / "src.tar"
        with archive.open("wb") as fh:
            proc = subprocess.run(
                ["git", "-C", str(repo), "archive", tag, "src/google"],
                stdout=fh,
                stderr=subprocess.PIPE,
                text=False,
            )
        if proc.returncode != 0:
            print(f"note: git archive failed ({proc.stderr!r}), falling back to PyPI", file=sys.stderr)
            return False
        shutil.unpack_archive(str(archive), str(tmpdir / "x"), format="tar")
        src = tmpdir / "x" / "src" / "google"
        if not src.is_dir():
            print("note: archive had no src/google, falling back to PyPI", file=sys.stderr)
            return False
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest / "google", dirs_exist_ok=True)
    print(f"materialized {version} from {repo} tag {tag} -> {dest}")
    return True


def from_pypi(package: str, version: str, dest: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        proc = run(
            [sys.executable, "-m", "pip", "download", f"{package}=={version}",
             "--no-deps", "--only-binary", ":all:", "-d", str(tmpdir)]
        )
        if proc.returncode != 0:
            die(f"pip download failed:\n{proc.stdout}\n{proc.stderr}")
        wheels = sorted(tmpdir.glob("*.whl"))
        if not wheels:
            die(f"no wheel downloaded for {package}=={version}")
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(wheels[0]) as zf:
            for member in zf.namelist():
                if member.startswith("google/") and not member.endswith("/"):
                    zf.extract(member, dest)
    print(f"materialized {package}=={version} from PyPI wheel -> {dest}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", help="exact version, e.g. 2.6.1; omit with --latest")
    ap.add_argument("--latest", action="store_true", help="resolve the latest release from PyPI")
    ap.add_argument("--package", default="google-adk", choices=["google-adk", "google-adk-community"])
    ap.add_argument("--dest", required=True, type=Path)
    ap.add_argument("--git-repo", type=Path, help="local adk-python checkout to archive the tag from")
    ap.add_argument("--no-fetch", action="store_true", help="do not run git fetch --tags when the tag is missing")
    ap.add_argument("--force", action="store_true", help="overwrite a non-empty --dest")
    args = ap.parse_args()

    if not args.version and not args.latest:
        die("pass --version X.Y.Z or --latest")
    version = args.version or latest_version(args.package)

    dest: Path = args.dest.expanduser().resolve()
    if dest.exists() and any(dest.iterdir()):
        if not args.force:
            die(f"{dest} is not empty (use --force to overwrite)")
        shutil.rmtree(dest)

    ok = False
    if args.git_repo and args.package == "google-adk":
        ok = from_git(args.git_repo.expanduser(), version, dest, fetch=not args.no_fetch)
    if not ok:
        from_pypi(args.package, version, dest)

    marker = dest / "google" / ("adk" if args.package == "google-adk" else "adk_community")
    if not marker.is_dir():
        die(f"expected {marker} after materialization")
    print(f"version={version} tree={dest}")


if __name__ == "__main__":
    main()
