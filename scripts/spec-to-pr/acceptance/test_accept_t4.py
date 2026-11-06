"""Hidden acceptance tests for T4."""
import unittest
from datetime import date
from decimal import Decimal

from invoicing.errors import InvoicingError
from invoicing.models import Invoice, LineItem


def inv():
    return Invoice("INV-1", "Acme", date(2026, 1, 15), [
        LineItem("A", "Widget", 2, Decimal("10.00"), Decimal("0.20")),
        LineItem("B", "Gadget", 1, Decimal("5.55"), Decimal("0.20")),
    ])


class T4Accept(unittest.TestCase):
    def apply(self, invoice, pct):
        from invoicing.discounts import apply_discount
        return apply_discount(invoice, pct)

    def test_example_totals(self):
        out = self.apply(inv(), 10)
        self.assertEqual((out.subtotal(), out.tax(), out.total()),
                         (Decimal("23.00"), Decimal("4.60"), Decimal("27.60")))

    def test_unit_prices_rounded_per_line(self):
        out = self.apply(inv(), 10)
        self.assertEqual([l.unit_price for l in out.lines], [Decimal("9.00"), Decimal("5.00")])

    def test_input_unchanged(self):
        src = inv()
        self.apply(src, 50)
        self.assertEqual(src.total(), Decimal("30.66"))

    def test_returns_new_invoice_same_identity(self):
        src = inv()
        out = self.apply(src, 10)
        self.assertIsNot(out, src)
        self.assertEqual((out.id, out.customer, out.issued), (src.id, src.customer, src.issued))

    def test_zero_and_hundred(self):
        self.assertEqual(self.apply(inv(), 0).total(), Decimal("30.66"))
        self.assertEqual(self.apply(inv(), 100).total(), Decimal("0.00"))

    def test_decimal_percent(self):
        self.assertEqual(self.apply(inv(), Decimal("12.5")).subtotal(), Decimal("22.36"))

    def test_out_of_range_raises(self):
        for bad in (-1, 101):
            with self.assertRaises(InvoicingError):
                self.apply(inv(), bad)

    def test_float_rejected(self):
        with self.assertRaises(InvoicingError):
            self.apply(inv(), 10.0)
