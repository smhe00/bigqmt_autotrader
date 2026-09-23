# Execution Core / Production Runtime 边界

更新：2026-09-23

## 1. 两层产品

项目现在明确拆成两个层级：

```text
Production Runtime
  Risk / MarketData / Health / Operations / Telemetry
  Strategy heartbeat / Calendar / Deployment / Backup
                 |
                 | one-way dependency
                 v
Execution Core
  OrderIntent / OMS / durable dispatch
  broker evidence / exactly-once / recovery
                 |
                 v
QMT Bridge / Broker
```

Execution Core 面向只需要可靠下单、撤单、恢复和订单生命周期管理的使用者；Production Runtime 是可选增强层。

设计目标类似 MiniQMT + QMT：Core 小、稳定、低依赖；Runtime 在其上增加生产级治理。

## 2. 永久依赖规则

依赖只能向下：

```text
Production Runtime -> Execution Core -> QMT / Broker
Execution Core -X-> Production Runtime
```

Core roots：

```text
core/
domain/
drivers/
oms/
qmt/
```

禁止 import Runtime roots：

```text
risk/
market_data/
operations/
service/
strategy_api/
runtime/
web/
```

CI 永久执行：

```bash
python tools/verify_core_dependency_boundary.py
```

任何反向依赖都会直接使 CI 失败。

## 3. Core 最小入口

最简使用入口：

```python
from bigqmt_autotrader.core import ExecutionCore
```

Core 只负责执行正确性：

- OrderIntent 身份和参数；
- durable order state；
- single writer / fencing；
- persist-before-side-effect；
- exactly-once submit/cancel；
- UNKNOWN / RECONCILING；
- broker evidence；
- restart recovery；
- duplicate/conflict fail-close。

Core 不要求 RiskPolicy、RiskSnapshot、MarketDataService、Strategy heartbeat、RuntimeMode、HealthRegistry、Telemetry、Calendar 或 Deployment Guard。

## 4. Risk ownership 上移

历史版本中 OfflineOms.submit_intent() 内部调用 Risk Engine。现在改为：

```text
Core mode:
OrderIntent
  -> OfflineOms.submit_intent()
  -> deterministic execution authorization
  -> durable execution

Production Runtime:
OrderIntent
  -> RiskManagedOms
  -> evaluate_risk()
  -> RiskDecision
  -> OfflineOms.submit_authorized_intent()
  -> durable execution
```

因此 OMS 源码不再 import Risk Engine。

数据库中的 risk_decisions / RISK_ACCEPTED 名称暂时保留，以兼容已有 durable schema 和历史数据；在 Core 模式中它表示 execution authorization，而不是 Production Risk policy evaluation。

## 5. 数据库边界

```text
CORE_SCHEMA_VERSION      = 8
SUPPORTED_SCHEMA_VERSION = 11
```

新建 Core 数据库使用 initialize_core_database(conn)，只执行 migration 1..8，因此不会创建 daily_risk_events、runtime_mode_transitions、operations_alert_events 等 Runtime 表。

完整 Production Runtime 继续使用 initialize_database(conn)，迁移到 schema 11。

已经升级到 schema 9..11 的历史 combined database 仍可以被 Core 打开；Core 不 downgrade、不删除 Runtime 表，也不重复执行 Runtime migration。

新部署建议逻辑上区分：

```text
core_oms.sqlite3   Execution Core
runtime.sqlite3    Production Runtime / operations
```

当前 schema 11 为历史兼容仍是 1..11 的 superset；关键保证是 Core-only 数据库不再依赖 Runtime migrations。

## 6. guojin_sim 进入 Core 边界

GuojinSimOmsRuntime.execute_intent() 现在只接受 OrderIntent：

```python
execute_intent(intent)
```

不再接受 RiskSnapshot / RiskPolicy。

仍保留 exact guojin_sim terminal、SIMULATION_CALIBRATION、simulation_only、账户/build pinning、immutable dispatch、broker token、quantity/mutation fuse、no blind retry 和 broker-evidence lifecycle authority。

本次隔离没有扩大 production Guojin / Galaxy / generic 的 mutation authority。

## 7. Production Runtime

完整生产能力通过 bigqmt_autotrader.runtime 或 service 层组合 Core。

Runtime 可继续扩展 Risk、Market Data、Health、Operations、Telemetry、Alerting、Lifecycle、Deployment 和 Backup，但这些扩展不能再次成为 Core 的 import 前置条件。

## 8. 验证 Gate

Core/Runtime 隔离必须同时满足：

1. Core-only database 停在 schema 8；
2. Core submit 不需要任何 Runtime object；
3. Core restart/recovery 独立工作；
4. clean Python process import bigqmt_autotrader.core 时不得加载 Runtime modules；
5. static AST dependency Gate；
6. 原有 broker side-effect surface audit；
7. 全量 pytest；
8. 全部 formal/TLC。

## 9. 设计结论

以后 Execution Core 修改应非常谨慎，主要围绕执行正确性和 broker lifecycle；Production Runtime 可以快速迭代，但只能依赖 Core。

目标是：即使上层 Runtime 继续增长，最小可靠下单系统仍保持小、稳定、可独立测试、可独立使用。
