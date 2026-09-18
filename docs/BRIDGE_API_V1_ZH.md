# BigQMT Bridge API v1

状态：**Architecture Contract / Permanent Safety Gate**

日期：2026-09-17

## 1. 目的

`BigQMT Bridge API v1` 是 `bigqmt_autotrader` 中 Host 与 Big QMT Bridge 之间的正式内部 API 契约。

它不是 HTTP/OpenAPI 公共接口，也不要求不同券商的 QMT 暴露相同 Python 函数。它定义的是：

- Host 如何发现并信任一个 Bridge 实例；
- Host 如何向 Bridge 发布不可变命令；
- Bridge 如何向 Host 发布账户、订单、成交和控制面事件；
- crash、重启、重复、乱序、缺口、过期、冲突和会话切换时的安全语义；
- 哪些信息属于 **transport/control-plane evidence**，哪些才属于 **broker lifecycle evidence**。

本契约的首要目标不是方便，而是 **fail closed**：当系统不能证明一次交易动作是否已经发生时，宁可进入 `UNKNOWN/RECONCILING`，也不能盲目重试并制造重复风险。

## 2. 版本结构

`BigQMT Bridge API v1` 是 umbrella version。为了不破坏已经在真实 QMT 上校准过的 wire format，v1 继续包含现有子版本：

| 层 | 当前版本 | 说明 |
| --- | --- | --- |
| Discovery Contract | `1` | `instance.json` + matching-session `bridge_ready` |
| Command Protocol | `0.1` | Host → Bridge 命令对象 |
| Event Protocol | `0.2` | Bridge → Host 事件对象 |
| File Transport | `1` | durable file-spool transport |
| API umbrella | `v1` | 对上述协议的组合语义、兼容性和安全约束 |

升级 umbrella API 不要求机械地升级每个 wire version。只有字段、语义或兼容规则发生不兼容改变时，才升级相应子协议。

## 3. 三层契约

### 3.1 Wire Contract

JSON Schema 位于：

```text
schemas/bridge/v1/
├── instance.schema.json
├── command.schema.json
├── event.schema.json
└── command_result.schema.json
```

Schema 定义消息“长什么样”，包括字段类型、枚举、格式、模式限制和当前允许的 execution mode。

Schema **不会**授权任何新的交易权限。当前只允许：

- `SHADOW`
- `SIMULATION_CALIBRATION`
- `LIVE_CANARY`

不存在 `LIVE` / `LIVE_ARMED` Schema 入口。

### 3.2 Semantic Contract

Python 实现仍是运行时语义的权威边界：

- `src/bigqmt_autotrader/qmt/instances.py`
- `src/bigqmt_autotrader/qmt/commands.py`
- `src/bigqmt_autotrader/qmt/protocol.py`
- `src/bigqmt_autotrader/qmt/receiver.py`
- `src/bigqmt_autotrader/qmt/ingestion.py`

JSON Schema 无法表达的关系约束继续由运行时代码验证，例如：

- `expires_ms > created_ms`
- simulation `authorized_account_fingerprint == account_fingerprint`
- `broker_token` 必须由 `(account_fingerprint, client_order_id)` 确定性生成
- `instance.json` 必须与 matching-session `bridge_ready` 一致
- directory leaf、`terminal_instance_id` 与 `bridge_ready` instance 必须一致

### 3.3 Safety Contract

TLA+/TLC 对有限抽象状态空间做穷举：

- `formal/BridgeCommandProtocol.tla`
- `formal/BridgeEventProtocol.tla`
- `formal/BrokerEvidenceBoundary.tla`

这些模型与现有：

- `SubmitProtocol`
- `EvidenceReplay`
- `OrderFSM`
- `LeaderLease`
- `PreSubmitRecovery`
- `RiskPrecedence`

共同构成永久 CI Gate。

## 4. 实例发现和握手

每个 Bridge 在自己的 spool leaf 下原子发布：

```text
D:\BigQMTData\spool\<terminal_instance_id>\instance.json
```

Host 不通过“国金/银河”名称赋予权限。一个实例只有在以下信息一致时才可被选择：

```text
directory leaf
    ==
instance.json.terminal_instance_id
    ==
matching bridge_ready.terminal_instance_id
```

同时必须核对：

- `manifest_version`
- `protocol_version`
- `transport_version`
- `bridge_build`
- `session_id`
- `account_fingerprint`
- `account_type`
- `execution_mode`
- `trading_enabled`
- `live_submit`
- `live_cancel`
- simulation-only 限额（如适用）

### 4.1 Production SHADOW

`galaxy` 和通用 production artifact 必须保持：

```text
execution_mode = SHADOW
trading_enabled = false
live_submit = false
live_cancel = false
```

并且 source-level static audit 必须证明这些 artifact 不存在 broker mutation call surface。

### 4.2 SIMULATION_CALIBRATION

只有 fingerprint-pinned 的 `guojin_sim` calibration artifact 可以具有：

```text
execution_mode = SIMULATION_CALIBRATION
simulation_only = true
trading_enabled = true
live_submit = true
live_cancel = true
```

这表示“允许调用模拟账户 QMT mutation API”，**不是生产实盘授权**。

Host 和 publisher 仍需分别显式授权 simulation calibration。

### 4.3 Guojin LIVE_CANARY

`guojin` 当前存在一个经过 P6 独立 Gate 的生产账户例外：

```text
execution_mode = LIVE_CANARY
simulation_only = false
trading_enabled = true
live_submit = true
live_cancel = true
```

该模式不是 general LIVE。它必须同时固定账户指纹、当前 QMT session、每 session submit/cancel fuse，并由独立 publisher 的精确确认字符串授权。当前 canary 仍被固定 symbol/side/quantity/price 与 instrument preflight 限制。

P6 build-5 新增的 `instrument_tick_capabilities` 仅用于只读 route 诊断，不改变上述 mutation authority。

## 5. Host → Bridge：Command API

当前命令：

```text
REQUEST_SNAPSHOT
SUBMIT_LIMIT
CANCEL_ORDER
```

统一字段：

```text
command_protocol_version
command_id
created_ms
expires_ms
account_fingerprint
command_type
client_order_id
broker_token
payload
```

订单命令必须携带：

- 非空 `client_order_id`
- 确定性 22 字符 `BQ...` broker token

`REQUEST_SNAPSHOT` 不允许携带订单 identity。

### 5.1 Durable publication

Host 发布过程必须：

1. 构造完整不可变 frame；
2. write；
3. flush；
4. `fsync`；
5. same-directory atomic rename 到 `commands/inbox`。

状态机：

```text
ABSENT
  ↓ publish
INBOX
  ↓ atomic claim
CLAIMED
  ├── PROCESSED
  ├── REJECTED
  └── UNKNOWN
```

`CLAIMED` 是 side-effect boundary。一个 crash 后遗留在 `CLAIMED` 的命令必须进入 `UNKNOWN_ORPHANED`，禁止盲目回放。

### 5.2 幂等和冲突

对于同一 `command_id`：

- **相同完整字节**：幂等，返回已有 command；
- **不同内容**：hard conflict，拒绝覆盖；
- terminal command 不会自动回到 `INBOX/CLAIMED`。

这不是“exactly once”承诺。系统提供的是：

> durable local at-most-once broker-call intent + unique identity + UNKNOWN/no blind resend + broker evidence reconciliation。

### 5.3 过期和 identity

命令在发布前和消费前都必须检查 expiration。

过期、错误账户、simulation session mismatch 或 safety-gate mismatch 必须在 broker mutation 前 fail closed。

## 6. Bridge → Host：Event API

统一 envelope：

```text
protocol_version
terminal_instance_id
session_id
sequence
timestamp_ms
event_type
source
account_fingerprint
account_type
payload
```

当前事件类型：

```text
bridge_ready
bridge_error
account_capabilities
instrument_capabilities
instrument_tick_capabilities
snapshot
account
position
order
deal
command_result
```

### 6.1 Route diagnostic events

`instrument_capabilities` 表示证券主数据只读探测；`instrument_tick_capabilities` 表示订阅 route 的真实行情 callback 证据。两者都是 control-plane / diagnostic event：

- 不属于 BrokerEvidence；
- 不推进 OMS order lifecycle；
- 不自动授予 submit/cancel 权限；
- subscription ID 成功不能证明 route 可交易；
- build-5 只有在 callback payload 精确包含预期 symbol 时才把该 route 标为 `tick_observed=true`。

### 6.2 session / sequence

Host 对每个已选择 instance 固定：

- `terminal_instance_id`
- `account_fingerprint`

并跟踪：

- 当前 `session_id`
- `last_sequence`
- `needs_resync`

语义：

- `sequence <= last_sequence`：`DUPLICATE`，不得重复应用业务状态；
- 同 session 出现 sequence gap：进入 `needs_resync`;
- session change：重置 sequence baseline 并进入 `needs_resync`;
- 只有**完整且 `query_errors=[]` 的 active snapshot**可以作为 resync boundary；
- wrong terminal instance / wrong account：拒绝进入 read model。

如果 gap event 本身就是完整 clean snapshot，它可以在同一个 ingress action 中完成 resync；“gap 必须 resync”的含义是：**未被 clean snapshot 覆盖的 gap 必须保持 `needs_resync=true`**。

## 7. `command_result` 不是 broker ACK

这是 API v1 最重要的语义之一：

```text
command_result != broker lifecycle evidence
```

特别是：

```text
SHADOW_ACCEPTED != ACKNOWLEDGED
```

`command_result` 只能说明 Bridge 对一个命令做了本地处理、拒绝或调用了受限 QMT API。

它不能单独产生：

- `ACKNOWLEDGED`
- `PARTIALLY_FILLED`
- `FILLED`
- `CANCELLED`
- broker-level `REJECTED`

在当前设计中，broker lifecycle evidence 只能来自经校准 mapper 接受的：

```text
ORDER callback
DEAL callback
active ORDER query
active DEAL query
```

因此数据流必须是：

```text
command_result
    └── control-plane journal

ORDER / DEAL / query
    ↓
BrokerEvidenceMapper
    ↓
BrokerEvidence
    ↓
EvidenceReplay
    ↓
OMS FSM
```

`BrokerEvidenceBoundary.tla` 将这一边界作为形式 invariant。

## 8. Snapshot 和 reconciliation

Snapshot 是 Host 与 Bridge 的显式状态收敛边界。

一个 clean snapshot 至少包含：

```text
account
positions
orders
deals
query_errors=[]
```

Snapshot 不代表历史事件全部重新发生；它代表“当前 QMT 查询面的一致观察”。

Host restart、sequence gap、session switch 和 ambiguous submit/cancel 都应优先依靠 snapshot/query + durable broker identity 做 reconciliation，而不是自动重发 broker mutation。

## 9. Compatibility Rules

### 9.1 Compatible

在同一子协议版本内，下列变化可以兼容：

- payload 增加 Host 可以安全忽略的非 authority 字段；
- 新增诊断字段，但不改变既有字段语义；
- 新增新的 `bridge_build`；
- 修复实现但保持 wire/semantic contract。

### 9.2 Requires version change

以下变化必须升级相应协议或 API major：

- 改变已存在字段的含义；
- 把 optional identity 改成另一种 identity；
- 改变 duplicate/gap/session/resync 语义；
- 改变 `command_result` 与 broker evidence 的边界；
- 引入新的 production mutation authority；
- 允许当前 Schema 不允许的 execution mode；
- 改变 at-most-once / UNKNOWN / no-blind-retry 原则。

## 10. Error semantics

协议错误按 fail-closed 原则处理。核心类别：

```text
MALFORMED_FRAME
UNSUPPORTED_VERSION
IDENTITY_MISMATCH
SEQUENCE_GAP
COMMAND_CONFLICT
COMMAND_EXPIRED
SAFETY_GATE_REJECTED
UNKNOWN_ORPHANED
BROKER_MUTATION_UNKNOWN
```

这些是语义分类，不要求当前所有实现都暴露同名字符串。若未来形成稳定 SDK，再冻结 wire-level error code enum。

## 11. 与 Market Data Bridge 的关系

未来独立的 Market Data Bridge 可以复用：

- instance discovery/versioning
- envelope
- terminal instance identity
- health/session telemetry

但**不得复用 execution command 的 mutation authority**。

行情数据适合 latest-value / streaming / batch 语义；交易命令适合 durable at-most-once intent。两者必须保持独立安全域。

## 12. 永久 Gate

任何修改 Host↔Bridge 安全语义的变更必须同时满足：

1. JSON Schema / schema-contract tests 通过；
2. Python protocol conformance checker 通过；
3. 所有 TLA+/TLC model 无 counterexample；
4. broker side-effect static audit 通过；
5. standalone QMT deployment build check 通过；
6. Galaxy/generic production mutation call surface 必须保持为零；Guojin 仅允许已通过独立 Gate 的 fingerprint-pinned LIVE_CANARY surface，任何权限扩大都必须经过新的明确 Gate。

API v1 现在定义 `LIVE_CANARY` 的传输语义，但协议存在不等于自动授权。只有
manifest 与 `bridge_ready` 同时固定账户指纹。当前国金校准 session 仅允许两个
各最多一次的 submit 场景（腾讯 HGT 固定低价路由、511880 资金不足）及最多两次 cancel（为每个
canary 各保留一次精确 token 匹配的紧急撤单能力）；
Host 显式使用 `--allow-live-canary`，并由独立 publisher 提供精确确认字符串时才允许
国金 canary 命令。`command_result` 仍然不是 broker evidence，不能产生 ACK。

## 13. 与 Broker Evidence Contract v1 的分层关系

Bridge API v1 的职责截止在“可信地传递 raw broker observation 与 control-plane result”。它**不定义**某个原始 QMT 状态码应该成为哪个 OMS lifecycle 状态。

该语义由独立的 [`BROKER_EVIDENCE_CONTRACT_V1_ZH.md`](BROKER_EVIDENCE_CONTRACT_V1_ZH.md) 冻结：

```text
BigQMT Bridge API v1
    ↓ ORDER / DEAL / active query observation
broker-specific calibrated mapper
    ↓
Broker Evidence Contract v1
    ↓
EvidenceReplay
    ↓
OMS FSM
```

因此：

- `Bridge API v1` 证明 transport/session/identity/control-plane 边界；
- `Broker Evidence Contract v1` 证明哪些 broker facts 有资格推进 OMS，以及如何做单调聚合和 terminal-conflict fail-close；
- broker-specific mapper 只能实现这两个协议之间的适配，不能自行创造新的 OMS 语义。

任何将 `command_result`、submit/cancel API return、未知 raw status 或 identity mismatch 提升为 `BrokerEvidence` 的变更，同时违反两个 v1 contract，必须拒绝进入生产 Gate。
