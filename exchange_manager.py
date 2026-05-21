import ccxt.async_support as ccxt
from typing import Dict, Optional
from config import SUPPORTED_EXCHANGES
class ExchangeManager:
    def __init__(self):
        self.exchanges: Dict[str, ccxt.Exchange] = {}
        self.api_credentials: Dict[str, dict] = {}
    def add_exchange(self, eid, key, sec, pwd=None):
        eid = eid.lower().strip()
        if eid not in SUPPORTED_EXCHANGES:
            raise ValueError(f"Биржа '{eid}' не поддерживается. Доступные: {', '.join(SUPPORTED_EXCHANGES)}")
        self.api_credentials[eid] = {'apiKey': key.strip(), 'secret': sec.strip(), 'password': pwd.strip() if pwd else None}
    async def connect(self, eid, market_type='spot'):
        eid = eid.lower().strip()
        if eid not in self.api_credentials:
            raise ValueError(f"API для '{eid}' не настроен")
        cls = getattr(ccxt, eid)
        ex = cls({'apiKey': self.api_credentials[eid]['apiKey'], 'secret': self.api_credentials[eid]['secret'], 'password': self.api_credentials[eid].get('password'), 'enableRateLimit': True, 'options': {'defaultType': market_type}})
        await ex.load_markets(); self.exchanges[eid] = ex; return ex
    async def get_ticker(self, eid, sym, market_type='spot'):
        eid = eid.lower().strip()
        if eid not in self.exchanges: await self.connect(eid, market_type)
        return await self.exchanges[eid].fetch_ticker(sym)
    async def get_balance(self, eid):
        eid = eid.lower().strip()
        if eid not in self.exchanges: await self.connect(eid)
        return await self.exchanges[eid].fetch_balance()
    async def close_all(self):
        for ex in self.exchanges.values(): await ex.close()
        self.exchanges.clear()