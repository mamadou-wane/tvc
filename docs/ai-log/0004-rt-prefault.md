# 0004: rt_setup prefaulting
Date: 2026-08-14
PR: #3 (merge 8f3c31e)
Agent: Claude Code (Sonnet 5 implementer, directed by Fable 5)
Produced: replaced the recursive stack prefault (optimizer-eliminated at -O2, stack-overflow risk at -O0) with a bounded alloca touch behind an asm barrier, capped by getrlimit; added the mallopt arena recipe (M_TRIM_THRESHOLD, M_MMAP_MAX) so the heap warm block survives free; lock_memory now reports the prefaulted budget and a post-warm minor-fault recheck.
Human: Mamadou reviewed and merged; no changes requested. Review noted two brief-inherited minors (uncapped RLIM_INFINITY branch, untested no-cap branch), deferred to the final review.
Verification: tests/functional/test_mlock.py red-then-green; runs under ulimit -s 8192 with recheck minor faults 0; ASan tree skips the mlock case by design (TVC_ASAN=1).
