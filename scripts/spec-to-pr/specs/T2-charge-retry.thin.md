# T2: Retry payment charges

Payments sometimes fail with gateway timeouts.

Add `charge_with_retry(client, invoice_id, amount, idempotency_key, max_attempts=3, sleep=time.sleep) -> str`
in `invoicing/payments.py` that retries.
