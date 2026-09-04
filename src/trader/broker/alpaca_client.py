"""Thin wrapper around alpaca-py clients. All broker access goes through here
so the judging-account swap is a pure .env change."""

from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.trading.client import TradingClient

from trader.config import Secrets


class Broker:
    def __init__(self, secrets: Secrets):
        secrets.require("alpaca_api_key", "alpaca_secret_key")
        if not secrets.alpaca_paper:
            # Hard guard: this project is paper-only by design (and by hackathon rules).
            raise RuntimeError("Refusing to start: ALPACA_PAPER must be true.")
        self.trading = TradingClient(
            secrets.alpaca_api_key, secrets.alpaca_secret_key, paper=True
        )
        self.stock_data = StockHistoricalDataClient(
            secrets.alpaca_api_key, secrets.alpaca_secret_key
        )
        self.option_data = OptionHistoricalDataClient(
            secrets.alpaca_api_key, secrets.alpaca_secret_key
        )

    def account(self):
        return self.trading.get_account()

    def positions(self):
        return self.trading.get_all_positions()

    def clock(self):
        return self.trading.get_clock()
