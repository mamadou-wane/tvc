#!/usr/bin/env python3
"""Lint receive locations and the future free-run blocking-call boundary.

This scans C++ source spelling after blanking comments and literals. It is lint,
not a C++ parser or a reachability proof: aliases and macros can defeat it. Actual
descriptor tests and review remain necessary. A missing run_freerun is reported
as not applicable; fixtures exercise that rule before runtime integration.
"""

import argparse
import pathlib
import re
import sys


NON_CODE = re.compile(
    r'//[^\n]*(?:\\\n[^\n]*)*|/\*[\s\S]*?\*/'
    r'|(?:u8|u|U|L)?R"(?P<delimiter>[^ ()\\\t\r\n]{0,16})\([\s\S]*?\)(?P=delimiter)"'
    r'|(?:u8|u|U|L)?"(?:\\[\s\S]|[^"\\])*"'
    r"|(?<![\w])(?:u8|u|U|L)?'(?:\\[\s\S]|[^'\\\n])*'"
)
RECEIVE = re.compile(r"\b(recvmmsg|recvmsg|recvfrom|recv)\s*\(")
FUNCTION = re.compile(
    r"(?<![\w:])((?:::)?(?:[A-Za-z_]\w*::)*(?:recv_blocking|run_freerun))\s*\("
)
FUNCTION_BODY = re.compile(r"\s*(?:noexcept(?:\s*\([^;{}]*\))?\s*)?(?:->\s*[^;{}]+)?\s*\{")
NAMESPACE = re.compile(r"(?:inline\s+)?namespace(?:\s+([A-Za-z_]\w*(?:::[A-Za-z_]\w*)*))?\s*$")
BLOCKING = re.compile(
    r"\b(?:recv_blocking|poll|select|epoll\w*|sleep|sleep_for|sleep_until)\s*\(|\bSO_RCVTIMEO\b"
)
HOT_FLAGS = re.compile(r"(?:::)?(?:net::)?(?:MSG_DONTWAIT|kHotRecvFlags)")


def blank_non_code(source):
    """Preserve offsets and line numbers while removing misleading text."""
    return NON_CODE.sub(lambda match: re.sub(r"[^\n]", " ", match.group()), source)


def brace_pairs(source):
    stack, pairs = [], {}
    for index, char in enumerate(source):
        if char == "{":
            stack.append(index)
        elif char == "}":
            if not stack:
                raise ValueError(f"unmatched closing brace at line {source.count(chr(10), 0, index) + 1}")
            pairs[stack.pop()] = index
    if stack:
        raise ValueError(f"unmatched opening brace at line {source.count(chr(10), 0, stack[-1]) + 1}")
    return pairs


def closing_paren(source, opening):
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "(":
            depth += 1
        elif source[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError("unmatched receive/function parentheses")


def namespace_at(source, position, pairs):
    """Only namespace scopes can establish the exact net helper allowlist."""
    names = []
    for opening, closing in sorted(pairs.items()):
        if not opening < position < closing:
            continue
        boundary = max(source.rfind(token, 0, opening) for token in ";{}")
        match = NAMESPACE.search(source[boundary + 1:opening])
        if match is None:
            return None  # A class, function, or other scope is not namespace net.
        names.append(match.group(1) or "(anonymous)")
    return "::".join(names)


def function_bodies(source, pairs):
    bodies = []
    for match in FUNCTION.finditer(source):
        end = closing_paren(source, match.end() - 1)
        suffix = FUNCTION_BODY.match(source, end + 1)
        if suffix is None:
            continue  # A call or a prototype is not a function definition.
        opening = suffix.end() - 1
        scope = namespace_at(source, match.start(), pairs)
        name = match.group(1).removeprefix("::")
        qualified = "::".join(part for part in (scope, name) if part)
        if scope is None:
            qualified = "(other scope)::" + name
        bodies.append((qualified, opening, pairs[opening]))
    return bodies


def call_arguments(source, opening, closing):
    arguments, start, depth = [], opening + 1, 0
    for index in range(start, closing):
        char = source[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            arguments.append(source[start:index].strip())
            start = index + 1
    arguments.append(source[start:closing].strip())
    return arguments


def fixed_flags(argument):
    while argument.startswith("(") and closing_paren(argument, 0) == len(argument) - 1:
        argument = argument[1:-1].strip()
    return HOT_FLAGS.fullmatch(argument) is not None


def check_source(path, source):
    source = blank_non_code(source)
    pairs = brace_pairs(source)
    bodies = function_bodies(source, pairs)
    bad = []
    for match in RECEIVE.finditer(source):
        line = source.count("\n", 0, match.start()) + 1
        if path != "src/net.cpp":
            bad.append((line, f"{match.group(1)} receive must be inside src/net.cpp"))
            continue
        if any(name == "net::recv_blocking" and start < match.start() < end
               for name, start, end in bodies):
            continue
        end = closing_paren(source, match.end() - 1)
        args = call_arguments(source, match.end() - 1, end)
        flags_index = 2 if match.group(1) == "recvmsg" else 3
        if len(args) <= flags_index or not fixed_flags(args[flags_index]):
            bad.append((line, f"{match.group(1)} receive requires MSG_DONTWAIT or kHotRecvFlags"))
    freerun = 0
    for name, start, end in bodies:
        if name.split("::")[-1] != "run_freerun":
            continue
        freerun += 1
        for match in BLOCKING.finditer(source, start + 1, end):
            line = source.count("\n", 0, match.start()) + 1
            operation = match.group().split("(", 1)[0].strip()
            bad.append((line, f"{operation} is forbidden inside run_freerun"))
    return sorted(bad), freerun


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".", type=pathlib.Path,
                        help="repository root (default: current directory)")
    root = parser.parse_args(argv).root
    src = root / "src"
    if not src.is_dir():
        print("check_nonblocking: src directory is missing", file=sys.stderr)
        return 1
    failures, freerun, files = 0, 0, 0
    for file in sorted(path for path in src.rglob("*") if path.is_file()):
        path = file.relative_to(root).as_posix()
        files += 1
        try:
            bad, count = check_source(path, file.read_text(encoding="utf-8"))
            freerun += count
        except (OSError, UnicodeError, ValueError) as error:
            bad = [(1, f"cannot check source: {error}")]
        for line, message in bad:
            print(f"{path}:{line}: {message}", file=sys.stderr)
        failures += len(bad)
    applicability = (f"{freerun} run_freerun body/bodies checked" if freerun
                     else "run_freerun not applicable (function absent)")
    print(f"check_nonblocking: {files} source files, {failures} violation(s); {applicability}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
