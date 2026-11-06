# T1: Late fee for overdue invoices

Add `late_fee(invoice: Invoice, today: date) -> Decimal` in `invoicing/fees.py`.

Rules:
- The due date is `invoice.issued + 30 days`.
- On or before the due date the fee is `Decimal("0.00")`.
- After the due date the fee is 1.5% of `invoice.total()` per *started* 30-day
  period overdue: 1-30 days overdue is one period, 31-60 days is two, and so on.
- The fee is capped at 10% of `invoice.total()`.
- Round with `invoicing.money.to_money` (half-up to cents) once, at the end.
- An invoice with no lines has fee `0.00`.
- `today` earlier than `invoice.issued` raises `InvoicingError`.

Acceptance examples (total 1000.00, issued 2026-01-01, due 2026-01-31):
- today 2026-01-31 -> 0.00
- today 2026-02-01 -> 15.00
- today 2026-03-02 (30 days overdue) -> 15.00
- today 2026-03-03 (31 days overdue) -> 30.00
- today 2027-01-01 -> 100.00 (cap)

Scope: `invoicing/fees.py` and new tests under `tests/`. Do not change other modules.
