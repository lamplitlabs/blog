from dataclasses import replace
from decimal import Decimal

from .errors import InvoicingError
from .models import Invoice
from .money import to_money


def apply_discount(invoice: Invoice, percent) -> Invoice:
    if isinstance(percent, float) or isinstance(percent, bool) or not isinstance(percent, (int, Decimal)):
        raise InvoicingError("percent must be int or Decimal")
    if not 0 <= percent <= 100:
        raise InvoicingError("percent must be within 0..100")
    factor = (Decimal(100) - Decimal(percent)) / Decimal(100)
    lines = [replace(l, unit_price=to_money(l.unit_price * factor)) for l in invoice.lines]
    return Invoice(invoice.id, invoice.customer, invoice.issued, lines)
