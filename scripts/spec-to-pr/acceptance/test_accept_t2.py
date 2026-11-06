"""Hidden acceptance tests for T2."""
import unittest
from decimal import Decimal

from invoicing.errors import InvoicingError
from invoicing.payments import CardDeclined, PaymentClient, TransientError


class Scripted(PaymentClient):
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def charge(self, invoice_id, amount, idempotency_key):
        self.calls.append((invoice_id, amount, idempotency_key))
        o = self.outcomes.pop(0)
        if isinstance(o, BaseException):
            raise o
        return o


def run(outcomes, **kw):
    from invoicing.payments import charge_with_retry
    c = Scripted(outcomes)
    sleeps = []
    try:
        r = charge_with_retry(c, "INV-1", Decimal("10.00"), "key-1", sleep=sleeps.append, **kw)
        return r, None, c, sleeps
    except Exception as e:  # noqa: BLE001 - the test inspects it
        return None, e, c, sleeps


class T2Accept(unittest.TestCase):
    def test_success_first_try_no_sleep(self):
        r, e, c, s = run(["ch_1"])
        self.assertEqual((r, e, len(c.calls), s), ("ch_1", None, 1, []))

    def test_retries_transient_then_succeeds(self):
        r, e, c, s = run([TransientError(), TransientError(), "ch_3"])
        self.assertEqual(r, "ch_3")
        self.assertEqual(len(c.calls), 3)

    def test_same_idempotency_key_every_attempt(self):
        r, e, c, s = run([TransientError(), TransientError(), "ch_3"])
        self.assertEqual({k for _, _, k in c.calls}, {"key-1"})

    def test_decline_not_retried(self):
        r, e, c, s = run([CardDeclined(), "ch_2"])
        self.assertIsInstance(e, CardDeclined)
        self.assertEqual(len(c.calls), 1)

    def test_other_exception_not_retried(self):
        r, e, c, s = run([KeyError("x"), "ch_2"])
        self.assertIsInstance(e, KeyError)
        self.assertEqual(len(c.calls), 1)

    def test_backoff_schedule(self):
        r, e, c, s = run([TransientError()] * 3 + ["ch"], max_attempts=4)
        self.assertEqual([float(x) for x in s], [0.5, 1.0, 2.0])

    def test_no_sleep_after_last_attempt_and_reraises_last(self):
        last = TransientError("third")
        r, e, c, s = run([TransientError(), TransientError(), last])
        self.assertIs(e, last)
        self.assertEqual(len(c.calls), 3)
        self.assertEqual(len(s), 2)

    def test_retry_after_honoured_and_capped(self):
        r, e, c, s = run([TransientError(retry_after=7), TransientError(retry_after=120), "ch"])
        self.assertEqual([float(x) for x in s], [7.0, 30.0])

    def test_max_attempts_below_one_raises(self):
        r, e, c, s = run(["ch"], max_attempts=0)
        self.assertIsInstance(e, InvoicingError)
        self.assertEqual(len(c.calls), 0)
