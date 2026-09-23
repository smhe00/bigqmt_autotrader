# Soak tests

Deterministic production-readiness longevity tests live here.

They deliberately avoid wall-clock sleeps and broker mutation. The current
suite stresses:

- 1,000 monotonic market-data and strategy-heartbeat updates;
- 1,000 duplicate daily-risk event replays without counter inflation;
- repeated Host runtime restarts, each defaulting to DISABLED;
- repeated health-loss -> HALTED transitions with no live-mode escape.

Real multi-session QMT/broker soak remains a separate runtime Gate.
