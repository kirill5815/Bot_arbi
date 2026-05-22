"""Бумажная торговля — виртуальный баланс, реальные цены."""
import asyncio
import logging
import time
from typing import Dict, Optional, List
from datetime import datetime
from config import PAPER_TRADING_BALANCE, PAPER_FEE_RATE

logger = logging.getLogger(__name__)

class PaperTradeExecutor:
    """Эмулирует торговлю без реальных ордеров. Использует реальные цены с бирж."""

    def __init__(self, exchange_manager):
        self.em = exchange_manager
        self.balance_usdt = PAPER_TRADING_BALANCE
        self.fee_rate = PAPER_FEE_RATE
        self.positions: Dict[str, float] = {}  # {symbol: qty} — виртуальные балансы монет
        self.trade_history: List[Dict] = []
        self.cnt = 0
        self._monitoring = False
        self._paper_positions = {}  # {tid: {...}} для скальпинга

    def get_virtual_balance(self) -> Dict:
        """Возвращает текущий виртуальный баланс."""
        total_crypto = 0
        for sym, qty in self.positions.items():
            # Упрощённо: считаем по последним ценам с первой доступной биржи
            if self.em.exchanges:
                eid = list(self.em.exchanges.keys())[0]
                try:
                    # Будет вызвано синхронно, но в асинхронном контексте это проблема
                    # Поэтому передаём цену извне
                    pass
                except:
                    pass
        return {
            'usdt': self.balance_usdt,
            'positions': dict(self.positions),
            'total_trades': len(self.trade_history),
            'total_profit': sum(t.get('profit', 0) for t in self.trade_history)
        }

    async def prepare(self, op, amount_usdt) -> str:
        """Подготовка сделки (как в реальном executor)."""
        self.cnt += 1
        tid = f"PAPER_{self.cnt}"
        ttype = op.get('type', 'spot')

        self._paper_positions[tid] = {
            'id': tid,
            'symbol': op.get('symbol', op.get('path', 'unknown')),
            'buy_exchange': op.get('buy_exchange', op.get('exchange', 'unknown')),
            'sell_exchange': op.get('sell_exchange', op.get('exchange', 'unknown')),
            'amount_usdt': amount_usdt,
            'expected_profit': op.get('net_profit_usd', op.get('profit_usdt', 0)),
            'status': 'pending',
            'opportunity': op,
            'trade_type': ttype,
            'created_at': datetime.now().isoformat()
        }
        return tid

    async def execute(self, tid) -> Dict:
        """Эмулирует исполнение сделки по реальным ценам."""
        if tid not in self._paper_positions:
            return {'success': False, 'error': 'Сделка не найдена'}

        tr = self._paper_positions[tid]
        tr['status'] = 'executing'
        ttype = tr['trade_type']

        try:
            if ttype in ('scalp_dip', 'scalp_pump'):
                return await self._execute_paper_scalp(tid, tr)
            elif ttype == 'triangular':
                return await self._execute_paper_triangular(tid, tr)
            elif ttype == 'futures_basis':
                return await self._execute_paper_futures(tid, tr)
            else:
                return await self._execute_paper_spot(tid, tr)
        except Exception as e:
            tr['status'] = 'failed'
            tr['error'] = str(e)
            logger.error(f"Paper execute error {tid}: {e}")
            return {'success': False, 'error': str(e), 'trade': tr}

    async def _execute_paper_scalp(self, tid, tr) -> Dict:
        """Бумажный скальпинг: эмулируем вход, ставим виртуальный TP/SL."""
        op = tr['opportunity']
        exchange_id = tr['buy_exchange']
        symbol = tr['symbol']
        amount = tr['amount_usdt']

        # Проверка баланса
        if self.balance_usdt < amount:
            raise ValueError(f"Недостаточно USDT. Баланс: {self.balance_usdt:.2f}, нужно: {amount:.2f}")

        # Получаем реальную цену
        ticker = await self.em.get_ticker(exchange_id, symbol)
        entry_price = ticker.get('ask', ticker.get('last', 0))
        if entry_price <= 0:
            raise ValueError("Неверная цена входа")

        qty = amount / entry_price
        fee = amount * self.fee_rate
        total_cost = amount + fee

        # Списываем USDT
        self.balance_usdt -= total_cost

        # Добавляем монету в позицию
        base = symbol.split('/')[0]
        self.positions[base] = self.positions.get(base, 0) + qty

        # Расчёт TP/SL
        tp_price = entry_price * 1.01  # +1%
        sl_price = entry_price * 0.985  # -1.5%

        tr.update({
            'entry_price': entry_price,
            'qty': qty,
            'fee': fee,
            'tp_price': tp_price,
            'sl_price': sl_price,
            'status': 'open',
            'profit': 0
        })

        # Запускаем фоновый мониторинг TP/SL
        asyncio.create_task(self._monitor_paper_position(tid))

        return {'success': True, 'trade': tr}

    async def _execute_paper_triangular(self, tid, tr) -> Dict:
        """Бумажный треугольный арбитраж."""
        op = tr['opportunity']
        exchange_id = tr['buy_exchange']
        amount = tr['amount_usdt']

        if self.balance_usdt < amount:
            raise ValueError(f"Недостаточно USDT: {self.balance_usdt:.2f}")

        # Получаем реальные цены
        t1 = await self.em.get_ticker(exchange_id, op['step1'])
        t2 = await self.em.get_ticker(exchange_id, op['step2'])
        t3 = await self.em.get_ticker(exchange_id, op['step3'])

        p1 = t1.get('ask', 0)
        p2 = t2.get('ask', 0)
        p3 = t3.get('bid', 0)

        if p1 <= 0 or p2 <= 0 or p3 <= 0:
            raise ValueError("Неверные цены")

        # Эмуляция 3 шагов
        fee = self.fee_rate
        btc_got = (amount / p1) * (1 - fee)
        eth_got = (btc_got / p2) * (1 - fee)
        final_usdt = eth_got * p3 * (1 - fee)

        profit = final_usdt - amount
        total_fee = amount * fee + (btc_got * p2) * fee + (eth_got * p3) * fee

        # Обновляем баланс
        self.balance_usdt += profit

        tr.update({
            'orders': [
                {'side': 'buy', 'symbol': op['step1'], 'price': p1, 'amount': amount},
                {'side': 'buy', 'symbol': op['step2'], 'price': p2, 'amount': btc_got * p2},
                {'side': 'sell', 'symbol': op['step3'], 'price': p3, 'amount': eth_got}
            ],
            'profit': profit,
            'fee': total_fee,
            'status': 'completed'
        })

        self.trade_history.append(tr)
        return {'success': True, 'trade': tr}

    async def _execute_paper_spot(self, tid, tr) -> Dict:
        """Бумажный спот арбитраж между биржами."""
        op = tr['opportunity']
        buy_ex = tr['buy_exchange']
        sell_ex = tr['sell_exchange']
        symbol = tr['symbol']
        amount = tr['amount_usdt']

        if self.balance_usdt < amount:
            raise ValueError(f"Недостаточно USDT: {self.balance_usdt:.2f}")

        # Реальные цены
        bt = await self.em.get_ticker(buy_ex, symbol)
        st = await self.em.get_ticker(sell_ex, symbol)
        buy_price = bt.get('ask', 0)
        sell_price = st.get('bid', 0)

        if buy_price <= 0 or sell_price <= 0:
            raise ValueError("Неверные цены")

        qty = amount / buy_price
        buy_fee = amount * self.fee_rate
        sell_revenue = qty * sell_price
        sell_fee = sell_revenue * self.fee_rate
        net_profit = sell_revenue - amount - buy_fee - sell_fee

        self.balance_usdt += net_profit

        tr.update({
            'buy_order': {'price': buy_price, 'qty': qty, 'fee': buy_fee},
            'sell_order': {'price': sell_price, 'qty': qty, 'fee': sell_fee},
            'profit': net_profit,
            'status': 'completed'
        })

        self.trade_history.append(tr)
        return {'success': True, 'trade': tr}

    async def _execute_paper_futures(self, tid, tr) -> Dict:
        """Бумажный фьючерсный арбитраж (упрощённо)."""
        op = tr['opportunity']
        amount = tr['amount_usdt']

        if self.balance_usdt < amount:
            raise ValueError(f"Недостаточно USDT: {self.balance_usdt:.2f}")

        # Эмулируем по расчётным данным из opportunity
        profit = op.get('profit_percent', 0) * amount / 100
        self.balance_usdt += profit

        tr.update({
            'profit': profit,
            'status': 'completed'
        })

        self.trade_history.append(tr)
        return {'success': True, 'trade': tr}

    async def _monitor_paper_position(self, tid):
        """Фоновый мониторинг TP/SL для бумажной позиции."""
        if tid not in self._paper_positions:
            return

        pos = self._paper_positions[tid]
        symbol = pos['symbol']
        exchange_id = pos['buy_exchange']
        entry = pos['entry_price']
        qty = pos['qty']
        tp = pos['tp_price']
        sl = pos['sl_price']
        base = symbol.split('/')[0]

        while pos['status'] == 'open':
            try:
                ticker = await self.em.get_ticker(exchange_id, symbol)
                current = ticker.get('last', 0)

                if current <= 0:
                    await asyncio.sleep(5)
                    continue

                # TP сработал
                if current >= tp:
                    revenue = qty * tp
                    fee = revenue * self.fee_rate
                    profit = (tp - entry) * qty - fee
                    self.balance_usdt += revenue - fee
                    self.positions[base] = self.positions.get(base, 0) - qty
                    if self.positions[base] <= 0:
                        del self.positions[base]

                    pos['status'] = 'tp_hit'
                    pos['exit_price'] = tp
                    pos['profit'] = profit
                    self.trade_history.append(pos)
                    logger.info(f"[PAPER] TP {symbol}: +{profit:.2f} USDT")
                    break

                # SL сработал
                if current <= sl:
                    revenue = qty * current
                    fee = revenue * self.fee_rate
                    loss = (entry - current) * qty + fee
                    self.balance_usdt += revenue - fee
                    self.positions[base] = self.positions.get(base, 0) - qty
                    if self.positions[base] <= 0:
                        del self.positions[base]

                    pos['status'] = 'sl_hit'
                    pos['exit_price'] = current
                    pos['profit'] = -loss
                    self.trade_history.append(pos)
                    logger.info(f"[PAPER] SL {symbol}: −{loss:.2f} USDT")
                    break

                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"[PAPER] Monitor error {tid}: {e}")
                await asyncio.sleep(10)

    async def cancel(self, tid):
        """Отмена бумажной сделки."""
        if tid in self._paper_positions:
            tr = self._paper_positions[tid]
            if tr['status'] == 'open':
                # Возвращаем USDT
                if 'entry_price' in tr and 'qty' in tr:
                    base = tr['symbol'].split('/')[0]
                    self.positions[base] = self.positions.get(base, 0) - tr['qty']
                    if self.positions[base] <= 0:
                        del self.positions[base]
                    self.balance_usdt += tr['amount_usdt']
                tr['status'] = 'cancelled'
            return True
        return False

    def get_stats(self) -> Dict:
        """Статистика бумажной торговли."""
        completed = [t for t in self.trade_history if t['status'] in ('completed', 'tp_hit', 'sl_hit')]
        profits = [t.get('profit', 0) for t in completed]
        return {
            'total_trades': len(completed),
            'total_profit': sum(profits),
            'avg_profit': sum(profits) / len(profits) if profits else 0,
            'win_rate': len([p for p in profits if p > 0]) / len(profits) * 100 if profits else 0,
            'current_balance': self.balance_usdt,
            'open_positions': len([t for t in self._paper_positions.values() if t['status'] == 'open'])
        }