import unittest

from invoicing.logs import log_line


class LogsTest(unittest.TestCase):
    def test_fields_sorted(self):
        line = log_line("charged", invoice="INV-1", amount="9.99")
        self.assertTrue(line.endswith(" charged amount=9.99 invoice=INV-1"))
