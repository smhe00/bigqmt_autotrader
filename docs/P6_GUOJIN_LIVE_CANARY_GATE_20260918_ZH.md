# P6 国金实盘 LIVE_CANARY Gate

日期：2026-09-18

## 状态

代码已实现并通过静态/回归 Gate；尚未在国金实盘 QMT 中加载，因此尚未武装，也
没有发送任何实盘命令。

## 固定授权面

```text
instance_id                 = guojin
execution_mode              = LIVE_CANARY
bridge_build                = p6-guojin-live-canary-1
account_type                = STOCK
authorized fingerprint      = sha256:7cbd3cda92705081654ef838f9b93ab9f7928349ecf05fe97205c2d2948434e5
allowed submit              = 00700.HK BUY 100 @ 1.00 HKD
max submit calls/session    = 1
max cancel calls/session    = 1
cancel identity             = exact broker_order_id + broker_token
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

## 部署后的首个实机步骤

首次启动只执行只读快照，核对 fingerprint、session、当日订单/成交和 broker token
冲突。首个 canary 的限价固定为 1.00 HKD，名义金额上限为 100 HKD，用于校准
受理/拒绝路径而非追求成交。任何实盘提交仍需要另一次明确指令；本次
代码更新与 Git 推送本身不构成下单授权。
