from datetime import date, timedelta
from decimal import Decimal

from .errors import InvoicingError
from .models import Invoice
from .money import to_money

RATE = Decimal("0.015")
CAP = Decimal("0.10")
TERMS = timedelta(days=30)


def late_fee(invoice: Invoice, today: date) -> Decimal:
    if today < invoice.issued:
        raise InvoicingError("today is before the issue date")
    days = (today - (invoice.issued + TERMS)).days
    if days <= 0 or not invoice.lines:
        return Decimal("0.00")
    periods = (days + 29) // 30
    total = invoice.total()
    return to_money(min(total * RATE * periods, total * CAP))
