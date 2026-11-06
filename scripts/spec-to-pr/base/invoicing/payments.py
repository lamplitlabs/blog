from decimal import Decimal
from typing import Optional


class TransientError(Exception):
    """Gateway timeout, 5xx or rate limit. Safe to retry with the same idempotency key."""

    def __init__(self, message: str = "transient", retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class CardDeclined(Exception):
    """The card was declined. Never retry."""


class PaymentClient:
    """Interface of the payment gateway client."""

    def charge(self, invoice_id: str, amount: Decimal, idempotency_key: str) -> str:
        """Charge amount; returns the gateway's charge id."""
        raise NotImplementedError


def charge(client: PaymentClient, invoice_id: str, amount: Decimal, idempotency_key: str) -> str:
    return client.charge(invoice_id, amount, idempotency_key)
