import ccxt.async_support as ccxt
import asyncio
from typing import Dict, Optional
from config import SUPPORTED_EXCHANGES

class ExchangeManager:
    def __init__(self):
        self.exchanges: Dict[str, ccxt.Exchange] = {}
        self.api_credentials: Dict[str, dict] = {}
    
    def add_exchange(self, exchange_id: str, api_key: str, api_secret: str, 
                     password: Optional[str] = None):
        """Добавление API биржи"""
        if exchange_id not in SUPPORTED_EXCHANGES:
            raise ValueError(f"Биржа {exchange_id} не поддерживается")
        
        self.api_credentials[exchange_id] = {
            'apiKey': api_key,
            'secret': api_secret,
            'password': password
        }
    
    async def connect(self, exchange_id: str):
        """Подключение к бирже"""
        if exchange_id not in self.api_credentials:
            raise ValueError(f"API для {exchange_id} не настроен")
        
        exchange_class = getattr(ccxt, exchange_id)
        exchange = exchange_class({
            'apiKey': self.api_credentials[exchange_id]['apiKey'],
            'secret': self.api_credentials[exchange_id]['secret'],
            'password': self.api_credentials[exchange_id].get('password'),
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'}
        })
        
        await exchange.load_markets()
        self.exchanges[exchange_id] = exchange
        return exchange
    
    async def get_ticker(self, exchange_id: str, symbol: str):
        """Получение цены"""
        if exchange_id not in self.exchanges:
            await self.connect(exchange_id)
        return await self.exchanges[exchange_id].fetch_ticker(symbol)
    
    async def get_balance(self, exchange_id: str):
        """Получение баланса"""
        if exchange_id not in self.exchanges:
            await self.connect(exchange_id)
        return await self.exchanges[exchange_id].fetch_balance()
    
    async def close_all(self):
        """Закрытие всех соединений"""
        for exchange in self.exchanges.values():
            await exchange.close()