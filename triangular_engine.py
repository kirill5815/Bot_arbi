"""Треугольный арбитраж внутри одной биржи."""
import asyncio
from typing import List, Dict
from config import TRIANGULAR_SETS

class TriangularEngine:
    def __init__(self, exchange_manager, fee_rate: float = 0.001, 
                 min_profit_percent: float = 0.8, trade_amount: float = 100):
        self.em = exchange_manager
        self.fee_rate = fee_rate
        self.min_profit_percent = min_profit_percent
        self.trade_amount = trade_amount

    async def scan_triangular(self, exchange_id: str) -> List[Dict]:
        opportunities = []
        
        for pair1, pair2, pair3 in TRIANGULAR_SETS:
            try:
                # Параллельное получение 3 тикеров (в 3 раза быстрее)
                t1, t2, t3 = await asyncio.gather(
                    self.em.get_ticker(exchange_id, pair1),
                    self.em.get_ticker(exchange_id, pair2),
                    self.em.get_ticker(exchange_id, pair3)
                )
                
                p1_ask = t1.get('ask', 0)
                p2_ask = t2.get('ask', 0)
                p3_bid = t3.get('bid', 0)
                
                if p1_ask <= 0 or p2_ask <= 0 or p3_bid <= 0:
                    continue
                
                # Фильтр ликвидности: quoteVolume > $100k/сутки
                vol1 = t1.get('quoteVolume', 0) or t1.get('baseVolume', 0)
                vol2 = t2.get('quoteVolume', 0) or t2.get('baseVolume', 0)
                vol3 = t3.get('quoteVolume', 0) or t3.get('baseVolume', 0)
                if vol1 < 100000 or vol2 < 100000 or vol3 < 100000:
                    continue
                
                amount_usdt = self.trade_amount
                
                # Шаг 1: USDT → BASE (покупаем pair1)
                base_got = (amount_usdt / p1_ask) * (1 - self.fee_rate)
                
                # Шаг 2: BASE → MID (покупаем pair2)
                mid_got = (base_got / p2_ask) * (1 - self.fee_rate)
                
                # Шаг 3: MID → USDT (продаем pair3)
                final_usdt = mid_got * p3_bid * (1 - self.fee_rate)
                
                profit = final_usdt - amount_usdt
                profit_percent = (profit / amount_usdt) * 100 if amount_usdt else 0
                
                if profit_percent > self.min_profit_percent:
                    opportunities.append({
                        'type': 'triangular',
                        'exchange': exchange_id,
                        'path': f"{pair1} → {pair2} → {pair3}",
                        'step1': pair1,
                        'step2': pair2,
                        'step3': pair3,
                        'profit_usdt': profit,
                        'profit_percent': profit_percent,
                        'amount_usdt': amount_usdt,
                        'details': {
                            'price1': p1_ask,
                            'price2': p2_ask,
                            'price3': p3_bid,
                            'base_got': base_got,
                            'mid_got': mid_got,
                            'final_usdt': final_usdt
                        }
                    })
                    
            except Exception:
                continue
        
        opportunities.sort(key=lambda x: x['profit_percent'], reverse=True)
        return opportunities