# bigqmt_autotrader 中文总览

更新：2026-09-25

## 1. 项目目标

本项目不是“封装一个 QMT 下单函数”，而是一个可恢复、可审计、默认 fail-closed 的个人
自动交易执行平台。Big QMT 是券商 Gateway；Host 保存 durable identity、OMS、风险、恢复和
审计状态。QMT 内置 Python 3.6 只运行薄 Bridge，Host 使用 Python 3.12。

## 2. 当前状态

- `core-v1.0.0` 已冻结，机器契约在 `contracts/core/v1/`。
- P0–P3 PASS；P4 SHADOW 部署 PASS；P5 国金模拟受限校准 PASS。
- P6 T001–T015 的最终迭代覆盖 Host/OMS 集成、单 writer、crash window、submit/cancel、
  fill、重启、HGT/SGT、session rollover、leader heartbeat、Windows fsync 与 archive
  discovery，均已有最终 PASS 审查。
- 通用生产实盘仍为 **NO**。Galaxy/generic 没有 broker mutation surface。
- `guojin_sim` build `p5-simulation-calibration-8` 只能做 fingerprint-pinned、
  `simulation_only=true` 的模拟校准。
- `guojin` build `p6-guojin-live-canary-7` 只保留固定的单案例 LIVE_CANARY，
  不是通用 LIVE。

精确部署矩阵和当前 checkpoint 见 [PROJECT_STATUS.md](PROJECT_STATUS.md)。

## 3. 两层架构

```text
Production Runtime (可选扩展)
Risk / Market Data / Operations / Strategy / Service
                         |
                         v
Execution Core v1 (冻结)
OrderIntent / OMS / identity / evidence / recovery / fencing
                         |
                         v
QMT adapter / file spool / Broker
```

Core 的冻结边界是 `core/`、`domain/`、`ports/`、指定 OMS 文件和
`oms/core_migrations/0001_initial.sql`。QMT、driver、Risk 和 Runtime 都是 Extension。
Core 不能反向 import Extension；CI 永久检查此规则。

## 4. OMS 与 BrokerEvidence

OMS 负责 `client_order_id`、persist-before-side-effect、submit/cancel reservation、订单
状态机、UNKNOWN/reconciliation、重启恢复、duplicate/conflict、single-writer 与 fencing。

控制面成功不等于券商事实：

```text
SHADOW_ACCEPTED / command_result / submit return / cancel return
    != broker ACK
```

ORDER/DEAL/callback/query 原始数据必须先经过已校准的 broker-specific mapper，输出
`BrokerEvidenceV1`，才能推进 OMS。未知 raw status、身份或数量冲突进入 quarantine 或
`MANUAL_REVIEW`，不能猜测或盲重试。

## 5. Runtime 与 Risk

Risk 属于 Production Runtime，不属于冻结 Core。Runtime 在 broker side effect 前做
fail-closed 风险判断，然后把已授权 `OrderIntent` 交给 Core。Core API 不依赖行情、策略、
健康检查或 Risk object；配置也不能自动取得生产权限。

## 6. Host 与 QMT Bridge

Bridge API v1 包含实例发现、Command Protocol 0.1、Event Protocol 0.2、File Transport 1、
JSON Schema 和形式验证。每个 QMT 实例写入独立的
`D:\BigQMTData\spool\<instance_id>`，由 `instance.json` 描述 build、mode、session、账户
类型和 fingerprint。Host 可以发现候选，但必须逐项校验；目录名或 broker 名不产生授权。

QMT Bridge 只做 query/callback、snapshot、command consumption、broker token、受 Gate 限制
的 mutation 和 durable spool。它不承载策略、Risk、OMS、ML 或通用远程调用。

## 7. 已验证的券商能力

国金 Big QMT 已验证 read-only query/callback、定时 reconcile、durable spool、Host
restart/replay、模拟 submit/cancel/fill、ORDER/DEAL token、HGT/SGT route、重复/冲突/
过期/错误账户/陈旧 session fail-close。国金模拟 mapper profile 为
`qmt-guojin-sim-20260917-v1`。

银河 Big QMT 已验证 STOCK/HUGANGTONG/SHENGANGTONG 动态发现、linked-account callback
抑制和实例隔离；尚无已授权 mapper 或 mutation surface。

## 8. 行情边界

`market_data/` 已有 Host 侧模型、service 与 QMT adapter 测试，但 Execution Bridge 不会变成
XtData 克隆。若部署独立 QMT 行情策略，必须使用独立权限和健康模型，不能继承 execution
mutation authority。历史数据继续由专用数据层承担。

## 9. 文档与历史

[文档索引](README.md) 将“当前权威说明”和“历史 Gate 证据”分开。日期化报告里的旧 build、
候选状态和“下一阶段”是当时事实，为审计保留，不应据此操作当前系统。

换机按[开发环境迁移手册](DEVELOPMENT_ENVIRONMENT_MIGRATION_ZH.md)执行；workflow 的唯一
bootstrap 是 `workflow/control/WORKFLOW_STATE.yaml`。

## 10. 后续方向

后续工作默认进入 Extension：新券商 mapper、行情源、Risk/Strategy/Operations/Web。
任何扩大 `guojin`、`galaxy` 或 generic mutation 权限的变更，都必须创建新的明确 Gate，
不能借由换机、配置、实例发现或 Core patch 获得。
