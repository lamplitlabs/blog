# T3: CSV export for finance

Add `export_csv(invoices: Iterable[Invoice]) -> str` in `invoicing/export.py`.

Rules:
- Header row exactly `id,customer,issued,subtotal,tax,total`.
- One row per invoice, sorted by `issued` ascending, then `id` ascending.
- `issued` as ISO date (`2026-01-15`); money columns via `invoicing.money.fmt`
  (two decimals, e.g. `25.55`).
- Use the `csv` module for quoting (a customer `Smith, J` must come out as `"Smith, J"`).
- Lines end with `\n` (not `\r\n`), including the last row.
- Spreadsheet formula injection: a customer value starting with `=`, `+`, `-` or `@`
  is written with a leading `'` (e.g. `'=HYPERLINK(...)`).
- No invoices -> just the header line.

Scope: `invoicing/export.py` and new tests under `tests/`.
