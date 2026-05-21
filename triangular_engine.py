"""Треугольный арбитраж — максимально быстрый, авто-генерация путей."""
import asyncio
import logging
from typing import List, Dict, Tuple

logger = logging.getLogger(__name__)

class TriangularEngine:
    def __init__(self, exchange_manager, fee_rate: float = 0.001,
                 min_profit_percent: float = 0.3, trade_amount: float = 100):
        self.em = exchange_manager
        self.fee_rate = fee_rate
        self.min_profit_percent = min_profit_percent
        self.trade_amount = trade_amount
        self._paths_cache: Dict[str, List[Tuple[str, str, str]]] = {}

    def generate_paths(self, exchange_id: str) -> List[Tuple[str, str, str]]:
        """Автогенерация всех треугольников из загруженных рынков."""
        if exchange_id in self._paths_cache:
            return self._paths_cache[exchange_id]
        ex = self.em.exchanges.get(exchange_id)
        if not ex:
            from config import TRIANGULAR_SETS
            return list(TRIANGULAR_SETS)
        markets = ex.markets
        symbols = set(markets.keys())
        paths = []
        quotes = {'USDT', 'USDC', 'BUSD', 'FDUSD'}
        bases_by_quote = {q: set() for q in quotes}
        for sym in symbols:
            if '/' not in sym or ':' in sym:
                continue
            base, quote = sym.split('/')
            if quote in quotes and base not in quotes:
                bases_by_quote[quote].add(base)
        main_bridges = ['BTC', 'ETH', 'BNB', 'SOL']
        for quote in ['USDT', 'USDC']:
            for bridge in main_bridges:
                p1 = f"{bridge}/{quote}"
                if p1 not in symbols:
                    continue
                for alt in bases_by_quote.get(quote, set()):
                    if alt == bridge:
                        continue
                    p2 = f"{alt}/{bridge}"
                    p3 = f"{alt}/{quote}"
                    if p2 in symbols and p3 in symbols:
                        paths.append((p1, p2, p3))
        from config import TRIANGULAR_SETS
        for tri in TRIANGULAR_SETS:
            if tri not in paths:
                paths.append(tri)
        self._paths_cache[exchange_id] = paths
        logger.info(f"{exchange_id}: сгенерировано {len(paths)} треугольников")
        return paths

    async def scan_triangular(self, exchange_id: str) -> List[Dict]:
        opportunities = []
        paths = self.generate_paths(exchange_id)
        if not paths:
            return opportunities
        all_symbols = list({sym for tri in paths for sym in tri})
        tickers = await self.em.fetch_tickers_batch(exchange_id, all_symbols)
        for pair1, pair2, pair3 in paths:
            t1 = tickers.get(pair1)
            t2 = tickers.get(pair2)
            t3 = tickers.get(pair3)
            if not t1 or not t2 or not t3:
                continue
            p1_ask = t1.get('ask', 0)
            p2_ask = t2.get('ask', 0)
            p3_bid = t3.get('bid', 0)
            if p1_ask <= 0 or p2_ask <= 0 or p3_bid <= 0:
                continue
            vol1 = t1.get('quoteVolume', 0) or 0
            vol2 = t2.get('quoteVolume', 0) or 0
            vol3 = t3.get('quoteVolume', 0) or 0
            if vol1 < 30000 or vol2 < 30000 or vol3 < 30000:
                continue
            amount_usdt = self.trade_amount
            base_got = (amount_usdt / p1_ask) * (1 - self.fee_rate)
            mid_got = (base_got / p2_ask) * (1 - self.fee_rate)
            final_usdt = mid_got * p3_bid * (1 - self.fee_rate)
            profit = final_usdt - amount_usdt
            profit_percent = (profit / amount_usdt) * 100 if amount_usdt else 0
            if profit_percent > self.min_profit_percent:
                opportunities.append({
                    'type': 'triangular',
                    'exchange': exchange_id,
                    'path': f"{pair1} → {pair2} → {pair3}",
                    'step1': pair1, 'step2': pair2, 'step3': pair3,
                    'profit_usdt': profit,
                    'profit_percent': profit_percent,
                    'amount_usdt': amount_usdt,
                    'details': {
                        'price1': p1_ask, 'price2': p2_ask, 'price3': p3_bid,
                        'base_got': base_got, 'mid_got': mid_got, 'final_usdt': final_usdt
                    }
                })
        opportunities.sort(key=lambda x: x['profit_percent'], reverse=True)
        return opportunities

    async def scan_all_exchanges(self) -> List[Dict]:
        """Параллельное сканирование всех бирж."""
        if not self.em.exchanges:
            return []
        tasks = [self.scan_triangular(eid) for eid in self.em.exchanges]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_ops = []
        for res in results:
            if isinstance(res, list):
                all_ops.extend(res)
        all_ops.sort(key=lambda x: x['profit_percent'], reverse=True)
        return all_ops