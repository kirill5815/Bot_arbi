import asyncio
from typing import List, Dict
from config import SPOT_PAIRS as TRADING_PAIRS, MIN_SPREAD_PERCENT
from exchange_manager import ExchangeManager
from fee_calculator import FeeCalculator

class ArbitrageEngine:
    def __init__(self, exchange_manager: ExchangeManager):
        self.exchange_manager = exchange_manager
        self.fee_calc = FeeCalculator(exchange_manager)
        self.active_opportunities: List[Dict] = []
        self.is_monitoring = False

    async def scan_opportunities(self) -> List[Dict]:
        """Сканирование арбитражных возможностей"""
        opportunities = []
        exchanges = list(self.exchange_manager.exchanges.keys())

        if len(exchanges) < 2:
            return opportunities

        for symbol in TRADING_PAIRS:
            prices = {}

            for ex_id in exchanges:
                try:
                    ticker = await self.exchange_manager.get_ticker(ex_id, symbol)
                    prices[ex_id] = {
                        'bid': ticker.get('bid', 0),
                        'ask': ticker.get('ask', 0)
                    }
                except Exception:
                    continue

            for buy_ex in prices:
                for sell_ex in prices:
                    if buy_ex == sell_ex:
                        continue

                    buy_price = prices[buy_ex]['ask']
                    sell_price = prices[sell_ex]['bid']

                    if sell_price <= buy_price or buy_price <= 0:
                        continue

                    spread = ((sell_price - buy_price) / buy_price) * 100

                    if spread >= MIN_SPREAD_PERCENT:
                        amount = 100 / buy_price if buy_price > 0 else 0
                        if amount <= 0:
                            continue

                        try:
                            net_profit, details = await self.fee_calc.calculate_net_profit(
                                buy_ex, sell_ex, symbol, amount
                            )
                        except Exception:
                            continue

                        if details['profit_percent'] > 0:
                            opportunities.append({
                                'symbol': symbol,
                                'buy_exchange': buy_ex,
                                'sell_exchange': sell_ex,
                                'buy_price': buy_price,
                                'sell_price': sell_price,
                                'spread_percent': spread,
                                'net_profit_usd': net_profit,
                                'profit_percent': details['profit_percent'],
                                'details': details
                            })

        opportunities.sort(key=lambda x: x['profit_percent'], reverse=True)
        return opportunities
    scan = scan_opportunities

    async def start_monitoring(self, callback):
        """Запуск мониторинга в фоне"""
        self.is_monitoring = True
        while self.is_monitoring:
            try:
                ops = await self.scan_opportunities()
                if ops:
                    await callback(ops)
                await asyncio.sleep(10)
            except Exception:
                await asyncio.sleep(30)

    def stop_monitoring(self):
        self.is_monitoring = False