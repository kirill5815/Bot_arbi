"""
Модуль балансировки капитала между биржами.
Анализирует USDT-балансы и предлагает/выполняет переводы.
"""
import asyncio
from typing import Dict, List, Tuple
from exchange_manager import ExchangeManager

class BalanceManager:
    def __init__(self, exchange_manager: ExchangeManager):
        self.em = exchange_manager
        self.threshold_percent = 20  # Если разница > 20% — предлагаем балансировку

    async def get_all_balances(self) -> Dict[str, float]:
        """Получить USDT-балансы всех бирж"""
        balances = {}
        for eid in self.em.exchanges:
            try:
                bal = await self.em.get_balance(eid)
                usdt = bal.get('USDT', {}).get('free', 0)
                balances[eid] = usdt
            except Exception as e:
                balances[eid] = 0
        return balances

    async def analyze_distribution(self) -> Dict:
        """
        Анализирует распределение USDT между биржами.
        Возвращает рекомендации по переводам.
        """
        balances = await self.get_all_balances()
        if len(balances) < 2:
            return {'error': 'Нужно минимум 2 биржи'}

        total = sum(balances.values())
        if total == 0:
            return {'error': 'Нулевые балансы'}

        target = total / len(balances)  # Целевой баланс на каждую биржу

        # Кто переполнен, кто недогружен
        overloaded = []   # У кого больше target — нужно вывести
        underloaded = []  # У кого меньше target — нужно пополнить

        for eid, amount in balances.items():
            diff = amount - target
            diff_percent = (diff / target) * 100 if target > 0 else 0

            if diff_percent > self.threshold_percent:
                overloaded.append({'exchange': eid, 'amount': amount, 'excess': diff, 'percent': diff_percent})
            elif diff_percent < -self.threshold_percent:
                underloaded.append({'exchange': eid, 'amount': amount, 'shortage': abs(diff), 'percent': abs(diff_percent)})

        # Формируем пары для перевода
        transfers = []
        for src in overloaded:
            for dst in underloaded:
                transfer_amount = min(src['excess'], dst['shortage'])
                if transfer_amount > 10:  # Минимум 10 USDT
                    transfers.append({
                        'from': src['exchange'],
                        'to': dst['exchange'],
                        'amount': round(transfer_amount, 2),
                        'from_balance_after': round(src['amount'] - transfer_amount, 2),
                        'to_balance_after': round(dst['amount'] + transfer_amount, 2)
                    })

        return {
            'total_usdt': round(total, 2),
            'target_per_exchange': round(target, 2),
            'balances': balances,
            'overloaded': overloaded,
            'underloaded': underloaded,
            'recommended_transfers': transfers,
            'needs_rebalancing': len(transfers) > 0
        }

    async def execute_transfer_plan(self, transfers: List[Dict], user_confirm_callback) -> List[Dict]:
        """
        Выполняет план переводов с подтверждением пользователя.

        Примечание: Автоматический вывод крипты через API — рискованно.
        Этот метод генерирует инструкции для ручного вывода.
        """
        results = []
        for t in transfers:
            # Проверяем подтверждение
            confirmed = await user_confirm_callback(t)
            if not confirmed:
                results.append({**t, 'status': 'cancelled'})
                continue

            # Пытаемся выполнить вывод через API (если биржа поддерживает)
            try:
                from_ex = self.em.exchanges.get(t['from'])
                if from_ex and hasattr(from_ex, 'withdraw'):
                    # Вывод USDT (нужно указать сеть, адрес и т.д.)
                    # Это требует настройки адресов вывода — пока генерируем инструкцию
                    results.append({
                        **t,
                        'status': 'manual_required',
                        'instruction': f"Выведите {t['amount']} USDT с {t['from']} на {t['to']}. Адрес пополнения {t['to']} нужно получить вручную."
                    })
                else:
                    results.append({
                        **t,
                        'status': 'manual_required',
                        'instruction': f"API вывода недоступен. Выведите {t['amount']} USDT с {t['from']} на {t['to']} вручную."
                    })
            except Exception as e:
                results.append({**t, 'status': 'error', 'error': str(e)})

        return results