# P5 模拟证券范围更新 — 2026-09-17

## 结论

`guojin_sim` V5 build 已升级为 `p5-simulation-calibration-4`。

原限制：

```text
side = BUY
quantity = 100
```

现限制：

```text
side in {BUY, SELL}
1 <= quantity <= 100
symbol = six-digit .SH/.SZ or five-digit .HK security
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
升级为 `p5-simulation-calibration-4`。账号发现仍只需要确认清单固定的 `STOCK`
账号；交易市场由证券代码后缀表达，不再要求额外发现 `HUGANGTONG` 或
`SHENGANGTONG` 账号类型。

新增的唯一证券格式为五位 `.HK`，例如 `00700.HK`。六位 `.SH/.SZ` 规则保持
不变。该扩展仍仅存在于 `guojin_sim` 生成物，生产 `guojin`、`galaxy` 文件没有
任何 broker mutation 调用面。
