# Execution Core v1 Freeze Plan

更新：2026-09-24

## 1. 目标

本文件定义 `bigqmt_autotrader` 的 **Execution Core v1 冻结边界**。

Freeze 的目标不是禁止一切修改，而是冻结以下可观察契约：

- Public API；
- OrderIntent / OrderStatus / FSM 语义；
- durable identity；
- persist-before-side-effect；
- exactly-once submit/cancel 语义；
- UNKNOWN / RECONCILING / MANUAL_REVIEW 语义；
- BrokerEvidence v1；
- leader/fencing；
- Core SQLite schema v1；
- recovery / dedup / conflict fail-close 行为。

冻结后：

- 兼容性 bugfix 可进入 Core 1.0.x；
- 新 broker、QMT route、行情、Risk、Strategy、Operations、Web 等默认进入 Extension；
- 改变上述契约需要 Core major version review。

## 2. Frozen Core candidate

Core v1 candidate 由以下部分组成：

```text
src/bigqmt_autotrader/core/
src/bigqmt_autotrader/domain/
src/bigqmt_autotrader/oms/
  authorization.py
  broker_evidence_v1.py
  db.py
  evidence.py
  leader.py
  repository.py
  service.py
src/bigqmt_autotrader/oms/migrations/
  0001_initial.sql
  0002.sql
  0003.sql
  0004.sql
  0005.sql
  0006.sql
  0007.sql
  0008.sql
```

`oms/__init__.py` 只能导出 Core public/internal surface；QMT-specific export 必须在 F003 前移出。

## 3. Adapter / Extension，不属于 Frozen Core

下列内容不是 Core ABI：

```text
src/bigqmt_autotrader/qmt/
src/bigqmt_autotrader/drivers/qmt_shadow.py
src/bigqmt_autotrader/drivers/simulated.py
src/bigqmt_autotrader/oms/qmt_bridge.py
src/bigqmt_autotrader/oms/command_results.py
src/bigqmt_autotrader/risk/
src/bigqmt_autotrader/market_data/
src/bigqmt_autotrader/operations/
src/bigqmt_autotrader/service/
src/bigqmt_autotrader/strategy_api/
src/bigqmt_autotrader/runtime/
src/bigqmt_autotrader/web/
```

其中：

- QMT 是 Core 的 adapter/consumer，不是 Core 本体；
- broker-specific raw status / route / terminal discovery 不得进入 Core；
- simulation driver 属于测试/reference adapter；
- migrations 9..11 属于 Runtime/历史 combined DB 兼容层，不属于 Core schema v1。

## 4. 当前必须消除的边界穿透

Freeze 前必须修复以下现状：

1. `oms/service.py` 直接依赖 `drivers.simulated.SimulatedDriver` 及其异常类型；
2. `oms/service.py` 仍含 QMT command-result ingestion；
3. `oms/command_results.py` 依赖 `qmt.commands.broker_token_for`；
4. `oms/qmt_bridge.py` 位于 OMS namespace，但语义属于 QMT adapter；
5. 当前 `verify_core_dependency_boundary.py` 将整个 `qmt/` 与 `drivers/` 视为 Core root，边界过宽。

F002/F003 必须将这些依赖改为 broker-neutral port，并让 `qmt/` 只能依赖 Core、不能被 Core 反向依赖。

## 5. Core v1 Public API candidate

冻结入口：

```python
from bigqmt_autotrader.core import (
    CORE_SCHEMA_VERSION,
    ExecutionCore,
    OrderIntent,
    OrderStatus,
    Side,
)
```

核心生命周期：

```python
core = ExecutionCore.open(database_path, driver)
core.recover()
result = core.submit(intent)
result = core.cancel(account_fingerprint, client_order_id)
core.close()
```

上层 Extension 不应依赖 `oms.repository`、`oms.service`、`domain.state_machine` 等内部模块。

## 6. Core schema v1

```text
Core schema v1 = SQLite schema 8
```

Freeze 后：

- Core v1.x 新建数据库必须停在 schema 8；
- schema 9..11 可作为 historical combined DB 的兼容 superset；
- Core v1.x 不允许新增必须表/列；
- 需要改变持久化 contract 时进入新的 Core major version review。

## 7. Freeze Gate

正式 `core-v1.0.0` 前必须完成：

### F001 — Inventory & Boundary
本文件 + machine-readable inventory。

### F002 — ExecutionDriver Port
Core OMS 仅依赖 broker-neutral Protocol，不依赖 SimulatedDriver/QMT。

### F003 — QMT out of Core root
`qmt/` 和 QMT-specific glue 从 Core dependency root 移出；CI 强制 Core -> QMT 为非法。

### F004 — API / Schema / Golden Contract
冻结 Public API、schema 8 snapshot、关键行为 golden scenarios。

### F005 — Release Gate
Core-only import/install/test + Core formal subset + compatibility checks 全绿后，才允许 tag `core-v1.0.0`。

## 8. Change Policy

### Core 1.0.x 允许

- 不改变 public contract 的 bugfix；
- test / formal strengthening；
- performance hardening；
- fail-close strengthening，且不改变已冻结成功路径语义。

### 默认必须进入 Extension

- 新 broker；
- 新 QMT route / terminal；
- 新行情源；
- Risk rule；
- Strategy；
- Operations / Health / Backup；
- Web / Service / Deployment。

### 需要 Core major review

- Public API breaking change；
- FSM / evidence semantics 变化；
- identity / exactly-once / recovery invariant 变化；
- Core schema 变化；
- BrokerEvidence v1 breaking change。
