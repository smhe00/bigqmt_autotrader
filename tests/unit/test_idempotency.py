import pytest

from bigqmt_autotrader.domain import ClientOrderIdRegistry, DuplicateClientOrderId


def test_client_order_id_is_unique_within_account():
    registry = ClientOrderIdRegistry()
    registry.register("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "cid-1")
    with pytest.raises(DuplicateClientOrderId):
        registry.register("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "cid-1")


def test_same_client_order_id_may_exist_in_different_accounts():
    registry = ClientOrderIdRegistry()
    registry.register("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "cid-1")
    registry.register("sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "cid-1")
    assert registry.contains("sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "cid-1")
