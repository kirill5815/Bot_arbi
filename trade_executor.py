import asyncio
from typing import Dict, Callable
from exchange_manager import ExchangeManager

class TradeExecutor:
    def __init__(self, exchange_manager: ExchangeManager):
        self.exchange_manager = exchange_manager
        self.pending_trades: Dict[str, Dict] = {}  # trade_id -> trade_info
        self.trade_counter = 0
    
    async def prepare_trade(self, opportunity: Dict, amount_usdt: float) -> str:
        """Подготовка сделки для подтверждения пользователем"""
        self.trade_counter += 1
        trade_id = f"TRADE_{self.trade_counter}"
        
        trade = {
            'id': trade_id,
            'symbol': opportunity['symbol'],
            'buy_exchange': opportunity['buy_exchange'],
            'sell_exchange': opportunity['sell_exchange'],
            'amount_usdt': amount_usdt,
            'expected_profit': opportunity['net_profit_usd'],
            'status': 'pending',
            'opportunity': opportunity
        }
        
        self.pending_trades[trade_id] = trade
        return trade_id
    
    async def execute_trade(self, trade_id: str) -> Dict:
        """Исполнение подтвержденной сделки"""
        if trade_id not in self.pending_trades:
            return {'success': False, 'error': 'Сделка не найдена'}
        
        trade = self.pending_trades[trade_id]
        trade['status'] = 'executing'
        
        try:
            symbol = trade['symbol']
            amount = trade['amount_usdt']
            
            # Шаг 1: Покупка на бирже A
            buy_ex = self.exchange_manager.exchanges[trade['buy_exchange']]
            buy_price = trade['opportunity']['buy_price']
            quantity = amount / buy_price
            
            # Маркет-ордер на покупку
            buy_order = await buy_ex.create_market_buy_order(symbol, quantity)
            trade['buy_order'] = buy_order
            
            # Шаг 2: Продажа на бирже B
            sell_ex = self.exchange_manager.exchanges[trade['sell_exchange']]
            
            # Маркет-ордер на продажу
            sell_order = await sell_ex.create_market_sell_order(symbol, quantity)
            trade['sell_order'] = sell_order
            
            trade['status'] = 'completed'
            
            return {
                'success': True,
                'trade': trade,
                'buy_order': buy_order,
                'sell_order': sell_order
            }
            
        except Exception as e:
            trade['status'] = 'failed'
            trade['error'] = str(e)
            return {'success': False, 'error': str(e), 'trade': trade}
    
    async def cancel_trade(self, trade_id: str):
        """Отмена подготовленной сделки"""
        if trade_id in self.pending_trades:
            self.pending_trades[trade_id]['status'] = 'cancelled'
            return True
        return False