---
workflow_schema: 1
phase: P6
task_id: P6-T019
iteration: I01
task_key: P6-T019-I01
reply_to: workflow/tasks/P6-T019-I01__live-canary-runtime-preflight.md
status: REVIEW_READY
owner: agent
review_target: workflow/reviews/P6-T019-I01__architect-review.md
---

# P6-T019-I01 Implementation Report

## 1. Result

- Status: `REVIEW_READY`
- Implementation commit: f26f1712211e7572803dc4881721dde823d83d4d
- Final commit: f26f1712211e7572803dc4881721dde823d83d4d

- `tools/live_canary_runtime_preflight.py`（新增，约 330 行）：只读 GO/NO-GO 预检工具，
  10 项检查全部落地（generator 同步、artifact 常量 vs probe、Host/schema 熔断钉一致性、
  真实 manifest load_instance、build 新鲜度、manifest 熔断/额度 vs schema、
  当前 session 熔断代理扫描、unknown 清空、quarantine/conflicts 清空、HGT 窗口）；
  `--json` 机器输出；末尾固定打印操作者人工清单（不影响退出码）。
- `tests/qmt/test_live_canary_runtime_preflight.py`（新增，15 项）：tmp_path 夹具；
  GO 路径在 Host/schema 熔断钉分叉修复前自动 skip（skip 理由写明）；
  熔断期望值从 schema 单一来源提取，工具不携带第二套常量。
- `docs/DEVELOPMENT_ENVIRONMENT_MIGRATION_ZH.md` §6：预检工具使用说明（4 行 + 代码块）。

## 3. Implementation summary

关键设计：熔断/额度期望值用 `schema_live_canary_pins()` 从
`schemas/bridge/v1/instance.schema.json` 的 LIVE_CANARY 条件分支提取；
`authority_pin_consistency` 检查在临时目录构造一个 schema 祝福的最小 LIVE_CANARY
实例并调用真实 `load_instance(allow_live_canary=True)`——Host 与 schema 任一侧漂移
都会被精确指出。

**该检查在当前 HEAD 即命中一个真实缺陷**：Host `src/bigqmt_autotrader/qmt/instances.py`
的 LIVE_CANARY 校验集把熔断钉在 2/2（`830c576`，build-6 时代放宽），而 build-7 的
schema 常量与 P6 Gate 文档都是 1/1（T001 收紧）。操作者按文档写 1/1 的 manifest 会被
Host 拒载（"instance manifest mismatch: max_submit_calls_per_session"）。此为 T001 的
遗漏面，建议作为独立任务把 Host 熔断钉收回 1/1（权限收窄方向，符合 Gate 文档）。

对真实 spool 只读演练输出（全部符合预期，无一处误报）：

```text
PASS  generator_sync / artifact_constants(build-7) / instance_load / fuse_unused / no_unknown
NO-GO authority_pin_consistency（Host 2/2 vs schema 1/1，即上述缺陷）
NO-GO build_fresh（manifest 仍是 build-6，需在 QMT 重载 build-7）
NO-GO manifest_pins（manifest fuse 2/2 ≠ schema 1/1）
NO-GO clean_evidence（guojin 实例 quarantine/ 存有 2 项历史隔离证据，待对账/归档）
NO-GO window_open（当前处于午休休市，fail-closed 正确）
```

## 4. Verification results

```text
python -m pytest -q: 639 passed, 1 skipped (19.1s) —— 新增 15 项（1 项按设计 skip）
tools/verify_workflow_contract.py: PASS
tools/verify_core_dependency_boundary.py: PASS
tools/verify_core_v1_release.py: PASS
tools/build_qmt_deployments.py --check: PASS
tools/audit_side_effect_calls.py: PASS
tools/live_canary_runtime_preflight.py --help: 正常
真实 spool 只读演练: NO-GO 清单如上，退出码 1（预期）
```

## 5. Safety declaration

- 工具与测试零写入 spool（唯一写操作是 tempfile 临时目录内的探针实例，测试全部
  tmp_path）；零 broker mutation；未触碰 `D:\BigQMTData\spool\`；
- 未改变 bridge/host/probe 任何行为代码；GO 判定无绕过（old-build/UNKNOWN/
  quarantine/conflicts/熔断已消费/窗口未开一律 NO-GO）；
- authority / build / fuse 零变化（发现的 Host 钉分叉仅报告，未在本任务修改）；未 push。

## 6. Deviations / unresolved items

1. `test_go_on_clean_build7_instance` 当前 skip：GO 路径被 Host/schema 熔断钉分叉
   阻塞（见 §3），Host 钉收回 1/1 后自动启用，无需改测试。
2. 真实 guojin 实例 `quarantine/` 有 2 项历史隔离证据——属运行数据，需操作者按
   P3 归档流程处理，本任务不动。
3. Host 熔断钉 2/2 → 1/1 的收窄修复未包含在本任务范围（任务书禁止改 authority 常量），
   建议立即开下一任务。

## 7. Handoff to Architect

After filling this report, run:

python tools/agent_workflow_handoff.py --implementation-commit <FULL_SHA>

Then run:

python tools/verify_workflow_contract.py

Commit the report and WORKFLOW_STATE changes together. Do not modify the Architect review
and do not create the next task.
