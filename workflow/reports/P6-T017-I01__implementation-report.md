---
workflow_schema: 1
phase: P6
task_id: P6-T017
iteration: I01
task_key: P6-T017-I01
reply_to: workflow/tasks/P6-T017-I01__windows-acceptance-portability.md
status: REVIEW_READY
owner: agent
review_target: workflow/reviews/P6-T017-I01__architect-review.md
---

# P6-T017-I01 Implementation Report

## 1. Result

- Status: `REVIEW_READY`
- Implementation commit: bd1029d95502f2db1d68e1389aad803cc31bd683
- Final commit: bd1029d95502f2db1d68e1389aad803cc31bd683

- `pyproject.toml` — `project.dependencies` 由 `[]` 改为 `["tzdata>=2024.1"]`，
  附注释说明日历模块需要 `ZoneInfo('Asia/Shanghai')`、Windows/精简容器无系统时区库。
- `.gitattributes`（新增）— `* text=auto`；对
  `*.py *.md *.toml *.json *.yml *.yaml *.sql *.jsonl *.cfg *.txt *.tla` 显式 `text eol=lf`；
  `*.jar *.png *.pptx *.ico *.db` 声明 `binary`。文件头注释说明
  `build_qmt_deployments.py --check` 与 `test_invariant_9` 做字节级比较的原因。
- `docs/DEVELOPMENT_ENVIRONMENT_MIGRATION_ZH.md` — §3 首次验收后追加
  "Windows 注意事项（P6-T017 起已仓库级修复）"：tzdata 自动安装说明 +
  `.gitattributes` 强制 LF 说明及 `git ls-files --eol` / 恢复命令。

未改动：Frozen Core v1（core/domain/oms/ports）、`qmt_side/` 内容、`schemas/`、
`contracts/`、`formal/`、其余产品代码、既有测试。

## 3. Implementation summary

两处 Windows 首次验收失败均为可移植性缺陷：

1. **tzdata 缺失**：`tests/service/test_calendar.py` 5 项失败
   （`ModuleNotFoundError: No module named 'tzdata'`）。Linux CI 依赖系统时区库掩盖了
   声明缺失。修复为无条件运行依赖（行为跨平台确定性优先；QMT 侧 CPython 3.6 代码
   不使用 zoneinfo，不受影响）。
2. **CRLF smudge**：`core.autocrlf=true` 使 Windows 工作树 `qmt_side/*.py` 为 CRLF，
   而 generator `--check` 期望恒 LF 的字节级一致 → `--check` exit 1 且
   `test_invariant_9_deployment_generator_is_in_sync` 失败（CI 的 LF checkout 掩盖）。
   `.gitattributes` 从仓库层强制 LF，任何后续 Windows clone 不再需要手工
   `git -c core.autocrlf=false checkout`。

本机验证前的临时绕过（tzdata 手动 pip install、qmt_side LF re-checkout）已被上述
仓库级修复取代；`.gitattributes` 生效后 `attr/text eol=lf` 已体现在
`git ls-files --eol qmt_side`。

## 4. Verification results

```text
python -m pytest -q: 625 passed in 14.02s (exit 0)
python tools/verify_workflow_contract.py: PASS (active P6-T017-I01, AGENT_READY)
python tools/verify_core_dependency_boundary.py: PASS
python tools/verify_core_v1_release.py: PASS (core-v1.0.0 契约未动)
python tools/build_qmt_deployments.py --check: PASS (exit 0)
python tools/audit_side_effect_calls.py: PASS (mutation 面不变)
git ls-files --eol qmt_side: i/lf w/lf attr/text eol=lf（索引侧无变化、无 CRLF 回归）
git status --short: 仅 pyproject.toml / .gitattributes / docs 迁移文档三个任务内文件
```

## 5. Safety declaration

- 未发生任何 broker mutation（无 `passorder`/`cancel` 调用，未向任何 spool 发布命令）；
- 未触碰 `D:\BigQMTData\spool\` 运行数据；
- 未改变任何 execution authority / build ID / fuse；
- `.gitattributes` 提交未引起索引内容 renormalize（status 仅含 3 个任务内文件）；
- 未 push。

## 6. Deviations / unresolved items

1. 本机仍无 Java 17 + `tla2tools.jar`，TLC 本地未跑（CI `formal-verification` job 覆盖，
   与基线一致，非本任务引入）。
2. 除任务书允许的三个文件外未新增回归测试（任务书标注可选）：625 项既有测试 +
   `--check` 已完整覆盖两处修复的行为。

## 7. Handoff to Architect

After filling this report, run:

python tools/agent_workflow_handoff.py --implementation-commit <FULL_SHA>

Then run:

python tools/verify_workflow_contract.py

Commit the report and WORKFLOW_STATE changes together. Do not modify the Architect review
and do not create the next task.
