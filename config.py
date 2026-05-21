import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("8880570485:AAFS1jsaclCy5EIkLoRYGZBTRgHHA45IbQk")
AUTHORIZED_USER_ID = int(os.getenv("AUTHORIZED_USER_ID", "5452533555"))

# Поддерживаемые биржи (через CCXT)
SUPPORTED_EXCHANGES = [
    'binance', 'bybit', 'okx', 'kraken', 'kucoin', 
    'gateio', 'mexc', 'htx', 'bitget'
]

# Минимальный спред для уведомления (в процентах)
MIN_SPREAD_PERCENT = 0.5

# Торговые пары для мониторинга
TRADING_PAIRS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']