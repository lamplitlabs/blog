# T6: Paginate invoice listing

Add `InvoiceStore.list(customer=None, page=1, page_size=20) -> List[Invoice]` in
`invoicing/store.py`.

Rules:
- Order: `issued` descending (newest first), then `id` ascending.
- `customer`, when given, filters by case-insensitive exact match on `Invoice.customer`.
- `page` is 1-based; a page past the end returns `[]`.
- `page < 1`, or `page_size` outside `1..100`, raises `InvoicingError`.
- `all()` keeps its current behaviour.

Scope: `invoicing/store.py` and new tests under `tests/`.
