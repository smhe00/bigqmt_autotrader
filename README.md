# bigqmt_autotrader

个人生产级 Big QMT 自动交易执行平台。项目把 **Big QMT 定位为券商执行终端**，策略、OMS、风险控制、数据库和恢复逻辑运行在外部 Host。

> 中文总览：[`docs/PROJECT_OVERVIEW_ZH.md`](docs/PROJECT_OVERVIEW_ZH.md)  
> Host↔Bridge 正式契约：[`docs/BRIDGE_API_V1_ZH.md`](docs/BRIDGE_API_V1_ZH.md)  
> Broker→OMS 证据正式契约：[`docs/BROKER_EVIDENCE_CONTRACT_V1_ZH.md`](docs/BROKER_EVIDENCE_CONTRACT_V1_ZH.md)

## 当前安全状态

| 项目 | 状态 |
| --- | --- |
| P0 / G0 订单领域模型 | **PASS** |
| P1 Offline OMS | **PASS** |
| P2 Deterministic Risk Engine | **PASS** |
| P3 Big QMT read-only | **PASS** |
| P4 SHADOW execution bridge | **DEPLOYMENT GATE PASS** |
| P5 国金模拟账户 submit/cancel/fill 校准 | **BOUNDED CALIBRATION PASS** |
| BigQMT Bridge API v1 | **正式契约 + 永久 CI Gate** |
| Broker Evidence Contract v1 | **协议封版 + 永久形式验证 Gate** |
| Guojin simulation raw status mapper | **PASS（仅 `guojin_sim`）** |
| Production Guojin / Galaxy mapper | **尚未实现/未授权** |
| Production live trading | **NO** |
| 国金 LIVE_CANARY | **仅 P6 两个 fingerprint-pinned 单次案例；build-6 已部署校验，仍非通用 LIVE** |

当前部署基线：

```text
generic / galaxy = p4-shadow-command-spool-5       SHADOW, mutation-free
guojin_sim      = p5-simulation-calibration-7      simulation-only calibration
guojin          = p6-guojin-live-canary-6          two named P6 canary cases only
```

静态审计保证 generic / `galaxy` 没有 broker mutation call surface；`guojin` 只允许
P6 独立 Gate 固定的 LIVE_CANARY 调用面，任何扩权都必须经过新的明确 Gate。

`guojin_sim` 是 fingerprint-pinned 的 simulation calibration artifact。它能调用受限模拟账户 submit/cancel API，但**不构成生产实盘授权**。

## 架构

```text
Market / Account State
        |
        v
    Strategy
  emits OrderIntent
        |
        v
    Risk Engine
        |
        v
       OMS
 identity/state/recovery/audit
        |
        v
      Host
        |
 BigQMT Bridge API v1
        |
        v
 Execution Bridge (QMT)
        |
        v
 Big QMT / Broker

ORDER / DEAL / active query
        |
        v
broker-specific mapper        ← 下一实现 Gate
        |
        v
Broker Evidence Contract v1   ← 已封版
        |
        v
EvidenceReplay -> OMS FSM
```

### OMS

OMS（Order Management System）负责订单的 durable identity、生命周期、submit/cancel reservation、UNKNOWN/reconciliation、重启恢复、broker evidence 去重和审计。

### Risk Engine

Risk Engine 在 broker side effect 前执行 fail-closed 风险判断。策略不能直接调用 QMT/broker mutation API。

## BigQMT Bridge API v1

Host↔Bridge 正式分成三层：

1. **Wire Contract**：JSON Schema；
2. **Semantic Contract**：session / sequence / duplicate / gap / UNKNOWN / resync / evidence boundary；
3. **Safety Contract**：TLA+/TLC + Python conformance + static audit。

当前 umbrella API 保留已经实机校准的 wire version：

```text
Discovery Contract 1
Command Protocol   0.1
Event Protocol     0.2
File Transport     1
```

关键不变量：

```text
SHADOW_ACCEPTED != broker ACK
```

`command_result` 是 control-plane 结果，不能单独产生 `ACKNOWLEDGED / FILLED / CANCELLED` 等 OMS broker lifecycle 状态。

详细规范见 [`docs/BRIDGE_API_V1_ZH.md`](docs/BRIDGE_API_V1_ZH.md)。

## Broker Evidence Contract v1

Broker raw ORDER/DEAL/query 不允许直接写 OMS state，而必须先经过已校准的 broker-specific mapper，输出 broker-neutral `BrokerEvidence v1`。

核心规则：

```text
command_result / submit return / cancel return
    !=
BrokerEvidence
```

以及：

```text
identity mismatch / unknown raw status
    -> quarantine
    -> NO OMS MUTATION
```

标准 evidence 只包括：

- `ORDER_ACCEPTED -> ACKNOWLEDGED`
- `PARTIAL_FILL -> PARTIALLY_FILLED`
- `FULL_FILL -> FILLED`
- `ORDER_CANCELLED -> CANCELLED`
- `ORDER_REJECTED -> REJECTED`

聚合采用单调事实，不使用“最新时间戳覆盖旧事实”。不同 terminal facts 冲突时进入 `MANUAL_REVIEW`，而不是猜测优先级。

详细规范见 [`docs/BROKER_EVIDENCE_CONTRACT_V1_ZH.md`](docs/BROKER_EVIDENCE_CONTRACT_V1_ZH.md)。

## 已验证的 Big QMT 能力

国金 Big QMT 已完成：

- ACCOUNT / POSITION / ORDER / DEAL query + callback；
- 1 秒 command timer；
- 300 秒主动 reconcile；
- durable file spool；
- Host restart replay；
- simulation submit；
- simulation cancel；
- resting order / full fill；
- ORDER/DEAL broker token 保留；
- duplicate / conflict / expiry / wrong-account / stale-session fail-close；
- 重复撤单发布抑制；
- Host 离线期间 QMT 事件持久化及重启恢复。

Galaxy Big QMT 已完成：

- STOCK / HUGANGTONG / SHENGANGTONG runtime discovery；
- linked-account callback suppression；
- terminal-instance spool 隔离。

## 行情数据方向

Execution Bridge 不会扩成 XtData 克隆。

未来计划独立建设 **QMT Market Data Bridge**，专门处理 quote/tick/bar/reference data；Host 通过统一 `MarketDataService` 消费。Execution Bridge 继续保持小、可审计、只处理账户和交易执行。

这部分目前是架构规划，**尚未实现**。

## 形式验证

永久 Gate 当前包括：

- `OrderFSM`
- `SubmitProtocol`
- `LeaderLease`
- `EvidenceReplay`
- `PreSubmitRecovery`
- `RiskPrecedence`
- `BridgeCommandProtocol`
- `BridgeEventProtocol`
- `BrokerEvidenceBoundary`
- `BrokerEvidenceContract`

CI 同时执行：

- Python tests；
- FSM / Bridge protocol / Broker Evidence finite conformance；
- JSON Schema contract drift checks；
- broker side-effect static audit；
- standalone QMT deployment consistency check；
- 全部 TLC model checking。

详细说明见 [`docs/FORMAL_VERIFICATION.md`](docs/FORMAL_VERIFICATION.md)。

## 本地开发

```bash
python -m pip install -e ".[test]"
pytest -q
python tools/verify_fsm_exhaustive.py
python tools/verify_bridge_protocol_exhaustive.py
python tools/verify_bridge_schema_contract.py
python tools/verify_broker_evidence_contract.py
```

项目状态见 [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md)。

**任何阶段都不能通过配置直接跳到生产实盘。**


## Agent workflow

Architect 任务、Agent 执行报告和 Architect 审计不放入 `docs/`。统一使用：

- `workflow/tasks/`
- `workflow/reports/`
- `workflow/reviews/`
- `workflow/control/WORKFLOW_STATE.yaml`

命名、匹配和排序规则见 [`workflow/README.md`](workflow/README.md)。
