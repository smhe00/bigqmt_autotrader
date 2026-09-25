---
workflow_schema: 1
phase: P6
task_id: P6-T017
iteration: I01
task_key: P6-T017-I01
state: AGENT_READY
owner: agent
audit_base_commit: 000d09437f3f8fce75745eb04cad01185506d8ed
expected_report: workflow/reports/P6-T017-I01__implementation-report.md
expected_review: workflow/reviews/P6-T017-I01__architect-review.md
---

# Windows first-acceptance portability fixes

日期：2026-09-25  
基线：`main@000d09437f3f8fce75745eb04cad01185506d8ed`（`core-v1.0.0` FROZEN 之后）  
背景：按 `docs/DEVELOPMENT_ENVIRONMENT_MIGRATION_ZH.md` 在 Windows 真机执行首次验收时，
625 项测试中有 6 项失败。全部为环境/可移植性缺陷，非测试逻辑缺陷；本任务把它们在
仓库层修死，使任何 Windows 新 clone 的首次验收一次通过。

## Objective

修复两处导致 Windows 首次验收失败的可移植性缺陷，并把修复经验固化进迁移文档：

1. `ZoneInfo('Asia/Shanghai')` 在 Windows 上 `ModuleNotFoundError: No module named 'tzdata'`
   （Linux CI 依赖系统 tzdata 掩盖了该缺失），导致 `tests/service/test_calendar.py` 5 项失败；
2. `core.autocrlf=true` 的 Windows checkout 把 `qmt_side/*.py` smudge 成 CRLF，而
   `tools/build_qmt_deployments.py --check` 与
   `tests/qmt/test_live_canary_authority_contract.py::test_invariant_9_deployment_generator_is_in_sync`
   做字节级比较（generator 输出恒为 LF），导致 1 项失败且 `--check` exit 1。

## Scope

允许修改：

1. `pyproject.toml` — `project.dependencies` 增加 `tzdata>=2024.1`（无条件依赖：保证
   Windows 与精简 Linux 容器行为一致；QMT 侧 3.6 代码不受影响，它不使用 zoneinfo）。
2. 新增 `.gitattributes` — 强制文本文件 LF：
   `* text=auto`，显式 `*.py`/`*.md`/`*.toml`/`*.json`/`*.yml`/`*.yaml`/`*.sql`/`*.jsonl`/`*.cfg`/`*.txt` `text eol=lf`，
   `*.jar`/`*.png`/`*.pptx`/`*.ico`/`*.db` `binary`。
   提交后索引内容不得变化（当前索引已全为 LF，`git ls-files --eol` 验证 `i/lf`）。
3. `docs/DEVELOPMENT_ENVIRONMENT_MIGRATION_ZH.md` — 在验收章节追加两条 Windows 说明：
   tzdata 现由 `pip install -e ".[test]"` 自动安装；换行符由 `.gitattributes` 强制 LF，
   若 `--check` 仍失败先查 `git ls-files --eol qmt_side`。
4. 必要的回归测试（如为 tzdata/换行符行为补一个轻量测试，可选；不强制）。

禁止修改：`src/bigqmt_autotrader/core|domain|oms|ports`（Frozen Core v1）、
`qmt_side/` 部署文件内容、`schemas/`、`contracts/`、`formal/`、其余产品代码。

## Workflow communication files

Agent may always update:

- workflow/reports/P6-T017-I01__implementation-report.md
- workflow/control/WORKFLOW_STATE.yaml

Agent must not modify:

- workflow/reviews/P6-T017-I01__architect-review.md

## Safety boundaries

- 无任何 broker mutation：不调用 `passorder`/`cancel`，不向任何 production spool 发布命令；
- 不触碰 `D:\BigQMTData\spool\` 运行数据；
- 不改变任何 execution authority / build ID / fuse；
- `.gitattributes` 提交不得引起索引内容 renormalize 变化（除其自身）；
- 不 push；Git 提交在本地由操作者检视。

## Required verification

```bash
python -m pytest -q                      # 625 passed
python tools/verify_workflow_contract.py
python tools/verify_core_dependency_boundary.py
python tools/verify_core_v1_release.py
python tools/build_qmt_deployments.py --check
python tools/audit_side_effect_calls.py
git ls-files --eol qmt_side              # 确认 i/lf（索引不变）
git status --short                       # 仅本任务明确修改的文件
```

## Exit criteria

1. Windows 全新 clone + `pip install -e ".[test]"` 后，手册 §3 全部验收命令一次通过；
2. `pytest -q` 625 passed（不得删除/放松任何既有测试）；
3. `git ls-files --eol` 显示索引侧无 CRLF 回归；
4. 迁移文档含两条 Windows 说明；
5. Frozen Core v1 与 authority 边界零变化。
