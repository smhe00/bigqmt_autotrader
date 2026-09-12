"""Test-only compatibility for P1 mechanics tests.

P1 tests intentionally isolate persistence/recovery from the P2 risk engine and
historically injected a precomputed RiskDecision into OfflineOms.submit_intent.
Production no longer exposes that bypass. For those legacy tests only, preserve
the old two-argument shape by routing it to the private P1 mechanics hook.

Any call using the P2 public shape (intent, RiskSnapshot, RiskPolicy) is delegated
unchanged to the real production method, so P2 integration tests exercise the
actual public boundary.
"""

import pytest

from bigqmt_autotrader.domain import RiskDecision
from bigqmt_autotrader.oms import OfflineOms


@pytest.fixture(autouse=True)
def _p1_decision_injection_compat(monkeypatch):
    production_submit = OfflineOms.submit_intent

    def submit_intent(self, intent, risk_input, risk_policy=None):
        if isinstance(risk_input, RiskDecision) and risk_policy is None:
            return self._submit_decided_intent(intent, risk_input)
        return production_submit(self, intent, risk_input, risk_policy)

    monkeypatch.setattr(OfflineOms, "submit_intent", submit_intent)
