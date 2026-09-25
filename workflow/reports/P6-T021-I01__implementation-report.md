---
workflow_schema: 1
phase: P6
task_id: P6-T021
iteration: I01
task_key: P6-T021-I01
reply_to: workflow/tasks/P6-T021-I01__fix-preflight-command-frame-fuse.md
status: AWAITING_AGENT
owner: agent
review_target: workflow/reviews/P6-T021-I01__architect-review.md
---

# P6-T021-I01 Implementation Report

## 1. Result

- Status: AWAITING_AGENT
- Implementation commit:
- Base commit: 1a14842（任务 issuance；audit base cd030e6a2e02c5c7efef0a35fc03d4932c5c2ea0）
- Final commit:

## 2. Files changed

- `tools/live_canary_runtime_preflight.py` — 仅 `fuse_unused_check()` 重写 + 常量/文档同步：
  - 弃用扁平 JSON 手解析，改用正式 `decode_command_frame()`（其内部含
    `MAX_COMMAND_FRAME_BYTES` 尺寸上限与全量契约校验）；尺寸上限常量改为从
    `commands` 模块导入（删除本地 `1 << 20` 第二常量）；
  - 正确读取解码后 `QmtCommand.command_type` 与 `QmtCommand.payload["expected_qmt_session_id"]`；
  - 扫描 `commands/{inbox,claimed,processed,unknown}` 全部文件（不再限定 `*.json`
    glob，临时/异常文件同样 fail-closed）；`rejected/` 明确排除并注释（桥入口拒绝、
    未执行 mutation，不消耗熔断）；
  - fail-closed 语义：unreadable / oversized（> `MAX_COMMAND_FRAME_BYTES`）/
    contract-invalid（含可解析但不符 frame 契约的扁平遗留 dict）/ 无
    `expected_qmt_session_id` 的 mutation command（不可归属）→ 一律 NO-GO，
    detail 前缀 `fail-closed: fuse state cannot be verified`；
  - foreign session command → 跳过不消费；REQUEST_SNAPSHOT 等非 mutation → 跳过。
- `tests/qmt/test_live_canary_runtime_preflight.py` — 删除全部手写扁平 JSON 夹具，
  改用 `QmtCommandSpool.publish_submit()/publish_cancel()/publish_snapshot_request()`
  生成生产路径一致的真实 frame（claimed/processed/unknown 用与桥相同的文件移动语义）；
  新增目录×类型参数化（inbox submit；claimed submit/cancel；processed submit/cancel；
  unknown submit/cancel = 7 例）+ foreign session + snapshot 不消费 + 无 session 绑定
  fail-closed + malformed + contract-invalid + oversized + 遗留扁平 dict 必须 fail-closed。

未改动：broker mutation 逻辑、authority、fuse 数值、live/simulation authorization、
Frozen Core、`schemas/`、`qmt_side/`、其余工具。

## 3. Implementation summary

Architect 审计属实：旧实现按扁平 JSON 读 `command_type`，对真实嵌套 frame 全盲，
已存在的 SUBMIT_LIMIT/CANCEL_ORDER 被误报为 `fuse_unused = PASS`（实盘 Gate blocker）。

**旧 bug 被捕获的证明（红→绿）**：先提交真实 frame 回归测试再修复，同一测试集——

- 修复前（旧实现）：**12 failed, 12 passed**。失败项 = 全部 7 个真实 frame 消熔断
  用例（inbox submit；claimed submit/cancel；processed submit/cancel；unknown
  submit/cancel——全部被旧实现误判 PASS）+ 无 session 绑定、malformed、
  contract-invalid、oversized、遗留扁平 dict 5 个 fail-closed 缺口用例；
- 修复后：**24 passed**（0 failed）。

真实 spool 只读复检（行为与 T020 收窄联动，符合预期）：

- `instance_load` 现拒绝真实 build-6 manifest（"instance manifest mismatch:
  max_submit_calls_per_session"）——T020 将 Host 钉收回 1/1 后，旧 build-6 manifest
  不可再加载，操作者必须重载 build-7（新 manifest 按 Gate 写 1/1）；
- `fuse_unused`/`build_fresh`/`manifest_pins` 因 instance_load 失败而 skip（fail-closed
  下游一致）；`clean_evidence` 仍报 quarantine/ 2 项（操作者侧行动）。

## 4. Verification results

```text
python -m pytest tests/qmt/test_live_canary_runtime_preflight.py -q: 24 passed
python -m pytest -q: 649 passed in 16.1s
python tools/verify_workflow_contract.py: PASS
python tools/verify_core_dependency_boundary.py: PASS
python tools/verify_core_v1_release.py: PASS
python tools/verify_bridge_protocol_exhaustive.py: PASS
python tools/build_qmt_deployments.py --check: PASS
python tools/audit_side_effect_calls.py: PASS
真实 spool 只读演练: NO-GO（细节见 §3，全部可解释）
```

## 5. Safety declaration

- 工具保持纯只读；零 broker mutation；零 spool 写入（测试全部 tmp_path，真实 spool
  仅读取）；
- broker mutation 逻辑、authority、fuse 数值、live/simulation authorization、
  Frozen Core 零变化；
- P6-T021 PASS 前未报告任何最终 GO（真实 spool 演练为 NO-GO）；未 push 前不部署。

## 6. Deviations / unresolved items

1. `rejected/` 目录未纳入熔断扫描（任务书目录清单四项之外的裁量）：桥在执行任何
   mutation 前即拒绝该目录命令，不消耗熔断；已在代码注释与本报告声明。如 Architect
   认为 fail-closed 应覆盖 rejected/，一行即可加入。
2. 未混入 Architect 指定的范围外发现：audit_base_commit SHA 问题留待 P6-T022（本任务
   未启动）；TICK_FRESHNESS_MS 覆盖缺口未处理（build-7 单案例不使用 fresh-tick 路径）。

## 7. Handoff to Architect

After filling this report, run:

python tools/agent_workflow_handoff.py --implementation-commit <FULL_SHA>

Then run:

python tools/verify_workflow_contract.py

Commit the report and WORKFLOW_STATE changes together. Do not modify the Architect review
and do not create the next task.
