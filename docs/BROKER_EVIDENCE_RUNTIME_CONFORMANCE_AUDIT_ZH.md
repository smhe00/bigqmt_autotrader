# Broker Evidence Runtime Conformance Audit

> 2026-09-17 后续实现结果：本文记录的缺口已由
> [`BROKER_EVIDENCE_RUNTIME_CONFORMANCE_RESULT_20260917_ZH.md`](BROKER_EVIDENCE_RUNTIME_CONFORMANCE_RESULT_20260917_ZH.md)
> 完成修复并通过回归。本文保留为修复前审计基线。

状态：**Architecture / Runtime Conformance Audit**  
日期：2026-09-17  
范围：`Broker Evidence Contract v1` 与当前 `main` 代码实现的一致性审计

---

## 1. 审计结论

当前项目已经完成 `BigQMT Bridge API v1` 与 `Broker Evidence Contract v1` 的协议、Schema 和形式验证封版，但**当前整个运行时代码仍不能判定为完全符合 `Broker Evidence Contract v1`**。

更准确的状态为：

```text
Broker Evidence Contract v1
    Protocol / Schema           PASS
    Formal specification        PASS
    Independent finite model    PASS

Bridge / command_result         PASS
QMT raw calibration boundary    PASS

OMS EvidenceReplay core         PARTIAL
BrokerEvidence v1 runtime       NOT IMPLEMENTED
Implementation ↔ Contract       NOT YET GATED

Guojin mapper                   NOT IMPLEMENTED
Galaxy mapper                   NOT IMPLEMENTED
Production live                 NO
```

当前实现中，Bridge 与 `command_result` 的控制面边界、QMT 原始 ORDER/DEAL 校准边界、broker order ID 固定、成交量单调聚合、旧 ACK 不回退 PARTIAL 等核心机制与新协议基本一致。

但仍存在几类明确的 runtime contract gap：

1. `EvidenceJournal` 仍是旧接口，尚未直接消费完整 `BrokerEvidence v1` 标准对象；
2. evidence identity 的数据库唯一键与新协议不完全一致；
3. source authority 目前主要由 Schema/独立 checker 约束，runtime journal 本身仍可被旧调用方式绕过；
4. 不同 broker terminal facts 的冲突目前未进入 `MANUAL_REVIEW`；
5. `CANCELLED/REJECTED` 后出现更高成交量时，repository 仍可能静默吸收 fill；
6. 旧 `OfflineOms + SimulatedDriver` 路径仍将 submit/cancel 本地 API 返回值直接推进 `ACKNOWLEDGED/CANCELLED`，与新协议的证据边界不一致。

其中第 4、5 项属于**高优先级语义偏差**；第 6 项属于架构一致性高优先级，但当前暴露面主要是 offline/simulation path，并非 production QMT live path。

当前 production `galaxy` / `guojin` 仍为 SHADOW，production broker mutation call surface 仍为 ZERO，未启用 `LIVE_CANARY`。因此本审计发现的缺口目前主要影响**架构一致性、未来 broker mapper 接入和生产化安全闭环**，而不是已经存在的生产实盘误判。

---

## 2. 审计基线

协议基线：

- `docs/BROKER_EVIDENCE_CONTRACT_V1_ZH.md`
- `schemas/broker_evidence/v1/broker_evidence.schema.json`
- `formal/BrokerEvidenceContract.tla`
- `tools/verify_broker_evidence_contract.py`

运行时代码基线：

- `src/bigqmt_autotrader/oms/command_results.py`
- `src/bigqmt_autotrader/oms/qmt_bridge.py`
- `src/bigqmt_autotrader/qmt/calibration.py`
- `src/bigqmt_autotrader/oms/evidence.py`
- `src/bigqmt_autotrader/oms/repository.py`
- `src/bigqmt_autotrader/domain/state_machine.py`
- `src/bigqmt_autotrader/oms/service.py`
- `src/bigqmt_autotrader/oms/migrations/0004.sql`

本报告审计的核心问题不是“单元测试是否通过”，而是：

> 当前真实 runtime implementation 是否逐项满足已经冻结的 Broker Evidence Contract v1 语义。

---

## 3. 总体一致性矩阵

| Contract 条款 | 当前实现 | 结论 | 风险 |
| --- | --- | --- | --- |
| `command_result != BrokerEvidence` | `QmtCommandResultJournal` 与 broker evidence journal 分离 | PASS | LOW |
| `SHADOW_ACCEPTED` 不得产生 ACK | 有显式 assertion 与独立 control-plane sink | PASS | LOW |
| submit/cancel command_result 不产生 lifecycle | QMT shadow path 符合 | PASS | LOW |
| 未校准 raw status 不推进 OMS | calibration 只观测，不映射 | PASS | LOW |
| broker order ID 固定后不可变化 | repository 抛 `BrokerOrderIdMismatch` | PASS | LOW |
| filled quantity 不能下降 | repository 使用 `max(current, new)` | PASS | LOW |
| stale ACK 不能覆盖 PARTIAL | FSM stale 规则已覆盖 | PASS | LOW |
| runtime 只消费完整 `BrokerEvidence v1` | `EvidenceJournal.ingest()` 仍是旧参数接口 | FAIL / PENDING | MEDIUM |
| evidence identity = `(source, account, source_event_id)` | DB 唯一键仍为 `(source, source_event_id)` | FAIL | MEDIUM |
| DEAL 只能产生 fill evidence | Schema 有限制，runtime journal 无 source-authority enforcement | FAIL | MEDIUM |
| terminal conflict → `MANUAL_REVIEW` | terminal 状态直接 `STALE_IGNORED` | FAIL | **HIGH** |
| CANCELLED/REJECTED 后更高 fill → `MANUAL_REVIEW` | repository 可能先更新 fill，再 stale lifecycle | FAIL | **HIGH** |
| submit API return 不能直接产生 ACK | Offline/Simulated path 仍直接 ACK | FAIL | HIGH architecture / LOW current production exposure |
| cancel API return 不能直接产生 CANCELLED | Offline/Simulated path 仍直接 CANCELLED | FAIL | HIGH architecture / LOW current production exposure |
| implementation 与独立 reference model differential gate | 尚未建立 | NOT IMPLEMENTED | MEDIUM |

---

## 4. 已符合协议的部分

### 4.1 `command_result` 与 broker lifecycle evidence 已严格分离

`src/bigqmt_autotrader/oms/command_results.py` 中的 `QmtCommandResultJournal` 明确定位为 control-plane journal。

当前代码已经具备以下关键语义：

```text
SHADOW_ACCEPTED
    !=
ACKNOWLEDGED
```

并且 journal 记录中显式写入：

```text
broker_evidence = False
evidence_class = EXECUTION_PLANE_NOT_BROKER_ACK
```

`SHADOW_ACCEPTED` 最多触发：

```text
SUBMITTING/CANCEL_PENDING
    ↓
UNKNOWN
    ↓
RECONCILING
```

不能直接产生：

- `ACKNOWLEDGED`
- `PARTIALLY_FILLED`
- `FILLED`
- `CANCELLED`
- broker-level `REJECTED`

这与 `Broker Evidence Contract v1` 的控制面/券商事实边界一致。

### 4.2 QMT command-result sink 仍保持 fail-closed

`src/bigqmt_autotrader/oms/qmt_bridge.py` 中 `OmsQmtCommandResultSink` 当前只接受：

```text
execution_mode = SHADOW
live_side_effect = false
```

并且限制允许的 command type / result status。

这意味着生产 SHADOW 路径不会把 Bridge 本地处理结果伪装成 broker lifecycle fact。

### 4.3 未校准 QMT 原始状态不会推进 OMS

`src/bigqmt_autotrader/qmt/calibration.py` 中：

- `order_deal_calibration_record()` 只抽取 raw ORDER/DEAL 字段；
- `QmtBrokerTokenCalibration` 只做 token/account correlation；
- `summary()` 明确返回：

```text
broker_evidence_mapping_enabled = False
live_submit = False
live_cancel = False
```

这与协议要求一致：

> 未经实机校准的 `status_code/submit_status_code` 只能进入 calibration/reconciliation，不允许猜测 OMS 状态。

### 4.4 broker order identity 已具备 fail-closed 保护

`src/bigqmt_autotrader/oms/repository.py` 中，如果当前已经存在 `broker_order_id`，新的 broker fact 携带不同 ID，则抛出：

```text
BrokerOrderIdMismatch
```

不会覆盖 durable identity。

这与协议中的 broker identity freeze 一致。

### 4.5 filled quantity 已采用单调聚合

当前 repository 对成交量使用：

```text
effective_filled = max(current_filled, filled_quantity)
```

因此正常情况下旧 observation 不会把已确认成交量降低。

### 4.6 stale ACK 不会覆盖 PARTIAL

当前 FSM 在 `PARTIALLY_FILLED` 状态收到旧 `ACKNOWLEDGED` 时会判定为 stale，而不是回退状态。

已有测试：

```text
test_stale_ack_query_cannot_erase_known_partial_fill
```

也覆盖了这一点。

---

## 5. Gap A：EvidenceJournal 尚未真正消费 `BrokerEvidence v1`

**风险等级：MEDIUM**

当前 `src/bigqmt_autotrader/oms/evidence.py` 的入口仍为旧接口：

```python
ingest(
    source,
    source_event_id,
    account_fingerprint,
    client_order_id,
    evidence_type,
    requested_status,
    filled_quantity,
    broker_order_id,
    payload,
    ...
)
```

而已冻结的 `BrokerEvidence v1` wire object 包含：

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
raw_status
```

### 5.1 当前缺失的 runtime contract information

现有 journal 没有一等字段处理：

- `source_kind`
- `mapper_profile`
- `semantic_digest`
- `broker_token`
- `order_ref`
- `trade_id`
- `raw_payload_ref`
- `raw_status`
- `evidence_version`

这意味着：

> 当前 Schema 已定义标准对象，但实际 OMS runtime 还没有把这个对象作为唯一合法输入边界。

### 5.2 风险

当前 caller 仍可以绕过标准 `BrokerEvidence v1`，直接调用旧接口并传入自由组合的：

```text
source
evidence_type
requested_status
```

这会使 Schema contract 与 runtime authority 分离。

### 5.3 建议整改

新增真正的 runtime model，例如：

```python
@dataclass(frozen=True)
class BrokerEvidenceV1:
    ...
```

并将 journal 入口收窄为：

```python
EvidenceJournal.ingest(evidence: BrokerEvidenceV1)
```

旧自由参数入口应逐步删除或降级为 internal/test-only adapter。

---

## 6. Gap B：Evidence identity 数据库键少了 account

**风险等级：MEDIUM**

协议定义逻辑 identity：

```text
(source, account_fingerprint, source_event_id)
```

但当前 `src/bigqmt_autotrader/oms/migrations/0004.sql` 中：

```sql
CREATE UNIQUE INDEX idx_broker_evidence_source_event_id
ON broker_evidence_keys(source, source_event_id)
WHERE source_event_id IS NOT NULL;
```

实际唯一键是：

```text
(source, source_event_id)
```

### 6.1 风险

如果不同账户使用同一来源字符串，并出现相同 `source_event_id`，当前 DB 会把它们误认为同一 evidence identity 或产生跨账户冲突。

虽然当前 QMT `source_event_id` 往往包含 session/sequence，实际 collision 概率低，但这不是协议允许依赖的隐含条件。

### 6.2 建议整改

数据库 migration 应改成：

```text
(source, account_fingerprint, source_event_id)
```

同时 `broker_evidence_keys` 本身需要持久化 `account_fingerprint`。

---

## 7. Gap C：DEAL source authority 尚未在 runtime journal 强制

**风险等级：MEDIUM**

Schema 已明确：

```text
DEAL_CALLBACK
ACTIVE_DEAL_QUERY
```

只能产生：

```text
PARTIAL_FILL
FULL_FILL
```

不能产生：

```text
ORDER_ACCEPTED
ORDER_CANCELLED
ORDER_REJECTED
```

但当前 `EvidenceJournal.ingest()` 不知道标准 `source_kind`，只接收自由字符串 `source`，也不验证 source/evidence authority matrix。

因此理论上旧 caller 可以直接调用：

```text
source = deal-like-source
requested_status = CANCELLED
```

runtime journal 本身不会因为“DEAL 无权证明 CANCELLED”而拒绝。

### 建议整改

source authority 必须成为 `BrokerEvidenceV1` runtime validation 的一部分，不能只存在于 JSON Schema 或独立 checker。

---

## 8. Gap D：不同 terminal facts 没有进入 `MANUAL_REVIEW`

**风险等级：HIGH**

协议规定 broker terminal facts：

```text
FILLED
CANCELLED
REJECTED
```

如果同一订单已经接受一个 terminal fact，又出现另一个不同 terminal fact：

```text
FILLED + CANCELLED
FILLED + REJECTED
CANCELLED + REJECTED
```

正确行为是：

```text
terminal conflict
    ↓
MANUAL_REVIEW
```

而不是选择某一个“更晚”或“看起来更强”的状态。

### 8.1 当前实现

`src/bigqmt_autotrader/domain/state_machine.py` 当前逻辑：

```python
if current in TERMINAL_STATUSES:
    return TransitionOutcome(
        previous=current,
        current=current,
        ...
        disposition=STALE_IGNORED,
    )
```

因此：

```text
current = FILLED
new broker fact = CANCELLED
```

当前结果为：

```text
FILLED
+ STALE_IGNORED
```

而新 Contract 要求：

```text
MANUAL_REVIEW
```

### 8.2 为什么这是重要差异

不同 terminal broker facts 同时通过 identity/calibration gate 后，不再是简单的“旧消息问题”，而意味着 broker observation 自身出现矛盾。

把它当 stale 会掩盖真实一致性故障。

### 8.3 建议整改

terminal conflict 不应继续走普通 `transition()` 的 absorbing-terminal 逻辑，而应由 broker-evidence aggregation 层识别后显式推进：

```text
MANUAL_REVIEW
```

---

## 9. Gap E：CANCELLED/REJECTED 后更高 fill 可能被静默吸收

**风险等级：HIGH**

协议明确：

```text
CANCELLED / REJECTED
    +
new evidence with higher cumulative fill
    ↓
MANUAL_REVIEW
```

不能静默吸收。

### 9.1 当前实现路径

`src/bigqmt_autotrader/oms/repository.py` 当前先计算：

```python
effective_filled = max(current_filled, filled_quantity)
```

随后才调用：

```python
transition(current, normalized_target)
```

如果 `current` 已是 terminal，FSM 会返回：

```text
STALE_IGNORED
```

但是 repository 后续仍可能执行：

```python
if effective_filled != current_filled:
    UPDATE broker_orders SET filled_quantity = ...
```

因此理论上可能形成：

```text
status = CANCELLED
filled_quantity = order_quantity
```

状态没变，但成交量被静默提高。

### 9.2 为什么不符合 Contract

Contract 允许：

```text
PARTIALLY_FILLED → CANCELLED
```

并保留已有 partial fill。

但不允许：

```text
CANCELLED 50
→ later evidence says 100
→ silently become CANCELLED 100
```

这种情况代表 broker lifecycle facts 冲突，必须 fail closed。

### 9.3 建议整改

在写入 `effective_filled` 之前增加 terminal consistency check：

```text
if current in {CANCELLED, REJECTED}
   and new_filled > current_filled:
       → MANUAL_REVIEW
       → do not silently update normal lifecycle aggregate
```

---

## 10. Gap F：旧 OfflineOms submit return 仍直接产生 ACK

**风险等级：HIGH（架构一致性） / LOW（当前 production exposure）**

`src/bigqmt_autotrader/oms/service.py` 中旧路径：

```python
ack = self.driver.submit_limit_order(intent)
...
transition_order(... ACKNOWLEDGED)
```

这代表：

```text
submit API return
    ↓
ACKNOWLEDGED
```

而新 Contract 明确要求：

```text
submit API return
    !=
BrokerEvidence
```

只有经校准的：

```text
ORDER callback
active ORDER query
```

才能证明 `ORDER_ACCEPTED/ACKNOWLEDGED`。

### 当前暴露面

这里当前主要用于：

```text
OfflineOms + SimulatedDriver
```

并不是 `guojin/galaxy` production QMT path。

所以：

- **架构一致性风险高**；
- **当前 production exposure 低**。

但如果未来直接复用这条逻辑接真实 broker driver，则会违反 Evidence Contract。

---

## 11. Gap G：旧 OfflineOms cancel return 仍直接产生 CANCELLED

**风险等级：HIGH（架构一致性） / LOW（当前 production exposure）**

当前：

```python
ack = self.driver.cancel_order(...)
...
transition_order(... CANCELLED)
```

相当于：

```text
cancel API return
    ↓
CANCELLED
```

新协议明确禁止：

```text
cancel() returned success
SIMULATION_CANCEL_SIGNAL_SENT
command_result
```

直接生成 `CANCELLED`。

因为撤单 API 成功通常只能证明：

```text
cancel request accepted/sent
```

并不能证明券商订单已经处于 cancelled terminal state。

这点在国金 simulation 校准中已经有实际观察依据：cancel call 返回后 active query 状态可能尚未立刻同步。

### 建议整改

submit/cancel driver API 应只产生 transport/control outcome，例如：

```text
SUBMIT_CALL_RETURNED
CANCEL_SIGNAL_SENT
UNKNOWN
```

真正 lifecycle 只能由 `BrokerEvidence v1` 驱动。

---

## 12. 为什么当前 CI 全绿仍不能证明实现完全符合 Contract

这是本审计最重要的工程结论之一。

当前：

```text
tools/verify_broker_evidence_contract.py
```

是**独立 reference model**。

它自己定义：

- valid source authority；
- quantity validity；
- terminal conflict；
- monotonic fill；
- duplicate semantics；
- `MANUAL_REVIEW` 条件；
- control-plane source exclusion。

它**不会调用**：

```text
EvidenceJournal
OmsRepository
state_machine.transition
OfflineOms
```

这是刻意设计的优点，因为这样它不会拿 implementation 自己证明 implementation 正确。

但这同时意味着：

```text
Reference Model PASS
    !=
Runtime Implementation Conformance PASS
```

当前 CI 证明的是：

1. Contract 自身是自洽的；
2. TLA+ 有限抽象没有找到 counterexample；
3. Schema 与独立 reference checker 一致；
4. Bridge protocol / side-effect audit 仍安全。

当前 CI **还没有证明**：

```text
实际 EvidenceJournal + Repository + FSM
```

对所有 contract case 都产生和 reference model 完全相同的结果。

因此需要新增独立的：

> `Broker Evidence Runtime Conformance Gate`

---

## 13. 风险分级

### HIGH

#### H1. 不同 terminal facts 被当 stale，而不是 `MANUAL_REVIEW`

可能掩盖 broker observation 自相矛盾。

#### H2. terminal 后新增更高 fill 可能被静默吸收

可能产生 lifecycle 与成交量语义不一致的 durable aggregate。

#### H3. 本地 submit/cancel API return 仍能直接推进 lifecycle

目前主要局限在 offline/simulation path，但与未来 broker-neutral architecture 明确冲突。

### MEDIUM

#### M1. EvidenceJournal 不是 `BrokerEvidence v1` 标准对象入口

Schema contract 与 runtime 入口尚未统一。

#### M2. runtime 未强制 source authority

DEAL fill-only 权限目前可以通过旧接口绕过。

#### M3. DB evidence identity 少 account dimension

当前 key 与正式 contract 不一致。

#### M4. 尚无 reference model ↔ runtime differential gate

CI 无法自动阻止未来实现偏离 contract。

### LOW

- 一些旧类名/注释仍带 P1/P4 历史语义；
- 文档与 runtime 类型名未完全统一；
- 这些问题本身不会直接造成 broker side effect。

---

## 14. 推荐下一 Gate：Broker Evidence Runtime Conformance Gate

在实现 Guojin mapper 之前，建议先完成这一 Gate。

### A. 引入真正的 `BrokerEvidenceV1` runtime model

例如：

```python
@dataclass(frozen=True)
class BrokerEvidenceV1:
    evidence_version: str
    source: str
    source_kind: BrokerEvidenceSourceKind
    source_event_id: str
    mapper_profile: str
    semantic_digest: str
    account_fingerprint: str
    client_order_id: str
    broker_token: str | None
    broker_order_id: str | None
    order_ref: str | None
    trade_id: str | None
    evidence_type: BrokerEvidenceType
    requested_status: OrderStatus
    filled_quantity: int
    observed_at_ms: int
    raw_payload_ref: str
    raw_status: ...
```

标准对象应在进入 OMS 前经过 Schema/semantic validation。

### B. EvidenceJournal 只消费标准对象

目标：

```text
BrokerEvidenceV1
    ↓
EvidenceJournal
```

禁止 production caller 自由拼接：

```text
source + evidence_type + requested_status
```

### C. DB migration 对齐 Contract

至少增加/调整：

```text
account_fingerprint
source_kind
mapper_profile
semantic_digest
broker_token
order_ref
trade_id
raw_payload_ref
raw_status
```

并将 identity key 改为：

```text
(source, account_fingerprint, source_event_id)
```

### D. 修正 terminal conflict 聚合

明确实现：

```text
FILLED + CANCELLED
FILLED + REJECTED
CANCELLED + REJECTED
    ↓
MANUAL_REVIEW
```

同时：

```text
CANCELLED/REJECTED + higher fill
    ↓
MANUAL_REVIEW
```

### E. 建立 differential / exhaustive implementation conformance

保留现有独立 reference model。

新增测试：

```text
for each finite contract case:
    expected = reference_model.apply(...)
    actual   = runtime_implementation.apply(...)
    assert actual == expected
```

不能让 runtime checker 复用 repository 的 transition table，否则又会退化为自证。

### F. 修改旧 SimulatedDriver API-return 语义

将：

```text
submit return → ACK
cancel return → CANCELLED
```

改为：

```text
submit/cancel return
    ↓
transport/control outcome
    ↓
ORDER/DEAL/query BrokerEvidence
    ↓
OMS lifecycle
```

这样 simulation/offline path 与未来 production path 共享相同 Evidence Contract。

### G. 完成 runtime gate 后再实现 broker-specific mapper

推荐顺序：

```text
Broker Evidence Runtime Conformance Gate
    ↓
Guojin raw → BrokerEvidence v1 mapper
    ↓
Guojin simulation replay / calibration
    ↓
Galaxy mapper
    ↓
production mapper soak
    ↓
未来独立 LIVE_CANARY Gate
```

不要反过来先写 Guojin mapper 再补 OMS runtime semantics，否则 mapper 会被迫适配一个尚未与 Contract 对齐的下游实现。

---

## 15. 安全边界结论

本审计没有发现当前 production SHADOW 部署存在新开启的 broker mutation authority。

当前边界继续保持：

```text
galaxy
  execution_mode = SHADOW
  live_submit = false
  live_cancel = false
  broker mutation call surface = ZERO

guojin
  execution_mode = SHADOW
  live_submit = false
  live_cancel = false
  broker mutation call surface = ZERO
```

`guojin_sim` 的 simulation calibration mutation 权限与 production 权限严格分离。

当前没有：

```text
LIVE
LIVE_ARMED
LIVE_CANARY
```

因此本文列出的 runtime contract gaps 当前主要影响：

- 架构一致性；
- 未来 mapper 接入安全；
- OMS lifecycle 语义完整性；
- 生产化前 Gate 完整性。

它们**不是“当前已经发生生产实盘错误”的证据**。

---

## 16. Gate 判定

### 当前判定

```text
Broker Evidence Protocol Gate              PASS
Broker Evidence Formal Verification Gate   PASS
Bridge Command/Event Protocol Gate          PASS
QMT Raw Calibration Boundary                PASS

Broker Evidence Runtime Conformance Gate    NOT STARTED / REQUIRED
Guojin Broker Evidence Mapper               NOT IMPLEMENTED
Galaxy Broker Evidence Mapper               NOT IMPLEMENTED
Production Live                             NO
```

### 推荐下一步

**不要直接开始 production mapper。**

下一正式任务应为：

> `Broker Evidence Runtime Conformance Gate`

验收条件：

1. `BrokerEvidenceV1` 成为 runtime 唯一标准输入；
2. EvidenceJournal / DB / FSM 与 v1 Contract 对齐；
3. terminal conflict 和 terminal-after-new-fill 全部 fail closed；
4.旧 API return 不再直接生成 broker lifecycle；
5. reference model 与 runtime implementation 做 differential exhaustive validation；
6. 所有现有 Bridge/TLA+/side-effect/deployment Gates 保持全绿；
7. production `galaxy/guojin` mutation authority 仍为 ZERO。

只有完成这一 Gate 后，才建议进入：

```text
Guojin raw status calibration
    ↓
Guojin BrokerEvidence mapper
```

---

## 17. 最终结论

当前系统已经完成了协议层的关键升级：

```text
“broker raw status 如何安全进入 OMS”
```

已经有明确、可形式验证的标准答案。

但当前代码库仍存在历史实现与新 Contract 的几处语义差异，因此目前不能把：

```text
Protocol PASS
```

等价为：

```text
Runtime Implementation PASS
```

下一阶段必须把两者真正收敛为：

```text
Contract
    ==
Reference Model
    ==
Runtime Implementation
    ==
CI Permanent Gate
```

完成这一步后，`Broker Evidence Contract v1` 才能从“已封版协议”升级为“已执行的运行时安全契约”。
