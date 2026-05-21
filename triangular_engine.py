"""Треугольный арбитраж внутри одной биржи."""
from typing import List, Dict
from config import TRIANGULAR_SETS
class TriangularEngine:
    def __init__(self, exchange_manager):
        self.em = exchange_manager
        self.fee_rate = 0.001
    async def scan_triangular(self, exchange_id: str) -> List[Dict]:
        opportunities = []
        for pair1, pair2, pair3 in TRIANGULAR_SETS:
            try:
                t1 = await self.em.get_ticker(exchange_id, pair1)
                t2 = await self.em.get_ticker(exchange_id, pair2)
                t3 = await self.em.get_ticker(exchange_id, pair3)
                p1_ask = t1.get('ask', 0); p2_ask = t2.get('ask', 0); p3_bid = t3.get('bid', 0)
                if p1_ask <= 0 or p2_ask <= 0 or p3_bid <= 0: continue
                amount_usdt = 100
                btc_amount = amount_usdt / p1_ask * (1 - self.fee_rate)
                eth_amount = btc_amount / p2_ask * (1 - self.fee_rate)
                eth_value_usdt = eth_amount * p3_bid * (1 - self.fee_rate)
                profit = eth_value_usdt - amount_usdt
                profit_percent = (profit / amount_usdt) * 100
                if profit_percent > 0.05:
                    opportunities.append({
                        'type': 'triangular', 'exchange': exchange_id, 'path': f"{pair1} → {pair2} → {pair3}",
                        'step1': pair1, 'step2': pair2, 'step3': pair3,
                        'profit_usdt': profit, 'profit_percent': profit_percent, 'amount_usdt': amount_usdt,
                        'details': {'price1': p1_ask, 'price2': p2_ask, 'price3': p3_bid, 'btc_got': btc_amount, 'eth_got': eth_amount}
                    })
            except Exception: continue
        opportunities.sort(key=lambda x: x['profit_percent'], reverse=True)
        return opportunities