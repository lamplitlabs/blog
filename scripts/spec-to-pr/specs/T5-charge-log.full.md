# T5: Log card charges

Add `log_charge(invoice_id, amount, card_number, email) -> str` in `invoicing/logs.py`;
it returns the line built with the existing `log_line`.

Rules:
- Event name `charge`; fields `invoice`, `amount` (via `invoicing.money.fmt`),
  `card` and `email_domain`.
- Never log the full card number or the email address (PCI DSS / GDPR).
  `card` is `****` plus the last 4 digits, e.g. `card=****4242`.
  `email_domain` is the part after `@`, e.g. `email_domain=example.com`.
- `card_number` may contain spaces or dashes; strip them first.
- Fewer than 12 digits after stripping raises `InvoicingError`.

Scope: `invoicing/logs.py` and new tests under `tests/`.
