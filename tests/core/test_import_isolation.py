import subprocess
import sys


def test_clean_core_import_does_not_load_runtime_packages():
    code = r"""
import sys
import bigqmt_autotrader.core

forbidden = {
    "bigqmt_autotrader.drivers",
    "bigqmt_autotrader.risk",
    "bigqmt_autotrader.market_data",
    "bigqmt_autotrader.operations",
    "bigqmt_autotrader.service",
    "bigqmt_autotrader.strategy_api",
    "bigqmt_autotrader.runtime",
    "bigqmt_autotrader.web",
}
loaded = sorted(
    name for name in sys.modules
    if any(name == root or name.startswith(root + ".") for root in forbidden)
)
if loaded:
    raise SystemExit("runtime modules loaded by Core import: " + ", ".join(loaded))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
