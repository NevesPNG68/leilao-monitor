import unittest
from decimal import Decimal

from monitor.config import parse_decimal, parse_list


class ConfigTests(unittest.TestCase):
    def test_parses_brazilian_currency(self):
        self.assertEqual(parse_decimal("R$ 70.000,00"), Decimal("70000.00"))

    def test_rejects_invalid_json_list(self):
        with self.assertRaises(ValueError):
            parse_list('["ONIX"')
