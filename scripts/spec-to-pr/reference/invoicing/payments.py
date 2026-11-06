import time
from decimal import Decimal
from typing import Optional

from .errors import InvoicingError


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


def charge_with_retry(client, invoice_id, amount, idempotency_key, max_attempts=3, sleep=time.sleep) -> str:
    if max_attempts < 1:
        raise InvoicingError("max_attempts must be >= 1")
    delay = 0.5
    for attempt in range(1, max_attempts + 1):
        try:
            return client.charge(invoice_id, amount, idempotency_key)
        except TransientError as e:
            if attempt == max_attempts:
                raise
            wait = min(e.retry_after, 30) if e.retry_after is not None else delay
            sleep(wait)
            delay *= 2
