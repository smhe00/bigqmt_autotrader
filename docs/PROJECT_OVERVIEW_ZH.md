# bigqmt_autotrader 中文总览

更新：2026-09-17

## 1. 项目目标

`bigqmt_autotrader` 的目标不是做一个“会调用 QMT 下单函数的脚本”，而是做一个面向个人账户、可恢复、可审计、默认 fail-closed 的自动交易执行平台。

Big QMT 被定位为 **券商执行终端 / Broker Gateway**。复杂策略、OMS、风险控制、数据库和分析运行在外部 Host（Python 3.12）；QMT 内置 Python 3.6 只保留薄的 Bridge。

当前第一生产目标仍然刻意收窄为：

- A 股普通现金账户；
- 普通现货证券；
- LIMIT 买卖；
- 低频 / 分钟级策略；
- 单 OMS writer；
- durable reconciliation；
- 明确的人为授权边界。

## 2. 当前 Gate 状态

| 阶段 | 状态 |
| --- | --- |
| P0 / G0 领域模型 | **PASS** |
| P1 Offline OMS | **PASS** |
| P2 Risk Engine | **PASS** |
| P3 Big QMT read-only | **PASS** |
| P4 SHADOW execution bridge | **DEPLOYMENT GATE PASS** |
| P5 国金模拟账户 submit/cancel/fill 校准 | **BOUNDED CALIBRATION PASS** |
| Production live trading | **NO** |
| 国金 LIVE_CANARY | **代码已实现，尚未部署/武装/实机校准** |

`galaxy` 和 `guojin` production artifacts 仍然在源代码级禁用 broker mutation。

`guojin_sim` 是 fingerprint-pinned 的模拟账户校准 artifact，只用于 simulation calibration，不能被解释成生产实盘授权。

## 3. 核心架构

```text
Market Data / Account State
            |
            v
      Strategy Service
      只产生 OrderIntent
            |
            v
        Risk Engine
      下单前风险判断
            |
            v
           OMS
  订单身份/状态/恢复/审计
            |
            v
        Host Driver
            |
      BigQMT Bridge API v1
            |
            v
    Execution Bridge (QMT)
            |
            v
        Big QMT / Broker
```

Broker 的 ORDER / DEAL / query evidence 反向进入 Host，经过 mapper 和 replay-safe evidence ingestion 后再推动 OMS 状态。

## 4. OMS 是什么

OMS = Order Management System。

它回答的是：

> 一张订单从创建、风险通过、提交、券商确认、部分成交、成交、撤单、异常到恢复，整个生命周期怎样可靠管理？

OMS 负责：

- `client_order_id` 唯一性；
- durable order state；
- persist-before-side-effect；
- submit/cancel reservation；
- broker order ID；
- UNKNOWN / RECONCILING；
- callback/query reconciliation；
- crash/restart recovery；
- duplicate evidence 去重；
- audit trail；
- single-writer/fencing。

策略不能直接调用 broker/QMT mutation API。

## 5. Risk Engine 是什么

Risk Engine 回答的是：

> 这张 OrderIntent 当前是否允许进入执行路径？

它位于策略和 OMS broker side-effect 之间，采用 fail-closed 规则。

当前风险模型覆盖 Global → Account → Strategy → Security/Order 的确定性优先级，并且 P2 authority policy 只允许 `SIMULATION` eligibility；配置本身不能把系统切到生产 live。

## 6. Execution Bridge 做什么

Execution Bridge 是 QMT 侧薄适配器，职责限定为：

- ACCOUNT / POSITION / ORDER / DEAL query；
- callback；
- snapshot；
- Host command consumption；
- broker token identity；
- 在被明确授权的 simulation artifact 中调用受限 submit/cancel；
- durable local spool。

它不承载：

- 策略；
- Risk Engine；
- OMS；
- ML；
- 数据分析；
- 复杂数据库；
- 自动扩大交易权限。

## 7. Host 与 Bridge 的标准契约

Host↔Bridge 已正式定义为：

**BigQMT Bridge API v1**

中文规范：

- [`BRIDGE_API_V1_ZH.md`](BRIDGE_API_V1_ZH.md)

API v1 包含：

- instance discovery / handshake；
- Command Protocol 0.1；
- Event Protocol 0.2；
- File Transport 1；
- JSON Schema；
- TLA+/TLC safety model；
- Python conformance / static audit。

关键原则：

```text
SHADOW_ACCEPTED != broker ACK
```

`command_result` 是 control-plane 信息，不能直接把 OMS 推成 `ACKNOWLEDGED/FILLED/CANCELLED`。

## 8. 当前已实机验证

国金 Big QMT：

- CPython 3.6.8；
- QMT 2.1.19.0；
- read-only query/callback；
- 1 秒 command timer；
- 300 秒 active reconcile；
- Host restart replay；
- durable spool；
- simulation submit；
- simulation cancel；
- resting order；
- full fill；
- ORDER/DEAL token preservation；
- Host outage recovery；
- duplicate/conflict/stale-session/wrong-account/expiry 等 fail-closed 检查。

Galaxy Big QMT：

- QMT 2.1.26.1；
- runtime account-type discovery；
- STOCK / HUGANGTONG / SHENGANGTONG；
- linked-account callback suppression；
- instance isolation。

国金模拟账户新增了版本化 broker evidence mapper：

- profile：`qmt-guojin-sim-20260917-v1`；
- 仅接受 `guojin_sim` 与固定账户指纹；
- durable OMS 必须先登记 `client_order_id + symbol + quantity`；
- exact `m_strRemark` 才能还原订单身份；
- 已校准 status `50/54/56/57`，并支持 DEAL 累计成交与 active-query 证据；
- 初始无 broker order ID 的 status `50`、未知状态、缺 token、身份/数量冲突全部检疫。

该 mapper 不适用于 `guojin` 实盘，也不会通过自动发现启用。`galaxy` 仍无 broker
status mapper。

国金模拟 V5 build `p5-simulation-calibration-4` 已解除原先的 BUY-only / 必须 100
份限制：现在要求显式 `BUY` 或 `SELL`，数量为 `1..100`，证券代码为六位
`.SH/.SZ` 或五位 `.HK`。国金港股通复用清单固定的 `STOCK` 模拟账号，交易市场
不再被错误建模为第二个账户。BUY/SELL 分别映射 passorder opType `23/24`。账户指纹、当前
session、simulation-only、token、价格、次数和撤单身份 Gate 均保留；生产文件不变。

## 9. 为什么 simulation 已经能下单，但 production 仍不能下单

这是刻意设计的权限隔离。

```text
guojin_sim
  execution_mode = SIMULATION_CALIBRATION
  simulation_only = true
  fingerprint pinned
  finite mutation fuse
```

而：

```text
guojin / galaxy
  execution_mode = SHADOW
  trading_enabled = false
  live_submit = false
  live_cancel = false
```

并且静态审计要求 production artifact 中 broker mutation call surface 为零。

所以“技术上已验证下单链路”和“生产账户获得实盘权限”是两件完全不同的事。

## 10. 为什么重复撤单要特别处理

盘后校准已经观察到：

- QMT `cancel()` 可以返回成功；
- broker/query surface 可能暂时仍显示原状态；
- 此时再次 cancel 可能变成 broker-side repeated-cancel。

因此 simulation publisher 已改成：

> 对同一 account + client order ID + broker order ID，只允许发布一次 cancel command。

query lag 不能触发自动重撤。必须等 broker evidence 收敛或人工处理。

## 11. 行情数据架构方向

执行和行情不应塞进同一个 Bridge。

规划结构：

```text
                    Host
             ┌───────┴────────┐
             │                │
     MarketDataService      OMS / Risk
             │                │
   ┌─────────┴───────┐        │
   │                 │        │
QMT Market        mktdata   Execution
Data Bridge       history    Bridge
   │                          │
Big QMT Quote                Big QMT Broker
```

### Execution Bridge

继续保持：

- 小；
- 可审计；
- durable；
- fail-closed；
- 专门处理账户/订单/成交/submit/cancel。

### Market Data Bridge（规划，尚未实现）

未来单独 QMT 策略负责：

- latest quote；
- tick subscription；
- 1m/5m bar；
- instrument/reference data；
- feed/session/latency health。

它可以复用 Bridge API v1 的 versioning/discovery/envelope 原则，但不会继承 execution mutation authority。

历史数据优先继续由 `mktdata` / 本地数据层承担，不把 Execution Bridge 做成 XtData 克隆。

## 12. 下一阶段

当前最重要的后续工作：

1. Broker ORDER/DEAL/query → 标准 OMS evidence mapper；
2. replay-safe OMS evidence convergence；
3. partial fill / cancel race / reject / disconnect / restart soak；
4. 保持 production artifact mutation-free；
5. 国金 LIVE_CANARY 只按 P6 独立 Gate 部署；银河仍禁止 mutation；
6. Market Data Bridge 另行立项，不与 execution safety surface 混合。

详细状态见：

- [`PROJECT_STATUS.md`](PROJECT_STATUS.md)
- [`FORMAL_VERIFICATION.md`](FORMAL_VERIFICATION.md)
- [`P5_GATE_RESULT_20260916.md`](P5_GATE_RESULT_20260916.md)
