from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

class TradeExecutor:
    def __init__(self, em, scalp_engine=None):
        self.em = em
        self.scalp_engine = scalp_engine
        self.pending: Dict[str, dict] = {}
        self.cnt = 0

    async def prepare(self, op, amount_usdt):
        self.cnt += 1
        tid = f"TRADE_{self.cnt}"

        ttype = op.get('type', 'spot')

        self.pending[tid] = {
            'id': tid,
            'symbol': op.get('symbol', op.get('path', 'unknown')),
            'buy_exchange': op.get('buy_exchange', op.get('exchange', 'unknown')),
            'sell_exchange': op.get('sell_exchange', op.get('exchange', 'unknown')),
            'amount_usdt': amount_usdt,
            'expected_profit': op.get('net_profit_usd', op.get('profit_usdt', 0)),
            'status': 'pending',
            'opportunity': op,
            'trade_type': ttype
        }
        return tid

    async def execute(self, tid) -> Dict:
        if tid not in self.pending:
            return {'success': False, 'error': 'Сделка не найдена'}

        tr = self.pending[tid]
        tr['status'] = 'executing'
        ttype = tr['trade_type']

        try:
            if ttype in ('scalp_dip', 'scalp_pump'):
                return await self._execute_scalp(tid, tr)
            elif ttype == 'triangular':
                return await self._execute_triangular(tid, tr)
            elif ttype == 'futures_basis':
                return await self._execute_futures(tid, tr)
            else:
                return await self._execute_spot(tid, tr)
        except Exception as e:
            tr['status'] = 'failed'
            tr['error'] = str(e)
            logger.error(f"Execute error {tid}: {e}")
            return {'success': False, 'error': str(e), 'trade': tr}

    async def _execute_scalp(self, tid, tr) -> Dict:
        """Скальпинг: market buy + limit sell TP. SL мониторится фоново."""
        op = tr['opportunity']
        exchange_id = tr['buy_exchange']
        symbol = tr['symbol']
        amount = tr['amount_usdt']

        if self.scalp_engine:
            # Используем ScalpingEngine для входа
            result = await self.scalp_engine.open_position(exchange_id, symbol, amount)
            if not result.get('success'):
                raise ValueError(result.get('error', 'Ошибка входа в позицию'))

            tr.update(result)
            tr['status'] = 'open'
            tr['exit_price'] = None
            tr['profit'] = 0

            # Добавляем в фоновый мониторинг TP/SL
            self.scalp_engine._positions[tid] = {
                'exchange': result['exchange'],
                'symbol': result['symbol'],
                'entry_price': result['entry_price'],
                'qty': result['qty'],
                'tp_price': result['tp_price'],
                'sl_price': result['sl_price'],
                'tp_order_id': result.get('tp_order_id'),
                'status': 'open'
            }

            return {'success': True, 'trade': tr}
        else:
            # Fallback: ручное исполнение
            ex = self.em.exchanges.get(exchange_id)
            if not ex:
                raise ValueError("Биржа не подключена")

            ticker = await self.em.get_ticker(exchange_id, symbol)
            price = ticker.get('ask', ticker.get('last', 0))
            if price <= 0:
                raise ValueError("Неверная цена")

            qty = amount / price
            buy_order = await ex.create_market_buy_order(symbol, qty)

            tp_price = price * 1.01  # +1%
            sl_price = price * 0.985  # -1.5%
            tp_order = await ex.create_limit_sell_order(symbol, qty, tp_price)

            tr['entry_price'] = price
            tr['qty'] = qty
            tr['tp_price'] = tp_price
            tr['sl_price'] = sl_price
            tr['tp_order_id'] = tp_order.get('id')
            tr['buy_order'] = buy_order
            tr['status'] = 'open'

            return {'success': True, 'trade': tr}

    async def _execute_triangular(self, tid, tr) -> Dict:
        """Треугольный арбитраж: 3 ордера подряд."""
        ex = self.em.exchanges.get(tr['buy_exchange'])
        if not ex:
            raise ValueError("Биржа не подключена")

        op = tr['opportunity']
        btc_qty = tr['amount_usdt'] / op['details']['price1']

        o1 = await ex.create_market_buy_order(op['step1'], btc_qty)
        eth_qty = btc_qty / op['details']['price2']

        o2 = await ex.create_market_buy_order(op['step2'], eth_qty)
        o3 = await ex.create_market_sell_order(op['step3'], eth_qty)

        tr['orders'] = [o1, o2, o3]
        tr['status'] = 'completed'
        return {'success': True, 'trade': tr}

    async def _execute_futures(self, tid, tr) -> Dict:
        """Фьючерсный базис: спот + фьючерс."""
        ex = self.em.exchanges.get(tr['buy_exchange'])
        if not ex:
            raise ValueError("Биржа не подключена")

        op = tr['opportunity']
        qty = tr['amount_usdt'] / op['details']['spot_price']

        if op['strategy'] == 'sell_futures_buy_spot':
            o1 = await ex.create_market_buy_order(op['spot_pair'], qty)
            o2 = await ex.create_market_sell_order(op['futures_pair'], qty)
        else:
            o1 = await ex.create_market_sell_order(op['spot_pair'], qty)
            o2 = await ex.create_market_buy_order(op['futures_pair'], qty)

        tr['orders'] = [o1, o2]
        tr['status'] = 'completed'
        return {'success': True, 'trade': tr}

    async def _execute_spot(self, tid, tr) -> Dict:
        """Классический спот арбитраж: buy на бирже A, sell на бирже B."""
        sym = tr['symbol']
        amt = tr['amount_usdt']
        bx = self.em.exchanges.get(tr['buy_exchange'])
        sx = self.em.exchanges.get(tr['sell_exchange'])

        if not bx or not sx:
            raise ValueError("Биржа не подключена")

        bp = tr['opportunity']['buy_price']
        qty = amt / bp if bp > 0 else 0
        if qty <= 0:
            raise ValueError("Неверный расчёт количества")

        tr['buy_order'] = await bx.create_market_buy_order(sym, qty)
        tr['sell_order'] = await sx.create_market_sell_order(sym, qty)
        tr['status'] = 'completed'
        return {'success': True, 'trade': tr}

    async def cancel(self, tid):
        if tid in self.pending:
            tr = self.pending[tid]
            tr['status'] = 'cancelled'

            # Для скальпинга отменяем TP-ордер если есть
            if tr.get('trade_type') in ('scalp_dip', 'scalp_pump'):
                if self.scalp_engine and tid in self.scalp_engine._positions:
                    del self.scalp_engine._positions[tid]
                if tr.get('tp_order_id') and tr.get('buy_exchange'):
                    try:
                        ex = self.em.exchanges.get(tr['buy_exchange'])
                        if ex:
                            await ex.cancel_order(tr['tp_order_id'], tr['symbol'])
                    except Exception:
                        pass
            return True
        return False