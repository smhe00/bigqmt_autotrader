# bigqmt_autotrader

面向个人账户的生产级 Big QMT 执行平台。Big QMT 只承担券商终端和薄 Bridge；订单身份、
OMS、恢复、风险、审计与运行治理位于外部 Host。

> [文档索引](docs/README.md) · [中文总览](docs/PROJECT_OVERVIEW_ZH.md) ·
> [项目状态](docs/PROJECT_STATUS.md) · [换开发环境](docs/DEVELOPMENT_ENVIRONMENT_MIGRATION_ZH.md)

## 当前结论

| 能力 | 当前状态 |
| --- | --- |
| Execution Core | **`core-v1.0.0` FROZEN**，Public API/schema/formal contract 有永久 CI Gate |
| P0/P1/P2/P3 | **PASS** |
| P4 SHADOW Bridge | **DEPLOYMENT GATE PASS** |
| P5 国金模拟 submit/cancel/fill | **BOUNDED CALIBRATION PASS** |
| P6 Host↔OMS/runtime/recovery | **已完成 T001–T015 的最终 PASS 链** |
| BigQMT Bridge API v1 | **正式契约 + Schema/形式验证 Gate** |
| Broker Evidence v1 | **正式契约 + Runtime conformance Gate** |
| 国金模拟 mapper | **PASS，仅 `guojin_sim`** |
| 通用生产实盘 | **NO** |

部署矩阵：

```text
galaxy     p4-shadow-command-spool-5    SHADOW; submit/cancel disabled
guojin_sim p5-simulation-calibration-8  simulation_only=true; bounded calibration
guojin     p6-guojin-live-canary-7       one fingerprint-pinned LIVE_CANARY case only
```

`galaxy` 和 generic 文件保持零 broker mutation surface。`guojin_sim` 的调用面只能作用于
固定模拟账户。`guojin` 不是通用 LIVE：它仅保留独立 Gate 固定的
`00700.HGT BUY 100 @ 1.00 HKD` 单案例、每 session submit/cancel fuse 1/1；GC001 与
`511880.SH` 不具有当前 mutation 授权。

## 架构

```text
Strategy / Risk / Operations / Market Data       Production Runtime (extension)
                    |
                    v
ExecutionCore + OMS + durable recovery           Frozen Core v1
                    |
                    v
QMT adapter + file spool + broker terminal       Extension / external system
```

冻结 Core 只包含 `core/`、`domain/`、`ports/`、指定的 broker-neutral OMS 文件和独立
Core migration。QMT、driver、Risk、MarketData、Operations、Service 与 Runtime 均是
adapter/extension，不属于 Core ABI。详细边界见
[Core v1 Freeze](docs/CORE_FREEZE_V1_ZH.md) 与
[Core / Runtime Boundary](docs/CORE_RUNTIME_BOUNDARY_ZH.md)。

最小 API：

```python
from bigqmt_autotrader.core import ExecutionCore, OrderIntent

core = ExecutionCore.open(database_path, driver)
core.recover()
result = core.submit(intent)
result = core.cancel(account_fingerprint, client_order_id)
core.close()
```

## 安全不变量

- 策略不能直接调用 QMT mutation API。
- `SHADOW_ACCEPTED`、submit/cancel 返回值和 `command_result` 都不是 broker ACK。
- 只有通过校准 mapper 的 ORDER/DEAL/query `BrokerEvidenceV1` 可以推进 OMS 生命周期。
- identity、session、sequence、quantity 或 terminal facts 冲突时 fail closed；未知结果进入
  `UNKNOWN/RECONCILING/MANUAL_REVIEW`，禁止盲重试。
- persist-before-side-effect、single writer/fencing、durable identity 与重启 replay 是 Core 契约。
- instance discovery 只发现候选，不产生交易授权。

正式规范：

- [BigQMT Bridge API v1](docs/BRIDGE_API_V1_ZH.md)
- [Broker Evidence Contract v1](docs/BROKER_EVIDENCE_CONTRACT_V1_ZH.md)
- [Security Boundary](docs/SECURITY_BOUNDARY.md)

## 已验证能力

- 国金：read-only query/callback、1 秒 command timer、300 秒 reconcile、durable spool、
  Host restart/replay、模拟 submit/cancel、resting/full fill、HGT/SGT 路由、token 保留、
  duplicate/conflict/stale-session/wrong-account/expiry fail-close。
- 银河：STOCK/HUGANGTONG/SHENGANGTONG 运行时发现、linked-account callback suppression、
  terminal-instance spool 隔离；仍无 mutation 授权。
- Host：durable dispatch、leader lease heartbeat、session rollover、archive integrity/readiness、
  Windows backup fsync、BrokerEvidence reconciliation 与语义去重。

P6 的逐项任务、报告和审查保存在 `workflow/`；日期化 Gate 文档保存在 `docs/`，它们是
历史审计证据，不等于当前授权。

## 开发和验证

Host 要求 Python 3.11+，CI 使用 Python 3.12；QMT-side 文件保持 Python 3.6 兼容。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe tools\verify_core_v1_release.py
.\.venv\Scripts\python.exe tools\verify_workflow_contract.py
```

完整迁移与验证命令见[开发环境迁移手册](docs/DEVELOPMENT_ENVIRONMENT_MIGRATION_ZH.md)。

## Workflow

唯一 bootstrap 入口是 `workflow/control/WORKFLOW_STATE.yaml`。Agent/Architect 必须按其中
`bootstrap_*`、`state`、`owner`、`authorized_next` 和 active handoff 执行，不能用日期、
最新文件或 git log 猜任务。协议见 [workflow/README.md](workflow/README.md)。

任何配置、换机或自动发现都不能直接把系统切到通用生产实盘。
