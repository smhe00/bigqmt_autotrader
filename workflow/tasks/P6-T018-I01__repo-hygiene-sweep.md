---
workflow_schema: 1
phase: P6
task_id: P6-T018
iteration: I01
task_key: P6-T018-I01
state: AGENT_READY
owner: agent
audit_base_commit: e08dc3163b4a2f14d78a1e06b70d23859c0467d4
expected_report: workflow/reports/P6-T018-I01__implementation-report.md
expected_review: workflow/reviews/P6-T018-I01__architect-review.md
---

# Repository hygiene sweep

日期：2026-09-25  
基线：`main@e08dc3163b4a2f14d78a1e06b70d23859c0467d4`  
类型：低风险仓库卫生；不触及任何产品行为。

## Objective

清掉两类遗留杂物，使工作树与 `git status` 在真机日常开发中保持干净：

1. 删除根目录死占位 `migrations/`（P0 时代占位，其 README 自述"P1 will introduce"，
   SQL 注释自述可执行权威在 `oms/db.py::SCHEMA_V1` 且"will move to packaged migration
   resources"——该迁移已通过 `src/bigqmt_autotrader/oms/migrations/`、
   `oms/core_migrations/`、`qmt/migrations/` 打包落地；全库无代码引用根目录
   `migrations/` 路径，`tests/oms/test_migrations.py` 仅测试打包资源）。
2. `.gitignore` 增补三类本机产物：`.runtime/`（本会话沙箱临时 shim/日志）、
   `.pytest-tmp-*/`（此前任务在仓库根留下的 pytest basetemp 目录名模式）、
   `deck/`（操作者本机的系统介绍 PPT 及其生成脚本，非仓库交付物）。

## Scope

允许修改：

- 删除 `migrations/0001_initial.sql`、`migrations/README.md`（整目录移除）；
- `.gitignore` 追加上述三行；
- 若存在直接引用根 `migrations/` 路径的文档表述，做最小限度更正（先
  `git grep -n "migrations/" -- "*.md"` 逐条确认；仅更正确实指向根目录死占位的句子）。

禁止修改：任何 `src/`、`tests/`、`qmt_side/`、`schemas/`、`contracts/`、`formal/`、
`tools/`、`workflow/` 协议文件（本任务自身的 report/state 除外）、Frozen Core v1。

## Workflow communication files

Agent may always update:

- workflow/reports/P6-T018-I01__implementation-report.md
- workflow/control/WORKFLOW_STATE.yaml

Agent must not modify:

- workflow/reviews/P6-T018-I01__architect-review.md

## Safety boundaries

- 无 broker mutation；不触碰 `D:\BigQMTData\spool\`；
- 不改变打包迁移资源（`oms/migrations/`、`oms/core_migrations/`、`qmt/migrations/`）
  的任何内容——删除的只是根目录无引用占位；
- `migrations` 目录名与 SQLite `user_version`/`schema_meta` 语义无关联（schema 版本
  由 `core_schema_meta`/`qmt_schema_meta` 管理），删除不构成 schema 变更。

## Required verification

```bash
git grep -n "^migrations/" -- "*.py" "*.toml"        # 应无命中
python -m pytest -q                                   # 625 passed
python tools/verify_workflow_contract.py
python tools/verify_core_dependency_boundary.py
python tools/verify_core_v1_release.py
python tools/build_qmt_deployments.py --check
python tools/audit_side_effect_calls.py
git status --short                                    # 仅本任务文件
```

## Exit criteria

1. 根目录 `migrations/` 不复存在，全库（代码/配置/文档）无指向该占位的活引用；
2. `.gitignore` 含 `.runtime/`、`.pytest-tmp-*/`、`deck/`；
3. 上述验证全绿，测试数量不减少；
4. Frozen Core v1、打包迁移资源、authority 边界零变化。
