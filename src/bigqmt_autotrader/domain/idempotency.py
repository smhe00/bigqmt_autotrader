from __future__ import annotations


class DuplicateClientOrderId(ValueError):
    pass


class ClientOrderIdRegistry:
    """P0 in-memory executable contract for account-scoped uniqueness.

    P1 MUST replace this process-local registry as the authority with a SQLite
    UNIQUE(account_fingerprint, client_order_id) constraint. The API is kept
    deliberately small so tests can freeze the intended semantics now.
    """

    def __init__(self) -> None:
        self._keys: set[tuple[str, str]] = set()

    def register(self, account_fingerprint: str, client_order_id: str) -> None:
        key = (account_fingerprint, client_order_id)
        if key in self._keys:
            raise DuplicateClientOrderId(
                f"client_order_id already registered for account: {client_order_id}"
            )
        self._keys.add(key)

    def contains(self, account_fingerprint: str, client_order_id: str) -> bool:
        return (account_fingerprint, client_order_id) in self._keys
