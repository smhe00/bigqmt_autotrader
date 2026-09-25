---
workflow_schema: 1
phase: P6
task_id: P6-T021
iteration: I01
task_key: P6-T021-I01
state: AGENT_READY
owner: agent
audit_base_commit: cd030e6a2e02c5c7efef0a35fc03d4932c5c2ea0
expected_report: workflow/reports/P6-T021-I01__implementation-report.md
expected_review: workflow/reviews/P6-T021-I01__architect-review.md
---

# Fix live-canary preflight real command-frame fuse detection

日期：2026-09-25（Architect 独立审计发现的 live-canary Gate blocker）  
基线：`main@cd030e6a2e02c5c7efef0a35fc03d4932c5c2ea0`  
类型：preflight 工具缺陷修复 + 真实 frame 回归测试。

## Objective（Architect 审计结论）

`tools/live_canary_runtime_preflight.py::fuse_unused_check()` 按扁平 JSON 读取
`payload.get("command_type")` / `payload.get("expected_qmt_session_id")`，但
`QmtCommandSpool` 的真实 durable frame 是嵌套结构：

```json
{
  "command_transport_version": "1",
  "command": {
    "command_type": "SUBMIT_LIMIT",
    "payload": {"expected_qmt_session_id": "..."}
  }
}
```

因此 preflight 识别不了真实已发布的 SUBMIT_LIMIT/CANCEL_ORDER，会把熔断已消费
误报为 `fuse_unused = PASS`——实盘 Gate blocker，必须先于任何 GO 修复。

## Requirements（Architect 指定，全量执行）

1. 不自行重实现 command parser：复用 `bigqmt_autotrader.qmt.commands.decode_command_frame()`
   （其内部含尺寸上限与全量契约校验）。
2. 正确读取 `command.command_type` 与 `command.payload["expected_qmt_session_id"]`
   （经解码后的 `QmtCommand` 属性）。
3. 扫描当前 session 的真实 durable command 目录：`commands/{inbox,claimed,processed,unknown}`
   （`rejected` 为桥入口拒绝、未执行 mutation，不消耗熔断，明确排除并注释）。
4. 当前 session 存在任一 `SUBMIT_LIMIT`/`CANCEL_ORDER` → 熔断已消费 → NO-GO。
5. foreign session command 不消费当前 session 熔断。
6. malformed / unreadable / oversized / contract-invalid frame 一律 fail-closed
   （视为无法确认熔断状态 → NO-GO），不得因解析失败当作未消费；无 session 绑定的
   mutation command 视为不可归属 → fail-closed。
7. 回归测试禁止手写扁平 JSON：用 `QmtCommandSpool.publish_submit()/publish_cancel()`
   （或 `encode_command_frame()`）生成与生产路径一致的真实 frame。
8. 覆盖至少：inbox submit → NO-GO；claimed submit/cancel → NO-GO；processed
   submit/cancel → NO-GO；unknown submit/cancel → NO-GO；foreign session → 不消费；
   malformed frame → fail-closed。另加：非 mutation（REQUEST_SNAPSHOT）不消费、
   oversized → fail-closed、无 session 绑定 mutation → fail-closed。
9. 先写真实 frame 回归测试，在旧实现上运行必须红（作为 bug 被捕获的证明），
   修复后转绿；红/绿两次输出记入 implementation report。
10. 不修改 QMT broker mutation 逻辑、authority、fuse 数值、live/simulation
    authorization、Frozen Core、`schemas/`、`qmt_side/`。

## Workflow communication files

Agent may always update:

- workflow/reports/P6-T021-I01__implementation-report.md
- workflow/control/WORKFLOW_STATE.yaml

Agent must not modify:

- workflow/reviews/P6-T021-I01__architect-review.md

## Safety boundaries

- 工具保持纯只读；零 broker mutation；零 spool 写入（测试全部 tmp_path）；
- P6-T021 PASS 前，live-canary Gate 不得报告最终 GO；
- 不启动 P6-T022（audit_base_commit SHA 问题留待独立任务）；
- TICK_FRESHNESS_MS 覆盖缺口不在本任务（build-7 单案例不使用 fresh-tick 路径）。

## Required verification

```bash
python -m pytest tests/qmt/test_live_canary_runtime_preflight.py -q   # targeted
python -m pytest -q                                                   # full
python tools/verify_workflow_contract.py
python tools/verify_core_dependency_boundary.py
python tools/verify_core_v1_release.py
python tools/verify_bridge_protocol_exhaustive.py
python tools/build_qmt_deployments.py --check
python tools/audit_side_effect_calls.py
```

## Exit criteria

1. `fuse_unused_check` 基于真实 frame + 正式解码器，fail-closed 语义完备；
2. 真实 frame 回归在旧实现上红、新实现上绿（证据入报告）；
3. 上述验证全绿，测试数量只增不减；
4. 其余行为面（broker mutation/authority/fuse 数值/Frozen Core）零变化；
5. 交回 REVIEW_READY，由 Architect 审计（Agent 不自行 PASS）。
