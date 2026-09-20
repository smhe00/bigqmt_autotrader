# P6 国金实盘 LIVE_CANARY Gate

日期：2026-09-18

> **当前授权（2026-09-20，任务 P6-T001 后生效）：`p6-guojin-live-canary-7`。**
> 一个 production LIVE_CANARY build 只授权一个 submit case：
> `00700.HGT BUY 100 @ 1.00 HKD`；submit/cancel fuse = 1/1。
> GC001 is a completed historical case and is **no longer authorized** in any current
> or later LIVE_CANARY mutation whitelist. `511880.SH` 保持 read-only diagnostic
> candidate，须等 HGT 实机结果经独立审计 PASS 后，由新的独立 Gate/build 授权，
> 本 build 不具有 511880 mutation authority。下文 build-1..build-6 内容仅作历史审计轨迹保留。

## 状态

已在国金实盘 QMT 中加载并完成首轮低风险校准。`00700.HK` 命令于本地交易模块
被明确拒绝为“下单代码 [HK00700] 不合法”，未进入券商委托表。国金本机行情日志
已发现南向港股通行情使用 `.SGT`。build-2 的强制合约预检成功阻止了一次无法确认
合约身份的提交，`passorder` 未被调用。build-3 在启动时只读探测 `.HK/.HGT/.SGT`
三种代码；实机中三者均返回空证券主数据。build-4 对三个候选代码建立只读 tick
订阅。实机结果表明 `.HK/.HGT/.SGT` 三者的订阅 API 均返回成功，但直到第 10 次
延迟探测，三者的 `get_instrument_detail` 仍全部为空，因此“订阅成功”本身不能用于
判定真实可交易路由。build-5 改为采集真实 tick callback 证据。券商登录权限开放后，
实机证券主数据又确认 `.SGT` 可归一为 `HK/00700` 且 `HSGTFlag=5`；因此在新的明确
授权下，build-5 先完成 GC001 实盘拒单校准，随后将新 session 的两个一次性 case
固定为腾讯 HGT 低价路由和 511880 资金不足路径。

## 固定授权面

```text
instance_id                 = guojin
execution_mode              = LIVE_CANARY
bridge_build                = p6-guojin-live-canary-7
account_type                = STOCK
authorized fingerprint      = sha256:7cbd3cda92705081654ef838f9b93ab9f7928349ecf05fe97205c2d2948434e5
allowed submit case (only)  = 00700.HGT BUY 100 @ 1.00 HKD (fixed non-marketable route probe)
max submit calls/session    = 1
max cancel calls/session    = 1 (one exact-token emergency cancel reserve)
cancel identity             = exact broker_order_id + broker_token
Tencent HGT preflight       = HK/00700, HSGTFlag 3|5, HUGANGTONG observed, fixed price 1.00
511880                      = read-only diagnostic candidate only; no mutation authority
GC001                       = historical completed case; no longer authorized
```

每个 build/session 至多一笔 submit。broker mutation crossing 后若发生异常：结果进入
UNKNOWN、当前 session 永久熔断、禁止自动 retry，重启也不得自动重新发布旧命令。
511880 的 exact-tick 路径须等下一个独立 Gate；其 freshness primitive
（`_live_canary_fresh_tick_price`，broker tick timestamp 权威、15 s 窗口、无时间语义即
fail closed）已在 build-7 中预先做对，但本 build 不使用它扩大任何 mutation symbol。

### 2026-09-18 GC001 实机结果

`204001.SH SELL 10 @ 100.000` 产生精确 token 匹配回报：status 50、broker order ID
`635003826`，随后 status 57，`cancel_info=订单价格超出范围`，零成交、10 全部撤销。
可用资金 2168.79 → 1168.78 → 2168.79，最终无持仓或资金副作用。校准扫描得到三条
`MATCHED_KNOWN_TOKEN`；该结果是 broker rejection，不是 UNKNOWN。

`galaxy` 和通用模板仍无 `passorder`/`cancel` 调用面。`guojin_sim` 保持独立模拟
profile，不与实盘 spool、session 或 fingerprint 混用。

## 三重显式授权

1. QMT 必须加载固定 build，并生成匹配的 `instance.json` 与 `bridge_ready`；
2. Host 如需接收该实例，必须显式传入 `--allow-live-canary`；
3. 发布命令必须使用独立 `live_canary_probe`，确认文本必须精确等于
   `AUTHORIZE_GUOJIN_LIVE_CANARY`，且命令携带当前 QMT session。

普通 Host 启动、SHADOW probe、simulation probe 均不能选择或驱动该实例。

## UNKNOWN 与 reconciliation

QMT 官方接口说明 `passorder` 为异步发送；函数返回不等待委托回报。因此：

- `LIVE_CANARY_SUBMIT_CALL_RETURNED` 只表示本地 API 调用返回；
- 它最多将 OMS 的 `SUBMITTING` 推进为 `UNKNOWN`，绝不产生 `ACKNOWLEDGED`；
- 只有严格映射后的 ORDER/DEAL/主动查询 `BrokerEvidenceV1` 能推进 broker lifecycle；
- 异常、进程崩溃或 claimed command 遗留一律进入 UNKNOWN，禁止自动重发；
- 没有 broker order ID 时禁止猜测撤单。

## build-1 实机结果与 build-2 修正

2026-09-18 04:02:54，build-1 在明确授权后调用：

```text
accountID   = pinned production account (redacted)
orderCode   = 00700.HK
broker_token= exact token observed locally (redacted)
```

QMT 本地日志证明 `passorder` 已到达 trade module，但同毫秒返回：

```text
[函数交易] 函数: passorder, 下单代码 [HK00700] 不合法!
```

随后的主动快照为 `orders=[]`、`deals=[]`，资金与持仓无变化，所以该次结果是
**LOCAL_REJECTED / zero broker side effect**，不是 broker ACK，也没有可撤订单。

QMT 官方代码约定区分香港交易所 `.HK`、沪港通 `.HGT`、深港通 `.SGT`。本机国金
行情日志已经存在 `00700.SGT` 的真实行情记录，故 build-2 禁止 `.HK` 并仅允许
`.SGT`。若合约详情预检缺失、为空或市场/代码不一致，将在 `passorder` 前失败关闭。

## build-2 安全门结果

build-2 重启后，`00700.SGT` 提交命令通过 Host/session/fingerprint 校验，但合约详情
预检没有得到严格匹配的 `SGT/00700`，命令进入 `commands/rejected`：

```text
result_status    = REJECTED_SAFETY_GATE
live_side_effect = false
passorder calls  = 0
orders/deals     = 0/0
```

这证明预检失败关闭有效，同时暴露出错误事件缺少细分原因、启动时没有证券路由证据。
build-3 补齐：

- 启动时探测 `00700.HK`、`00700.HGT`、`00700.SGT`；
- 输出查询方法、exchange/instrument/name/IsTrading/HSGTFlag；
- 仅输出白名单字段，不输出账户号；
- `CommandError` 的受控原因写入 `bridge_error.reason`；
- 探测本身纯只读，不消耗 submit/cancel 额度。

## build-4 实机只读结果

build-4 在国金实盘 QMT 中完成只读路由探测：

```text
00700.HK   subscribe_quote accepted=true  subscription_id=6
00700.HGT  subscribe_quote accepted=true  subscription_id=7
00700.SGT  subscribe_quote accepted=true  subscription_id=8
```

但启动探测、attempt=1 和 attempt=10 均得到：

```text
00700.HK   observed=false  instrument master empty
00700.HGT  observed=false  instrument master empty
00700.SGT  observed=false  instrument master empty
```

因此固定结论为：

- subscription ID 只证明 QMT 接受了订阅请求，不能证明该 suffix 是真实交易路由；
- `get_instrument_detail/get_instrumentdetail` 在当前国金 model runtime 中不能提供这三个港股/港股通候选代码的证券主数据；
- build-4 不足以在 HGT 与 SGT 之间做 route resolution；
- 在取得更强只读证据前，不发送下一笔 LIVE_CANARY。

## build-5 tick-evidence probe

build-5 为每个候选代码注册独立 `subscribe_quote(..., callback=...)` 回调，并仅把白名单字段写入新的 `instrument_tick_capabilities` 事件。QMT callback 的标准输入按 `{code: DataFrame}` 处理；只有 callback payload 中精确存在预期 symbol，且能读取最后一条 tick，才置 `tick_observed=true`。若特定 QMT 发行版无法加载 callback，定时探测改用官方只读 `get_full_tick([exact_symbol])` 取得同一白名单证据；返回字典必须精确包含所请求 symbol，禁止别名回退。核心判据从“subscription accepted”提升为“精确 route 的真实 tick 证据是否到达”。

每个候选 route 记录：

```text
symbol
subscription_id
accepted
callback_registered
tick_observed
callback_count
evidence.requested_symbol
evidence.reported_symbol
evidence.exact_symbol
evidence.raw_symbol
evidence.tick_index
evidence.exchange_id
evidence.tick_time
evidence.last_price
evidence.volume
evidence.amount
```

完整 tick 对象不会写入 spool。首次 callback 会立即发布诊断证据；若 callback 的 symbol 与预期 route 不匹配，只记录 mismatch，不算作 `tick_observed`。首次精确 route tick 到达后会再次发布证据；10 秒窗口结束后再发布 final summary。该探测纯只读，不调用 `passorder/cancel`，不消耗 submit/cancel fuse。

下一次实机动作（历史 build-5 计划，已被 build-7 收窄取代）当时只允许只读证据收集。
**当前有效指令以 build-7 为准（见文末）：旧的“先 GC001、reconciliation、再腾讯”多笔
顺序已作废；一个 build 只有一笔 `00700.HGT BUY 100 @ 1.00 HKD`。**

tick callback 只是必要条件，不是下单授权。Host publisher、当前 session、固定账户
指纹、时间窗、账户/证券主数据仍须同时满足；任何一项不满足都 fail-close。

## build-6 启动校验（2026-09-19）

QMT 已实际加载 build-6，并生成新的隔离会话：

```text
bridge_build = p6-guojin-live-canary-6
session_id   = 8756a38e70004a5ca3df026540bd4a6a
instance_id  = guojin
mode         = LIVE_CANARY
submit/cancel fuse = 2/2
```

启动主动查询确认 `STOCK`、`HUGANGTONG`、`SHENGANGTONG` 均为 `DETECTED`。
只读证券主数据将 `00700.HGT` 规范化到 `HK/00700`，名称为腾讯控股，
`HSGTFlag=5`。`get_full_tick([exact_symbol])` 回退取得了严格同代码证据：

```text
00700.HGT  exact_symbol=true  last_price=419.0
511880.SH  exact_symbol=true  last_price=100.8
```

上述 tick 来自上一交易日，不构成非交易时段下单依据。build-6 启动与路由预检通过，
但交易校准仍待下一个有效交易窗口。

> build-6 的后续多笔执行计划（HGT 之后再做 511880）**已作废**：build-7 已将授权
> 收窄为单笔 HGT，见下节。

## build-7 授权收窄（2026-09-20，任务 P6-T001）

审计发现 build-6 的“two named cases only”只是文档声明，代码仍保留第三条
GC001 mutation 路径，且 case 去重/session 计数不能强制“上一笔完全收敛后才允许下一笔”。
build-7 的修复决策是更窄、更易审计的规则：**一个 production LIVE_CANARY build 只授权
一个 submit case**。

当前有效执行指令：

1. 加载 `p6-guojin-live-canary-7`，启动 Host 并读取 `bridge_ready`；
2. 在下一个有效交易窗口内，仅发布一次 `00700.HGT BUY 100 @ 1.00 HKD`；
3. 随后完整做 ORDER/DEAL/query/BrokerEvidence reconciliation；任何 UNKNOWN 立即永久熔断；
4. 如该委托意外进入可撤状态，仅允许一次按精确 `broker_order_id + broker_token` 的撤单；
5. 不授权 `511880.SH` submit：它保持只读诊断身份，待 HGT 结果被独立审计 PASS 后，
   由新的独立 Gate/build 授权，届时 exact-tick preflight 必须通过
   `_live_canary_fresh_tick_price`（broker tick timestamp 权威、15 s 新鲜窗口、
   无法证明时间语义即拒绝；本地刚调用过 `get_full_tick` 不会把旧 tick 变成新 tick）。

永久 regression gate：`tests/qmt/test_live_canary_authority_contract.py`
（host/artifact/schema/docs 的授权语义，而非仅 call-site 数量）。
