from typing import Dict, Tuple

class FeeCalculator:
    def __init__(self, exchange_manager):
        self.exchange_manager = exchange_manager
        self.fee_cache: Dict[str, dict] = {}
    
    async def get_trading_fee(self, exchange_id: str, symbol: str) -> float:
        """Получение торговой комиссии (taker)"""
        cache_key = f"{exchange_id}:{symbol}"
        if cache_key in self.fee_cache:
            return self.fee_cache[cache_key]
        
        exchange = self.exchange_manager.exchanges.get(exchange_id)
        if not exchange:
            return 0.001  # Дефолт 0.1%
        
        try:
            markets = exchange.markets
            if symbol in markets:
                fee = markets[symbol].get('taker', 0.001)
                self.fee_cache[cache_key] = fee
                return fee
        except:
            pass
        
        return 0.001
    
    async def calculate_net_profit(self, buy_exchange: str, sell_exchange: str,
                                   symbol: str, amount: float) -> Tuple[float, dict]:
        """
        Расчет чистой прибыли с учетом:
        - Комиссии на покупку
        - Комиссии на продажу  
        - Комиссии на вывод (приблизительно)
        """
        # Получаем цены
        buy_ticker = await self.exchange_manager.get_ticker(buy_exchange, symbol)
        sell_ticker = await self.exchange_manager.get_ticker(sell_exchange, symbol)
        
        buy_price = buy_ticker['ask']  # Цена покупки (лучший ask)
        sell_price = sell_ticker['bid']  # Цена продажи (лучший bid)
        
        # Комиссии
        buy_fee_rate = await self.get_trading_fee(buy_exchange, symbol)
        sell_fee_rate = await self.get_trading_fee(sell_exchange, symbol)
        
        # Расчеты
        buy_cost = amount * buy_price
        buy_fee = buy_cost * buy_fee_rate
        actual_crypto = amount * (1 - buy_fee_rate)
        
        sell_revenue = actual_crypto * sell_price
        sell_fee = sell_revenue * sell_fee_rate
        net_revenue = sell_revenue * (1 - sell_fee_rate)
        
        # Приблизительная комиссия на вывод (0.0005 BTC для примера)
        withdrawal_fee = 0  # Уточняйте через exchange.fetch_currencies()
        
        gross_profit = net_revenue - buy_cost
        net_profit = gross_profit - withdrawal_fee
        profit_percent = (net_profit / buy_cost) * 100
        
        details = {
            'buy_price': buy_price,
            'sell_price': sell_price,
            'spread_percent': ((sell_price - buy_price) / buy_price) * 100,
            'buy_fee': buy_fee,
            'sell_fee': sell_fee * actual_crypto,
            'withdrawal_fee': withdrawal_fee,
            'net_profit': net_profit,
            'profit_percent': profit_percent,
            'amount': amount
        }
        
        return net_profit, details