from typing import Dict, List

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
