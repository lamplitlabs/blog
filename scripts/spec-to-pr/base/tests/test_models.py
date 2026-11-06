import unittest
from datetime import date
from decimal import Decimal

from invoicing.models import Invoice, LineItem


def make_invoice():
    return Invoice("INV-1", "Acme", date(2026, 1, 15), [
        LineItem("A", "Widget", 2, Decimal("10.00"), Decimal("0.20")),
        LineItem("B", "Gadget", 1, Decimal("5.55"), Decimal("0.20")),
    ])


class InvoiceTest(unittest.TestCase):
    def test_subtotal(self):
        self.assertEqual(make_invoice().subtotal(), Decimal("25.55"))

    def test_tax(self):
        self.assertEqual(make_invoice().tax(), Decimal("5.11"))

    def test_total(self):
        self.assertEqual(make_invoice().total(), Decimal("30.66"))
