"""Hidden acceptance tests for T3."""
import unittest
from datetime import date
from decimal import Decimal

from invoicing.models import Invoice, LineItem


def inv(i, cust, d, price="10.00"):
    return Invoice(i, cust, d, [LineItem("A", "x", 1, Decimal(price), Decimal("0.20"))])


class T3Accept(unittest.TestCase):
    def export(self, invoices):
        from invoicing.export import export_csv
        return export_csv(invoices)

    def test_header_only_when_empty(self):
        self.assertEqual(self.export([]), "id,customer,issued,subtotal,tax,total\n")

    def test_row_format(self):
        out = self.export([inv("INV-1", "Acme", date(2026, 1, 15), "25.55")])
        self.assertEqual(out.splitlines()[1], "INV-1,Acme,2026-01-15,25.55,5.11,30.66")

    def test_lf_line_endings(self):
        out = self.export([inv("INV-1", "Acme", date(2026, 1, 15))])
        self.assertNotIn("\r", out)
        self.assertTrue(out.endswith("\n"))

    def test_sorted_by_issued_then_id(self):
        out = self.export([
            inv("B", "Acme", date(2026, 2, 1)),
            inv("C", "Acme", date(2026, 1, 1)),
            inv("A", "Acme", date(2026, 2, 1)),
        ])
        self.assertEqual([l.split(",")[0] for l in out.splitlines()[1:]], ["C", "A", "B"])

    def test_quotes_commas(self):
        out = self.export([inv("INV-1", "Smith, J", date(2026, 1, 15))])
        self.assertIn('"Smith, J"', out)

    def test_formula_injection_neutralised(self):
        out = self.export([inv("INV-1", "=HYPERLINK(\"http://x\")", date(2026, 1, 15)),
                           inv("INV-2", "@SUM(A1)", date(2026, 1, 16))])
        rows = out.splitlines()[1:]
        self.assertFalse(rows[0].split(",", 2)[1].lstrip('"').startswith("="))
        self.assertIn("'=HYPERLINK", rows[0])
        self.assertIn("'@SUM", rows[1])
