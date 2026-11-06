import re
from datetime import datetime, timezone

from .errors import InvoicingError
from .money import fmt


def log_line(event: str, **fields) -> str:
    """Format one structured log line: `<ts> <event> k=v k=v`."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    parts = [ts, event] + [f"{k}={v}" for k, v in sorted(fields.items())]
    return " ".join(parts)


def log_charge(invoice_id, amount, card_number, email) -> str:
    digits = re.sub(r"[\s-]", "", card_number)
    if len(digits) < 12 or not digits.isdigit():
        raise InvoicingError("card number too short")
    domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    return log_line("charge", invoice=invoice_id, amount=fmt(amount),
                    card="****" + digits[-4:], email_domain=domain)
