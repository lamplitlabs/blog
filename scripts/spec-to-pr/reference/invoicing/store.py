from typing import Dict, List, Optional

from .errors import InvoicingError, NotFound
from .models import Invoice


class InvoiceStore:
    """In-memory invoice store."""

    def __init__(self):
        self._items: Dict[str, Invoice] = {}

    def add(self, invoice: Invoice) -> None:
        if invoice.id in self._items:
            raise InvoicingError(f"duplicate invoice id {invoice.id}")
        self._items[invoice.id] = invoice

    def get(self, invoice_id: str) -> Invoice:
        try:
            return self._items[invoice_id]
        except KeyError:
            raise NotFound(invoice_id) from None

    def all(self) -> List[Invoice]:
        return list(self._items.values())

    def list(self, customer: Optional[str] = None, page: int = 1, page_size: int = 20) -> List[Invoice]:
        if page < 1:
            raise InvoicingError("page must be >= 1")
        if not 1 <= page_size <= 100:
            raise InvoicingError("page_size must be within 1..100")
        items = self._items.values()
        if customer is not None:
            want = customer.casefold()
            items = [i for i in items if i.customer.casefold() == want]
        ordered = sorted(sorted(items, key=lambda i: i.id), key=lambda i: i.issued, reverse=True)
        start = (page - 1) * page_size
        return ordered[start:start + page_size]
