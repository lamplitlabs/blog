# T5: Log card charges

Support needs to trace card charges in the logs.

Add `log_charge(invoice_id, amount, card_number, email) -> str` in `invoicing/logs.py`
that returns the log line.
