# 开发环境迁移手册

更新：2026-09-25

## 1. 迁移目标

迁移后必须保持三件事不变：Git `main` 是代码权威来源，Execution Core v1 契约不漂移，
任何 QMT mutation 权限不因换机自动扩大。当前冻结版本为 `core-v1.0.0`。

## 2. 环境基线

- Host：Windows，CPython 3.12，Git，Java 17（运行 TLC 时需要）。
- QMT Bridge：券商 Big QMT 内置 CPython 3.6；它不是 Host 虚拟环境的一部分。
- Host 与 QMT：使用 `D:\BigQMTData\spool\<instance_id>` 文件 spool；不依赖 miniQMT。
- 测试依赖：由 `pyproject.toml` 的 `.[test]` 安装。

推荐在新仓库内创建独立 `.venv`，不要继续依赖旧项目的虚拟环境：

```powershell
git clone https://github.com/smhe00/bigqmt_autotrader.git
cd bigqmt_autotrader
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
```

## 3. 首次验收

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe tools\verify_workflow_contract.py
.\.venv\Scripts\python.exe tools\verify_core_dependency_boundary.py
.\.venv\Scripts\python.exe tools\verify_core_v1_release.py
.\.venv\Scripts\python.exe tools\verify_fsm_exhaustive.py
.\.venv\Scripts\python.exe tools\verify_bridge_protocol_exhaustive.py
.\.venv\Scripts\python.exe tools\verify_bridge_schema_contract.py
.\.venv\Scripts\python.exe tools\verify_broker_evidence_contract.py
.\.venv\Scripts\python.exe tools\audit_side_effect_calls.py
.\.venv\Scripts\python.exe tools\build_qmt_deployments.py --check
```

TLC 与 CI 一致使用 `tla2tools.jar` v1.7.4，SHA-256 为
`936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`。

Windows 注意事项（P6-T017 起已仓库级修复）：

- `tzdata` 由 `pip install -e ".[test]"` 作为运行依赖自动安装（日历模块需要
  `ZoneInfo('Asia/Shanghai')`，Windows/精简容器没有系统时区库）；
- 换行符由 `.gitattributes` 强制 LF：Windows checkout 不再把 `qmt_side/*.py`
  smudge 成 CRLF，`build_qmt_deployments.py --check` 的字节级比较才成立。
  若 `--check` 仍失败，先查 `git ls-files --eol qmt_side`，工作树侧应为 `w/lf`；
  异常时用 `git -c core.autocrlf=false checkout -- qmt_side` 恢复。

## 4. 哪些内容来自 Git

必须从 Git 获取而不是从旧机器复制：

- `src/`、`tests/`、`formal/`、`schemas/`、`contracts/`；
- `qmt_side/` 当前部署文件；
- `docs/` 与 `workflow/`；
- `.github/workflows/ci.yml`、`pyproject.toml`。

不要复制 `.venv`、`__pycache__`、`.pytest_cache`、测试临时目录或旧的 editable-install
元数据。`.formal-tools/tla2tools.jar` 可以重新下载并校验，不是源代码。

## 5. Runtime 数据迁移

Runtime 数据不进入 Git。迁移前先停止对应 Host writer，再按实例整体备份：

```text
D:\BigQMTData\spool\galaxy
D:\BigQMTData\spool\guojin
D:\BigQMTData\spool\guojin_sim
```

实例目录名就是 `instance_id`。保留 `instance.json`、event/command spool、archive、checkpoint
及需要延续的 OMS SQLite 数据；不得跨实例混拷。数据库、`-wal`、`-shm` 必须在 writer
停止后做一致性备份。不要迁移进程锁、临时 claim、日志缓存或任何无法解释来源的文件。

账户号、密码、原始身份、QMT userdata、日志和数据库都可能包含敏感信息，禁止提交 Git。

## 6. QMT 端恢复顺序

1. 先安装并登录对应券商 Big QMT，人工确认是模拟还是真实账户。
2. 从 Git 选择精确部署文件；不要使用 V03/V04 历史 fixture。
3. 检查文件顶部 `SPOOL_BASE_DIR` 与 `TERMINAL_INSTANCE_ID`。
4. 启动 V5，等待它生成当前 session 的 `instance.json` 和初始 snapshot。
5. Host 无参数启动时只从 spool 子目录发现实例；选择后仍会校验 manifest、账户类型、
   build、mode、session 和 fingerprint。
6. 先完成只读 snapshot/replay 健康检查，再依据新的明确 Gate 决定是否允许 mutation。

当前部署矩阵：

| instance | 文件 | build | 权限 |
| --- | --- | --- | --- |
| `galaxy` | `BIGQMT_EXECUTION_BRIDGE_V05_GALAXY.py` | `p4-shadow-command-spool-5` | SHADOW，禁止 submit/cancel |
| `guojin_sim` | `BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN_SIM.py` | `p5-simulation-calibration-8` | `simulation_only=true` 的受限模拟校准 |
| `guojin` | `BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN.py` | `p6-guojin-live-canary-7` | 仅既有单案例 LIVE_CANARY，不是通用实盘 |

## 7. 切换验收

- `git status --short` 只显示你明确保留的本地文件；
- 本地 `HEAD` 与 `origin/main` 一致；
- 全量测试及永久 Gate 通过；
- `contracts/core/v1/release.json` 仍为 `core-v1.0.0 / FROZEN`；
- QMT 先启动，Host 后启动；Host 选中的 instance/build/session/fingerprint 全部匹配；
- `read_model_healthy=true` 且无未解释 quarantine/backlog；
- 未得到新 Gate 时不发布任何 submit/cancel。

旧机器至少保留到新环境完成一次干净启动、replay 和快照核对后再退役。
