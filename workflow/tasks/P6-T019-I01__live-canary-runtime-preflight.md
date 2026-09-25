---
workflow_schema: 1
phase: P6
task_id: P6-T019
iteration: I01
task_key: P6-T019-I01
state: AGENT_READY
owner: agent
audit_base_commit: d8fc9510617aa4de4a460a8ee0d789e7418d6d30
expected_report: workflow/reports/P6-T019-I01__implementation-report.md
expected_review: workflow/reviews/P6-T019-I01__architect-review.md
---

# HGT canary runtime gate preflight tool

日期：2026-09-25  
基线：`main@d8fc9510617aa4de4a460a8ee0d789e7418d6d30`  
类型：新增只读工具 + 测试；不改变任何运行时行为。

## Objective

新增 `tools/live_canary_runtime_preflight.py`：在操作者于 QMT 终端加载 build-7 执行
唯一实盘案例（`00700.HGT BUY 100 @ 1.00 HKD`，fuse 1/1）之前，把手册与 P6 Gate 文档
规定的全部机器可查前置条件一次跑成 GO/NO-GO 清单，杜绝人工漏检。

检查项（全部只读）：

1. `build_qmt_deployments.py --check`（generator 同步）；
2. 静态常量核验：guojin 部署产物 `BRIDGE_BUILD == "p6-guojin-live-canary-7"`、
   `_LIVE_CANARY_MUTATION_SYMBOLS == ("00700.HGT",)`、AUTHORIZED_SIDE/QUANTITY/
   LIMIT_PRICE/TICK_FRESHNESS_MS 与 Host probe（`live_canary_probe`）常量一致；
3. `load_instance(spool_root, "guojin", allow_live_canary=True)` 全量校验通过
   （manifest 字段、bridge_ready 最新 session/instance/account 匹配）；
4. manifest `bridge_build` 必须等于 build-7（旧 build-6 会话 → NO-GO，需重载新产物）；
5. 当前 session 熔断未消费：`commands/{claimed,processed,unknown,inbox}` 中不存在
   `expected_qmt_session_id == 当前 session` 的 `SUBMIT_LIMIT`/`CANCEL_ORDER` 命令；
6. `commands/unknown/` 为空（存在 UNKNOWN 未对账 → NO-GO）；
7. 事件侧 `quarantine/` 与 `conflicts/` 为空（身份冲突/隔离证据未解释 → NO-GO）；
8. 港股通提交窗口开启（复用 `live_canary_probe._live_canary_submit_window_open()`，
   与桥内同一套窗口逻辑，保证判定一致）。

输出：逐项 `PASS/NO-GO` 表格 + `--json` 机器输出；全部通过打印 GO 并退出 0，
否则 NO-GO 退出 1；末尾固定打印操作者人工清单（QMT 终端在跑、publisher 确认串、
单一案例核对）作为 REMINDER，不影响退出码。工具自身对 spool 绝不写入。

## Scope

允许新增/修改：

- `tools/live_canary_runtime_preflight.py`（新增）；
- `tests/qmt/test_live_canary_runtime_preflight.py`（新增，全部 tmp_path 夹具，
  禁止触碰真实 `D:\BigQMTData\spool`）；
- `docs/DEVELOPMENT_ENVIRONMENT_MIGRATION_ZH.md` §6 QMT 恢复/实盘 gate 一节追加
  预检工具使用说明（最小两三句）。

禁止修改：`src/`、`qmt_side/`、`schemas/`、`contracts/`、`formal/`、`tools/` 既有
文件、Frozen Core v1、任何 authority/build/fuse 常量。

## Workflow communication files

Agent may always update:

- workflow/reports/P6-T019-I01__implementation-report.md
- workflow/control/WORKFLOW_STATE.yaml

Agent must not modify:

- workflow/reviews/P6-T019-I01__architect-review.md

## Safety boundaries

- 工具与测试零写入 spool；零 broker mutation；不构造任何指向真实 spool 的路径写入；
- 测试不得读取真实 `D:\BigQMTData\spool`（夹具全部 tmp_path）；
- 不改变 bridge/host/probe 任何行为代码；
- GO 判定不得引入任何绕过（unknown/quarantine/conflicts/旧 build 一律 NO-GO）。

## Required verification

```bash
python -m pytest -q                      # ≥625 passed（新增测试）
python tools/verify_workflow_contract.py
python tools/verify_core_dependency_boundary.py
python tools/verify_core_v1_release.py
python tools/build_qmt_deployments.py --check
python tools/audit_side_effect_calls.py
python tools/live_canary_runtime_preflight.py --help
python tools/live_canary_runtime_preflight.py   # 对真实 spool 只读演练，预期 NO-GO（旧 build-6 会话）
```

## Exit criteria

1. 工具 + 测试落地，全部既有验证保持绿，测试数量只增不减；
2. 对真实 spool 只读演练输出可解释的 NO-GO 清单（当前为旧 build-6 会话，属预期）；
3. GO 判定逻辑与 `load_instance`/probe 常量同源，无第二套常量；
4. 文档补充到位；Frozen Core v1、authority 边界零变化。
