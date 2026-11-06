import csv
import io
from typing import Iterable

from .models import Invoice
from .money import fmt

HEADER = ["id", "customer", "issued", "subtotal", "tax", "total"]


def _safe(value: str) -> str:
    return "'" + value if value[:1] in ("=", "+", "-", "@") else value


def export_csv(invoices: Iterable[Invoice]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEADER)
    for inv in sorted(invoices, key=lambda i: (i.issued, i.id)):
        w.writerow([inv.id, _safe(inv.customer), inv.issued.isoformat(),
                    fmt(inv.subtotal()), fmt(inv.tax()), fmt(inv.total())])
    return buf.getvalue()
