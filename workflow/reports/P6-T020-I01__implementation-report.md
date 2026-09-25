---
workflow_schema: 1
phase: P6
task_id: P6-T020
iteration: I01
task_key: P6-T020-I01
reply_to: workflow/tasks/P6-T020-I01__align-live-canary-fuse-pin.md
status: AWAITING_AGENT
owner: agent
review_target: workflow/reviews/P6-T020-I01__architect-review.md
---

# P6-T020-I01 Implementation Report

## 1. Result

- Status: AWAITING_AGENT
- Implementation commit:
- Base commit: f19a6af（任务 issuance；audit base 9ae9dc146f15c79db9a76e39b3d76261a3c86b45）
- Final commit:

## 2. Files changed

- `src/bigqmt_autotrader/qmt/instances.py` — LIVE_CANARY 分支 `safety_required`：
  `max_submit_calls_per_session` 2 → 1、`max_cancel_calls_per_session` 2 → 1（仅这两行）。
- `tests/qmt/test_instance_discovery.py` — LIVE_CANARY 夹具熔断 2 → 1；
  拒绝测试更名为 `test_live_canary_rejects_submit_fuse_above_pin`，越界值 3 → 2
  （2 现在也必须被拒，断言强度提升）。
- `tests/qmt/test_live_canary_runtime_preflight.py` — GO 测试的 fixture 调用方式从
  直接调用改为参数注入（pytest 禁止直接调用 fixture；与新 pytest 行为对齐，
  测试逻辑不变）。

未改动：SIMULATION_CALIBRATION 2000 钉、SHADOW 分支、`qmt_side/`、`schemas/`、
`tools/live_canary_runtime_preflight.py`、P6 Gate 文档（build-7 节本就 1/1；
build-6 历史证据节按分类不可变，未触碰）。

## 3. Implementation summary

Host 熔断钉 2/2（`830c576`，build-6 时代）与 build-7 权威（schema const 1/1、
Gate 文档、T001 审计链）分叉，导致按文档写的 build-7 manifest 被 Host 拒载。
本任务把 Host 钉收回 1/1——纯收窄：此前被 2/2 接受、被 1/1 拒绝的 manifest 只会更难
加载，不存在放宽路径。

修复后：预检工具 `authority_pin_consistency` PASS（"Host accepts schema-blessed
LIVE_CANARY manifest"）；`test_go_on_clean_build7_instance` 自动解除 skip 并通过；
真实 spool 演练仍 NO-GO（build-6 旧 manifest、quarantine 2 项、休市时段——均为
操作者侧动作，符合预期）。

## 4. Verification results

```text
python -m pytest -q: 640 passed in 14.7s（0 skip；GO 测试已激活）
tools/verify_workflow_contract.py: PASS
tools/verify_core_dependency_boundary.py: PASS
tools/verify_core_v1_release.py: PASS
tools/verify_bridge_protocol_exhaustive.py: PASS
tools/build_qmt_deployments.py --check: PASS
tools/audit_side_effect_calls.py: PASS
tools/live_canary_runtime_preflight.py --json: authority_pin_consistency=True
```

## 5. Safety declaration

- 权限收窄方向：LIVE_CANARY 熔断 2/2 → 1/1，无任何放宽；
- SIMULATION_CALIBRATION/SHADOW 分支与其余 authority 常量零变化；
- 零 broker mutation；未触碰 `D:\BigQMTData\spool\` 运行数据；未 push。

## 6. Deviations / unresolved items

1. 附带修正 GO 测试的 fixture 调用方式（直接调用在新 pytest 下被禁）——属让
   P6-T019 交付的测试在本任务后可运行的必要机械修正，测试逻辑零变化。
2. 遗留操作者侧事项（非本任务范围）：guojin quarantine/ 2 项历史隔离证据待按
   P3 归档流程处理；QMT 终端重载 build-7 后 manifest 熔断按 Gate 写 1/1。

## 7. Handoff to Architect

After filling this report, run:

python tools/agent_workflow_handoff.py --implementation-commit <FULL_SHA>

Then run:

python tools/verify_workflow_contract.py

Commit the report and WORKFLOW_STATE changes together. Do not modify the Architect review
and do not create the next task.
