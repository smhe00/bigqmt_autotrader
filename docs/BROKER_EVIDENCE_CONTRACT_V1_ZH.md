# Broker Evidence Contract v1

状态：**Architecture Contract / Permanent Safety Gate**

日期：2026-09-17

## 1. 目的

`Broker Evidence Contract v1` 定义“券商原始事实”进入 OMS 之前必须满足的 broker-neutral 语义边界。

它解决的问题不是某一家券商的状态码翻译，而是：

```text
QMT / Broker raw ORDER, DEAL, active query
            ↓
   calibrated broker-specific mapper
            ↓
        BrokerEvidence v1
            ↓
       EvidenceReplay
            ↓
          OMS FSM
```

OMS 只消费 `BrokerEvidence v1`，不直接理解国金、银河、MiniQMT 或其他券商的原始 `status_code`。

本契约当前只冻结**协议、语义和安全边界**。券商专用 mapper 仍是下一阶段实现工作，不在本 Gate 中完成。

## 2. 与 BigQMT Bridge API v1 的关系

`BigQMT Bridge API v1` 负责 Host↔Bridge 的发现、命令、事件、session/sequence 和 durable transport。

`Broker Evidence Contract v1` 位于其上层：

```text
Bridge API v1
  ├── command_result              control-plane evidence
  ├── order / deal events
  └── active ORDER / DEAL query
             ↓
Broker-specific mapper
             ↓
Broker Evidence Contract v1
             ↓
OMS
```

关键边界：

```text
command_result != BrokerEvidence
```

以下结果无论如何都不能直接生成 broker lifecycle evidence：

- `SHADOW_ACCEPTED`
- `SIMULATION_SUBMIT_CALL_RETURNED`
- `SIMULATION_CANCEL_SIGNAL_SENT`
- `SIMULATION_CANCEL_NOT_SENT`
- 任意 submit/cancel 本地函数返回值

`cancel()` 返回“请求已发出”也不等于 `CANCELLED`。

## 3. Wire Contract

标准 Schema：

```text
schemas/broker_evidence/v1/broker_evidence.schema.json
```

`BrokerEvidence v1` 必须包含：

```text
evidence_version
source
source_kind
source_event_id
mapper_profile
semantic_digest

account_fingerprint
client_order_id
broker_token
broker_order_id
order_ref
trade_id

evidence_type
requested_status
filled_quantity

observed_at_ms
raw_payload_ref
raw_status (optional)
```

### 3.1 字段语义

| 字段 | 语义 |
| --- | --- |
| `evidence_version` | 固定为 `1` |
| `source` | broker adapter / QMT bridge 的稳定来源标识，不承担权限 |
| `source_kind` | `ORDER_CALLBACK` / `DEAL_CALLBACK` / `ACTIVE_ORDER_QUERY` / `ACTIVE_DEAL_QUERY` |
| `source_event_id` | 来源内逻辑事件的稳定唯一身份，用于 dedup |
| `mapper_profile` | 已校准 mapper 的版本化 profile，例如未来可用 `qmt-guojin-order-v1` |
| `semantic_digest` | 标准 evidence 语义内容的 SHA-256 摘要，用于检测同 ID 异内容冲突 |
| `account_fingerprint` | OMS durable account identity |
| `client_order_id` | OMS durable order identity；生成 evidence 前必须已经被可靠解析 |
| `broker_token` | 可选 broker correlation token；QMT mapper 必须校验当前项目的确定性 `BQ...` token |
| `broker_order_id` | 券商订单 ID；一旦 OMS 固定后不可被不同值替换 |
| `order_ref` | 可选 broker/order reference，只是辅助身份 |
| `trade_id` | 可选 trade identity；`DEAL_CALLBACK` 必须有稳定 trade ID |
| `evidence_type` | 标准化 broker 事实类型 |
| `requested_status` | evidence 请求 OMS 聚合到的标准 lifecycle status |
| `filled_quantity` | **累计成交量**，不是成交增量 |
| `observed_at_ms` | 来源观察时间；不能被用作“新时间覆盖旧事实”的依据 |
| `raw_payload_ref` | 可审计回原始 ORDER/DEAL/query payload 的引用 |
| `raw_status` | 可选保存原始状态码，仅供审计/校准；OMS 不解释它 |

## 4. 标准 evidence 类型

v1 定义五类：

| `evidence_type` | `requested_status` | 可接受来源 |
| --- | --- | --- |
| `ORDER_ACCEPTED` | `ACKNOWLEDGED` | ORDER callback / active ORDER query |
| `PARTIAL_FILL` | `PARTIALLY_FILLED` | ORDER/DEAL callback / active ORDER/DEAL query |
| `FULL_FILL` | `FILLED` | ORDER/DEAL callback / active ORDER/DEAL query |
| `ORDER_CANCELLED` | `CANCELLED` | ORDER callback / active ORDER query |
| `ORDER_REJECTED` | `REJECTED` | ORDER callback / active ORDER query |

### 4.1 `ACKNOWLEDGED`

只有当 broker order 已经被可靠观察到时才能生成。

至少要求：

- identity 校验通过；
- `broker_order_id` 非空；
- broker-specific mapper 已校准该 raw 状态为“券商已接收/订单已存在”；
- `filled_quantity == 0`。

禁止使用：

- `command_result`；
- `passorder()` 返回值；
- submit API 调用完成；
- Host 成功写入 command spool；

作为 `ACKNOWLEDGED` 证据。

### 4.2 `PARTIALLY_FILLED`

至少要求：

- identity 校验通过；
- `broker_order_id` 非空；
- `filled_quantity > 0`；
- 累计成交量小于 durable OMS order quantity；
- DEAL 来源必须已经 dedup 后转换为**累计成交量**。

`BrokerEvidence` 不使用“本次成交增量”作为 `filled_quantity`。

### 4.3 `FILLED`

至少要求：

- identity 校验通过；
- `broker_order_id` 非空；
- mapper/aggregator 能证明累计成交量等于 durable OMS order quantity；
- 原始 ORDER/DEAL/query 事实与订单数量一致。

### 4.4 `CANCELLED`

只有 broker lifecycle 事实能够生成：

- ORDER callback 明确确认取消终态；或
- active ORDER query 明确确认取消终态。

以下事实不能生成 `CANCELLED`：

```text
cancel() returned success
SIMULATION_CANCEL_SIGNAL_SENT
本地 command_result
```

部分成交后撤单是合法的：

```text
status = CANCELLED
filled_quantity > 0
```

已成交量必须保留，不得归零。

### 4.5 `REJECTED`

只有已校准的 ORDER callback / active ORDER query 可以产生 broker-level `REJECTED`。

它与：

- `RISK_REJECTED`
- command safety-gate rejection
- expired command
- local validation error

完全不同。

v1 要求 `ORDER_REJECTED.filled_quantity == 0`。如果系统已经确认存在成交，再出现 broker rejected 终态，属于 terminal conflict，必须 fail closed。

## 5. Identity Contract

mapper 在创建 `BrokerEvidence` **之前**必须完成身份校验。

### 5.1 account

```text
raw account
    ==
selected Bridge account
    ==
BrokerEvidence.account_fingerprint
    ==
durable OMS order account
```

任何 mismatch：

```text
QUARANTINE
NO OMS MUTATION
```

### 5.2 client order identity / broker token

标准 evidence 必须含 `client_order_id`。

对 Big QMT adapter：

- `m_strRemark` 只有精确匹配当前项目 broker-token 规则时才可以用于关联；
- token 必须和 `(account_fingerprint, client_order_id)` 的 durable expected token 一致；
- 未知 token / 缺 token / token 指向另一订单时，不得猜测 `client_order_id`。

其他 broker adapter 可以使用不同 correlation mechanism，但输出到 v1 时仍必须解析成同一个 durable `client_order_id`。

### 5.3 broker order ID

若 OMS 尚未固定 `broker_order_id`：

- 经可靠 token/client identity 校验的 `ACKNOWLEDGED/PARTIAL/FILLED/CANCELLED` evidence 可以首次固定它。

一旦固定：

```text
new broker_order_id != durable broker_order_id
    → terminal/identity conflict
    → quarantine / MANUAL_REVIEW
```

禁止覆盖原值。

`order_ref`、`trade_id` 是辅助 identity，不能绕过 account + client identity 约束。

## 6. Evidence identity、重复与冲突

逻辑 evidence identity：

```text
(source, account_fingerprint, source_event_id)
```

`semantic_digest` 是同一 identity 下标准化语义的摘要。

规则：

```text
same identity + same semantic_digest
    → DUPLICATE / idempotent

same identity + different semantic_digest
    → CONFLICT
    → quarantine / MANUAL_REVIEW
```

不能用“后来的 payload 覆盖前面的 payload”。

## 7. Unknown / uncalibrated raw status

以下情况**不生成** `BrokerEvidence`：

- mapper 不认识 raw status；
- raw status 的含义尚未实机校准；
- identity 不完整或冲突；
- quantity 不一致；
- broker order ID 与 durable identity 冲突；
- source 类型不允许产生目标 evidence；
- 同一 source_event_id 语义摘要冲突。

正确行为：

```text
raw fact
  ↓
quarantine / calibration journal / reconciliation
```

不是：

```text
raw fact
  ↓
guess an OMS status
```

## 8. Aggregation Contract

OMS 不采用“最新 event 覆盖旧 event”的模型。

`observed_at_ms` 只用于审计和诊断，不能单独决定事实优先级。

聚合遵循**单调事实**。

### 8.1 filled quantity

```text
aggregate_filled = max(current_filled, evidence.filled_quantity)
```

但只有 identity 和 quantity consistency 都通过的 evidence 才能进入聚合。

已确认成交量永远不能下降。

### 8.2 非终态

正常生命周期：

```text
UNKNOWN / RECONCILING
      ↓
ACKNOWLEDGED
      ↓
PARTIALLY_FILLED
```

旧 `ACKNOWLEDGED` 到达时不能把 `PARTIALLY_FILLED` 降级。

### 8.3 终态

broker 终态：

```text
FILLED
CANCELLED
REJECTED
```

终态之后到达的旧 ACK/旧 PARTIAL 不能回退状态。

同一终态的重复/等价 evidence 是幂等的。

不同 broker 终态之间**没有简单优先级**。例如：

```text
FILLED + CANCELLED
FILLED + REJECTED
CANCELLED + REJECTED
```

如果两边都已经通过 identity/calibration gate，则属于真实矛盾：

```text
MANUAL_REVIEW
```

不能用“query 比 callback 新”或“时间戳更晚”覆盖其中一方。

### 8.4 fill / cancel race

允许：

```text
ACKNOWLEDGED
  ↓
PARTIALLY_FILLED
  ↓
CANCELLED
```

此时 `filled_quantity` 保留部分成交累计值。

不允许把已经确认的 `CANCELLED` 后新增更高成交量静默吸收；这意味着 broker facts 自相矛盾，应进入 `MANUAL_REVIEW`。

### 8.5 filled absorption

`FILLED` 对旧的 ACK/PARTIAL evidence 是吸收态。

如果之后出现另一个不同 terminal evidence，则不是“FILLED 被覆盖”，而是：

```text
terminal conflict → MANUAL_REVIEW
```

## 9. Source semantics

### ORDER callback

可以在 mapper 校准后产生：

- `ORDER_ACCEPTED`
- `PARTIAL_FILL`
- `FULL_FILL`
- `ORDER_CANCELLED`
- `ORDER_REJECTED`

### DEAL callback

只能证明成交事实，因此只能产生：

- `PARTIAL_FILL`
- `FULL_FILL`

`DEAL_CALLBACK` 必须有稳定 `trade_id`，重复 trade ID 不能重复增加成交事实。

### active ORDER query

可以产生与 ORDER callback 相同的 lifecycle evidence，但不能因为 query 时间更晚而使状态回退。

### active DEAL query

用于恢复/校准成交集合并构造累计成交事实，只能产生：

- `PARTIAL_FILL`
- `FULL_FILL`

## 10. Broker-specific mapper 的职责

未来每个 mapper 都必须声明版本化 `mapper_profile`，并负责：

1. 解析 raw ORDER/DEAL/query；
2. 只使用已经实机校准过的 status semantics；
3. 解析 durable client identity；
4. 校验 account/broker token/broker order ID；
5. 把 DEAL delta/rows 聚合成 cumulative filled quantity；
6. 校验 quantity boundaries；
7. 输出 `BrokerEvidence v1`；或
8. 返回“不足以形成 evidence”，进入 quarantine。

mapper **不能直接写 OMS state**。

## 11. 形式验证边界

`formal/BrokerEvidenceContract.tla` 对有限抽象穷举验证：

- `CommandResultCannotCreateBrokerEvidence`
- `IdentityMismatchNeverMutatesOms`
- `DuplicateEvidenceAppliedAtMostOnce`
- `OutOfOrderEvidenceCannotRegressState`
- `FilledIsAbsorbingUnlessTerminalConflict`
- `CancelSignalCannotCreateCancelled`
- `PartialFillCannotRegressToAck`
- `ConflictingTerminalEvidenceFailsClosed`
- `UnknownRawStatusCannotAdvanceOms`
- broker ORDER/DEAL/query aggregation maintains monotonic fill/lifecycle facts

它与：

```text
BrokerEvidenceBoundary
EvidenceReplay
OrderFSM
```

形成分层关系：

- `BrokerEvidenceBoundary`：谁有资格成为 broker evidence；
- `BrokerEvidenceContract`：合法 evidence 的身份、类型和聚合语义；
- `EvidenceReplay`：重复/乱序 evidence 的 replay safety；
- `OrderFSM`：最终 OMS lifecycle 状态机。

## 12. Compatibility

v1 内允许：

- 增加不改变 authority 的可选审计字段；
- 新增 mapper profile；
- 新增 broker adapter，只要输出语义保持一致。

以下变化需要升级 contract major：

- 改变某 evidence type 的含义；
- 把 command/control-plane result 允许为 broker evidence；
- 改变 terminal conflict 的 fail-closed 规则；
- 允许 filled quantity 回退；
- 允许 identity mismatch 进入 OMS；
- 改变 evidence identity / semantic conflict 规则。

## 13. 当前 Gate 状态

本次 Gate 只冻结协议层。

完成后应具备：

```text
Broker Evidence Contract v1
JSON Schema
TLA+/TLC model
independent finite contract checker
CI permanent gate
```

仍然**不包含**：

- 国金 raw status → v1 mapper 实现；
- 银河 raw status → v1 mapper 实现；
- production live trading；
- LIVE_CANARY。

本契约本身不授予任何 mutation authority。当前部署边界由 Bridge API 与独立 Gate
共同约束：generic / `galaxy` 的 broker mutation call surface 必须保持为零；
`guojin` 仅允许 P6 明确固定的两个 LIVE_CANARY 案例，且不能解释为通用实盘授权。
