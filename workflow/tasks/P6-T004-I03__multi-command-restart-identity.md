---
workflow_schema: 1
phase: P6
task_id: P6-T004
iteration: I03
task_key: P6-T004-I03
state: CHANGES_REQUIRED
owner: agent
audit_base_commit: e5f814895b500739b5f40ad172d5c4d296d05f39
expected_report: workflow/reports/P6-T004-I03__implementation-report.md
expected_review: workflow/reviews/P6-T004-I03__architect-review.md
---

# P6-T004-I03 — Fix Multi-Command Restart Identity Validation

## Objective

Repair the I02 restart bug where `refresh_identities()` validates multiple historical candidates
against the last scanned command's `raw` bytes.

## Required change

Each candidate must carry or deterministically recover its own immutable command frame.

When validating an existing OMS intent against `qmt_execution_dispatches`, require exact equality
for that candidate:

- command_id;
- account fingerprint;
- client_order_id;
- qmt session;
- broker token;
- command type;
- frame digest;
- exact frame bytes.

Do not replace exact byte equality with a weaker metadata-only comparison.

## Regression coverage

Add tests with at least two OMS-owned historical submit commands in the same instance/session.

Required assertions:

1. restart succeeds with both commands present;
2. each historical command is matched against its own dispatch frame;
3. both mapper identities are restored;
4. both durable QMT identities are present exactly once where applicable;
5. no duplicate OMS order/intent is created;
6. no command is republished merely because of restart;
7. a deliberately mismatched frame still fails closed.

Prefer a processed + unknown combination if the test harness can express both without introducing
unrelated broker semantics.

## Preserve I02 guarantees

Do not change:

- atomic submit/cancel reservation + dispatch plan;
- startup orphan sweep;
- expired-plan fail-close;
- UNKNOWN no blind retry;
- production/Galaxy/generic mutation = 0;
- LIVE_CANARY authority.

No broker runtime test is required for I03.

## Verification

Run full repository verification and CI/TLC.

## Handoff

Update only the matching implementation report plus workflow state. Do not edit Architect review.


## Scope lock

本 iteration 严格保持小粒度，只允许：

1. 修复 `refresh_identities()` 中 per-candidate exact raw frame 绑定；
2. 增加多历史 command restart regression；
3. 增加 deliberate mismatch fail-closed regression；
4. 运行现有完整 CI/TLC 作为验收。

禁止在 I03 中顺带重构其它 OMS/QMT 路径、修改 runtime authority、增加新的 broker feature，
或处理 review 中尚未形成 blocker 的其它想法。

如果实现/复审发现新的独立问题，记录并创建 `P6-T004-I04`，不要扩大 I03。
