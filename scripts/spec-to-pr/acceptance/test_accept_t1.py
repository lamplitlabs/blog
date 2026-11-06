"""Hidden acceptance tests for T1, written from the full spec's rules and examples."""
import unittest
from datetime import date
from decimal import Decimal

from invoicing.errors import InvoicingError
from invoicing.models import Invoice, LineItem


def inv(total="1000.00"):
    return Invoice("INV-1", "Acme", date(2026, 1, 1), [LineItem("A", "x", 1, Decimal(total))])


class T1Accept(unittest.TestCase):
    def fee(self, today, total="1000.00"):
        from invoicing.fees import late_fee
        return late_fee(inv(total), today)

    def test_on_due_date_zero(self):
        self.assertEqual(self.fee(date(2026, 1, 31)), Decimal("0.00"))

    def test_first_day_overdue_one_period(self):
        self.assertEqual(self.fee(date(2026, 2, 1)), Decimal("15.00"))

    def test_thirty_days_overdue_one_period(self):
        self.assertEqual(self.fee(date(2026, 3, 2)), Decimal("15.00"))

    def test_thirty_one_days_overdue_two_periods(self):
        self.assertEqual(self.fee(date(2026, 3, 3)), Decimal("30.00"))

    def test_cap_ten_percent(self):
        self.assertEqual(self.fee(date(2027, 1, 1)), Decimal("100.00"))

    def test_rounds_half_up_once(self):
        # 1.5% of 33.30 = 0.4995 -> 0.50
        self.assertEqual(self.fee(date(2026, 2, 1), "33.30"), Decimal("0.50"))

    def test_empty_invoice_zero(self):
        from invoicing.fees import late_fee
        self.assertEqual(late_fee(Invoice("E", "Acme", date(2026, 1, 1)), date(2026, 6, 1)), Decimal("0.00"))

    def test_today_before_issue_raises(self):
        with self.assertRaises(InvoicingError):
            self.fee(date(2025, 12, 31))
