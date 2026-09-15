# P4 multi-terminal spool isolation

Date: 2026-09-16

## Decision

Every running Big QMT terminal has an independent spool namespace. The
deployment names are operator-owned terminal instance identifiers, not
broker-detection logic:

```text
D:\BigQMTData\spool\
  galaxy\
    inbox\
    processed\
    quarantine\
    commands\
  guojin\
    inbox\
    processed\
    quarantine\
    commands\
```

Account capability discovery remains broker-neutral. V05 still probes standard
QMT account types from runtime evidence and never selects a behavior profile by
broker name.

## QMT process configuration

Set both variables in the parent process before starting each QMT terminal:

```powershell
$env:BIGQMT_SPOOL_BASE = 'D:\BigQMTData\spool'
$env:BIGQMT_INSTANCE_ID = 'galaxy'
# Start the Galaxy QMT executable from this PowerShell process.
```

Use `guojin` in a separate parent process for the Guojin terminal. Instance IDs
must be lowercase ASCII letters, digits, `_`, or `-`, with a maximum length of
32 characters.

`BIGQMT_SPOOL_DIR` remains an exact-path override for tests and controlled
deployments. For example, setting it to
`D:\BigQMTData\spool\galaxy` selects that directory directly.

The former common `D:\BigQMTData\spool` leaf layout is retained only as
historical calibration evidence. New terminal sessions must write to an
instance-specific child directory; historical files are not migrated or mixed
into either new stream.

## Host and probe binding

Run one Host process per terminal namespace. Never point a single Host process
at the common parent directory.

```powershell
python -m bigqmt_autotrader.qmt.host `
  --spool-dir D:\BigQMTData\spool\galaxy `
  --expected-account-fingerprint <galaxy-stock-fingerprint>
```

All shadow and calibration probes must use the same terminal-specific leaf:

```powershell
python -m bigqmt_autotrader.qmt.shadow_probe `
  --spool-dir D:\BigQMTData\spool\galaxy `
  --account-fingerprint <galaxy-stock-fingerprint> `
  snapshot
```

## Safety invariants

- an instance directory has exactly one QMT producer;
- its Host consumer is pinned to that instance's selected account fingerprint;
- commands are published only to that instance's `commands/inbox`;
- archives and quarantine remain inside the instance leaf;
- account discovery does not grant submit or cancel authority;
- `TRADING_ENABLED=False`, `live_submit=false`, and `live_cancel=false` remain
  unchanged.
