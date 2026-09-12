import pytest

from bigqmt_autotrader.domain import ClientOrderIdRegistry, DuplicateClientOrderId


def test_client_order_id_is_unique_within_account():
    registry = ClientOrderIdRegistry()
    registry.register("account-A", "cid-1")
    with pytest.raises(DuplicateClientOrderId):
        registry.register("account-A", "cid-1")


def test_same_client_order_id_may_exist_in_different_accounts():
    registry = ClientOrderIdRegistry()
    registry.register("account-A", "cid-1")
    registry.register("account-B", "cid-1")
    assert registry.contains("account-B", "cid-1")
