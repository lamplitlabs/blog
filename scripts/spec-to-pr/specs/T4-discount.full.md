# T4: Percentage discounts

Add `apply_discount(invoice: Invoice, percent) -> Invoice` in `invoicing/discounts.py`.

Rules:
- Return a *new* `Invoice` (same `id`, `customer`, `issued`); the input invoice and
  its lines must not change.
- Each line keeps sku, description, qty and tax_rate; its `unit_price` becomes
  `to_money(unit_price * (100 - percent) / 100)`. Tax then follows from the
  discounted net through the existing `LineItem.tax()`.
- `percent` is an `int` or `Decimal` in `[0, 100]`. Anything outside that range,
  and any `float` (binary floats do not belong in money code), raises `InvoicingError`.
- Example: lines 2 x 10.00 and 1 x 5.55, tax 20%, 10% off -> unit prices 9.00 and
  5.00, subtotal 23.00, tax 4.60, total 27.60.

Scope: `invoicing/discounts.py` and new tests under `tests/`.
