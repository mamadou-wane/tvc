#!/usr/bin/env python3
"""Refuse a tracked document that points at a gitignored path.

The engineering plan's rule: no public document points at an ignored or
unavailable governing document. A governing document in this repository is a
markdown file, so the scope is every token ending in ".md" inside a tracked
"*.md". Each token is resolved three ways, as written, against the containing
file's own directory, and against docs/, and every resolution is put to
git check-ignore. A hit exits 1 naming the file, the line, and the token.

Code blocks are scanned like prose. A path inside a fence is still a pointer a
reader will follow.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

TOKEN = re.compile(r"(?<![A-Za-z0-9_./-])((?:\.{1,2}/)*[A-Za-z0-9_][A-Za-z0-9_./-]*\.md)")


def _git(root, *args, stdin=None):
    return subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", root, *args],
        input=stdin, capture_output=True, text=True,
    )


def tracked_markdown(root):
    """Every tracked *.md, repo-relative, sorted."""
    out = _git(root, "ls-files", "-z", "*.md")
    if out.returncode != 0:
        raise SystemExit(f"check_public_paths: git ls-files failed: {out.stderr.strip()}")
    return sorted(p for p in out.stdout.split("\0") if p)


def resolutions(path, token):
    """The three ways a token can name a file, minus anything outside the repo."""
    here = os.path.dirname(path)
    out = []
    for cand in (token, os.path.join(here, token) if here else token,
                 os.path.join("docs", token)):
        norm = os.path.normpath(cand)
        if norm.startswith("..") or os.path.isabs(norm):
            continue
        if norm not in out:
            out.append(norm)
    return out


def scan(root, paths):
    """[(path, lineno, token, [resolution, ...])] over the given tracked files."""
    found = []
    for path in paths:
        with open(os.path.join(root, path), encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                for token in TOKEN.findall(line):
                    found.append((path, lineno, token, resolutions(path, token)))
    return found


def ignored(root, candidates):
    """The subset of candidates the repository's ignore rules match."""
    if not candidates:
        return set()
    out = _git(root, "check-ignore", "-z", "--stdin",
               stdin="\0".join(sorted(candidates)))
    if out.returncode not in (0, 1):
        raise SystemExit(f"check_public_paths: git check-ignore failed: {out.stderr.strip()}")
    return {p for p in out.stdout.split("\0") if p}


def violations(root="."):
    """[(path, lineno, token, resolution)], one per token that names an ignored path."""
    paths = tracked_markdown(root)
    found = scan(root, paths)
    bad_paths = ignored(root, {r for _, _, _, rs in found for r in rs})
    out = []
    for path, lineno, token, rs in found:
        hit = next((r for r in rs if r in bad_paths), None)
        if hit is not None:
            out.append((path, lineno, token, hit))
    return out


def main(argv=None):
    root = (argv or sys.argv[1:] or ["."])[0]
    paths = tracked_markdown(root)
    total = len(scan(root, paths))
    bad = violations(root)
    for path, lineno, token, hit in bad:
        print(f"{path}:{lineno}: {token} resolves to {hit}, which is gitignored",
              file=sys.stderr)
    if bad:
        print(f"check_public_paths: {len(bad)} tracked document(s) point at an "
              f"ignored path", file=sys.stderr)
        return 1
    print(f"check_public_paths: {total} .md tokens in {len(paths)} tracked "
          f"markdown files, 0 pointing at ignored paths")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
