# 文档索引

更新：2026-09-25

文档分为三类，换开发环境时不要把历史结论误当成当前授权。

## 当前权威说明

- [项目入口](../README.md)：最短的当前状态、安装和验证入口。
- [中文总览](PROJECT_OVERVIEW_ZH.md)：产品边界、架构和已验证能力。
- [项目状态](PROJECT_STATUS.md)：当前版本、部署矩阵、Gate 和已知边界。
- [开发环境迁移](DEVELOPMENT_ENVIRONMENT_MIGRATION_ZH.md)：换机、恢复与验收清单。
- [Execution Core v1 冻结](CORE_FREEZE_V1_ZH.md)：Core v1 的正式冻结契约。
- [Core / Runtime 边界](CORE_RUNTIME_BOUNDARY_ZH.md)：依赖和数据库边界。
- [形式验证](FORMAL_VERIFICATION.md)：永久验证 Gate。
- [安全与权限](SECURITY_BOUNDARY.md)：不可绕过的授权边界。
- [Bridge API v1](BRIDGE_API_V1_ZH.md)：Host 与 QMT Bridge 的协议。
- [Broker Evidence v1](BROKER_EVIDENCE_CONTRACT_V1_ZH.md)：券商事实进入 OMS 的契约。

机器可读的 Core 冻结来源是 `contracts/core/v1/`；当前 workflow 的唯一入口是
`workflow/control/WORKFLOW_STATE.yaml`。发生文字冲突时，机器可读契约与 workflow
控制文件优先。

## 历史审计证据

文件名包含日期、`GATE_RESULT`、`IMPLEMENTATION_REPORT`、`CALIBRATION` 或明确阶段号
的文档，记录当时的候选版本与结论。它们可能包含后来已完成的“下一阶段”或旧 build，
为保证审计链不追写、不删除。当前状态以本页“当前权威说明”为准。

`workflow/tasks/`、`workflow/reports/`、`workflow/reviews/` 也是不可改写的任务证据，
不是普通产品说明文档。

## QMT 部署文件

- `BIGQMT_EXECUTION_BRIDGE_V05_GALAXY.py`：`galaxy`，SHADOW，零 mutation surface。
- `BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN_SIM.py`：`guojin_sim`，受限模拟校准。
- `BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN.py`：`guojin`，仅冻结的单案例 LIVE_CANARY。
- `BIGQMT_EXECUTION_BRIDGE_V05.py`：生成部署文件的模板。
- V03/V04 和无版本文件：仍由回归测试引用的历史兼容 fixture，不是当前部署入口。

不要仅凭文件名或 instance discovery 扩大交易权限。
