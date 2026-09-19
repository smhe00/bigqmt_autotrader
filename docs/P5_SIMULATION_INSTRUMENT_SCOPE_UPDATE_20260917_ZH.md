# P5 模拟证券范围更新 — 2026-09-17

## 结论

`guojin_sim` V5 build 已升级为 `p5-simulation-calibration-6`。

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
升级为 `p5-simulation-calibration-6`。交易仍使用清单固定的 `STOCK` 账号；启动时
同时只读探测 `STOCK/HUGANGTONG/SHENGANGTONG` 能力，但不会把附挂能力错误建模为
第二个资金账号。交易市场由证券代码后缀表达。

允许的港股代码格式为五位 `.HK/.HGT/.SGT`，例如 `00700.HGT`。六位 `.SH/.SZ`
规则保持不变。build-5 还复用实盘已验证的只读证券主数据与精确
`get_full_tick([exact_symbol])` 证据探测，以便先校准实际路由再提交。该扩展仍仅
存在于 `guojin_sim` 生成物；生产 `guojin`、`galaxy` 文件未发生变化。

## build 5 实机启动结果（2026-09-19）

模拟 QMT 已加载 build `p5-simulation-calibration-5`，新 session 为
`3b81348312894dce8df6de5d83e1dcb3`。主动账户探测同时发现 `STOCK`、
`HUGANGTONG`、`SHENGANGTONG`，选定交易身份仍为清单固定的 `STOCK`。

证券主数据对 `00700.HK/.HGT/.SGT` 均返回规范身份 `HK/00700`、腾讯控股和
`HSGTFlag=5`。五个候选代码全部取得严格同代码 quote callback：

```text
204001.SH  exact=true  last=1.025
511880.SH  exact=true  last=100.8
00700.HK   exact=true  last=419.0
00700.HGT  exact=true  last=419.0
00700.SGT  exact=true  last=419.0
```

Host 使用 `--allow-simulation-mutation` 完成当前会话回放：read model healthy、
spool pending 0、transport/semantic quarantine 0。上述行情属于上一交易日，
本次只读验收没有发布 SUBMIT/CANCEL；交易路由能力仍须在有效交易时段以模拟账户
ORDER/DEAL 证据校准。

## 非交易时段实机安全矩阵（2026-09-19）

在同一 build-5 session 中执行了仅包含只读动作或保证在 broker mutation 调用前
失败的实机矩阵：

| Case | QMT 结果 | Broker side effect |
|---|---|---:|
| `REQUEST_SNAPSHOT` | `SNAPSHOT_EMITTED` | false |
| stale session | `REJECTED_SAFETY_GATE` | false |
| missing simulation authorization | `REJECTED_SAFETY_GATE` | false |
| malformed `700.HGT` symbol | `REJECTED_SAFETY_GATE` | false |
| quantity `101` | `REJECTED_SAFETY_GATE` | false |
| zero limit price | `REJECTED_SAFETY_GATE` | false |
| cancel without exact token/order match | `REJECTED_SAFETY_GATE` | false |
| wrong account fingerprint | command frame rejected | false |

Host 发布端另外在写入 spool 前拒绝 expired command、冲突的重复 command ID，
以及 `market=CN` 搭配 `route_hint=HGT` 的不一致路由。

测试前后主动快照均为 available cash `6406056.56`、positions `2`、orders `0`、
deals `0`、query errors `0`。最终 command inbox/claimed/unknown 均为 0；Host 回放
`read_model_healthy=true`、spool pending 0、transport/semantic quarantine 0。

## build 6 有界板块发现

build-6 在大QMT策略内部调用只读 `ContextInfo.get_stock_list_in_sector`，尝试多个
常见港股通板块名称。无论板块返回多少成分，最多选择 6 个底层五位港股代码，并
展开为 `.HK/.HGT/.SGT`；连同 `204001.SH`、`511880.SH`，启动诊断 route 总数
上限为 20。板块返回值、选择结果、截断状态和查询错误均写入
`bridge_ready.instrument_subscription.sector_discovery`。

板块不可用、名称不匹配或查询异常时，系统退回腾讯加两只沪市证券的原固定候选。
发现列表只用于证券主数据和精确 tick 证据，不发布命令、不调用 `passorder/cancel`，
也不代表证券已经获得交易授权。
