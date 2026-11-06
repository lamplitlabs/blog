import unittest
from decimal import Decimal

from invoicing.payments import PaymentClient, charge


class FakeClient(PaymentClient):
    def __init__(self):
        self.calls = []

    def charge(self, invoice_id, amount, idempotency_key):
        self.calls.append((invoice_id, amount, idempotency_key))
        return "ch_1"


class PaymentsTest(unittest.TestCase):
    def test_charge_passes_through(self):
        c = FakeClient()
        self.assertEqual(charge(c, "INV-1", Decimal("9.99"), "k1"), "ch_1")
        self.assertEqual(c.calls, [("INV-1", Decimal("9.99"), "k1")])
