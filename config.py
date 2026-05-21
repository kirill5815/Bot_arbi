import os
import sys
from dotenv import load_dotenv

# Загружаем .env из текущей директории
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8880570485:AAFS1jsaclCy5EIkLoRYGZBTRgHHA45IbQk").strip()
AUTHORIZED_USER_ID = os.getenv("AUTHORIZED_USER_ID", "5452533555").strip()

# Валидация токена
if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "123456789:ABCdefGHIjklMNOpqrSTUvwxyz1234567890":
    print("❌ ОШИБКА: TELEGRAM_BOT_TOKEN не задан или используется placeholder!")
    print("   1. Получите токен у @BotFather в Telegram")
    print("   2. Замените значение в файле .env")
    print("   3. Перезапустите бота")
    sys.exit(1)

try:
    AUTHORIZED_USER_ID = int(AUTHORIZED_USER_ID)
except ValueError:
    print("❌ ОШИБКА: AUTHORIZED_USER_ID должен быть числом (ваш Telegram ID)")
    sys.exit(1)

# Поддерживаемые биржи (через CCXT)
SUPPORTED_EXCHANGES = [
    'binance', 'bybit', 'okx', 'kraken', 'kucoin', 
    'gateio', 'mexc', 'htx', 'bitget'
]

# Минимальный спред для уведомления (в процентах)
MIN_SPREAD_PERCENT = 0.5

# Торговые пары для мониторинга
TRADING_PAIRS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']