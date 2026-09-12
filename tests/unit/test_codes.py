from bigqmt_autotrader.domain import RiskReasonCode, SystemErrorCode


def test_stable_reason_and_error_codes():
    assert RiskReasonCode.UNKNOWN_ORDER.value == "RISK_UNKNOWN_ORDER"
    assert RiskReasonCode.DUPLICATE_CLIENT_ORDER_ID.value == "RISK_DUPLICATE_CLIENT_ORDER_ID"
    assert SystemErrorCode.TRADING_DISABLED.value == "E_TRADING_DISABLED"
    assert SystemErrorCode.INVALID_TRANSITION.value == "E_INVALID_TRANSITION"
