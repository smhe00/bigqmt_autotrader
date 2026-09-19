# P6 LIVE_CANARY Authority Repair Task

日期：2026-09-20  
基线：`main@1e5c42e9a6e19107fb01a888ea95499751a8726d`  
Gate verdict：**CHANGES_REQUIRED**  
任务类型：**执行安全边界修复；仅代码/测试/文档，禁止任何 broker mutation**

## 1. 审计结论

当前 P6 文档声明 production Guojin LIVE_CANARY 只保留两个命名 case：

1. `00700.HGT BUY 100 @ 1.00`
2. `511880.SH BUY 100 @ guarded exact tick`

并明确写明 GC001 已完成、不得重复提交。

但当前代码实际仍允许第三条 mutation 路径：

```text
204001.SH SELL 10 @ 100.000
```

该残留同时存在于：

- `src/bigqmt_autotrader/qmt/live_canary_probe.py`
- `tools/build_qmt_deployments.py` 的 `LIVE_CANARY_EXECUTOR`
- 生成物 `qmt_side/BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN.py`
- `tests/qmt/test_live_canary_probe.py`

因此“two named cases only”目前不是代码级不变量，只是文档声明。

另外，当前两个 case 的顺序与 reconciliation barrier 也没有代码强制：
publisher 可以直接发布任一 case，bridge 只限制 case 去重和 session submit 总数，并不知道上一笔是否已经由 ORDER/DEAL/query 完整收敛。

第三个问题是 511880 的 exact-tick guard 只要求历史上存在 `tick_observed=true` 和正价格，没有验证该 tick 对当前交易时刻仍然新鲜。启动时 `get_full_tick` 取得的上一交易日 tick 也可能被写成 observed；若 bridge 长时间运行，该记录不会自动失效。

## 2. 本任务的安全决策

不在同一 build/session 中实现复杂的“case 1 reconciliation 后自动解锁 case 2”。

采用更窄、更易审计的规则：

> **一个 production LIVE_CANARY build 只授权一个 submit case。**

下一 build 只允许：

```text
00700.HGT BUY 100 @ 1.00 HKD
```

511880 保留为 **read-only diagnostic candidate**，但本 build 不具有 511880 mutation authority。

GC001 彻底从当前及后续 LIVE_CANARY mutation whitelist 移除。

完成 HGT 实机结果及 broker evidence reconciliation 后，再通过新的独立 Gate/build 明确授权 511880。

## 3. 必须修改

### A. Host publisher 收窄为单一 case

修改：

`src/bigqmt_autotrader/qmt/live_canary_probe.py`

要求：

- 删除 GC001 submit authority；
- 删除 511880 submit authority；
- 本 build 只接受：
  - symbol = `00700.HGT`
  - side = `BUY`
  - quantity = `100`
  - limit_price = `1.00`
- 其它 symbol/side/quantity/price 必须在写入 command spool **之前** fail closed；
- cancel 仍只允许 exact `client_order_id + broker_order_id + broker_token` 对应订单；
- 保留精确 confirmation string、fingerprint、build、session pinning。

### B. QMT production bridge 收窄为单一 mutation symbol

修改：

`tools/build_qmt_deployments.py`

要求 production live executor：

```text
_LIVE_CANARY_MUTATION_SYMBOLS = ("00700.HGT",)
```

并删除 `_execute_order_command()` 中 GC001 与 511880 submit 分支。

`_LIVE_CANARY_INSTRUMENT_CANDIDATES` 可以继续包含：

- 204001.SH
- 511880.SH
- 00700.HK
- 00700.HGT
- 00700.SGT

因为它们只是只读诊断对象；**diagnostic candidate != mutation authorization**。

### C. 每个 build/session 只允许一次 submit

production Guojin LIVE_CANARY：

```text
max submit calls/session = 1
max cancel calls/session = 1
```

同步修改 mutation gate 的静态常量检查。

如果 broker API crossing 后发生异常：

- 结果仍必须进入 UNKNOWN；
- 当前 session 永久 halt；
- 禁止自动 retry；
- 重启后也不能把旧命令自动重新发布。

### D. bump build

新 build：

```text
p6-guojin-live-canary-7
```

必须通过 generator 生成：

`qmt_side/BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN.py`

不得手工维护 generated artifact 与 generator 两份逻辑。

### E. 建立 LIVE_CANARY authority permanent regression gate

新增 pytest（建议文件）：

`tests/qmt/test_live_canary_authority_contract.py`

永久验证至少以下不变量：

1. Host publisher 当前只接受 `00700.HGT BUY 100 @ 1.00`；
2. `204001.SH` submit 必须拒绝且 spool 中无 command；
3. `511880.SH` submit 必须拒绝且 spool 中无 command；
4. generated Guojin bridge mutation whitelist 精确等于 `("00700.HGT",)`；
5. generated Guojin bridge submit fuse = 1；
6. generated Guojin bridge cancel fuse = 1；
7. generic / Galaxy artifact 仍为零 mutation surface；
8. `guojin_sim` 权限不因本任务发生变化；
9. `tools/build_qmt_deployments.py --check` 必须通过；
10. docs/Host/generated artifact 对 build ID 和 live mutation case 的描述必须一致。

不要只测试 `passorder` 调用点数量。当前 bug 正是证明：

> **“只有一个 passorder 调用点”不能推出“只有两个/一个授权 case”。**

CI 必须检查 authorization semantics，而不仅是 call surface。

## 4. Tick freshness 修复

本 build 不授权 511880 mutation，但必须在本任务中把未来 exact-tick preflight 的 freshness primitive 做正确，防止下一 Gate 再带着已知缺陷推进。

要求：

- tick record 必须保留本地 observation timestamp；
- 若 broker tick 自带可解析 timestamp，也必须保留并校验；
- 提供一个 fail-closed helper，例如：
  `_live_canary_fresh_tick_price(symbol, ...)`；
- stale observation 必须拒绝；
- 上一交易日 tick 必须拒绝；
- 无法证明时间语义时必须拒绝，而不是假定 fresh；
- 单纯因为 `get_full_tick`“刚刚被调用”不能把旧行情变成新行情；
- exact-symbol identity 检查继续保留。

本 build 不得使用这个 helper 来扩大任何 mutation symbol；它是为下一次独立 511880 Gate 准备的基础设施。

测试至少覆盖：

- fresh exact tick -> PASS helper；
- stale local observation -> reject；
- previous-session/day tick -> reject；
- symbol mismatch -> reject；
- missing/invalid tick time -> reject 或明确证明所选 QMT 时间格式可安全判断；
- positive price 但 stale -> reject。

## 5. 文档一致性修复

至少更新：

- `README.md`
- `docs/PROJECT_OVERVIEW_ZH.md`
- `docs/PROJECT_STATUS.md`
- `docs/P6_GUOJIN_LIVE_CANARY_GATE_20260918_ZH.md`
- `docs/FORMAL_VERIFICATION.md`（若其中记录了 build/fuse/authority）

当前状态应明确：

```text
p6-guojin-live-canary-7
authorized mutation case = 00700.HGT BUY 100 @ 1.00 only
submit fuse = 1
cancel fuse = 1
GC001 = historical completed case, no longer authorized
511880 = read-only / future independent Gate only
general production live trading = NO
```

同时清理 P6 Gate 中仍出现的旧“GC001 -> reconciliation -> Tencent”执行指令，避免操作者误读。

## 6. Allowed files

实现原则上限定在：

- `src/bigqmt_autotrader/qmt/live_canary_probe.py`
- `tools/build_qmt_deployments.py`
- `qmt_side/BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN.py`（generator 生成）
- `tests/qmt/test_live_canary_probe.py`
- `tests/qmt/test_live_canary_authority_contract.py`（新增）
- 必要的 live-canary / deployment tests
- 上述状态文档

若必须修改其它执行代码，先在 implementation report 中说明原因；不要顺手重构 OMS、Risk、BrokerEvidence 或 simulation path。

## 7. 明确禁止

本任务禁止：

- 在国金实盘调用 `passorder`；
- 在国金实盘调用 `cancel`；
- 发布任何 production command 到正在运行的 QMT spool；
- 扩大 symbol / side / quantity / price 范围；
- 开启 Galaxy mutation；
- 开启 generic mutation；
- 将 `LIVE_CANARY` 升级成 `LIVE_ARMED`；
- 自动重试 UNKNOWN；
- 用 command_result 代替 BrokerEvidence；
- 因测试方便而放宽 fingerprint / session / token / trading-window gate。

## 8. 必须运行的验证

至少：

```bash
pytest -q
python tools/audit_side_effect_calls.py
python tools/build_qmt_deployments.py --check
python tools/verify_bridge_protocol_exhaustive.py
python tools/verify_bridge_schema_contract.py
python tools/verify_broker_evidence_contract.py
```

若本机具备 TLA+ 环境，再运行全部现有 TLC permanent models；本任务不允许通过修改 invariant 来消除失败。

## 9. Implementation report

完成后新增：

`docs/P6_LIVE_CANARY_AUTHORITY_REPAIR_RESULT_20260920_ZH.md`

报告必须包含：

- 修改文件；
- build ID；
- live mutation whitelist；
- submit/cancel fuse；
- GC001 negative test；
- 511880 negative mutation test；
- HGT positive bounded test；
- tick freshness test matrix；
- generator consistency；
- side-effect static audit；
- pytest / protocol / schema / evidence verification 结果；
- 明确声明 **未执行任何实盘 broker mutation**；
- git commit SHA。

## 10. Gate exit criteria

只有全部满足以下条件才允许进入下一次实机 HGT canary：

1. production live mutation authority 精确只有 `00700.HGT BUY 100 @ 1.00`；
2. submit/cancel fuse = 1/1；
3. GC001 和 511880 mutation 均有 fail-closed negative test；
4. authority semantic regression gate 已进入 pytest/CI；
5. generated artifact 与 generator 完全一致；
6. generic/Galaxy 仍 mutation-free；
7. simulation 权限未变化；
8. 所有要求验证 PASS；
9. 文档与代码无授权漂移；
10. 本修复任务本身没有发生任何 production broker mutation。

满足后，下一 runtime Gate 才是：

> 在新的 `p6-guojin-live-canary-7` session 中，仅执行一次
> `00700.HGT BUY 100 @ 1.00`，随后完整做 ORDER/DEAL/query/BrokerEvidence reconciliation。

在该结果被独立审计并 PASS 之前，**不得授权 511880 submit**。
