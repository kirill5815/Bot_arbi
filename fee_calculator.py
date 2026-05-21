from typing import Tuple, Dict
class FeeCalculator:
    def __init__(self, em): self.em = em; self.cache = {}
    async def fee(self, eid, sym):
        k = f"{eid}:{sym}"
        if k in self.cache: return self.cache[k]
        ex = self.em.exchanges.get(eid)
        if not ex: return 0.001
        try:
            if sym in ex.markets:
                f = ex.markets[sym].get('taker', 0.001)
                self.cache[k] = f; return f
        except: pass
        return 0.001
    async def calc(self, buy_ex, sell_ex, sym, amount) -> Tuple[float, Dict]:
        bt = await self.em.get_ticker(buy_ex, sym); st = await self.em.get_ticker(sell_ex, sym)
        bp = bt.get('ask', 0); sp = st.get('bid', 0)
        if bp <= 0 or sp <= 0: return 0, {'profit_percent': 0}
        bfr = await self.fee(buy_ex, sym); sfr = await self.fee(sell_ex, sym)
        cost = amount * bp; got = amount * (1 - bfr); rev = got * sp * (1 - sfr)
        profit = rev - cost; pct = (profit / cost) * 100 if cost else 0
        return profit, {'buy_price': bp, 'sell_price': sp, 'spread_percent': ((sp - bp) / bp) * 100, 'net_profit': profit, 'profit_percent': pct, 'amount': amount}