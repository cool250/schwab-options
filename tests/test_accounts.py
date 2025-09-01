import unittest
from unittest.mock import MagicMock
from broker.accounts import AccountsTrading
from model.account_models import SecuritiesAccount

class TestAccountsTrading(unittest.TestCase):

    def setUp(self):
        self.accounts_trading = AccountsTrading()
        self.mock_securities_account = MagicMock(spec=SecuritiesAccount)

    def test_get_positions(self):
        """Test the get_positions method."""
        self.accounts_trading._fetch_positions = MagicMock(return_value=self.mock_securities_account)
        result = self.accounts_trading._fetch_positions()
        self.assertEqual(result, self.mock_securities_account)

    def test_calculate_total_exposure_for_short_puts(self):
        """Test the calculate_total_exposure_for_short_puts method."""
        self.mock_securities_account.positions = [
            MagicMock(shortQuantity=2, instrument=MagicMock(assetType="OPTION", symbol="AAPL230915P00150000")),
            MagicMock(shortQuantity=1, instrument=MagicMock(assetType="OPTION", symbol="MSFT230915P00200000"))
        ]
        self.accounts_trading.calculate_total_exposure_for_short_puts = MagicMock(return_value=4500.0)
        result = self.accounts_trading.calculate_total_exposure_for_short_puts(self.mock_securities_account)
        self.assertEqual(result, 4200.0)

if __name__ == "__main__":
    unittest.main()
