import unittest
from datetime import date

from invoicing.errors import InvoicingError, NotFound
from invoicing.models import Invoice
from invoicing.store import InvoiceStore


class StoreTest(unittest.TestCase):
    def test_add_get(self):
        s = InvoiceStore()
        s.add(Invoice("INV-1", "Acme", date(2026, 1, 1)))
        self.assertEqual(s.get("INV-1").customer, "Acme")

    def test_duplicate(self):
        s = InvoiceStore()
        s.add(Invoice("INV-1", "Acme", date(2026, 1, 1)))
        with self.assertRaises(InvoicingError):
            s.add(Invoice("INV-1", "Acme", date(2026, 1, 1)))

    def test_missing(self):
        with self.assertRaises(NotFound):
            InvoiceStore().get("nope")
