---
workflow_schema: 1
phase: P6
task_id: P6-T001
iteration: I01
task_key: P6-T001-I01
reply_to: workflow/tasks/P6-T001-I01__live-canary-authority-repair.md
status: REVIEW_READY
owner: agent
review_target: workflow/reviews/P6-T001-I01__architect-review.md
---

# P6-T001-I01 Implementation Report

> 本文件是该任务唯一合法的 Agent 回复位置。  
> Agent 完成实现后直接更新本文件，不另建“最新报告”或日期命名报告。

## 1. Result

- Status: `REVIEW_READY`
- Implementation commit: 52879b448cfae0b3b8678457732a58b56073f454
- Final commit: 52879b448cfae0b3b8678457732a58b56073f454
`00700.HGT BUY 100 @ 1.00 HKD`，submit/cancel fuse = 1/1，build bump 到
`p6-guojin-live-canary-7`，GC001/511880 submit 授权在 Host publisher 与生成的 QMT
bridge 两侧均被移除，tick freshness fail-closed primitive 已落地并带完整测试矩阵，
永久 authorization-semantic regression gate 已进入 pytest。

## 2. Files changed

产品/契约代码：

- `src/bigqmt_autotrader/qmt/live_canary_probe.py` — Host publisher 收窄为单一固定 case；
  删除 GC001/511880 submit 分支与 per-symbol 时间窗；任何其它 symbol/side/quantity/price
  在写入 command spool 前 fail closed；cancel 语义不变（exact id+token，含全状态目录去重）。
- `tools/build_qmt_deployments.py` — LIVE_CANARY_EXECUTOR 收窄：
  `_LIVE_CANARY_MUTATION_SYMBOLS = ("00700.HGT",)`；新增固定授权常量
  `_LIVE_CANARY_AUTHORIZED_SIDE/QUANTITY/LIMIT_PRICE`；删除 GC001/511880 preflight 与
  submit 分支、per-case 记账与现金门槛分支；交易窗只保留 HGT；新增
  `_live_canary_tick_epoch_ms` + `_live_canary_fresh_tick_price`；
  live_canary profile 替换表改为 build-7 与 fuse 1/1，不再改写模板静态 gate；
  simulation 诊断剥离规则同步更新（live 授权常量不泄漏到 guojin_sim）。
- `qmt_side/BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN.py` — 由 generator 重新生成（未手工编辑）。
- `schemas/bridge/v1/instance.schema.json` — LIVE_CANARY 条件契约的
  `max_submit_calls_per_session` / `max_cancel_calls_per_session` const 2 → 1
  （**偏差项**，见 §11：schema 是 fuse 的正式契约常量，必须与 artifact 一致）。

测试：

- `tests/qmt/test_live_canary_authority_contract.py` — **新增**，永久 gate（34 个测试）。
- `tests/qmt/test_live_canary_probe.py` — 按单一 case 重写。
- `tests/contract/test_qmt_bridge_v05_live_canary.py` — 由“三 case 正向”改为
  “HGT 单 case 正向 + GC001/511880/shape drift 负向 + fuse 第二笔拒绝”。
- `tests/qmt/test_bridge_api_contract.py` — LIVE_CANARY manifest fixture 更新 build-7 / fuse 1。

文档：

- `README.md`、`docs/PROJECT_OVERVIEW_ZH.md`、`docs/PROJECT_STATUS.md`、
  `docs/P6_GUOJIN_LIVE_CANARY_GATE_20260918_ZH.md`、`docs/FORMAL_VERIFICATION.md`（任务指定）；
- 另更新 `docs/BRIDGE_API_V1_ZH.md`、`docs/BROKER_EVIDENCE_CONTRACT_V1_ZH.md`、
  `docs/P4_SHADOW_BRIDGE_SCOPE.md` 以消除“两个案例”的规范性授权漂移（见 §11）。

未改动：OMS、Risk、BrokerEvidence、simulation path、generic 模板、galaxy artifact。
`qmt_side/BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN_SIM.py` 经 generator 重生成后内容零差异
（最终 diff 为空）。

## 3. Authority boundary after change

```text
bridge_build = p6-guojin-live-canary-7
authorized live mutation symbols = ("00700.HGT",)
authorized live submit case = 00700.HGT BUY 100 @ 1.00 HKD (fixed, non-marketable)
max submit calls/session = 1
max cancel calls/session = 1
generic mutation surface = ZERO (TRADING/LIVE_SUBMIT/LIVE_CANCEL all False)
galaxy mutation surface = ZERO (same)
guojin_sim authority changed = NO (build p5-simulation-calibration-7, SIMULATION_ONLY, fuse 2000/2000, qty 100)
```

QMT 侧静态绑定 gate（模板内置）在 LIVE_CANARY 分支要求 fuse 恰好 1/1；build-7 的
artifact 常量与之一致，旧的“把 1 改写成 2”替换已删除。broker crossing 后异常仍进入
UNKNOWN、session 永久 halt、无自动 retry；重启不自动重发（命令 TTL/去重语义未改）。

## 4. Required negative tests

| Test | Expected | Result |
|---|---|---|
| GC001 `204001.SH` live submit（Host） | reject before spool，inbox 无命令 | PASS `test_invariants_2_3_...[case0]` / probe `test_live_probe_rejects_every_other_case_before_spool` |
| GC001 live submit（generated bridge） | CommandError，passorder 不调用，fuse 不消耗 | PASS `test_generated_executor_rejects_gc001_and_511880_without_broker_call` |
| `511880.SH` live submit（Host） | reject before spool | PASS 同上参数化 case1 |
| `511880.SH` live submit（generated bridge） | CommandError，passorder 不调用 | PASS 同上 |
| wrong HGT side (`SELL`) | reject | PASS（Host + bridge 参数化） |
| wrong HGT quantity (200/1000/11) | reject | PASS（Host + bridge 参数化） |
| wrong HGT price (1.01/0.99/99.99) | reject | PASS（Host + bridge 参数化） |
| wrong session / live_canary flag / unknown symbol | fail closed | PASS `test_live_canary_rejects_any_scope_expansion`（10 参数） |
| 旧 build-6 instance | Host pinned loader 拒绝 | PASS `test_live_probe_rejects_old_build_instance` |
| 第二笔 HGT submit | fuse=1 拒绝，passorder 仅 1 次 | PASS `test_generated_executor_blocks_second_submit_via_fuse` / contract `test_live_canary_submit_is_exactly_bounded` |

## 5. HGT bounded positive test

仅离线执行，未向任何 production QMT spool 发布命令：

```text
00700.HGT BUY 100 @ 1.00
```

- Host publisher：`test_invariant_1_host_publisher_accepts_exactly_the_single_hgt_case`、
  `test_live_probe_publishes_exact_hgt_case`（payload 精确等于
  symbol/side/quantity/limit_price + live_canary + 当前 session pin）。PASS
- Generated bridge：`test_live_canary_submit_is_exactly_bounded` 断言
  `passorder(23, 1101, account, "00700.HGT", 11, 1.0, 100, "BIGQMT_LIVE_CANARY", 2, token, ContextInfo)`。PASS

## 6. Tick freshness test matrix

Primitive：`_live_canary_fresh_tick_price(symbol, now_ms=None, freshness_ms=15000)`，
位于生成的 Guojin bridge（live-only，不进入 sim diagnostics）。规则：
broker tick timestamp（`evidence.tick_time`，秒级自动×1000）为权威时间；
本地 `last_callback_ms` 新鲜不能洗白旧行情；缺失/不可解析/非正时间戳、exact-symbol
不成立、reported_symbol 不匹配、未来时间戳（时钟偏移）、年龄 > 15 s 一律 fail closed。

| Scenario | Expected | Result |
|---|---|---|
| fresh exact-symbol tick（5 s） | 返回 100.805 | PASS `test_fresh_exact_symbol_tick_is_accepted` |
| 秒级 epoch 时间戳 | 归一化后接受 | PASS `test_seconds_epoch_tick_time_is_normalized_and_accepted` |
| stale local observation（callback 刚到，broker tick 30 s 旧） | reject（“刚调 get_full_tick”不能洗白） | PASS `test_stale_local_observation_is_rejected_even_if_callback_was_recent` |
| previous trading day tick（86400 s） | reject stale | PASS `test_previous_trading_day_tick_is_rejected` |
| symbol mismatch（reported_symbol≠请求） | reject mismatch | PASS `test_tick_symbol_mismatch_is_rejected` |
| missing/invalid broker tick time（None/""/文本/0/-1） | reject unavailable | PASS `test_missing_or_invalid_broker_tick_time_fails_closed[*]` |
| positive price but stale（101.0, 60 s） | reject stale | PASS `test_positive_price_but_stale_tick_is_rejected` |
| future tick（broker 时间领先 60 s） | reject future/clock-skew | PASS `test_future_broker_tick_is_rejected_as_clock_skew` |
| 非法价格（None/""/0/负数/文本） | fail closed | PASS `test_invalid_price_fails_closed[*]` |
| 无 observation 记录 | reject unavailable | PASS `test_missing_observation_fails_closed` |
| exact_symbol=false | reject invalid | PASS `test_exact_symbol_identity_remains_required_for_freshness` |
| 常量值 | `_LIVE_CANARY_TICK_FRESHNESS_MS == 15000` | PASS `test_freshness_constant_is_fifteen_seconds` |

本 build 不使用该 helper 扩大 mutation；511880 重新授权时其 exact-tick preflight 必须经此 gate。

## 7. Generator / artifact consistency

- `python tools/build_qmt_deployments.py --check`: **PASS (exit 0)**，含永久 pytest gate
  `test_invariant_9_deployment_generator_is_in_sync`（子进程实跑 --check）。
- generated Guojin bridge build: `p6-guojin-live-canary-7`
- mutation whitelist: `("00700.HGT",)`
- submit/cancel fuse: 1/1（artifact 头部常量 + 模板静态 bind gate + schema const 三处一致）
- generic/galaxy/guojin_sim artifact：generator 输出与已提交文件一致（sim 零 diff）。

## 8. Static side-effect audit

- `python tools/audit_side_effect_calls.py`: **PASS (exit 0)**
- generic: 0 mutation calls
- galaxy: 0 mutation calls
- guojin: exactly 1 `passorder` + 1 `cancel` inside `_execute_order_command()`
- guojin_sim: exactly 1 `passorder` + 1 `cancel` inside `_execute_order_command()`

AST 级 `test_invariant_7_generic_and_galaxy_have_zero_mutation_surface` 额外扫描
passorder/cancel/order_lots/algo_passorder/smart_algo_passorder/cancel_task/pause_task/resume_task。

## 9. Verification results

```text
python tools/verify_workflow_contract.py: PASS (active P6-T001-I01, AGENT_READY, owner=agent)
pytest -q: 416 passed in 60.49s (exit 0)   # 基线 371 + 本次净增 45
python tools/audit_side_effect_calls.py: PASS
python tools/build_qmt_deployments.py --check: PASS
python tools/verify_bridge_protocol_exhaustive.py: PASS (4608 event transitions + spool idempotency/conflict/expiry)
python tools/verify_bridge_schema_contract.py: PASS
python tools/verify_broker_evidence_contract.py: PASS (7200 cases)
python tools/verify_fsm_exhaustive.py: PASS (196 pairs; 25 applied; reachable 14/14)
TLC permanent models: NOT RUN LOCALLY —本机无 Java 运行时（java 不在 PATH）；CI (Temurin 17, tla2tools 1.7.4) 覆盖全部 10 个模型。formal/ 下模型不含 build/symbol/fuse 授权常量（grep 511880|204001|canary|GC001 无命中），本任务无需改模型/invariant。
```

测试解释器：`D:\gitee\miniQMT\.venv\Scripts\python.exe`（Python 3.12.10，pytest 9.1.1）。
注：在本会话的 DSH Windows 沙箱内运行 pytest 需要临时 0o700-ACL shim
（仅影响一次性临时目录权限，不改变测试语义）；普通终端直接 `pytest -q` 即可。
shim 位于未跟踪的 `.runtime/`，不提交。

## 10. Safety declaration

```text
production passorder executed = NO
production cancel executed = NO
production command published to live QMT spool = NO
general live trading enabled = NO
```

所有 broker 相关验证均为离线单元/契约测试（passorder/cancel 被 monkeypatch 捕获或静态扫描）。

## 11. Deviations / unresolved items

1. **`schemas/bridge/v1/instance.schema.json`** 不在任务 Allowed Files 列表中，但其
   LIVE_CANARY 条件 const 把 fuse 钉死为 2，不收窄为 1 则 schema/实例契约与 artifact
   冲突（`test_instance_schema_accepts_current_execution_modes` 直接失败）。改动仅 2 行常量，
   未动协议结构。
2. 在任务“至少更新”清单外，另更新三份规范性文档（BRIDGE_API v1、Broker Evidence
   Contract v1、P4 scope）中“两个 LIVE_CANARY 案例”的当前授权描述，以满足 exit
   criteria 9“文档与代码无授权漂移”。P6 Gate 保留 build-1..6 历史证据原文，仅在顶部/
   授权面/执行指令处改为 build-7 当前语义。
3. 生成的 `_live_canary_tick_price`（旧的“曾观察到 tick 即可”助手）保留在 artifact 中，
   当前无 submit 路径调用；未来 511880 Gate 必须使用新的
   `_live_canary_fresh_tick_price`，两者语义差异已在 P6 Gate 文档中写明。
4. TLC 未在本机执行（无 Java），其余全部必跑验证 PASS；无未解决项。

## 12. Handoff to Architect

完成实现并填写本报告后，不手工改 control state。执行：

```bash
python tools/agent_workflow_handoff.py --implementation-commit <FULL_SHA>
python tools/verify_workflow_contract.py
```

然后把 **代码 + 本 report + `WORKFLOW_STATE.yaml`** 一起提交。

工具会自动：

- 将 report frontmatter 改为 `REVIEW_READY`；
- 将 control state 改为 `REVIEW_READY`；
- owner 交还 `architect`；
- 清空 `authorized_next`；
- 递增 `handoff_seq` 并生成新的 handoff ID。

不得修改 Architect review 文件，也不得自行创建下一 task。
