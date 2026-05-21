"""Балансировка капитала."""
from typing import Dict, List
from exchange_manager import ExchangeManager
class BalanceManager:
    def __init__(self, exchange_manager: ExchangeManager):
        self.em = exchange_manager; self.threshold_percent = 20
    async def get_all_balances(self) -> Dict[str, float]:
        balances = {}
        for eid in self.em.exchanges:
            try:
                bal = await self.em.get_balance(eid); usdt = bal.get('USDT', {}).get('free', 0)
                balances[eid] = usdt
            except Exception: balances[eid] = 0
        return balances
    async def analyze_distribution(self) -> Dict:
        balances = await self.get_all_balances()
        if len(balances) < 2: return {'error': 'Нужно минимум 2 биржи'}
        total = sum(balances.values())
        if total == 0: return {'error': 'Нулевые балансы'}
        target = total / len(balances)
        overloaded = []; underloaded = []
        for eid, amount in balances.items():
            diff = amount - target; diff_percent = (diff / target) * 100 if target > 0 else 0
            if diff_percent > self.threshold_percent: overloaded.append({'exchange': eid, 'amount': amount, 'excess': diff, 'percent': diff_percent})
            elif diff_percent < -self.threshold_percent: underloaded.append({'exchange': eid, 'amount': amount, 'shortage': abs(diff), 'percent': abs(diff_percent)})
        transfers = []
        for src in overloaded:
            for dst in underloaded:
                transfer_amount = min(src['excess'], dst['shortage'])
                if transfer_amount > 10: transfers.append({'from': src['exchange'], 'to': dst['exchange'], 'amount': round(transfer_amount, 2)})
        return {'total_usdt': round(total, 2), 'target_per_exchange': round(target, 2), 'balances': balances, 'overloaded': overloaded, 'underloaded': underloaded, 'recommended_transfers': transfers, 'needs_rebalancing': len(transfers) > 0}