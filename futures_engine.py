"""Фьючерсный арбитраж (базис + фандинг)."""
from typing import List, Dict
from config import FUTURES_PAIRS, FUTURES_LEVERAGE
class FuturesEngine:
    def __init__(self, exchange_manager):
        self.em = exchange_manager
        self.fee_rate = 0.0005
    async def scan_basis(self, exchange_id: str) -> List[Dict]:
        opportunities = []
        for fut_pair in FUTURES_PAIRS:
            spot_pair = fut_pair.replace(':USDT', '')
            try:
                spot_ticker = await self.em.get_ticker(exchange_id, spot_pair, 'spot')
                spot_price = spot_ticker.get('last', 0)
                fut_ticker = await self.em.get_ticker(exchange_id, fut_pair, 'swap')
                fut_price = fut_ticker.get('last', 0)
                if spot_price <= 0 or fut_price <= 0: continue
                basis = ((fut_price - spot_price) / spot_price) * 100
                funding_rate = 0
                try:
                    ex = self.em.exchanges.get(exchange_id)
                    if ex and hasattr(ex, 'fetchFundingRate'):
                        fr = await ex.fetchFundingRate(fut_pair)
                        funding_rate = fr.get('fundingRate', 0) * 100
                except: pass
                if basis > 0.1:
                    profit = basis - (self.fee_rate * 2 * 100)
                    if profit > 0.05:
                        opportunities.append({
                            'type': 'futures_basis', 'exchange': exchange_id, 'symbol': spot_pair.split('/')[0],
                            'spot_pair': spot_pair, 'futures_pair': fut_pair, 'basis_percent': basis,
                            'funding_rate': funding_rate, 'strategy': 'sell_futures_buy_spot',
                            'profit_percent': profit, 'details': {'spot_price': spot_price, 'futures_price': fut_price, 'leverage': FUTURES_LEVERAGE}
                        })
                elif basis < -0.1:
                    profit = abs(basis) - (self.fee_rate * 2 * 100)
                    if profit > 0.05:
                        opportunities.append({
                            'type': 'futures_basis', 'exchange': exchange_id, 'symbol': spot_pair.split('/')[0],
                            'spot_pair': spot_pair, 'futures_pair': fut_pair, 'basis_percent': basis,
                            'funding_rate': funding_rate, 'strategy': 'buy_futures_sell_spot',
                            'profit_percent': profit, 'details': {'spot_price': spot_price, 'futures_price': fut_price, 'leverage': FUTURES_LEVERAGE}
                        })
                if funding_rate > 0.01:
                    opportunities.append({
                        'type': 'futures_funding', 'exchange': exchange_id, 'symbol': spot_pair.split('/')[0],
                        'futures_pair': fut_pair, 'funding_rate': funding_rate,
                        'strategy': 'short_futures_collect_funding',
                        'profit_percent': funding_rate * 3,
                        'details': {'spot_price': spot_price, 'futures_price': fut_price}
                    })
            except Exception: continue
        opportunities.sort(key=lambda x: x.get('profit_percent', 0), reverse=True)
        return opportunities