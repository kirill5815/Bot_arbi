import asyncio
import logging
import time
from typing import Dict, Optional, List
import ccxt.async_support as ccxt
from config import SUPPORTED_EXCHANGES, CACHE_TTL_SECONDS

logger = logging.getLogger(__name__)

class ExchangeManager:
    def __init__(self):
        self.exchanges: Dict[str, ccxt.Exchange] = {}
        self.api_credentials: Dict[str, dict] = {}
        self._ticker_cache: Dict[str, dict] = {}
        self._cache_ttl = CACHE_TTL_SECONDS

    def add_exchange(self, eid, key, sec, pwd=None):
        eid = eid.lower().strip()
        if eid not in SUPPORTED_EXCHANGES:
            raise ValueError(f"Биржа '{eid}' не поддерживается. Доступные: {', '.join(SUPPORTED_EXCHANGES)}")
        self.api_credentials[eid] = {
            'apiKey': key.strip(),
            'secret': sec.strip(),
            'password': pwd.strip() if pwd else None
        }

    async def connect(self, eid, market_type='spot'):
        eid = eid.lower().strip()
        if eid not in self.api_credentials:
            raise ValueError(f"API для '{eid}' не настроен")
        cls = getattr(ccxt, eid)
        ex = cls({
            'apiKey': self.api_credentials[eid]['apiKey'],
            'secret': self.api_credentials[eid]['secret'],
            'password': self.api_credentials[eid].get('password'),
            'enableRateLimit': True,
            'options': {'defaultType': market_type}
        })
        await ex.load_markets()
        self.exchanges[eid] = ex
        logger.info(f"Подключено: {eid} ({market_type})")
        return ex

    async def get_ticker(self, eid, sym, market_type='spot'):
        eid = eid.lower().strip()
        cache_key = f"{eid}:{market_type}:{sym}"
        now = time.time()
        if cache_key in self._ticker_cache:
            if now - self._ticker_cache[cache_key]['ts'] < self._cache_ttl:
                return self._ticker_cache[cache_key]['data']
        if eid not in self.exchanges:
            await self.connect(eid, market_type)
        data = await self.exchanges[eid].fetch_ticker(sym)
        self._ticker_cache[cache_key] = {'data': data, 'ts': now}
        return data

    async def fetch_tickers_batch(self, eid: str, symbols: List[str], market_type='spot') -> Dict[str, dict]:
        """Пакетное получение тикеров. В 10-30 раз быстрее чем по одному."""
        eid = eid.lower().strip()
        if eid not in self.exchanges:
            await self.connect(eid, market_type)
        now = time.time()
        result = {}
        missing = []
        for sym in symbols:
            ck = f"{eid}:{market_type}:{sym}"
            if ck in self._ticker_cache and now - self._ticker_cache[ck]['ts'] < self._cache_ttl:
                result[sym] = self._ticker_cache[ck]['data']
            else:
                missing.append(sym)
        if not missing:
            return result
        ex = self.exchanges[eid]
        try:
            if hasattr(ex, 'fetchTickers') and len(missing) > 1:
                tickers = await ex.fetchTickers(missing)
                for sym, data in tickers.items():
                    ck = f"{eid}:{market_type}:{sym}"
                    self._ticker_cache[ck] = {'data': data, 'ts': time.time()}
                    if sym in missing:
                        result[sym] = data
            else:
                raise AttributeError("fetchTickers not available")
        except Exception as e:
            logger.debug(f"Batch fetch failed for {eid}, falling back: {e}")
            tasks = [self.get_ticker(eid, sym, market_type) for sym in missing]
            datas = await asyncio.gather(*tasks, return_exceptions=True)
            for sym, data in zip(missing, datas):
                if not isinstance(data, Exception):
                    result[sym] = data
        return result

    async def get_balance(self, eid):
        eid = eid.lower().strip()
        if eid not in self.exchanges:
            await self.connect(eid)
        return await self.exchanges[eid].fetch_balance()

    def invalidate_cache(self, eid=None):
        if eid:
            keys = [k for k in self._ticker_cache if k.startswith(f"{eid}:")]
            for k in keys:
                del self._ticker_cache[k]
        else:
            self._ticker_cache.clear()

    async def close_all(self):
        for ex in self.exchanges.values():
            try:
                await ex.close()
            except Exception:
                pass
        self.exchanges.clear()
        self._ticker_cache.clear()