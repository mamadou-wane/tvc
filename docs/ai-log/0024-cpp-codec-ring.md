# 0024: c++ codec and spsc ring

Date: 2026-08-16
PR: #25 (9961a7c34b1e596cec401ab4505a317a7f044848)
Agent: Claude Code (Fable 5), subagent-driven: fresh implementer per
task, independent reviewer per task, scoped re-review per fix round.
Produced: src/telemetry.{hpp,cpp} (56-byte Record, table CRC-32C, frame
encoder, stream decoder with the seven spec counters, SpscRing),
tests/cpp/wire_tests.cpp and ring_stress.cpp, CMake targets, ci.sh TSan
tree, .gitignore build-tsan/ entry (Tasks 7-10 of the committed plan).
Human: Mamadou reviewed and merged.
Verification: full container gate green (normal, ASan/UBSan, TSan
trees); C++ decoder reproduces every golden-corpus manifest counter and
re-encodes roundtrip files byte-exactly; reviewer independently
re-derived the ring's acquire/release pairings. The task review caught
the TSan lane never executing the full-ring drop branch (TSan slows the
producer, the ring never filled); fixed with a deterministic 20 ms
initial consumer stall plus CHECK(drops > 0), after which the TSan tree
drops 1,228,393 of 2,000,000 attempts through the branch with zero
findings. That catch is the review process paying for itself: a green
sanitizer lane was proving less than it claimed.
