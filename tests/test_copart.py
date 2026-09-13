import unittest

from monitor.providers.copart import _location


class CopartParsingTests(unittest.TestCase):
    def test_parses_city_and_uf_from_validated_listing_format(self):
        self.assertEqual(_location("MANAUS - AM"), ("MANAUS", "AM"))

    def test_keeps_city_when_uf_is_not_available(self):
        self.assertEqual(_location("LOCAL DO VENDEDOR"), ("LOCAL DO VENDEDOR", ""))
