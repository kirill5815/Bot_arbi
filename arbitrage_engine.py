import asyncio
from typing import List, Dict, Optional
from config import TRADING_PAIRS, MIN_SPREAD_PERCENT
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
            
            # Собираем цены со всех бирж
            for ex_id in exchanges:
                try:
                    ticker = await self.exchange_manager.get_ticker(ex_id, symbol)
                    prices[ex_id] = {
                        'bid': ticker['bid'],
                        'ask': ticker['ask']
                    }
                except Exception as e:
                    continue
            
            # Ищем арбитраж
            for buy_ex in prices:
                for sell_ex in prices:
                    if buy_ex == sell_ex:
                        continue
                    
                    buy_price = prices[buy_ex]['ask']
                    sell_price = prices[sell_ex]['bid']
                    
                    if sell_price <= buy_price:
                        continue
                    
                    spread = ((sell_price - buy_price) / buy_price) * 100
                    
                    if spread >= MIN_SPREAD_PERCENT:
                        # Расчет с учетом комиссий
                        amount = 100  # USDT для теста
                        net_profit, details = await self.fee_calc.calculate_net_profit(
                            buy_ex, sell_ex, symbol, amount / buy_price
                        )
                        
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
        
        # Сортируем по прибыли
        opportunities.sort(key=lambda x: x['profit_percent'], reverse=True)
        return opportunities
    
    async def start_monitoring(self, callback):
        """Запуск мониторинга в фоне"""
        self.is_monitoring = True
        while self.is_monitoring:
            try:
                ops = await self.scan_opportunities()
                if ops:
                    await callback(ops)
                await asyncio.sleep(10)  # Интервал сканирования
            except Exception as e:
                await asyncio.sleep(30)
    
    def stop_monitoring(self):
        self.is_monitoring = False