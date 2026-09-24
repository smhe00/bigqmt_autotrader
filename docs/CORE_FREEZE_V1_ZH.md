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

Core v1 冻结边界由以下部分组成：

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
src/bigqmt_autotrader/ports/
src/bigqmt_autotrader/oms/core_migrations/
  0001_initial.sql
```

`oms/__init__.py` 只导出 broker-neutral Core surface；QMT command-result glue 已迁入 `qmt/`。

## 3. Adapter / Extension，不属于 Frozen Core

下列内容不是 Core ABI：

```text
src/bigqmt_autotrader/qmt/
src/bigqmt_autotrader/drivers/qmt_shadow.py
src/bigqmt_autotrader/drivers/simulated.py
src/bigqmt_autotrader/qmt/oms_bridge.py
src/bigqmt_autotrader/qmt/command_results.py
src/bigqmt_autotrader/qmt/durable_identity.py
src/bigqmt_autotrader/qmt/migrations/
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
- 原有 `oms/migrations/0001..0011` 仅保留为历史 combined DB 兼容线；
- 新 Core-only DB 使用独立 `core_schema_meta` + `oms/core_migrations`；
- QMT 使用独立 `qmt_schema_meta` + `qmt/migrations`。

## 4. 已完成的边界收敛

- F002：OMS 改为依赖 broker-neutral `ExecutionDriver` Protocol；
- F003：QMT command-result journal/sink 已迁出 OMS；
- F003：`qmt/` 与 `drivers/` 已从 Core dependency roots 移除，并成为 Core forbidden imports；
- F004：QMT durable identity 逻辑迁出 `OmsRepository`；
- F004：Core / QMT 使用独立 schema lineage。

## 5. Core v1 Public API

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
Core schema v1 = independent Core schema version 1
```

Freeze 后：

- Core v1.x 新建数据库只创建 broker-neutral Core 表，禁止创建 `qmt_*` 表；
- historical combined schema 7..11 可在验证 Core shape 后原地采用为 Core v1；
- historical combined schema 11 继续由原 legacy migrator 维护，不做 downgrade；
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
冻结 Public API、独立 Core schema v1 snapshot、关键行为 golden scenarios。

### F005 — Release Gate
已固化独立 `core-v1-release` CI job：Core-only tests + dependency boundary + release contract。
Core formal subset 由 `contracts/core/v1/formal_models.json` 锁定，并要求主 CI 持续执行。
所有 Gate 全绿后，release identity 为 `core-v1.0.0`。

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

## 9. Freeze 后维护规则

`contracts/core/v1/` 是 Core v1 的机器可读冻结契约。CI 会阻止：

- Public API export 漂移；
- OrderIntent / OrderStatus contract 漂移；
- Core schema 表/列漂移；
- Core import QMT / Driver / Runtime / Risk / Operations 等扩展层；
- Core-only import 隐式加载扩展；
- Core formal model 从 CI 中消失。

Core v1 的修改默认按补丁版本处理；只有保持上述 contract 完全兼容才允许进入 1.0.x。
