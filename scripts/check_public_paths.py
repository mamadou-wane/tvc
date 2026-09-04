#!/usr/bin/env python3
"""Refuse a tracked document that points at an ignored or unavailable path.

The engineering plan's rule, turned into a command. A governing document in this
repository is a markdown file, so the scope is every token ending in ".md" inside
a tracked "*.md", plus every local target of a markdown link in one. Two things
are refused:

  ignored      the target resolves to a path the repository's ignore rules match
  unavailable  the target resolves to nothing tracked: missing, or present in the
               working tree and never committed

Every ".md" token is resolved three ways, as written, against the containing
file's own directory, and against docs/, because a document names a sibling by
bare filename as readily as by full path. A markdown link target is resolved
against the containing file's directory alone, because a link is unambiguous.

Code blocks are scanned like prose. A path inside a fence is still a pointer a
reader will follow.
"""

from __future__ import annotations

import collections
import os
import re
import subprocess
import sys

TOKEN = re.compile(r"(?<![A-Za-z0-9_./-])((?:\.{1,2}/)*[A-Za-z0-9_][A-Za-z0-9_./-]*\.md)")
LINK = re.compile(r"]\(([^)\s]+)")
EXTERNAL = ("http://", "https://", "mailto:", "//")

Violation = collections.namedtuple("Violation", "path line target kind detail")


def _git(root, *args, stdin=None):
    return subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", root, *args],
        input=stdin, capture_output=True, text=True,
    )


def tracked(root):
    """Every tracked path, repo-relative."""
    out = _git(root, "ls-files", "-z")
    if out.returncode != 0:
        raise SystemExit(f"check_public_paths: git ls-files failed: {out.stderr.strip()}")
    return {p for p in out.stdout.split("\0") if p}


def _norm(*parts):
    n = os.path.normpath(os.path.join(*parts))
    return None if n.startswith("..") or os.path.isabs(n) else n


def resolutions(path, token):
    """The three ways a bare token can name a file, minus anything outside the repo."""
    here = os.path.dirname(path)
    out = []
    for cand in (_norm(token), _norm(here, token) if here else _norm(token),
                 _norm("docs", token)):
        if cand and cand not in out:
            out.append(cand)
    return out


def is_available(cand, tracked_paths):
    """A tracked file, or a tracked directory."""
    c = cand.rstrip("/")
    return c in tracked_paths or any(p.startswith(c + "/") for p in tracked_paths)


def targets(root, paths):
    """[(path, lineno, target, [resolution, ...], require_tracked_dir_ok)]."""
    out = []
    for path in paths:
        with open(os.path.join(root, path), encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                for token in TOKEN.findall(line):
                    out.append((path, lineno, token, resolutions(path, token)))
                for link in LINK.findall(line):
                    target = link.split("#")[0]
                    if not target or target.startswith(EXTERNAL):
                        continue          # external URL, or an anchor-only link
                    if target.endswith(".md"):
                        continue          # already covered by the token rule
                    here = os.path.dirname(path)
                    cand = _norm(here, target) if here else _norm(target)
                    out.append((path, lineno, target, [cand] if cand else []))
    return out


def ignored(root, candidates):
    """The subset of candidates the repository's ignore rules match."""
    if not candidates:
        return set()
    out = _git(root, "check-ignore", "-z", "--stdin", stdin="\0".join(sorted(candidates)))
    if out.returncode not in (0, 1):
        raise SystemExit(f"check_public_paths: git check-ignore failed: {out.stderr.strip()}")
    return {p for p in out.stdout.split("\0") if p}


def violations(root="."):
    """Every tracked-document pointer that is ignored or unavailable."""
    tracked_paths = tracked(root)
    found = targets(root, sorted(p for p in tracked_paths if p.endswith(".md")))
    bad_paths = ignored(root, {r for _, _, _, rs in found for r in rs})
    out = []
    for path, lineno, target, rs in found:
        hit = next((r for r in rs if r in bad_paths), None)
        if hit is not None:
            out.append(Violation(path, lineno, target, "ignored",
                                 f"resolves to {hit}, which is gitignored"))
        elif not any(is_available(r, tracked_paths) for r in rs):
            out.append(Violation(path, lineno, target, "unavailable",
                                 "resolves to nothing tracked"))
    return out


def main(argv=None):
    root = (argv or sys.argv[1:] or ["."])[0]
    tracked_paths = tracked(root)
    md = sorted(p for p in tracked_paths if p.endswith(".md"))
    total = len(targets(root, md))
    bad = violations(root)
    for v in bad:
        print(f"{v.path}:{v.line}: {v.target} {v.detail}", file=sys.stderr)
    if bad:
        n_ign = sum(1 for v in bad if v.kind == "ignored")
        print(f"check_public_paths: {n_ign} ignored and {len(bad) - n_ign} unavailable "
              f"target(s) in tracked documents", file=sys.stderr)
        return 1
    print(f"check_public_paths: {total} local targets in {len(md)} tracked markdown "
          f"files, 0 ignored and 0 unavailable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
