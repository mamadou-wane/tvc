# 0032: timer_migration in the env block

Date: 2026-08-29
PR: #34 (0fafb7cc0d71a8665966ff44b1f484bc627d1e4e)
Agent: Claude Code (Fable 5)
Produced: env_probe::timer_migration with the -1 sentinel, the env key
appended after cpuidle so older summaries stay a strict prefix, unit
tests over fake files (0, 1, missing, non-integer, out of range), the
functional shape assertion (value in {-1, 0, 1}, last two keys in
order), and the doc lines in results.md and qualification.md.
Human: Mamadou merged unchanged.
Verification: test first; the red build on the ProBook was the three
missing-member errors. Full container ci.sh green in the normal, ASan,
and TSan trees. On the ProBook the live summary ends with cpuidle,
timer_migration and reads 0 under the session discipline; the one
functional failure there is test_strict expecting --fifo=80 to be
refused, which the realtime group grants outside the container.
