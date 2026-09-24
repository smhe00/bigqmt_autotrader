# Execution Core / Production Runtime 边界

更新：2026-09-25

## 1. 结论

Execution Core v1 已以 `core-v1.0.0` 冻结。Core 只负责 broker-neutral 的可靠执行；
QMT、Risk、行情和运维都是 adapter/extension。机器权威清单是
`contracts/core/v1/inventory.json`，本文件只解释它。

```text
Production Runtime / adapters
Risk, MarketData, QMT, Operations, Service, Strategy, Web
                         |
                         v
Frozen Execution Core v1
OrderIntent, OMS, evidence, exactly-once, recovery, fencing
                         |
                         v
ExecutionDriver port -> broker adapter
```

## 2. Frozen Core v1

目录：

```text
src/bigqmt_autotrader/core/
src/bigqmt_autotrader/domain/
src/bigqmt_autotrader/ports/
```

加上 `oms/` 内冻结清单指定的 authorization、BrokerEvidence、db、evidence、leader、
repository、service，以及 `oms/core_migrations/0001_initial.sql`。

Public API 从 `bigqmt_autotrader.core` 导出 `ExecutionCore`、`ExecutionDriver`、
`OrderIntent`、`OrderStatus`、`Side`、unknown outcome types 和 Core schema helper。
上层不应依赖 `oms.repository` 等内部模块。

## 3. Adapter / Extension

下列内容不属于 Core ABI：

```text
qmt/              QMT protocol, discovery, spool and OMS glue
drivers/          concrete reference/adapters
risk/             production risk policy
market_data/      market-data models and services
operations/       health, control, backup, telemetry
service/          composition and lifecycle
strategy_api/     strategy-facing runtime
runtime/          production assembly
web/              presentation/API extension
```

依赖方向只能是 Extension → Core。Core import QMT/driver/Runtime 会被
`verify_core_dependency_boundary.py` 拒绝。

## 4. 数据库边界

Core v1 使用独立 `core_schema_meta` 和 Core schema version 1。新 Core-only 数据库不创建
QMT 表。QMT extension 使用独立 `qmt_schema_meta` 与 `qmt/migrations/0001_initial.sql`。

旧的 `oms/migrations/0001..0011` 是 historical combined DB 兼容线。既有 combined schema
7–11 可在验证 Core shape 后被 Core v1 采用；不会 downgrade，也不会删除 extension 表。
新部署应优先使用独立 Core/QMT 数据库边界。

## 5. Risk ownership

Core 接收已经被调用方授权的 `OrderIntent`，负责执行正确性，不负责 Production Risk
policy。Production Runtime 必须在 side effect 前 fail closed 地评估 Risk，再调用 Core。
Core schema 中为兼容历史保留的 risk 命名不代表 Runtime Risk 被重新嵌入 Core。

## 6. QMT ownership

Core 依赖 broker-neutral `ExecutionDriver` port，不 import QMT。QMT command-result journal、
durable token、instance/session discovery 和 mapper 均位于 `qmt/` extension。它们必须遵守
Core identity/evidence contract，但不能改变 Core ABI 或自动扩大 authority。

## 7. 变更规则

Core 1.0.x 允许保持 frozen contract 的 bugfix、性能/测试/形式验证增强和 fail-close 加固。
新的 broker、route、行情、Risk、Strategy、Operations、Service、Web 默认进入 Extension。

改变 Public API、FSM/evidence、identity/exactly-once/recovery 或 Core schema，需要 Core major
review。详细 policy 见 [CORE_FREEZE_V1_ZH.md](CORE_FREEZE_V1_ZH.md)。

## 8. 永久 Gate

```powershell
python tools\verify_core_dependency_boundary.py
python tools\verify_core_v1_release.py
pytest -q tests\core
```

CI 的 `core-v1-release` job 永久执行以上边界；主 formal job 还保证冻结模型持续被检查。
