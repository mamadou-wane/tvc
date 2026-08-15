# Founding commit + v0.1 week 1 implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the tvc repo with its AI-workflow evidence trail, then land the measurement harness as a reviewed PR series with every week-1 fix from the 2026-08-14 stress test.

**Architecture:** One public monorepo. The harness imports verbatim as a baseline PR, then six focused PRs fix measurement semantics (CO removal), rt_setup prefaulting, the alloc guard, the timing loop, sweep/plot behavior, and the docs. Functional verification runs in a Linux container on the Mac (the ProBook is still on Windows this week); no timing claims come from the container.

**Tech Stack:** C++20, CMake, HdrHistogram_c 0.11.8 (FetchContent), Python 3 stdlib (`unittest`, no pip deps), Docker (ubuntu:24.04), gh CLI.

**Spec:** `docs/superpowers/specs/2026-08-14-tvc-restructure-design.md`

## Global constraints

- Build flags: `-O2 -g -fno-omit-frame-pointer -ffp-contract=off -Wall -Wextra -Wpedantic`; never `-ffast-math`. C++20, extensions off.
- `CLOCK_MONOTONIC` only. The record() path stays allocation-free.
- Commit subjects: short, imperative, lowercase, no bodies, no AI attribution, no Co-Authored-By. Example: `replace corrected jitter series with naive-measurement series`.
- Every PR description ends with the AI-assistance section defined in AGENTS.md. After Mamadou merges a PR, a `docs/ai-log/NNNN-slug.md` entry is committed to main (template in AGENTS.md).
- Mamadou reviews and merges every PR himself. Executor opens PRs and stops; never merge.
- Prose rules for all docs: no em dashes, sentence-case headings, the banned-word list in the global CLAUDE.md applies.
- Container runs are functional only. Any output used in a published figure must come from the ProBook (not this week).
- All commands below run from the repo root `/Users/wane/projects/tvc` unless stated.

---

### Task 1: Founding commit

**Files:**
- Create: `.gitignore`, `LICENSE`, `README.md`, `AGENTS.md`, `CLAUDE.md`, `docs/adr/000-agent-roles.md`, `docs/ai-log/0001-pre-repo-planning.md`
- Already present, committed as-is: `docs/superpowers/specs/2026-08-14-tvc-restructure-design.md`, `docs/superpowers/plans/2026-08-14-founding-and-week1.md`

**Interfaces:**
- Produces: the review protocol and PR/ai-log templates every later task follows.

- [ ] **Step 1: Initialize the repo**

```bash
cd /Users/wane/projects/tvc
git init -b main
```

- [ ] **Step 2: Write `.gitignore`**

```
build/
build-asan/
results/
__pycache__/
.DS_Store
```

- [ ] **Step 3: Write `LICENSE`** (MIT)

```
MIT License

Copyright (c) 2026 Mamadou Wane

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 4: Write `README.md`** (skeleton; the CDF and results land in week 3)

```markdown
# One-Axis TVC

A hard real-time control and telemetry stack: a 500 Hz C++20 control loop on
Linux, measured as a latency distribution, with a Python ground station,
simulation, and fault injection to follow.

Status: v0.1 in progress. This repo currently contains the measurement
harness and its methodology. The headline artifact, a p99.9 wakeup-jitter
CDF with per-mitigation attribution, ships with v0.1.

## Layout

    src/         control-cycle timing harness (C++20)
    scripts/     campaign runner and plotting
    tests/       functional and unit tests (container-run for C++)
    docs/        methodology, plan, ADRs, AI log

## Build and test

Measurement runs happen on bare-metal Linux only. Functional builds and
tests run anywhere Docker does:

    docker build -t tvc-dev docker/
    docker run --rm -v "$PWD":/w -w /w --cap-add=IPC_LOCK \
      --ulimit memlock=-1:-1 tvc-dev bash tests/ci.sh

## Working with AI

This project is deliberately built with AI agents as collaborators: Claude
Code for real-time-sensitive C++ and review, OpenAI Codex for well-specified
subtasks. Every merged PR carries an AI-assistance disclosure in its
description and a matching entry in docs/ai-log/. Roles and review protocol
are defined in docs/adr/000-agent-roles.md. All agent output is
human-reviewed before merge, and agent proposals are accepted or rejected
against measurements.
```

- [ ] **Step 5: Write `AGENTS.md`**

```markdown
# Agent instructions

Shared instructions for all AI agents (Claude Code, Codex) working in this
repo. CLAUDE.md layers Claude-specific notes on top of this file.

## What this project is

A real-time control loop measurement stack. The product is published
numbers; anything that could corrupt a number is a bug of the highest
severity. Full design: docs/superpowers/specs/2026-08-14-tvc-restructure-design.md.

## Build and test

    docker build -t tvc-dev docker/          # once
    docker run --rm -v "$PWD":/w -w /w --cap-add=IPC_LOCK \
      --ulimit memlock=-1:-1 tvc-dev bash tests/ci.sh

tests/ci.sh builds normal and ASan/UBSan trees and runs all tests. Python
unit tests also run natively: python3 -m unittest discover -s tests/unit.
Container output is functional only; never quote timing numbers from it.

## Real-time invariants

- No allocation, locks, blocking syscalls, or formatted I/O inside the
  control cycle. The alloc guard enforces the allocator part at runtime.
- CLOCK_MONOTONIC only. Never CLOCK_REALTIME, never
  std::chrono::high_resolution_clock.
- Deadlines derive from a single origin (origin + n * period), never from
  now + period.
- Measurement semantics: the harness is coordinated-omission-free by
  construction; do not add "corrected" series.
- Failed mitigations must fail loudly: nonzero exit, applied config
  recorded in summary.json.

## Roles and review

- Codex: well-specified, testable subtasks (scripts, codecs, plotting).
- Claude Code: RT-sensitive C++; reviews Codex output.
- Codex does not review Claude output (see docs/adr/000-agent-roles.md).
- Mamadou reviews everything and owns every merge. Open PRs; never merge,
  never push to main except ai-log entries after a merge.

## Style

- Commit subjects: short, imperative, lowercase, no bodies, no AI
  attribution of any kind.
- Prose: no em dashes, sentence-case headings, concrete over abstract.
- C++ matches the existing files: 4-space indent, trailing return rare,
  comments state constraints, not narration.

## PR description template

Every PR body ends with:

    ## AI assistance
    - Agent: <Claude Code (model) | Codex (model) | none>
    - Scope: <what the agent produced>
    - Human changes: <what was modified or rejected, and why>
    - Verification: <commands run and their result>

## AI log ritual

After a PR merges, commit docs/ai-log/NNNN-slug.md to main (next NNNN in
sequence):

    # NNNN: <task>
    Date: YYYY-MM-DD
    PR: #N (merge SHA)
    Agent: <agent and model>
    Produced: <what the agent wrote>
    Human: <what was changed or rejected, and why>
    Verification: <what proved it correct>
```

- [ ] **Step 6: Write `CLAUDE.md`**

```markdown
# Claude instructions

Read AGENTS.md first; it is the source of truth for build, invariants,
roles, and rituals. This file adds only what is Claude-specific.

- The global ~/.claude/CLAUDE.md writing and git rules apply, with one
  project carve-out, chosen deliberately: PR descriptions here MUST carry
  the AI-assistance section from AGENTS.md. Commit subjects stay clean.
- You are the reviewer for Codex output in this repo. Review against the
  RT invariants and the spec, and verify claims by running tests, not by
  reading alone.
- When a proposal can be settled by a measurement, run the measurement.
  Record who was right in the ai-log entry.
```

- [ ] **Step 7: Write `docs/adr/000-agent-roles.md`**

```markdown
# ADR-000: agent roles and review direction

Date: 2026-08-14. Status: accepted.

## Context

The project uses two coding agents. The obvious symmetric setup (each
reviews the other) is contradicted by the one controlled study on this
pair: arXiv 2607.21656 (116 tasks) found Claude reviewing Codex raised
task pass rates from 71.6% to 89.7%, while Codex reviewing Claude lowered
them from 91.4% to 82.8%.

## Decision

- Codex implements well-specified, testable subtasks: scripts, codecs,
  plotting, schema work.
- Claude Code implements RT-sensitive C++ and reviews all Codex output.
- The reverse review direction is not used.
- Mamadou reviews everything and performs every merge.
- Each PR records which agent authored it, so the division is auditable.

## Consequences

Claude review time becomes the bottleneck on Codex-authored work. Codex
gets no automated reviewer for its reviews of nothing; the human review
is the only gate on Claude-authored C++, so those PRs stay small.
```

- [ ] **Step 8: Write `docs/ai-log/0001-pre-repo-planning.md`**

```markdown
# 0001: pre-repo planning and stress test

Date: 2026-08-14
PR: none (pre-repo)
Agent: Claude Code (Fable 5); earlier drafting sessions also used Claude

Produced: the two draft documents (project overview, phased plan) and the
measurement harness were drafted in collaboration with Claude before this
repo existed. On 2026-08-14 a 15-agent adversarial review (7 lenses,
independent verification of every candidate blocker) produced 103
findings, 7 confirmed blockers, and 1 refuted finding, then the approved
restructure spec in docs/superpowers/specs/.

Human: chose the project, the two goals, and the hardware; set the 3-week
v0.1 target; approved the PR-body attribution carve-out; approved the spec
after review. The stress test rejected several claims in the human- and
AI-authored drafts alike (CI jitter gate on VMs, misapplied coordinated
omission correction, undesigned TMR input alignment, SMT-blind core
isolation); the week-1 PR series fixes them.

Verification: findings were adversarially verified by independent agents
against the documents, the code, and primary sources before being acted on.
```

- [ ] **Step 9: Commit and publish**

```bash
git add -A
git commit -m "add repo skeleton, agent policy, and founding ai log"
```

Confirm with Mamadou before this next command (it makes the repo public), then:

```bash
gh repo create tvc --public --source . --push
```

---

### Task 2: PR #1, harness import baseline

**Files:**
- Create: `CMakeLists.txt`, `src/main.cpp`, `src/loop_stats.{cpp,hpp}`, `src/alloc_guard.{cpp,hpp}`, `src/rt_setup.{cpp,hpp}`, `scripts/sweep.py`, `scripts/plot_jitter.py` (verbatim from the zip), `docs/methodology.md` (verbatim copy of the harness README), `docker/Dockerfile.dev`, `tests/ci.sh`

**Interfaces:**
- Produces: the reviewed baseline every fix PR diffs against; the container build loop (`tvc-dev` image, `tests/ci.sh`).

- [ ] **Step 1: Branch and import**

```bash
git switch -c harness-import
unzip -o "$HOME/Desktop/Measurement-Harness/tvc-harness.zip" -d /tmp/tvc-import
cp -R /tmp/tvc-import/tvc-harness/src /tmp/tvc-import/tvc-harness/scripts .
cp /tmp/tvc-import/tvc-harness/CMakeLists.txt .
cp /tmp/tvc-import/tvc-harness/README.md docs/methodology.md
```

Import verbatim; every fix arrives in a later, reviewable diff.

- [ ] **Step 2: Write `docker/Dockerfile.dev`**

```dockerfile
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends \
    g++ cmake git ca-certificates python3 python3-matplotlib make \
    && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 3: Write `tests/ci.sh`**

```bash
#!/usr/bin/env bash
# Functional gate. Runs inside the tvc-dev container. Never a timing source.
set -euo pipefail
cmake -S . -B build && cmake --build build -j
if [ -d tests/unit ]; then python3 -m unittest discover -s tests/unit -v; fi
if [ -d tests/functional ]; then
  TVC_BIN="$PWD/build/tvc_harness" python3 -m unittest discover -s tests/functional -v
fi
cmake -S . -B build-asan -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DCMAKE_CXX_FLAGS="-fsanitize=address,undefined -fno-sanitize-recover=all"
cmake --build build-asan -j
if [ -d tests/functional ]; then
  TVC_BIN="$PWD/build-asan/tvc_harness" python3 -m unittest discover -s tests/functional -v
fi
echo "ci.sh: all green"
```

`chmod +x tests/ci.sh`.

- [ ] **Step 4: Verify the container build**

```bash
docker build -t tvc-dev docker/
docker run --rm -v "$PWD":/w -w /w --cap-add=IPC_LOCK --ulimit memlock=-1:-1 tvc-dev bash tests/ci.sh
```

Expected: both builds succeed, "ci.sh: all green" (no test dirs yet).

- [ ] **Step 5: Commit and open the PR**

```bash
git add -A
git commit -m "import measurement harness as reviewed baseline"
git push -u origin harness-import
gh pr create --title "Import measurement harness baseline" --body "$(cat <<'EOF'
Verbatim import of the pre-repo measurement harness plus the container
build loop. No fixes in this PR; the week-1 series lands each fix as its
own diff against this baseline. Provenance: the harness was drafted in
collaboration with Claude before the repo existed (see docs/ai-log/0001).

## AI assistance
- Agent: Claude Code (Fable 5) drafted the imported harness pre-repo; import itself mechanical
- Scope: all imported source; Dockerfile and ci.sh written this PR
- Human changes: none in this PR by design; review gates the baseline
- Verification: container build green, both trees (normal, ASan/UBSan)
EOF
)"
```

Stop. Mamadou reviews and merges. After merge: write `docs/ai-log/0002-harness-import.md` per the AGENTS.md template (PR #1, merge SHA from `gh pr view 1 --json mergeCommit`), commit to main with subject `add ai log entry 0002`.

---

### Task 3: PR #2, measurement semantics (CO removal, naive series, hdr checks, build hardening)

**Files:**
- Modify: `src/loop_stats.hpp`, `src/loop_stats.cpp`, `src/main.cpp` (call site + console text), `scripts/sweep.py` (JSON key), `scripts/plot_jitter.py` (series names, flag), `CMakeLists.txt`
- Create: `tests/functional/test_summary.py`

**Interfaces:**
- Consumes: baseline from Task 2.
- Produces: `LoopStats::record(std::int64_t jitter_ns, std::int64_t naive_ns, std::int64_t exec_ns)`; `Summary` fields `naive_p999_ns` and `dropped` (replacing `co_p999_ns`); output files `<label>.jitter.csv`, `<label>.jitter_naive.csv`, `<label>.exec.csv`; summary.json keys `jitter_us.p99.9_naive` (replacing `p99.9_corrected`) and top-level `dropped_samples`. Task 6 relies on these exact names.

- [ ] **Step 1: Write the failing functional test** `tests/functional/test_summary.py`

```python
import json, os, pathlib, subprocess, tempfile, unittest

BIN = os.environ["TVC_BIN"]

def run(*extra, cwd):
    return subprocess.run(
        [BIN, "--label=t", f"--out={cwd}", "--rate=1000",
         "--cycles=2000", "--warmup=100", *extra],
        capture_output=True, text=True)

class SummaryOutputs(unittest.TestCase):
    def test_files_and_keys(self):
        with tempfile.TemporaryDirectory() as d:
            p = run(cwd=d)
            self.assertEqual(p.returncode, 0, p.stderr)
            for suffix in ("jitter", "jitter_naive", "exec"):
                self.assertTrue((pathlib.Path(d) / f"t.{suffix}.csv").exists(),
                                f"missing t.{suffix}.csv")
            s = json.loads((pathlib.Path(d) / "t.summary.json").read_text())
            self.assertIn("p99.9_naive", s["jitter_us"])
            self.assertNotIn("p99.9_corrected", s["jitter_us"])
            self.assertEqual(s["dropped_samples"], 0)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
git switch main && git pull && git switch -c stats-semantics
docker run --rm -v "$PWD":/w -w /w --cap-add=IPC_LOCK --ulimit memlock=-1:-1 tvc-dev bash tests/ci.sh
```

Expected: FAIL (files are named `t.jitter_raw.csv`, key is `p99.9_corrected`).

- [ ] **Step 3: Implement**

`src/loop_stats.hpp`: replace the header comment paragraph about the corrected series (lines 13-17) with:

```cpp
// Jitter is measured against absolute deadlines derived from a fixed origin,
// so every cycle produces exactly one sample and nothing is ever omitted:
// this design is coordinated-omission-free by construction. A second series,
// jitter_naive, records what a self-referencing measurement (previous wakeup
// + period) would have seen; the gap between the two is the CO demonstration
// for the writeup, and the naive series is never the published number.
```

In `Summary`: replace `std::int64_t co_p999_ns = 0;` with

```cpp
    std::int64_t naive_p999_ns  = 0;   // self-referenced measurement, demo only
    std::int64_t dropped        = 0;   // samples outside histogram range
```

Replace the `record` declaration and the `note_missed` comment:

```cpp
    // Hot path. Allocation-free, no syscalls, no locks.
    void record(std::int64_t jitter_ns, std::int64_t naive_ns,
                std::int64_t exec_ns) noexcept;

    // Counted in addition to the cycle's histogram sample: the cycle finished
    // after its successor's deadline, so the schedule slipped a full period.
    void note_missed() noexcept { missed_++; }
```

Rename member `jitter_co_` to `jitter_naive_` and add `std::int64_t dropped_ = 0;`.

`src/loop_stats.cpp`: in the constructor, check every init:

```cpp
LoopStats::LoopStats(std::int64_t period_ns) : period_ns_(period_ns) {
    if (hdr_init(kLowest, kHighest, kSigFigs, &jitter_raw_) != 0 ||
        hdr_init(kLowest, kHighest, kSigFigs, &jitter_naive_) != 0 ||
        hdr_init(kLowest, kHighest, kSigFigs, &exec_) != 0) {
        std::fputs("loop_stats: hdr_init failed\n", stderr);
        std::abort();
    }
}
```

Replace `record`:

```cpp
void LoopStats::record(std::int64_t jitter_ns, std::int64_t naive_ns,
                       std::int64_t exec_ns) noexcept {
    if (!seen_ || jitter_ns < min_signed_) { min_signed_ = jitter_ns; seen_ = true; }
    if (jitter_ns < 0) early_++;

    // HdrHistogram cannot hold negatives; clamp to the floor.
    const std::int64_t j = jitter_ns < 1 ? 1 : jitter_ns;
    const std::int64_t n = naive_ns  < 1 ? 1 : naive_ns;

    if (!hdr_record_value(jitter_raw_, j))   dropped_++;
    if (!hdr_record_value(jitter_naive_, n)) dropped_++;
    if (!hdr_record_value(exec_, exec_ns < 1 ? 1 : exec_ns)) dropped_++;
}
```

In `summary()`: `s.naive_p999_ns = hdr_value_at_percentile(jitter_naive_, 99.9); s.dropped = dropped_;` (delete the `co_p999_ns` line). In `reset()`: reset `jitter_naive_`, `dropped_ = 0`. In `write_csv`, the series table becomes:

```cpp
    const Series series[] = {
        {"jitter",       jitter_raw_},
        {"jitter_naive", jitter_naive_},
        {"exec",         exec_},
    };
```

In `write_json`, replace the `"p99.9_corrected"` line and add dropped:

```cpp
        "    \"p99.9_naive\": %.3f\n"
        "  },\n"
        "  \"dropped_samples\": %" PRId64 ",\n"
```

(with `us(s.naive_p999_ns), s.dropped` in the argument list, keeping order matched to the format string).

`src/main.cpp`: track the previous wakeup and pass the naive series. Before the loop add `std::int64_t prev_woke = 0;`. After `const std::int64_t woke = now_ns();` add:

```cpp
        const std::int64_t naive_jitter =
            prev_woke ? woke - (prev_woke + period_ns) : 0;
        prev_woke = woke;
```

Change the record call to `stats.record(woke - deadline, naive_jitter, done - woke);`. Replace the corrected-ratio console block (the `printf("    p99.9 corrected for coordinated omission: ...` lines) with:

```cpp
    std::printf("    p99.9 as a naive self-referenced measurement would report it: %.1f\n",
                us(s.naive_p999_ns));
    if (s.dropped > 0)
        std::printf("    WARNING: %" PRId64 " samples outside histogram range\n", s.dropped);
```

Update the final "wrote" message to name `{jitter,jitter_naive,exec}`.

`scripts/sweep.py`: in the table header change `'p99.9 CO':>10` to `'p99.9 nv':>10` and in the row change `j['p99.9_corrected']` to `j['p99.9_naive']`.

`scripts/plot_jitter.py`: replace `--corrected` with `--naive` (`help="plot the self-referenced naive-measurement series (CO demo)"`); `series = "jitter_naive" if args.naive else "jitter"`; the summary key `"p99.9_naive" if args.naive else "p99.9"`; title suffix `"  ·  naive self-referenced measurement"`; default out name `jitter_naive.svg`; and rewrite the docstring paragraph that says "The gap between them is a real result, not an artifact" to:

```
--naive plots what a self-referencing measurement (previous wakeup + period)
would have reported. The primary series is coordinated-omission-free by
construction; the naive series exists to demonstrate what CO hides.
```

`CMakeLists.txt`: append to the flags line so it reads

```cmake
set(CMAKE_CXX_FLAGS_RELWITHDEBINFO "-O2 -g -fno-omit-frame-pointer -ffp-contract=off")
```

replace the fast-math comment with

```cmake
# -ffast-math is deliberately absent and -ffp-contract=off is set: both can
# change bit-level results across builds, which breaks replay goldens.
```

and add after `project(...)`:

```cmake
if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
  message(FATAL_ERROR "Linux-only: clock_nanosleep/SCHED_FIFO/sched_setaffinity. Build in the tvc-dev container on other hosts.")
endif()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker run --rm -v "$PWD":/w -w /w --cap-add=IPC_LOCK --ulimit memlock=-1:-1 tvc-dev bash tests/ci.sh
```

Expected: PASS in both trees.

- [ ] **Step 5: Commit and open the PR**

```bash
git add -A
git commit -m "replace corrected jitter series with naive-measurement series"
git push -u origin stats-semantics
gh pr create --title "Fix coordinated-omission semantics" --body "$(cat <<'EOF'
The harness measures every cycle against a fixed absolute origin, so it is
CO-free by construction; hdr_record_corrected_value was double-counting
stalls (stress-test blocker B2). The corrected series is removed. A naive
self-referenced series replaces it as an explicit demo of what CO hides,
never as a published number. Also: hdr_init/hdr_record_value returns
checked with a dropped-sample counter, missed-cycle wording unified with
the code, -ffp-contract=off, and a fatal CMake check on non-Linux hosts.

## AI assistance
- Agent: Claude Code (Fable 5)
- Scope: full diff
- Human changes: <filled at review>
- Verification: tests/ci.sh green in normal and ASan/UBSan trees
EOF
)"
```

Stop for review. After merge: `docs/ai-log/0003-stats-semantics.md`, commit `add ai log entry 0003`.

---

### Task 4: PR #3, rt_setup prefaulting that actually happens

**Files:**
- Modify: `src/rt_setup.cpp`
- Create: `tests/functional/test_mlock.py`

**Interfaces:**
- Consumes: `rt::lock_memory(std::size_t stack_bytes, std::size_t heap_bytes)` signature (unchanged).
- Produces: same signature; `Result.detail` now reports the prefaulted stack budget and the post-warm minor-fault delta.

- [ ] **Step 1: Write the failing test** `tests/functional/test_mlock.py`

```python
import os, subprocess, tempfile, unittest

BIN = os.environ["TVC_BIN"]

class MlockPrefault(unittest.TestCase):
    def test_mlock_survives_default_stack_ulimit(self):
        with tempfile.TemporaryDirectory() as d:
            p = subprocess.run(
                ["bash", "-c",
                 f"ulimit -s 8192; exec {BIN} --label=m --out={d} "
                 "--rate=1000 --cycles=500 --warmup=50 --mlock"],
                capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
            self.assertIn("mlock      ok", p.stdout)
            self.assertIn("prefaulted", p.stdout)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify current behavior**

```bash
git switch main && git pull && git switch -c rt-prefault
docker run --rm -v "$PWD":/w -w /w --cap-add=IPC_LOCK --ulimit memlock=-1:-1 tvc-dev bash tests/ci.sh
```

Expected: at -O2 the recursion is compiled to a loop, so the test may pass by accident; the assertion on "prefaulted" (new detail text) fails either way. Confirm FAIL.

- [ ] **Step 3: Implement** in `src/rt_setup.cpp`

Add includes `<alloca.h>`, `<sys/resource.h>`, `<sys/time.h>`. Replace `prefault_stack` (lines 20-31) with:

```cpp
// Touch a stack region in one live frame. alloca plus an asm barrier so the
// optimizer can neither elide the touch nor turn this into anything else.
[[gnu::noinline]] void prefault_stack(std::size_t bytes) {
    if (bytes == 0) return;
    unsigned char* p = static_cast<unsigned char*>(::alloca(bytes));
    std::memset(p, 0, bytes);
    __asm__ __volatile__("" ::"r"(p) : "memory");
}

std::size_t stack_budget(std::size_t requested) {
    rlimit rl{};
    if (::getrlimit(RLIMIT_STACK, &rl) != 0 || rl.rlim_cur == RLIM_INFINITY)
        return requested;
    // Half the limit: main() and callees already own part of the stack.
    const std::size_t cap = static_cast<std::size_t>(rl.rlim_cur) / 2;
    return requested < cap ? requested : cap;
}
```

Replace `lock_memory` with:

```cpp
Result lock_memory(std::size_t stack_bytes, std::size_t heap_bytes) {
    Result r;
    if (::mlockall(MCL_CURRENT | MCL_FUTURE) != 0) {
        r.detail = errno_str("mlockall");
        return r;
    }
    const std::size_t budget = stack_budget(stack_bytes);
    prefault_stack(budget);

    // Keep freed memory in the arena instead of returning it to the kernel,
    // then warm the arena to its working size. Without these mallopt calls a
    // large warm block is served by mmap and munmapped on free (man mallopt),
    // and the "prefault" buys nothing.
    if (heap_bytes) {
        ::mallopt(M_TRIM_THRESHOLD, -1);
        ::mallopt(M_MMAP_MAX, 0);
        std::vector<unsigned char> warm(heap_bytes);
        for (std::size_t i = 0; i < heap_bytes; i += 4096) warm[i] = 1;
    }

    // Prove it: allocating and touching again should fault nearly nothing.
    rusage before{}, after{};
    ::getrusage(RUSAGE_SELF, &before);
    if (heap_bytes) {
        std::vector<unsigned char> check(heap_bytes / 2);
        for (std::size_t i = 0; i < check.size(); i += 4096) check[i] = 1;
    }
    ::getrusage(RUSAGE_SELF, &after);

    r.ok = true;
    r.detail = "prefaulted " + std::to_string(budget >> 20) + " MiB stack, " +
               std::to_string(heap_bytes >> 20) + " MiB heap; recheck minor faults: " +
               std::to_string(after.ru_minflt - before.ru_minflt);
    return r;
}
```

Add `<malloc.h>` and `<vector>` includes (vector already present).

- [ ] **Step 4: Run tests to verify they pass**

Same container command. Expected: PASS; the printed recheck fault count is near zero.

- [ ] **Step 5: Commit and open the PR**

```bash
git add -A
git commit -m "make stack and heap prefault real and self-verifying"
git push -u origin rt-prefault
gh pr create --title "Fix rt_setup prefaulting" --body "$(cat <<'EOF'
The recursive stack prefault was compiled to a single reused frame at -O2
(no-op) and overflowed the default 8 MiB rlimit at -O0; the 64 MiB heap
warm block was above the mmap threshold and returned to the kernel on free
(stress-test findings). Replaced with a bounded alloca touch and the
standard mallopt arena recipe, with a minor-fault recheck reported in the
mlock status line.

## AI assistance
- Agent: Claude Code (Fable 5)
- Scope: full diff
- Human changes: <filled at review>
- Verification: tests/ci.sh green; test_mlock runs under ulimit -s 8192
EOF
)"
```

Stop for review. After merge: `docs/ai-log/0004-rt-prefault.md`, commit `add ai log entry 0004`.

---

### Task 5: PR #4, alloc guard thread safety

**Files:**
- Modify: `src/alloc_guard.cpp`
- Create: `tests/functional/test_alloc_guard.py`

**Interfaces:**
- Consumes/produces: `guard::set_mode`, `guard::tally` signatures unchanged.

- [ ] **Step 1: Write the failing test** `tests/functional/test_alloc_guard.py`

```python
import os, subprocess, tempfile, unittest

BIN = os.environ["TVC_BIN"]

def run(*extra, cwd):
    return subprocess.run(
        [BIN, "--label=g", f"--out={cwd}", "--rate=1000",
         "--cycles=1000", "--warmup=50", *extra],
        capture_output=True, text=True)

class AllocGuard(unittest.TestCase):
    def test_count_mode_sees_naive_log(self):
        with tempfile.TemporaryDirectory() as d:
            p = run("--alloc-guard=count", cwd=d)
            self.assertEqual(p.returncode, 0)
            self.assertIn("alloc guard", p.stdout)
            self.assertNotIn(" 0 allocations", p.stdout)

    def test_clean_path_is_clean(self):
        with tempfile.TemporaryDirectory() as d:
            p = run("--alloc-guard=count", "--no-naive-log", cwd=d)
            self.assertEqual(p.returncode, 0)
            self.assertIn("hot path is clean", p.stdout)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify baseline** — these two should already pass (they pin current behavior before the refactor):

```bash
git switch main && git pull && git switch -c alloc-guard-atomic
docker run --rm -v "$PWD":/w -w /w --cap-add=IPC_LOCK --ulimit memlock=-1:-1 tvc-dev bash tests/ci.sh
```

Expected: PASS. This task's change is behavior-preserving; the tests guard the refactor.

- [ ] **Step 3: Implement** in `src/alloc_guard.cpp`

```cpp
#include <atomic>
```

Replace `int g_mode = 0;` with:

```cpp
// Written by the main thread around the run; read from any thread that
// allocates. Relaxed atomic: no ordering needed, only tear-freedom.
std::atomic<int> g_mode{0};
```

In `note_alloc`/`note_free`, replace `g_mode` reads with `const int m = g_mode.load(std::memory_order_relaxed);` and use `m`. In `set_mode`/`mode`, use `.store(..., std::memory_order_relaxed)` / `.load(std::memory_order_relaxed)`.

- [ ] **Step 4: Run tests to verify they still pass** — same container command. Expected: PASS.

- [ ] **Step 5: Commit and open the PR**

```bash
git add -A
git commit -m "make alloc guard mode atomic"
git push -u origin alloc-guard-atomic
gh pr create --title "Alloc guard: atomic mode flag" --body "$(cat <<'EOF'
g_mode was a plain int read cross-thread, a data race the moment the v0.2a
drain thread exists; TSan would flag it in our own CI. Relaxed atomic, no
hot-path cost on x86/ARM. Tests pin count-mode and clean-path behavior.

## AI assistance
- Agent: Claude Code (Fable 5)
- Scope: full diff
- Human changes: <filled at review>
- Verification: tests/ci.sh green both trees
EOF
)"
```

Stop for review. After merge: `docs/ai-log/0005-alloc-guard.md`, commit `add ai log entry 0005`.

---

### Task 6: PR #5, timing loop honesty (naive L0, timer slack, strict exits, applied config, environment record)

**Files:**
- Modify: `src/main.cpp`, `src/loop_stats.hpp`, `src/loop_stats.cpp` (write_json signature)
- Create: `tests/functional/test_strict.py`

**Interfaces:**
- Consumes: Task 3's `record(jitter, naive, exec)`.
- Produces: exit codes 0 ok, 1 usage, 2 mitigation failed, 3 interrupted, 4 write failed; `LoopStats::write_json(const std::string& path, const std::string& label, const std::string& config, const std::string& applied_json, const std::string& env_json)`; summary.json gains `"applied": {...}` and `"env": {...}` objects. Task 7's sweep relies on the exit codes and the `applied` object.

- [ ] **Step 1: Write the failing test** `tests/functional/test_strict.py`

```python
import json, os, pathlib, subprocess, tempfile, unittest

BIN = os.environ["TVC_BIN"]

class StrictExits(unittest.TestCase):
    def test_bad_arg_value_rejected(self):
        p = subprocess.run([BIN, "--cpu=abc"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)

    def test_bad_label_rejected(self):
        p = subprocess.run([BIN, "--label=a/b"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)

    def test_failed_mitigation_exits_2_and_is_recorded(self):
        # Unprivileged container process: SCHED_FIFO must fail.
        with tempfile.TemporaryDirectory() as d:
            p = subprocess.run(
                [BIN, "--label=s", f"--out={d}", "--rate=1000",
                 "--cycles=500", "--warmup=50", "--fifo=80"],
                capture_output=True, text=True)
            self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
            s = json.loads((pathlib.Path(d) / "s.summary.json").read_text())
            self.assertFalse(s["applied"]["fifo"])
            self.assertIn("kernel", s["env"])

    def test_unwritable_out_exits_4(self):
        p = subprocess.run(
            [BIN, "--label=w", "--out=/nonexistent-dir-xyz", "--rate=1000",
             "--cycles=200", "--warmup=10"],
            capture_output=True, text=True)
        self.assertEqual(p.returncode, 4)

if __name__ == "__main__":
    unittest.main()
```

Note: the fifo test requires `tests/ci.sh`'s container to be unprivileged for RT (it is: no `--cap-add=SYS_NICE`).

- [ ] **Step 2: Run to verify it fails**

```bash
git switch main && git pull && git switch -c timing-loop-honesty
docker run --rm -v "$PWD":/w -w /w --cap-add=IPC_LOCK --ulimit memlock=-1:-1 tvc-dev bash tests/ci.sh
```

Expected: FAIL (`--cpu=abc` silently becomes 0; failures exit 0; no `applied` key).

- [ ] **Step 3: Implement**

`src/main.cpp` includes: add `<sys/prctl.h>`, `<sys/utsname.h>`.

Argument parsing: add helpers in the anonymous namespace and use them in `parse`:

```cpp
bool to_i64(const char* s, std::int64_t& out) {
    char* end = nullptr;
    errno = 0;
    const long long v = std::strtoll(s, &end, 10);
    if (errno != 0 || end == s || *end != '\0') return false;
    out = v;
    return true;
}
bool to_double(const char* s, double& out) {
    char* end = nullptr;
    errno = 0;
    out = std::strtod(s, &end);
    return errno == 0 && end != s && *end == '\0';
}
bool label_ok(const std::string& s) {
    if (s.empty()) return false;
    for (char c : s)
        if (!std::isalnum(static_cast<unsigned char>(c)) &&
            c != '.' && c != '_' && c != '-') return false;
    return true;
}
```

In `parse`, replace each `atof`/`atoll`/`atoi` use with the checked helper and a `fprintf(stderr, "bad value: %s\n", a); return false;` on failure. After the option loop, validate: `label_ok(c.label)`, `c.rate_hz > 0`, `c.cycles > 0`, `c.warmup >= 0`, `c.fifo_prio == 0 || (c.fifo_prio >= 1 && c.fifo_prio <= 99)`, `c.cpu >= -1`; print a specific message and return false on each violation. Update `usage()` with a line: `exit codes: 0 ok, 1 usage, 2 mitigation failed, 3 interrupted, 4 write failed` and label charset `[A-Za-z0-9._-]`.

Naive L0: replace the `sleep_for` branch body (the `remain` computation and conditional sleep) with:

```cpp
            // Genuinely naive: sleep one period from "now", the pattern that
            // drifts by the overshoot every cycle. Measurement still happens
            // against the origin schedule, so the drift is visible.
            std::this_thread::sleep_for(std::chrono::nanoseconds(period_ns));
```

Timer slack, right after signal setup in `main`:

```cpp
    // 50 us default slack would otherwise contaminate every non-RT level.
    ::prctl(PR_SET_TIMERSLACK, 1UL, 0UL, 0UL, 0UL);
```

Applied tracking: after the privilege block, collect results:

```cpp
    bool ok_mlock = !cfg.mlock, ok_cpu = cfg.cpu < 0, ok_fifo = cfg.fifo_prio <= 0;
```

(set each from `r.ok` inside its `if` block). Build the JSON fragments before writing:

```cpp
    auto b = [](bool v) { return v ? "true" : "false"; };
    utsname un{};
    ::uname(&un);
    const std::string applied_json =
        std::string("{ \"mlock\": ") + b(!cfg.mlock || ok_mlock) +
        ", \"fifo\": " + b(!(cfg.fifo_prio > 0) || ok_fifo) +
        ", \"cpu\": " + b(cfg.cpu < 0 || ok_cpu) + " }";
    const std::string env_json =
        std::string("{ \"kernel\": \"") + un.release +
        "\", \"machine\": \"" + un.machine +
        "\", \"cpu_end\": " + std::to_string(::sched_getcpu()) +
        ", \"timer_slack_ns\": 1 }";
```

Exit logic at the end of `main` (replacing `return 0;`):

```cpp
    bool wrote_ok = stats.write_csv(cfg.outdir, cfg.label);
    wrote_ok = stats.write_json(cfg.outdir + "/" + cfg.label + ".summary.json",
                                cfg.label, cfgstr, applied_json, env_json) && wrote_ok;
    if (wrote_ok)
        std::printf("\n  wrote %s/%s.{jitter,jitter_naive,exec}.csv and .summary.json\n",
                    cfg.outdir.c_str(), cfg.label.c_str());
    else
        std::fprintf(stderr, "\nerror: could not write results into %s\n", cfg.outdir.c_str());

    const bool mitigation_failed =
        (cfg.mlock && !ok_mlock) || (cfg.fifo_prio > 0 && !ok_fifo) ||
        (cfg.cpu >= 0 && !ok_cpu);
    if (!wrote_ok) return 4;
    if (g_stop.load()) return 3;
    if (mitigation_failed) return 2;
    return 0;
```

(Move the existing `write_csv`/`write_json` calls into this block; delete the old unconditional success print.)

`src/loop_stats.hpp` / `.cpp`: extend `write_json` to `(path, label, config, applied_json, env_json)`; in the format string add after the `"config"` line:

```cpp
        "  \"applied\": %s,\n"
        "  \"env\": %s,\n"
```

with `applied_json.c_str(), env_json.c_str()` in the argument list.

- [ ] **Step 4: Run tests to verify they pass** — container command. Expected: all functional suites PASS in both trees (test_summary from Task 3 still green: it asserts exit 0 with no mitigations requested).

- [ ] **Step 5: Commit and open the PR**

```bash
git add -A
git commit -m "make timing loop honest: naive L0, slack pin, strict exits, applied config"
git push -u origin timing-loop-honesty
gh pr create --title "Timing loop honesty" --body "$(cat <<'EOF'
Four stress-test fixes: L0 is now the genuinely drifting naive loop the
docs describe; timer slack is pinned to 1 ns so the SCHED_FIFO level
measures policy rather than slack removal; failed mitigations exit 2 and
summary.json records applied (not requested) config plus an environment
record; argument parsing rejects garbage instead of silently running a
wrong configuration. Exit codes: 0 ok, 1 usage, 2 mitigation failed,
3 interrupted, 4 write failed.

## AI assistance
- Agent: Claude Code (Fable 5)
- Scope: full diff
- Human changes: <filled at review>
- Verification: tests/ci.sh green both trees; strict-exit tests exercise the unprivileged container path
EOF
)"
```

Stop for review. After merge: `docs/ai-log/0006-timing-loop.md`, commit `add ai log entry 0006`.

---

### Task 7: PR #6, sweep and plot correctness

**Files:**
- Modify: `scripts/sweep.py`, `scripts/plot_jitter.py`
- Create: `tests/unit/test_sweep.py`, `tests/unit/test_plot.py`

**Interfaces:**
- Consumes: Task 6's exit codes and `applied` object; Task 3's file names.
- Produces: `sweep.plan_levels(levels, cpu)` and `sweep.row_ok(summary)` pure functions; `--repeat N`; chain-break behavior.

- [ ] **Step 1: Write the failing unit tests**

`tests/unit/test_sweep.py`:

```python
import sys, pathlib, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
import sweep

class PlanLevels(unittest.TestCase):
    def test_chain_breaks_at_first_skipped_level(self):
        runnable, stopped = sweep.plan_levels(sweep.LEVELS, cpu=None)
        self.assertEqual([l[0] for l in runnable], ["L0", "L1", "L2", "L3"])
        self.assertIn("--cpu", stopped)

    def test_full_chain_with_cpu(self):
        runnable, stopped = sweep.plan_levels(sweep.LEVELS, cpu=3)
        self.assertEqual([l[0] for l in runnable],
                         ["L0", "L1", "L2", "L3", "L4", "L5"])
        self.assertIsNone(stopped)

class RowOk(unittest.TestCase):
    def test_rejects_unapplied_mitigation(self):
        self.assertFalse(sweep.row_ok({"applied": {"fifo": False, "mlock": True, "cpu": True}}))
        self.assertTrue(sweep.row_ok({"applied": {"fifo": True, "mlock": True, "cpu": True}}))

    def test_missing_applied_is_rejected(self):
        self.assertFalse(sweep.row_ok({}))

if __name__ == "__main__":
    unittest.main()
```

`tests/unit/test_plot.py`:

```python
import sys, pathlib, tempfile, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
import plot_jitter

class ReadCdf(unittest.TestCase):
    def test_reads_and_drops_p1(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("Value,Percentile,TotalCount,1/(1-Percentile)\n")
            f.write("10.0,0.5,100,2.0\n10.0,1.0,200,inf\n")
            path = f.name
        xs, ys = plot_jitter.read_cdf(path)
        self.assertEqual(xs, [10.0])
        self.assertEqual(ys, [0.5])

class YFloor(unittest.TestCase):
    def test_y_floor_from_counts(self):
        self.assertAlmostEqual(plot_jitter.y_floor([300_000]), 0.5 / 300_000)
        self.assertEqual(plot_jitter.y_floor([]), 5e-6)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify they fail**

```bash
git switch main && git pull && git switch -c sweep-plot-fixes
python3 -m unittest discover -s tests/unit -v
```

Expected: FAIL (`plan_levels`, `row_ok`, `y_floor` do not exist). Note matplotlib is needed to import plot_jitter; on the Mac `pip install matplotlib` once, or run inside the container.

- [ ] **Step 3: Implement**

`scripts/sweep.py`: add the two pure functions after `LEVELS`:

```python
def plan_levels(levels, cpu):
    """Cumulative prefix of levels that can run. Once any level is skipped,
    everything after it is invalid (it would differ from its predecessor by
    more than one change), so the campaign stops there."""
    runnable = []
    for label, desc, add in levels:
        if any("{cpu}" in f for f in add) and cpu is None:
            return runnable, f"{label} needs --cpu; campaign stops here"
        runnable.append((label, desc, add))
    return runnable, None


def row_ok(summary):
    """A row enters the table only if every requested mitigation was applied."""
    applied = summary.get("applied")
    if not isinstance(applied, dict):
        return False
    return all(applied.values())
```

In `main()`: add `ap.add_argument("--repeat", type=int, default=1, help="runs per level; table reports median and spread")`. Replace the level loop with:

```python
    runnable, stopped = plan_levels(LEVELS, args.cpu)
    if stopped:
        print(f"note: {stopped}", file=sys.stderr)

    flags: list[str] = []
    ran: list[str] = []
    for label, desc, add in runnable:
        flags += [f.format(cpu=args.cpu) for f in add]
        if args.only and label not in args.only:
            continue
        for r in range(1, args.repeat + 1):
            run_label = label if args.repeat == 1 else f"{label}.r{r}"
            print(f"\n{'=' * 72}\n{run_label}  {desc}\n{'=' * 72}")
            cmd = [str(binary), f"--label={run_label}", f"--out={outdir}",
                   f"--rate={args.rate}", f"--cycles={args.cycles}",
                   f"--warmup={args.warmup}", *flags]
            print("  " + " ".join(cmd) + "\n")
            rc = subprocess.run(cmd).returncode
            if rc != 0:
                print(f"\n{run_label} exited {rc}.", file=sys.stderr)
                if rc == 2:
                    print("A requested mitigation was not applied; this run "
                          "will not enter the table.", file=sys.stderr)
                if label == "L5":
                    print("If the allocation guard aborted, that is the harness "
                          "working: something in the cycle still allocates. "
                          "Re-run with --alloc-guard=count.", file=sys.stderr)
                return rc
        ran.append(label)
```

Replace the table build with median/spread over repeats and the `row_ok` gate:

```python
    import statistics
    rows, excluded = [], []
    for label in ran:
        pattern = f"{label}.summary.json" if args.repeat == 1 else f"{label}.r*.summary.json"
        summaries = [json.loads(p.read_text()) for p in sorted(outdir.glob(pattern))]
        good = [s for s in summaries if row_ok(s)]
        excluded += [s["label"] for s in summaries if not row_ok(s)]
        if not good:
            continue
        p999s = [s["jitter_us"]["p99.9"] for s in good]
        base = dict(good[0])
        base["label"] = label
        base["jitter_us"] = dict(good[0]["jitter_us"])
        base["jitter_us"]["p99.9"] = statistics.median(p999s)
        base["p999_spread"] = (min(p999s), max(p999s)) if len(p999s) > 1 else None
        rows.append(base)
    if excluded:
        print(f"\nexcluded (mitigation not applied): {', '.join(excluded)}",
              file=sys.stderr)
```

In the table print, after the p99.9 cell add the spread when present:

```python
            spread = r.get("p999_spread")
            sp = f" ({spread[0]:.0f}-{spread[1]:.0f})" if spread else ""
```

and append `sp` to the printed p99.9 column (widen that column to 16). Update the `--cpu` help to `"isolated core for L4+; without it the campaign stops after L3"`. Return `1` at the end if `excluded` is nonempty, else `0`.

`scripts/plot_jitter.py`: add after `read_cdf`:

```python
def y_floor(counts, default=5e-6):
    """Lower y limit: half the reciprocal of the largest series, so the last
    real point stays on the axis."""
    if not counts:
        return default
    return 0.5 / max(counts)
```

In `main()`: initialize `counts = []` next to `lo, hi = 1e9, 0.0`; inside the `if meta.exists():` block append `counts.append(d.get("cycles", 0))`; guard the no-data case before setting limits:

```python
    if hi <= 0:
        return print(f"no plottable data in {rdir}") or 1
    ax.set_xlim(max(lo * 0.8, 0.05), hi * 1.4)
    ax.set_ylim(y_floor(counts), 1.4)
```

(`0.05` µs floors the axis above the 1 ns early-wakeup clamp.)

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m unittest discover -s tests/unit -v
docker run --rm -v "$PWD":/w -w /w --cap-add=IPC_LOCK --ulimit memlock=-1:-1 tvc-dev bash tests/ci.sh
```

Expected: PASS. Also run an end-to-end smoke in an unprivileged container (no `--cap-add`): `python3 scripts/sweep.py --bin build/tvc_harness --out /tmp/r --cycles 2000 --warmup 100` and confirm the `--cpu` note prints, L0/L1 complete, and the campaign halts at L2 with the harness's exit code 2 (mlockall fails at the container's default memlock limit) instead of tabulating a bad row.

- [ ] **Step 5: Commit and open the PR**

```bash
git add -A
git commit -m "stop sweep at first skipped level, gate table on applied config, add repeats"
git push -u origin sweep-plot-fixes
gh pr create --title "Sweep and plot correctness" --body "$(cat <<'EOF'
sweep.py previously ran L5 unpinned when --cpu was absent, breaking the
one-change-per-level invariant, and tabulated runs whose mitigations had
silently failed. The campaign now stops at the first skipped level, rows
enter the table only when summary.json applied config matches the request,
and --repeat N reports median and spread for p99.9. plot_jitter derives
its y floor from cycle counts (the deepest tail was clipped), guards the
empty-results case, and floors x above the early-wakeup clamp.

## AI assistance
- Agent: Codex (planned; if unavailable this week, Claude Code with note here)
- Scope: full diff, implemented against the unit tests in this PR
- Human changes: <filled at review>
- Verification: tests/unit green natively; tests/ci.sh green; container smoke run of the campaign
EOF
)"
```

Stop for review. After merge: `docs/ai-log/0007-sweep-plot.md`, commit `add ai log entry 0007`. This PR is the designated Codex task per ADR-000; Claude reviews the diff before Mamadou does and records the review in the log entry.

---

### Task 8: PR #7, documentation corrections

**Files:**
- Modify: `docs/methodology.md`, `README.md`
- Create: `docs/plan.md`

**Interfaces:**
- Consumes: measured alloc-guard count from a Task 5 container run.

- [ ] **Step 1: Rewrite the falsified sections of `docs/methodology.md`**

```bash
git switch main && git pull && git switch -c docs-corrections
```

Replace the "Coordinated omission" section (starting "Jitter is recorded twice, raw and corrected.") with:

```markdown
### Coordinated omission

This harness has no coordinated omission by construction. Every cycle is
measured against its intended absolute deadline (origin + n x period), and
every cycle produces exactly one sample: when one cycle runs long, the
displaced cycles behind it wake immediately and record their true lateness.
Nothing is omitted, so nothing needs correcting.

A second series, jitter_naive, records what a self-referencing measurement
(previous wakeup + period) would have reported. After a stall, that scheme
sees the very next cycle as on time, which is exactly how naive harnesses
hide their worst behavior. The gap between the two series is the
demonstration; the primary series is the only published number.
```

Replace the "Deadline misses" paragraph with:

```markdown
### Deadline misses

A cycle that finishes after the next cycle's deadline slipped the schedule
by a full period. These are counted separately and also appear in the
histogram: the cycle did run, and its lateness is real data. The miss
counter is the cross-check that the tail is being read honestly.
```

In "The allocation guard": append to the intro paragraph:

```markdown
The guard intercepts C++ operator new and delete only; direct malloc-family
calls from C code bypass it. The hot path is all C++, so this scope is
sufficient today, and the limit is stated so the claim stays honest.
```

Replace the sentence "With it on, the guard reports two allocations and two frees per cycle." with the measured value: run in the container

```bash
docker run --rm -v "$PWD":/w -w /w tvc-dev bash -c \
  "build/tvc_harness --label=c --out=/tmp --rate=1000 --cycles=2000 --warmup=100 --alloc-guard=count | grep 'alloc guard'"
```

and write: "With it on, the guard reports N allocations and M frees per K cycles on the reference toolchain (gcc, libstdc++, Ubuntu 24.04); the exact count is toolchain-dependent, which is why the harness measures it instead of asserting it." (substituting the observed N, M, and the run's cycle count).

Replace the "Host preparation" section body with the 465 G11 recipe:

```markdown
Numbers from a VM, WSL, or a container are not usable. Bare metal only.
The reference machine is an HP ProBook 465 G11 (Ryzen 7 7735U: 8 cores,
16 threads, homogeneous Zen 3+) on Ubuntu 24.04 LTS.

**Identify the topology first.** `lscpu --all --extended` and
`cat /sys/devices/system/cpu/cpu*/topology/thread_siblings_list`. On this
part, core N typically pairs with thread N+8.

**Isolate a full physical core.** Both SMT siblings, for example CPUs 3
and 11:

    isolcpus=3,11 nohz_full=3,11 rcu_nocbs=3,11

in GRUB_CMDLINE_LINUX_DEFAULT, then update-grub and reboot. Pin the loop
to 3 and leave 11 idle. Isolating a lone SMT thread is not isolation: the
sibling shares the core's execution units and caches. `nosmt` is the
simpler alternative when the core count can be spared.

**Move interrupts away.** Stop irqbalance if it is running; write masks
excluding the isolated pair to /proc/irq/*/smp_affinity. Some kernel-
managed IRQs refuse the write; that is expected. Verify with
/proc/interrupts deltas during a run.

**Benchmark on AC power, always.** power-profiles-daemon rewrites the
energy performance preference on AC/battery transitions; mask it for the
run and pin EPP to performance under amd_pstate. Disable deep idle on the
isolated pair only (per-CPU cpuidle sysfs or /dev/cpu_dma_latency), not
machine-wide: forcing 16 threads to C0 in a 15 W thin chassis invites
thermal throttling mid-run.

**Qualify the platform before trusting it.** An hour of hwlatdetect at
idle, and the SMI counter (turbostat) logged across every run. Firmware
stalls are invisible to the kernel and no setting removes them; if this
chassis has them, that is a finding to publish, not to discover in an
interview.

**Real-time throttling.** The kernel default (sched_rt_runtime_us =
950000) leaves 5% of each second to non-RT tasks and is the actual
runaway-loop protection on a stock kernel; this loop's duty cycle is
around 1%, far from the limit. Priority 80 rather than 99 is convention
plus headroom for future higher-criticality threads, not a safety
mechanism.
```

In "Notes": replace the fast-math bullet rationale with "It permits floating-point reassociation and sets FTZ/DAZ at startup, which breaks bit-identical replay across builds; -ffp-contract=off is set for the same reason." Replace the plant-model bullet with "The plant stand-in's clamps are branches on data, but they are perfectly predicted in steady state; the workload's contribution to jitter is negligible either way, and the claim is scoped accordingly." Add a bullet: "Linux only. CMake fails fast elsewhere; functional work on other hosts uses the tvc-dev container."

Update the campaign table section: L0 description becomes "baseline: sleep_for(period) from now, the naive drifting loop"; note that without `--cpu` the campaign stops after L3.

- [ ] **Step 2: Write `docs/plan.md`**

```markdown
# Engineering plan

The governing document is the spec
(superpowers/specs/2026-08-14-tvc-restructure-design.md). This file is the
working summary of what ships when.

## Releases

| Release | Ships | Check |
|---|---|---|
| v0.1 | Harness with corrected methodology; qualified ProBook 465 G11; six-level campaign with repeats; writeup with the CDF at the top of the README; CI lane split | A stranger can reproduce the figure from the README |
| v0.2a | Framing, CRC-32C, SPSC ring, drain thread; unit tests and sanitizers in CI | Jitter CDF unchanged with telemetry enabled |
| v0.2b | Sim, PID, link_sim, ground station, episode state machine, latency budget | Pendulum survives 30% packet loss; GIF in README |
| Stretch | Deterministic replay, then TMR (lockstep, tick-aligned, digest voting) | Replay bit-identity in CI; voter demo |

## Cut order under pressure

Live plotting, then TMR, then replay. Never cut: the jitter campaign, the
methodology, the writeup, the AI log.

## Two modes

Real-time free-run mode produces all published jitter numbers
(single instance, isolated core). Lockstep mode is the deterministic lane:
CI, seed-exact scenarios, replay goldens, TMR. Seed reproduction is
claimed only in lockstep mode; input-log replay is claimed everywhere.

## Measurement rules

Bare metal only for numbers. AC power, masked power daemon, pinned EPP,
SMI counter logged. Every summary.json carries applied config and
environment. The corrected draft documents' remaining content (project
overview) moves into the repo with v0.2b, when the system it describes
exists.
```

- [ ] **Step 3: Update `README.md`** status line to "Status: v0.1 week 1 complete: harness landed and corrected. Next: Linux bring-up and qualification on the ProBook 465 G11." and add `docs/methodology.md` and `docs/plan.md` links under Layout.

- [ ] **Step 4: Verify docs**

```bash
grep -n '—' docs/methodology.md docs/plan.md README.md || echo "no em dashes"
python3 -m unittest discover -s tests/unit -v
```

Expected: "no em dashes"; tests still green (no code touched).

- [ ] **Step 5: Commit and open the PR**

```bash
git add -A
git commit -m "correct methodology docs and add working plan"
git push -u origin docs-corrections
gh pr create --title "Documentation corrections" --body "$(cat <<'EOF'
Rewrites every methodology section the stress test falsified: CO framing
(the harness is CO-free by construction), missed-cycle wording matched to
the code, alloc-guard scope and measured counts, host prep rewritten for
the actual machine (465 G11 sibling-pair isolation, amd_pstate, SMI
qualification, RT throttling), fast-math rationale corrected. Adds
docs/plan.md as the working release summary.

## AI assistance
- Agent: Claude Code (Fable 5)
- Scope: full diff
- Human changes: <filled at review>
- Verification: em-dash and banned-word scan clean; unit tests green
EOF
)"
```

Stop for review. After merge: `docs/ai-log/0008-docs-corrections.md`, commit `add ai log entry 0008`.

---

### Task 9: Week-1 exit verification

**Files:** none created; this is the spec's week-1 check.

- [ ] **Step 1: Full clean run**

```bash
git switch main && git pull
docker build -t tvc-dev docker/
docker run --rm -v "$PWD":/w -w /w --cap-add=IPC_LOCK --ulimit memlock=-1:-1 tvc-dev bash tests/ci.sh
```

Expected: "ci.sh: all green" (normal + ASan/UBSan, unit + functional).

- [ ] **Step 2: Unprivileged sweep behavior check**

```bash
docker run --rm -v "$PWD":/w -w /w tvc-dev bash -c \
  "cmake -S . -B build && cmake --build build -j && python3 scripts/sweep.py --bin build/tvc_harness --out /tmp/r --cycles 2000 --warmup 100"
```

Expected: the campaign never reaches L4/L5 (the note about `--cpu` prints), and it halts at the first level whose mitigation fails in an unprivileged container: L2, where `mlockall` hits the default 64 KiB memlock limit and the harness exits 2. Sweep reports the failure instead of tabulating the run. This is the spec's "unprivileged sweep behaves correctly": no silently wrong rows, ever.

- [ ] **Step 3: Evidence trail check**

```bash
ls docs/ai-log/        # 0001 through 0008 present
gh pr list --state merged --json number,title | python3 -m json.tool
```

Expected: seven merged PRs, each with an AI-assistance section (spot-check two with `gh pr view N`). Report the checklist result to Mamadou; week 2 (Ubuntu install, isolation, qualification) starts on his go.
