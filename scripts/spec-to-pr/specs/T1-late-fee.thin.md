# T1: Late fee for overdue invoices

Overdue invoices should get a late fee of 1.5% per month.

Add `late_fee(invoice, today) -> Decimal` in `invoicing/fees.py`.
