"""Спотовый скальпинг — сигналы на отскоке/импульсе + авто TP/SL."""
import asyncio
import logging
import time
from typing import List, Dict, Optional
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

class ScalpingEngine:
    def __init__(self, exchange_manager, history_seconds: int = 60,
                 dip_threshold: float = 0.015, pump_threshold: float = 0.02,
                 tp_percent: float = 0.01, sl_percent: float = 0.015,
                 min_volume_24h: float = 500000):
        self.em = exchange_manager
        self.history_seconds = history_seconds
        self.dip_threshold = dip_threshold      # −1.5%
        self.pump_threshold = pump_threshold    # +2.0%
        self.tp_percent = tp_percent            # +1.0%
        self.sl_percent = sl_percent            # −1.5%
        self.min_volume_24h = min_volume_24h

        # История цен: {exchange: {symbol: deque[(timestamp, price)]}}
        self.price_history = defaultdict(lambda: defaultdict(lambda: deque(maxlen=500)))
        self._monitoring = False
        self._positions = {}  # {trade_id: {'symbol': ..., 'exchange': ..., 'tp_price': ..., 'sl_price': ..., 'qty': ..., 'tp_order_id': ...}}

    def get_scalp_pairs(self, exchange_id: str) -> List[str]:
        """Возвращает ликвидные пары для скальпинга."""
        ex = self.em.exchanges.get(exchange_id)
        if not ex:
            return []
        pairs = []
        for sym, market in ex.markets.items():
            if ':' in sym or not sym.endswith('/USDT'):
                continue
            # Только основные активы, без экзотики
            base = sym.split('/')[0]
            if base in {'BTC', 'ETH', 'SOL', 'BNB', 'ADA', 'AVAX', 'DOT', 'LINK',
                        'TRX', 'DOGE', 'XRP', 'SUI', 'APT', 'INJ', 'FET', 'RENDER',
                        'OP', 'ARB', 'WLD'}:
                pairs.append(sym)
        return pairs

    async def update_history(self, exchange_id: str):
        """Обновляет историю цен для всех скальпинг-пар."""
        pairs = self.get_scalp_pairs(exchange_id)
        if not pairs:
            return
        tickers = await self.em.fetch_tickers_batch(exchange_id, pairs)
        now = time.time()
        for sym, tick in tickers.items():
            price = tick.get('last', 0)
            vol = tick.get('quoteVolume', 0) or 0
            if price > 0 and vol >= self.min_volume_24h:
                self.price_history[exchange_id][sym].append((now, price))

    def calc_change(self, exchange_id: str, symbol: str) -> Optional[Dict]:
        """Считает изменение цены за history_seconds."""
        hist = self.price_history[exchange_id].get(symbol)
        if not hist or len(hist) < 2:
            return None
        now = time.time()
        cutoff = now - self.history_seconds
        # Находим цену cutoff секунд назад
        old_price = None
        for ts, price in hist:
            if ts >= cutoff:
                old_price = price
                break
        if not old_price:
            return None
        latest = hist[-1][1]
        change = (latest - old_price) / old_price
        return {
            'symbol': symbol,
            'exchange': exchange_id,
            'old_price': old_price,
            'price': latest,
            'change_percent': change * 100,
            'volume_24h': 0  # заполняется позже
        }

    async def scan_scalp(self, exchange_id: str) -> List[Dict]:
        """Ищет сигналы DIP-BUY и PUMP-LONG."""
        await self.update_history(exchange_id)
        signals = []
        pairs = self.get_scalp_pairs(exchange_id)
        tickers = await self.em.fetch_tickers_batch(exchange_id, pairs)

        for sym in pairs:
            calc = self.calc_change(exchange_id, sym)
            if not calc:
                continue
            tick = tickers.get(sym)
            if not tick:
                continue
            vol = tick.get('quoteVolume', 0) or 0
            if vol < self.min_volume_24h:
                continue
            calc['volume_24h'] = vol
            change = calc['change_percent']

            if change <= -self.dip_threshold * 100:
                # DIP-BUY: упало резко, ждём отскока
                tp_price = calc['price'] * (1 + self.tp_percent)
                sl_price = calc['price'] * (1 - self.sl_percent)
                signals.append({
                    'type': 'scalp_dip',
                    'exchange': exchange_id,
                    'symbol': sym,
                    'strategy': 'buy_dip',
                    'change_percent': round(change, 2),
                    'entry_price': calc['price'],
                    'tp_price': round(tp_price, 8),
                    'sl_price': round(sl_price, 8),
                    'tp_percent': self.tp_percent * 100,
                    'sl_percent': self.sl_percent * 100,
                    'volume_24h': vol,
                    'details': calc
                })
            elif change >= self.pump_threshold * 100:
                # PUMP-LONG: растёт сильно, вход в импульс
                tp_price = calc['price'] * (1 + self.tp_percent)
                sl_price = calc['price'] * (1 - self.sl_percent)
                signals.append({
                    'type': 'scalp_pump',
                    'exchange': exchange_id,
                    'symbol': sym,
                    'strategy': 'buy_pump',
                    'change_percent': round(change, 2),
                    'entry_price': calc['price'],
                    'tp_price': round(tp_price, 8),
                    'sl_price': round(sl_price, 8),
                    'tp_percent': self.tp_percent * 100,
                    'sl_percent': self.sl_percent * 100,
                    'volume_24h': vol,
                    'details': calc
                })

        signals.sort(key=lambda x: abs(x['change_percent']), reverse=True)
        return signals

    async def scan_all_exchanges(self) -> List[Dict]:
        """Сканирует скальпинг на всех биржах."""
        if not self.em.exchanges:
            return []
        tasks = [self.scan_scalp(eid) for eid in self.em.exchanges]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_sig = []
        for res in results:
            if isinstance(res, list):
                all_sig.extend(res)
        all_sig.sort(key=lambda x: abs(x['change_percent']), reverse=True)
        return all_sig

    async def open_position(self, exchange_id: str, symbol: str, amount_usdt: float) -> Dict:
        """Открывает позицию: market buy + лимитный TP sell."""
        ex = self.em.exchanges.get(exchange_id)
        if not ex:
            return {'success': False, 'error': 'Биржа не подключена'}

        try:
            ticker = await self.em.get_ticker(exchange_id, symbol)
            entry_price = ticker.get('ask', ticker.get('last', 0))
            if entry_price <= 0:
                return {'success': False, 'error': 'Неверная цена входа'}

            qty = amount_usdt / entry_price
            # Market buy
            buy_order = await ex.create_market_buy_order(symbol, qty)

            # Расчёт TP/SL
            tp_price = entry_price * (1 + self.tp_percent)
            sl_price = entry_price * (1 - self.sl_percent)

            # Limit sell (TP)
            tp_order = await ex.create_limit_sell_order(symbol, qty, tp_price)

            position = {
                'success': True,
                'exchange': exchange_id,
                'symbol': symbol,
                'entry_price': entry_price,
                'qty': qty,
                'amount_usdt': amount_usdt,
                'tp_price': tp_price,
                'sl_price': sl_price,
                'tp_order_id': tp_order.get('id'),
                'buy_order_id': buy_order.get('id'),
                'status': 'open'
            }
            return position
        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def monitor_positions(self):
        """Фоновый мониторинг открытых позиций. Проверяет TP/SL."""
        self._monitoring = True
        while self._monitoring:
            try:
                to_remove = []
                for tid, pos in list(self._positions.items()):
                    if pos.get('status') != 'open':
                        continue
                    ex = self.em.exchanges.get(pos['exchange'])
                    if not ex:
                        continue
                    try:
                        ticker = await self.em.get_ticker(pos['exchange'], pos['symbol'])
                        current = ticker.get('last', 0)
                        if current <= 0:
                            continue

                        # Проверка TP — лимитный ордер исполнился?
                        if pos.get('tp_order_id'):
                            try:
                                order = await ex.fetch_order(pos['tp_order_id'], pos['symbol'])
                                if order.get('status') in ('closed', 'filled'):
                                    pos['status'] = 'tp_hit'
                                    pos['exit_price'] = pos['tp_price']
                                    pos['profit'] = (pos['tp_price'] - pos['entry_price']) * pos['qty']
                                    to_remove.append(tid)
                                    logger.info(f"TP исполнен: {pos['symbol']} @ {pos['tp_price']}")
                                    continue
                            except Exception:
                                pass

                        # Проверка SL
                        if current <= pos['sl_price']:
                            # Отменяем TP-ордер
                            if pos.get('tp_order_id'):
                                try:
                                    await ex.cancel_order(pos['tp_order_id'], pos['symbol'])
                                except Exception:
                                    pass
                            # Market sell
                            sell_order = await ex.create_market_sell_order(pos['symbol'], pos['qty'])
                            pos['status'] = 'sl_hit'
                            pos['exit_price'] = current
                            pos['profit'] = (current - pos['entry_price']) * pos['qty']
                            to_remove.append(tid)
                            logger.info(f"SL сработан: {pos['symbol']} @ {current}")
                    except Exception as e:
                        logger.error(f"Monitor error {tid}: {e}")

                for tid in to_remove:
                    if tid in self._positions:
                        del self._positions[tid]

                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
                await asyncio.sleep(10)

    def start_monitor(self):
        """Запускает фоновый мониторинг."""
        if not self._monitoring:
            asyncio.create_task(self.monitor_positions())

    def stop_monitor(self):
        self._monitoring = False