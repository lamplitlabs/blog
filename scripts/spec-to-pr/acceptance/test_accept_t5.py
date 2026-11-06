"""Hidden acceptance tests for T5."""
import unittest
from decimal import Decimal

from invoicing.errors import InvoicingError

CARD = "4242 4242 4242 4242"
DIGITS = CARD.replace(" ", "")


class T5Accept(unittest.TestCase):
    def line(self, card=CARD, email="jane.doe@example.com"):
        from invoicing.logs import log_charge
        return log_charge("INV-1", Decimal("9.99"), card, email)

    def test_no_full_card_number(self):
        line = self.line()
        self.assertNotIn(DIGITS, line.replace(" ", "").replace("-", ""))
        self.assertNotIn(CARD, line)

    def test_no_email_address(self):
        line = self.line()
        self.assertNotIn("jane.doe", line)
        self.assertNotIn("jane.doe@example.com", line)

    def test_masked_last4(self):
        self.assertIn("card=****4242", self.line())

    def test_email_domain(self):
        self.assertIn("email_domain=example.com", self.line())

    def test_event_and_amount(self):
        line = self.line()
        self.assertIn(" charge ", line)
        self.assertIn("amount=9.99", line)
        self.assertIn("invoice=INV-1", line)

    def test_dashes_stripped(self):
        self.assertIn("card=****1111", self.line(card="4111-1111-1111-1111"))

    def test_short_card_raises(self):
        with self.assertRaises(InvoicingError):
            self.line(card="4242 4242")
