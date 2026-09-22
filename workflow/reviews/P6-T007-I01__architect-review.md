---
workflow_schema: 1
phase: P6
task_id: P6-T007
iteration: I01
task_key: P6-T007-I01
review_of: workflow/reports/P6-T007-I01__implementation-report.md
task_file: workflow/tasks/P6-T007-I01__guojin-sim-resting-host-restart.md
status: PASS
owner: architect
---

# P6-T007-I01 Architect Review

## Gate verdict

**PASS**

## Runtime evidence audit

The report records one passive `guojin_sim` order that reached broker-evidence-backed
`ACKNOWLEDGED` before Host restart:

- `SELL 100 510300.SH LIMIT 4.90`;
- one deterministic SUBMIT_LIMIT command;
- broker order ID `3504`;
- exact durable token `BQ3335a3d9938b087ffcfa`;
- raw ORDER `50/51`, zero fill, remaining 100;
- final pre-restart OMS state `ACKNOWLEDGED`.

The Host was then stopped and restarted against the same manifest/session. The persisted OMS row,
durable identity and broker order ID remained unchanged. Post-restart callback/query evidence
continued to resolve the same order.

## Zero-replay audit

The report records:

- exactly one SUBMIT_LIMIT dispatch row;
- exactly one processed submit command file;
- one `SIMULATION_SUBMIT_CALL_RETURNED`;
- one broker order ID throughout;
- no second submit dispatch;
- no blind retry through transient UNKNOWN/RECONCILING states.

This is consistent with the previously verified dispatch/recovery implementation and its permanent
TLC model.

## Cleanup / safety audit

One exact OMS-owned cancel targeted trusted broker order ID `3504` and the persisted token.
`SIMULATION_CANCEL_SIGNAL_SENT` remained control-plane only; ORDER `54/51` broker evidence
advanced the order to `CANCELLED`.

Final mutation accounting:

```text
guojin_sim submits = 1
guojin_sim cancels = 1
production guojin mutations = 0
galaxy mutations = 0
generic mutations = 0
UNKNOWN blind retries = 0
```

GitHub Actions run `35684697203` passed both test and formal-verification jobs, including all
permanent TLC models.

The process-filter false positive described in the report was diagnostic-only, was corrected before
the final Host restart, and did not create a second Python Host writer or broker mutation.

## Decision

**PASS.**

Validated invariant:

> one ACKed resting simulation order survives Host restart with the same durable broker identity,
> zero submit replay, and can be cleaned up by exactly one OMS-owned cancel.

No production/live authority is granted.
