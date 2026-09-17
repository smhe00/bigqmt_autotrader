# Broker Evidence Runtime Conformance Gate Result — 2026-09-17

## 判定

**BROKER EVIDENCE RUNTIME CONFORMANCE GATE：PASS**

**GUOJIN/GALAXY PRODUCTION MUTATION：仍为 ZERO**

**GUOJIN RAW STATUS MAPPER：仍未启用**

本 Gate 修复 `BROKER_EVIDENCE_RUNTIME_CONFORMANCE_AUDIT_ZH.md` 记录的通用 OMS
运行时缺口。它没有把任何国金或银河原始状态码直接映射成 OMS 生命周期，也没有
授权生产账户下单、撤单或 LIVE_CANARY。

## 已完成的运行时边界

1. 新增强类型 `BrokerEvidenceV1`，运行时校验版本、来源权限、证据类型与目标状态、
   身份字段、数量约束以及标准语义摘要。
2. `EvidenceJournal` 的唯一 broker-fact 输入改为完整 `BrokerEvidenceV1`；自由组合
   `source/evidence_type/requested_status` 的旧入口已删除。
3. SQLite schema 升级到 v6：证据身份键改为
   `(source, account_fingerprint, source_event_id)`，并持久化 `source_kind`、
   `mapper_profile`、`semantic_digest`、`broker_token`、`order_ref`、`trade_id`、
   `raw_payload_ref` 与 `raw_status`。
4. 同 ID 不同摘要、broker order ID 改变、不同 terminal broker facts、
   `CANCELLED/REJECTED` 后新增更高累计成交量全部 fail closed 到
   `MANUAL_REVIEW`，不再被普通 terminal absorption 当作 stale 静默忽略。
5. broker evidence 使用独立单调聚合器；它不依赖 submit/cancel command-path FSM
   是否恰好存在某条边。
6. `OfflineOms` 不再把 submit/cancel API 返回值直接写成 `ACKNOWLEDGED` 或
   `CANCELLED`。API 返回只记录 transport/control outcome；随后必须由 active order
   query 生成标准 `BrokerEvidenceV1` 才能推进 lifecycle。
7. QMT Host mapper/sink 边界已改为完整标准对象；`command_result` 和模拟 API 返回
   仍不能进入 broker evidence journal。

## 交易时段校准证据

在 `guojin_sim`、session `5fb8e71cf33e4fd985f68d51185bce21` 中完成一轮最小
正常撤单闭环：

| 项目 | 观察值 |
| --- | --- |
| 标的/方向/数量 | `510300.SH` BUY 100 |
| 下单价 / 当时持仓快照价 | `4.000` / `4.54` |
| client order ID | `cal-20260917-resting-001` |
| broker token / `m_strRemark` | `BQdfb735bcd645acaaa4bc` |
| broker order ID | `4083` |
| 初始 ORDER | status `50`, submit status `51`, filled `0`, remaining `100` |
| 撤单终态 ORDER | status `54`, submit status `51`, filled `0`, remaining `100` |
| command results | submit call returned；单次 cancel signal sent |
| DEAL | 无 |

该次委托明显低于观察价，未成交；撤单只发布一次。Host 在 broker-specific mapper
启用前继续把三条 raw ORDER 事件放入语义检疫区，没有将 status `50/54` 猜测为 OMS
状态。今日初始 active snapshot 的 `orders=[]`、`deals=[]` 也证明前一交易日订单未被
错误带入今日 read model。

## 回归与永久 Gate

- Python：`300 passed`；
- runtime/reference finite differential：全部非冲突组合一致；terminal conflict 由独立
  end-to-end 测试覆盖；
- Broker Evidence finite contract：`7200 cases PASS`；
- FSM exhaustive：`196 pairs PASS`；
- Bridge event finite matrix：`4608 transitions PASS`；
- Bridge command idempotency/conflict/expiry：PASS；
- Bridge Schema drift：PASS；
- side-effect surface audit：PASS；
- standalone QMT deployment check：PASS；
- production QMT artifacts：template/galaxy/guojin broker mutation calls 均为 `0`。

TLA+ 模型没有在本变更中修改，GitHub CI 继续运行全部十个 pinned TLC checks。

## 下一 Gate

下一阶段可以开始国金 mapper，但必须保持两段式：

```text
raw ORDER/DEAL/query
  -> calibrated Guojin mapper
  -> BrokerEvidenceV1 validation
  -> EvidenceJournal
```

status `50/54/56/57` 只能在版本化、实机校准的 mapper profile 中解释。未知状态、
缺 token、账户不匹配、broker ID 冲突和数量矛盾继续 quarantine，不得猜测。

