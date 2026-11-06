# T2: Retry payment charges

Add `charge_with_retry(client, invoice_id, amount, idempotency_key, max_attempts=3, sleep=time.sleep) -> str`
in `invoicing/payments.py`.

Rules:
- Retry only on `TransientError`. `CardDeclined` (and any other exception)
  propagates immediately after the first call - never retry a decline.
- Every attempt uses the *same* `idempotency_key` (the gateway de-duplicates on it;
  a new key per attempt can charge the customer twice).
- At most `max_attempts` calls to `client.charge` in total.
- Wait between attempts with `sleep(seconds)`: 0.5 s before the 2nd attempt,
  1.0 s before the 3rd, doubling after that. If the `TransientError` has
  `retry_after`, wait that many seconds instead, capped at 30.
- Never sleep after the last attempt.
- When every attempt fails, re-raise the last `TransientError`.
- `max_attempts < 1` raises `InvoicingError`.

Scope: `invoicing/payments.py` and new tests under `tests/`. Tests must pass a fake
`sleep`; the suite must not actually sleep.
