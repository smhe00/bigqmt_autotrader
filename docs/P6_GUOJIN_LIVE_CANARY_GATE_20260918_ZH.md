# P6 国金实盘 LIVE_CANARY Gate

日期：2026-09-18

## 状态

已在国金实盘 QMT 中加载并完成首轮低风险校准。`00700.HK` 命令于本地交易模块
被明确拒绝为“下单代码 [HK00700] 不合法”，未进入券商委托表。国金本机行情日志
已发现南向港股通行情使用 `.SGT`。build-2 的强制合约预检成功阻止了一次无法确认
合约身份的提交，`passorder` 未被调用。build-3 在启动时只读探测 `.HK/.HGT/.SGT`
三种代码，并把规范化结果写入 `bridge_ready`，继续仅允许 `00700.SGT`。

## 固定授权面

```text
instance_id                 = guojin
execution_mode              = LIVE_CANARY
bridge_build                = p6-guojin-live-canary-3
account_type                = STOCK
authorized fingerprint      = sha256:7cbd3cda92705081654ef838f9b93ab9f7928349ecf05fe97205c2d2948434e5
allowed submit              = 00700.SGT BUY 100 @ 1.00 HKD
max submit calls/session    = 1
max cancel calls/session    = 1
cancel identity             = exact broker_order_id + broker_token
instrument preflight        = get_instrument_detail/get_instrumentdetail must return non-empty SGT/00700 metadata
```

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

## build-3 下一实机步骤

重新加载 build-3 后首次启动只读取 `bridge_ready.instrument_probe`，核对 fingerprint、
session、当日订单/成交和 broker token
冲突。首个 canary 的限价固定为 1.00 HKD，名义金额上限为 100 HKD，用于校准
受理/拒绝路径而非追求成交。任何实盘提交仍需要另一次明确指令；本次
代码更新与 Git 推送本身不构成下单授权。
