from typing import Dict
class TradeExecutor:
    def __init__(self, em): self.em = em; self.pending = {}; self.cnt = 0
    async def prepare(self, op, amount_usdt):
        self.cnt += 1; tid = f"TRADE_{self.cnt}"
        self.pending[tid] = {
            'id': tid, 'symbol': op.get('symbol', op.get('path', 'unknown')),
            'buy_exchange': op.get('buy_exchange', op.get('exchange', 'unknown')),
            'sell_exchange': op.get('sell_exchange', op.get('exchange', 'unknown')),
            'amount_usdt': amount_usdt,
            'expected_profit': op.get('net_profit_usd', op.get('profit_usdt', 0)),
            'status': 'pending', 'opportunity': op,
            'trade_type': op.get('type', 'spot')
        }
        return tid
    async def execute(self, tid) -> Dict:
        if tid not in self.pending: return {'success': False, 'error': 'Сделка не найдена'}
        tr = self.pending[tid]; tr['status'] = 'executing'
        try:
            ttype = tr['trade_type']
            if ttype == 'triangular':
                ex = self.em.exchanges.get(tr['buy_exchange'])
                if not ex: raise ValueError("Биржа не подключена")
                op = tr['opportunity']
                btc_qty = tr['amount_usdt'] / op['details']['price1']
                o1 = await ex.create_market_buy_order(op['step1'], btc_qty)
                eth_qty = btc_qty / op['details']['price2']
                o2 = await ex.create_market_buy_order(op['step2'], eth_qty)
                o3 = await ex.create_market_sell_order(op['step3'], eth_qty)
                tr['orders'] = [o1, o2, o3]; tr['status'] = 'completed'
                return {'success': True, 'trade': tr}
            elif ttype == 'futures_basis':
                ex = self.em.exchanges.get(tr['buy_exchange'])
                if not ex: raise ValueError("Биржа не подключена")
                op = tr['opportunity']
                qty = tr['amount_usdt'] / op['details']['spot_price']
                if op['strategy'] == 'sell_futures_buy_spot':
                    o1 = await ex.create_market_buy_order(op['spot_pair'], qty)
                    o2 = await ex.create_market_sell_order(op['futures_pair'], qty)
                else:
                    o1 = await ex.create_market_sell_order(op['spot_pair'], qty)
                    o2 = await ex.create_market_buy_order(op['futures_pair'], qty)
                tr['orders'] = [o1, o2]; tr['status'] = 'completed'
                return {'success': True, 'trade': tr}
            else:
                sym = tr['symbol']; amt = tr['amount_usdt']
                bx = self.em.exchanges.get(tr['buy_exchange']); sx = self.em.exchanges.get(tr['sell_exchange'])
                if not bx or not sx: raise ValueError("Биржа не подключена")
                bp = tr['opportunity']['buy_price']; qty = amt / bp if bp > 0 else 0
                if qty <= 0: raise ValueError("Неверный расчет")
                tr['buy_order'] = await bx.create_market_buy_order(sym, qty)
                tr['sell_order'] = await sx.create_market_sell_order(sym, qty)
                tr['status'] = 'completed'
                return {'success': True, 'trade': tr}
        except Exception as e:
            tr['status'] = 'failed'; tr['error'] = str(e)
            return {'success': False, 'error': str(e), 'trade': tr}
    async def cancel(self, tid):
        if tid in self.pending: self.pending[tid]['status'] = 'cancelled'; return True
        return False