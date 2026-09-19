# P5 模拟证券范围更新 — 2026-09-17

## 结论

`guojin_sim` V5 build 已升级为 `p5-simulation-calibration-5`。

原限制：

```text
side = BUY
quantity = 100
```

现限制：

```text
side in {BUY, SELL}
1 <= quantity <= 100
symbol = six-digit .SH/.SZ or five-digit .HK/.HGT/.SGT security
```

BUY 使用官方 passorder opType `23`，SELL 使用 opType `24`。这允许在绑定的
STOCK 模拟账户中校准股票、ETF、可转债、`204001.SH` 以及港股通证券的受限买卖路径。

## 仍然保留的安全门

- `terminal_instance_id == guojin_sim`；
- `SIMULATION_CALIBRATION` + `simulation_only=true`；
- 固定模拟账户 fingerprint；
- command 必须携带当前 QMT session；
- 每单最多 100 单位，价格必须为正且不超过既有上限；
- submit/cancel session fuse 仍为 2,000；
- exact `client_order_id -> broker_token -> m_strRemark`；
- cancel 仍要求 broker order ID 与 token 唯一匹配；
- claimed/unknown command 仍禁止盲目重放；
- `guojin`、`galaxy`、通用模板的 broker mutation call surface 仍为零。

## Publisher

`simulation_probe submit` 现在强制显式传入 `--side BUY|SELL`。例如 GC001 的
simulation command 必须由操作者在新 build 启动后，根据新鲜行情明确提供数量与
限价；代码不会自动选择价格、重发或撤单。

## 国金单一股票账号下的港股通修正

实机确认国金将 A 股和港股通交易挂在同一个 `STOCK` 资金账号后，模拟 build
升级为 `p5-simulation-calibration-5`。交易仍使用清单固定的 `STOCK` 账号；启动时
同时只读探测 `STOCK/HUGANGTONG/SHENGANGTONG` 能力，但不会把附挂能力错误建模为
第二个资金账号。交易市场由证券代码后缀表达。

允许的港股代码格式为五位 `.HK/.HGT/.SGT`，例如 `00700.HGT`。六位 `.SH/.SZ`
规则保持不变。build-5 还复用实盘已验证的只读证券主数据与精确
`get_full_tick([exact_symbol])` 证据探测，以便先校准实际路由再提交。该扩展仍仅
存在于 `guojin_sim` 生成物；生产 `guojin`、`galaxy` 文件未发生变化。
