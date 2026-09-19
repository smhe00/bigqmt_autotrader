# 国金模拟 Broker Evidence Mapper Gate — 2026-09-17

## 判定

**GUOJIN_SIM VERSIONED MAPPER：IMPLEMENTED / PASS**

**GUOJIN PRODUCTION MAPPER：DISABLED**

**GALAXY MAPPER：NOT IMPLEMENTED**

**PRODUCTION BROKER MUTATION：ZERO**

本 Gate 只把已经实机校准的国金模拟 ORDER/DEAL/active-query 原始事实转换为
`BrokerEvidenceV1`。它没有新增下单或撤单代码，也没有扩大 `guojin`、`galaxy`
权限。

## Profile 与身份边界

mapper profile 固定为：

```text
qmt-guojin-sim-20260917-v1
```

必须同时满足：

1. `terminal_instance_id == guojin_sim`；
2. event 账户指纹等于 mapper 构造时固定的模拟账户指纹；
3. durable OMS 预先登记 `client_order_id + symbol + original quantity`；
4. `m_strRemark` 严格等于该身份计算出的 22 字符 broker token；
5. broker order ID、trade ID 与累计数量不存在冲突。

任一条件不满足都不产生 broker evidence。

## 已启用的窄映射

| 国金模拟 raw fact | BrokerEvidenceV1 | 额外约束 |
| --- | --- | --- |
| ORDER status 50 / submit 51 | `ORDER_ACCEPTED` | broker ID 已出现、fill=0、remaining=原数量 |
| ORDER status 54 / submit 51 | `ORDER_CANCELLED` | broker ID 存在、fill=0、remaining=原数量 |
| ORDER status 56 / submit 51 | `FULL_FILL` | fill 严格等于原数量 |
| ORDER status 57 / submit 51 | `ORDER_REJECTED` | fill=0 |
| DEAL callback/query | `PARTIAL_FILL` 或 `FULL_FILL` | trade 去重后的累计量，不能超过原数量 |

初始 callback 中 status 50 但 broker ID 为空、remaining=0 的事实明确不能成为
`ORDER_ACCEPTED`。`command_result`、submit API return、cancel API return 仍不属于
broker evidence。

## Active query 与检疫

active snapshot 的 ORDER/DEAL 行通过 `ACTIVE_ORDER_QUERY` /
`ACTIVE_DEAL_QUERY` 进入同一个严格 mapper。一个 snapshot 可以同时包含：

- 已证明行：写入 EvidenceJournal；
- 无法证明行：snapshot 仍更新只读模型，同时整帧保留在语义检疫区供审计。

因此未知行不会阻止账户/持仓读模型恢复，也不会被静默忽略或猜测成 OMS 状态。

## 当日真实 spool 只读回放

对 `guojin_sim` session `5fb8e71cf33e4fd985f68d51185bce21` 的落盘文件进行
只读回放，没有移动或消费文件：

| sequence | raw fact | mapper 结果 |
| --- | --- | --- |
| 224 | status 50，broker ID 为空 | quarantine |
| 225 | status 50，broker ID `4083` | `ORDER_ACCEPTED -> ACKNOWLEDGED` |
| 230 | status 54，broker ID `4083` | `ORDER_CANCELLED -> CANCELLED` |
| 248 | active-query status 54 | `ACTIVE_ORDER_QUERY / ORDER_CANCELLED` |

token 全程为 `BQdfb735bcd645acaaa4bc`，对应 durable client order ID
`cal-20260917-resting-001`。回放只读，不产生 broker mutation。

## 交易时段 closing-auction 补充验证

14:57:29 在同一 `guojin_sim` session 发布一笔受限 BUY 100：

| 项目 | 观察值 |
| --- | --- |
| client order ID | `mapper-20260917-fill-001` |
| broker token | `BQ88f0a220b2a35b94c41c` |
| broker order ID | `5652` |
| 标的 / 限价 | `510300.SH` / `4.600` |
| 集合竞价前 | status `50/51`，filled 0，remaining 100 |
| 15:00 terminal ORDER | status `56/51`，filled 100 |
| DEAL | trade `50043738`，100 份，价格 `4.532` |
| active query | ORDER 与 DEAL 同时收敛，`query_errors=[]` |
| 持仓 | 200 → 300，其中当日新增 100 为 on-road |

实机 mapper 回放结果：

```text
sequence 1017  initial status 50 without broker ID -> quarantine
sequence 1018  ORDER_ACCEPTED / ORDER_CALLBACK
sequence 1026  FULL_FILL / ORDER_CALLBACK
sequence 1028  FULL_FILL / DEAL_CALLBACK
sequence 1033  FULL_FILL / ACTIVE_ORDER_QUERY
sequence 1033  FULL_FILL / ACTIVE_DEAL_QUERY
```

这也验证了收盘集合竞价边界：14:57 后已受理订单保持 status 50，15:00:01
产生 fill callback 和 DEAL。期间没有自动撤单、重复 submit 或第二笔测试订单。

## Fail-closed 回归

测试覆盖：

- status `50/54/56/57` 的合法组合；
- 初始无 broker ID 的 status 50 不得 ACK；
- 未知 status / 未校准 submit status；
- missing、malformed、unregistered token；
- production instance 与 account mismatch；
- broker order ID / trade ID 冲突；
- DEAL 去重、partial/full 累计和 overfill；
- active query 混合已知/未知行；
- Host 已知行入 EvidenceJournal、未知行继续检疫。

## 后续 Gate

下一步不是开放实盘，而是把 durable OMS identity registry 与 Host composition 做成
可恢复、显式启用的运行配置，并用 simulation restart/replay 验证 mapper 状态恢复。
在此之前，mapper 不由普通 Host 自动启用。国金生产与银河仍保持 SHADOW-only。

## 新品种模拟授权记录与当前阻塞

用户已授权后续把受限模拟校准扩展到 `GC001` 逆回购及港股通，但本次没有把该
授权误用为立即 broker mutation：

- 当前 `guojin_sim` manifest 与 executor 只允许 `STOCK`、A 股 BUY 100；
- session `5fb8e71cf33e4fd985f68d51185bce21` 的运行时能力探测只检测到
  `STOCK`，`HUGANGTONG` / `SHENGANGTONG` 均为 `UNCONFIRMED`；
- 官方 passorder 契约确认股票/ETF/可转债及港股通买卖使用 opType `23/24`，
  但 GC001 的回购方向、数量单位、最小金额、价格 tick 仍必须在独立 profile
  中固定并经模拟实测，不能复用普通股票 BUY gate 猜测；
- 国金港股通与 A 股共用同一个 `STOCK` 资金账号；市场由证券代码后缀区分，
  不得臆造第二个资金账号或指纹。

随后已生成 build `p5-simulation-calibration-4`：在同一受限 STOCK 模拟实例内支持
显式 BUY/SELL、数量 `1..100`、六位 `.SH/.SZ` 或五位 `.HK` 证券，BUY/SELL 分别使用
passorder opType `23/24`。这解除原有 BUY-only / exactly-100 限制，可用于下一次
GC001 SELL 校准；其余身份、session、token、价格、次数及撤单 Gate 均保留。

新 artifact 仍需操作员在 Big QMT 中替换并重启后才会生效。港股通复用当前
manifest 固定的 `STOCK` simulation account；`guojin` / `galaxy` 权限没有变化。

后续 build `p5-simulation-calibration-5` 将港股格式扩展为五位
`.HK/.HGT/.SGT`，并加入只读证券身份与精确 tick 探测；本 mapper 的 broker-token、
ORDER/DEAL 和状态语义边界不变。

build `p5-simulation-calibration-6` 进一步增加只读、有界的港股通板块成分发现；
其结果仅用于扩大证券身份/tick 校准样本，不改变 mapper 或订单状态权限。
