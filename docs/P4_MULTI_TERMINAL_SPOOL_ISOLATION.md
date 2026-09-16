# P4 multi-terminal spool discovery and isolation

Date: 2026-09-16

## Decision

Each Big QMT terminal runs a standalone V05 strategy with an embedded instance
identifier. The Host contains no broker names, broker profiles, account-type
assumptions, or instance registry. It knows only the spool base directory:

```text
D:\BigQMTData\spool
```

The supplied standalone deployments create:

```text
D:\BigQMTData\spool\
  galaxy\
    instance.json
    inbox\
    commands\
  guojin\
    instance.json
    inbox\
    commands\
  guojin_sim\
    instance.json
    inbox\
    commands\
```

The names `galaxy`, `guojin`, and `guojin_sim` occur only in the generated QMT
deployment files and their filesystem directories. Adding another terminal
does not require a Host code change.

## First discovery

Start Big QMT and its V05 strategy before starting Host. During initialization,
V05 atomically publishes `instance.json`, then emits `bridge_ready` with the
same terminal instance, session, account fingerprint, account type, build, and
safety capabilities.

With no arguments, Host enumerates only immediate child directories of the
spool base. A directory becomes selectable only when all of these agree:

```text
directory leaf name
  == instance.json.terminal_instance_id
  == bridge_ready.terminal_instance_id
```

Host also pins and verifies the manifest session, account fingerprint, account
type, protocol versions, bridge build, `execution_mode=SHADOW`, and all three
disabled trading flags. It derives the path from the trusted base plus validated
leaf name and never accepts an absolute path from the manifest.

If no valid instance exists, Host waits. When one or more instances validate,
it displays a numbered selection menu:

```powershell
python -m bigqmt_autotrader.qmt.host
```

For repeatable startup, the optional shortcut selects a discovered directory
but performs exactly the same manifest and event validation:

```powershell
python -m bigqmt_autotrader.qmt.host --instance-id galaxy
python -m bigqmt_autotrader.qmt.host --instance-id guojin
python -m bigqmt_autotrader.qmt.host --instance-id guojin_sim
```

## Standalone QMT files

- `qmt_side/BIGQMT_EXECUTION_BRIDGE_V05_GALAXY.py`
- `qmt_side/BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN.py`
- `qmt_side/BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN_SIM.py`

They are complete Python 3.6-compatible strategies with no runtime child-module
or environment-variable dependency. All are generated from the broker-neutral
V05 template. CI fails if any generated file differs from its template plus
embedded instance identifier.

For operator visibility, each standalone file keeps its only two deployment
settings directly below the module header and future import:

```python
SPOOL_BASE_DIR = r"D:\BigQMTData\spool"
TERMINAL_INSTANCE_ID = "guojin_sim"
```

The supplied files are generated and should not otherwise be edited by hand.

## Fail-closed rules

- only lowercase ASCII letters, digits, `_`, and `-` are accepted in an
  instance ID, with a maximum of 32 characters;
- symbolic links and Windows reparse-point directories are rejected;
- malformed, oversized, stale, or mismatched manifests are not selectable;
- a matching `bridge_ready` from the manifest session is mandatory;
- ingestion rejects any later event with another terminal instance ID;
- each Host process consumes one selected instance only;
- commands, quarantine, conflicts, and archives stay inside that instance leaf;
- `TRADING_ENABLED=False`, `live_submit=false`, and `live_cancel=false` remain
  unchanged.

The former common spool layout is retained only as historical calibration
evidence. Its structural directories do not contain a valid instance manifest
and are ignored by discovery.
