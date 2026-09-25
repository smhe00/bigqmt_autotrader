---
workflow_schema: 1
phase: P6
task_id: P6-T020
iteration: I01
task_key: P6-T020-I01
state: AGENT_READY
owner: agent
audit_base_commit: 9ae9dc146f15c79db9a76e39b3d76261a3c86b45
expected_report: workflow/reports/P6-T020-I01__implementation-report.md
expected_review: workflow/reviews/P6-T020-I01__architect-review.md
---

# Align LIVE_CANARY fuse pin with build-7 gate (1/1)

日期：2026-09-25  
基线：`main@9ae9dc146f15c79db9a76e39b3d76261a3c86b45`  
类型：authority 收窄（2→1），修复 P6-T019 发现的 Host/schema 熔断钉分叉。

## Objective

把 Host `load_instance` 对 LIVE_CANARY 的熔断钉从 2/2（`830c576`，build-6 时代放宽）
收回 1/1，与 build-7 的三处既有权威一致：`schemas/bridge/v1/instance.schema.json`
（const 1/1）、P6 Gate 文档 build-7 节（"submit/cancel fuse = 1/1"）、T001 审计链
（单案例 `00700.HGT BUY 100 @ 1.00 HKD`）。修复后，操作者按文档写 1/1 的 build-7
manifest 才能被 Host 正常加载；P6-T019 预检工具的
`authority_pin_consistency` 检查转为 PASS，GO 路径测试自动启用。

## Scope

允许修改：

1. `src/bigqmt_autotrader/qmt/instances.py` — LIVE_CANARY 分支
   `safety_required` 中 `max_submit_calls_per_session: 2 → 1`、
   `max_cancel_calls_per_session: 2 → 1`（仅这两行）。
2. `tests/qmt/test_instance_discovery.py` — LIVE_CANARY 夹具熔断 2 → 1；
   `test_live_canary_rejects_more_than_two_submits_per_session` 更名为
   `test_live_canary_rejects_submit_fuse_above_pin` 并把越界值 3 → 2
   （断言强度提升：2 现在也必须被拒）。
3. `docs/P6_GUOJIN_LIVE_CANARY_GATE_20260918_ZH.md` build-7 节如已有 1/1 表述则不改；
   **禁止**改写 build-6 历史证据节（2/2 属历史证据，按文档分类保持不可变）。

禁止修改：其余任何 `src/`（尤其 SIMULATION_CALIBRATION 分支的 2000 钉）、
`qmt_side/`、`schemas/`、`tools/live_canary_runtime_preflight.py`（其探针自动受益，
不得改动）、`contracts/`、`formal/`、Frozen Core v1。

## Workflow communication files

Agent may always update:

- workflow/reports/P6-T020-I01__implementation-report.md
- workflow/control/WORKFLOW_STATE.yaml

Agent must not modify:

- workflow/reviews/P6-T020-I01__architect-review.md

## Safety boundaries

- 这是权限**收窄**：任何此前被 2/2 接受、被 1/1 拒绝的 manifest 只会更难加载；
  不存在放宽路径；
- SIMULATION_CALIBRATION 2000 熔断、SHADOW 分支、max_order_quantity=100、
  account fingerprint 钉、bridge_build 校验全部不变；
- 不触碰 spool 运行数据（真实 guojin manifest 仍为 build-6/2/2，加载行为不受影响，
  直至操作者按 Gate 重载 build-7）；零 broker mutation；未 push 前不部署。

## Required verification

```bash
python -m pytest -q                                  # 640 passed（skip 的 GO 测试转为执行）
python tools/verify_workflow_contract.py
python tools/verify_core_dependency_boundary.py
python tools/verify_core_v1_release.py
python tools/verify_bridge_protocol_exhaustive.py
python tools/build_qmt_deployments.py --check
python tools/audit_side_effect_calls.py
python tools/live_canary_runtime_preflight.py --json # authority_pin_consistency 转为 PASS
```

## Exit criteria

1. Host LIVE_CANARY 熔断钉 = 1/1，与 schema/Gate 文档/T001 审计链三者一致；
2. 预检工具 `authority_pin_consistency` PASS，`test_go_on_clean_build7_instance`
   不再 skip 并通过；
3. 全量测试只增不减（640 passed），既有验证全绿；
4. SIMULATION_CALIBRATION/SHADOW 分支与其余 authority 常量零变化。
