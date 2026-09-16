# P4 Shadow Execution Gate Result — 2026-09-15

## Decision

**SHADOW CODE GATE: PASS**

**ORDER/DEAL broker-token lifecycle calibration: PASS IN AUTHORIZED GUOJIN SIMULATION**

**Production-account broker mutation: DISABLED, UNIMPLEMENTED, NOT AUTHORIZED**

## Passed evidence

- real-QMT `REQUEST_SNAPSHOT` and `SUBMIT_LIMIT` SHADOW round-trips completed on the one-second command cadence;
- every observed result reported `live_side_effect=false`;
- `command_result` now enters a durable OMS execution-result journal with conflict detection;
- `SHADOW_ACCEPTED` can move `UNKNOWN` only to `RECONCILING`, never to `ACKNOWLEDGED`;
- Host command-result logs include `session_id`, `command_id`, `command_type` and `result_status`, plus safe correlation fields;
- the broker-token calibration observer correlates only pre-registered exact `m_strRemark` tokens and produces no broker evidence;
- ORDER/DEAL remain quarantined without an explicitly calibrated evidence mapper;
- regression suite: 197 passed on CPython 3.12;
- QMT bridge Python 3.6 syntax and broker-mutation static audits pass.
- FSM exhaustive conformance remains 196/196, and all six pinned TLA+ models pass TLC 2.19 with no errors.

## Simulation calibration update — 2026-09-16

The separately authorized, fingerprint-pinned `guojin_sim` artifact completed
the bounded runtime calibration. Seven callback ORDER/DEAL observations all
preserved and matched their registered exact `m_strRemark` broker tokens. One
order was accepted and cancelled without a fill; the other filled 100 shares
and produced a token-matched DEAL.

The detailed evidence is in `P5_GATE_RESULT_20260916.md`. This closes the token
transport/calibration question, but does not enable an OMS status mapper:
ORDER/DEAL remain quarantined and raw QMT codes remain uninterpreted facts.

## Historical baseline

The 2026-09-15 07:40 UTC+08 read-only probe scanned 29 current spool frames and found 54 historical snapshot ORDER/DEAL rows, all with missing remarks and no callback samples. This is a valid fail-closed baseline, not a token-calibration pass.
