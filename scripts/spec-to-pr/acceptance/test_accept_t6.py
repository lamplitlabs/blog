"""Hidden acceptance tests for T6."""
import unittest
from datetime import date, timedelta

from invoicing.errors import InvoicingError
from invoicing.models import Invoice
from invoicing.store import InvoiceStore


def store(n=45):
    s = InvoiceStore()
    base = date(2026, 1, 1)
    for i in range(n):
        cust = "Acme" if i % 3 else "Globex"
        s.add(Invoice(f"INV-{i:03d}", cust, base + timedelta(days=i // 2)))
    return s


class T6Accept(unittest.TestCase):
    def test_default_page_size_20(self):
        self.assertEqual(len(store().list()), 20)

    def test_newest_first_then_id(self):
        page = store().list(page_size=4)
        self.assertEqual([i.id for i in page], ["INV-044", "INV-042", "INV-043", "INV-040"])

    def test_pages_cover_all_without_overlap(self):
        s = store()
        ids = [i.id for p in (1, 2, 3) for i in s.list(page=p)]
        self.assertEqual(len(ids), 45)
        self.assertEqual(len(set(ids)), 45)

    def test_page_past_end_empty(self):
        self.assertEqual(store().list(page=4), [])

    def test_customer_filter_case_insensitive(self):
        page = store().list(customer="globex", page_size=100)
        self.assertEqual(len(page), 15)
        self.assertTrue(all(i.customer == "Globex" for i in page))

    def test_invalid_args_raise(self):
        s = store()
        for kw in ({"page": 0}, {"page_size": 0}, {"page_size": 101}):
            with self.assertRaises(InvoicingError):
                s.list(**kw)

    def test_all_unchanged(self):
        self.assertEqual(len(store().all()), 45)
