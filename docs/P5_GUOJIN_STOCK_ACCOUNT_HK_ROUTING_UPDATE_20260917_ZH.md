# 国金模拟 STOCK 单账号港股通路由修正

日期：2026-09-17

## 实机结论

国金 QMT 的 A 股和港股通交易复用同一个股票资金账号。V5 启动探测只发现
`STOCK` 是正常结果；`HUGANGTONG`、`SHENGANGTONG` 未被探测为独立账号，不能
被解释为港股通交易能力不存在。

因此账号身份与交易市场必须分离：

```text
account identity = instance.json 固定的 STOCK 指纹
market routing   = symbol 后缀 SH / SZ / HK
```

## build 4 变更

仅 `guojin_sim` 的 `p5-simulation-calibration-4` 接受：

- 六位数字加 `.SH` 或 `.SZ`；
- 五位数字加 `.HK`；
- 显式 `BUY` 或 `SELL`；
- 整数数量 `1..100`。

Host 发布器与 QMT V5 执行器执行同一证券格式校验。`00700.HK` 会继续使用当前
清单固定的 `STOCK` 账号和原有 passorder BUY/SELL 路径；不会切换账户、猜测
账号类型或绕过指纹、session、broker_token、价格、次数及撤单闸门。

## 不变的安全边界

- 只允许实例 `guojin_sim`；
- `guojin`、`galaxy` 仍为 SHADOW，`live_submit=false`、`live_cancel=false`；
- 港股代码必须是五位数字，`700.HK` 等非规范格式拒绝；
- build 3 运行实例不会接受 `.HK`，必须显式加载 build 4 后才能校准；
- 非交易时段不以券商返回作为成交能力校准证据；
- `command_result` 或 passorder 返回仍不等于 broker ACK，生命周期只由严格
  ORDER/DEAL/主动查询证据推进。

## 2026-09-17 盘后实机探测

build 4 在 session `914404bedcee421899b284d63b7b5edc` 中发布了一次：

```text
client_order_id = hk-afterhours-cal-20260917-001
command_id      = fde8ab7045d04cf4a614f3b355ce62e1
broker_token    = BQ4918b9ada7c7c6a4b82d
symbol          = 00700.HK
side            = BUY
quantity        = 100
limit_price     = 1.00
```

V5 返回 `SIMULATION_SUBMIT_CALL_RETURNED` 与 `live_side_effect=true`，证明 `.HK`
命令通过同一个 `STOCK` 账号到达 `passorder` 调用面。随后主动
`REQUEST_SNAPSHOT`（command `99db706441024c33908cd94c89b16a36`）返回完整且
无查询错误的快照，但订单、成交、持仓和可用资金均未出现该 token 的变化，也没有
收到 ORDER/DEAL callback。

该结果严格分类为 `API_CALL_RETURNED_BROKER_STATE_NOT_OBSERVED`，不是 broker
ACK、拒绝证据或成交证据。由于处于非交易时段，没有重发，也没有构造无 broker
order ID 的撤单。交易时段仍需用新的 client order ID 做一次受限校准。
