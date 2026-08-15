# 0002: harness import baseline
Date: 2026-08-14
PR: #1 (merge 8a065d7)
Agent: Claude Code (Haiku 4.5 implementer, directed by Fable 5)
Produced: verbatim import of the pre-repo measurement harness (src/, scripts/, CMakeLists.txt, docs/methodology.md) plus the container dev loop (docker/Dockerfile.dev, tests/ci.sh). No fixes by design; later PRs diff against this baseline.
Human: Mamadou reviewed and merged; no changes requested. Import fidelity was independently verified byte-for-byte by a review agent before the PR reached him.
Verification: container build green in normal and ASan/UBSan trees; diff -r against the unzipped original showed zero deviation.
