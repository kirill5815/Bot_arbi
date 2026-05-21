import os
import sys
from dotenv import load_dotenv

script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, '.env')

if not os.path.exists(env_path):
    print("=" * 60)
    print("❌ ОШИБКА: Файл .env не найден!")
    print(f"   Ожидался: {env_path}")
    print("=" * 60)
    print("\nСоздайте файл .env в той же папке, где bot.py:")
    print("   TELEGRAM_BOT_TOKEN=ваш_токен_от_BotFather")
    print("   AUTHORIZED_USER_ID=ваш_telegram_id\n")
    sys.exit(1)

load_dotenv(env_path)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8880570485:AAFS1jsaclCy5EIkLoRYGZBTRgHHA45IbQk").strip()
AUTHORIZED_USER_ID_STR = os.getenv("AUTHORIZED_USER_ID", "5452533555").strip()

if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "123456789:ABCdefGHIjklMNOpqrSTUvwxyz1234567890":
    print("=" * 60)
    print("❌ ОШИБКА: TELEGRAM_BOT_TOKEN не задан или это placeholder!")
    print("=" * 60)
    print("\n1. Получите токен у @BotFather в Telegram")
    print("2. Откройте файл .env и замените строку:")
    print("   TELEGRAM_BOT_TOKEN=123456789:ABC...")
    print("   на ваш реальный токен, например:")
    print("   TELEGRAM_BOT_TOKEN=1234567890:AAH...\n")
    sys.exit(1)

if ":" not in TELEGRAM_BOT_TOKEN:
    print("❌ ОШИБКА: Неверный формат токена (должен содержать ':')")
    sys.exit(1)

try:
    AUTHORIZED_USER_ID = int(AUTHORIZED_USER_ID_STR)
except ValueError:
    print("❌ ОШИБКА: AUTHORIZED_USER_ID должен быть числом")
    sys.exit(1)

SUPPORTED_EXCHANGES = [
    'binance', 'bybit', 'okx', 'kraken', 'kucoin', 
    'gate', 'mexc', 'htx', 'bitget', 'bitmart'
]

MIN_SPREAD_PERCENT = 0.01

SPOT_PAIRS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'BNB/USDT',
    'ADA/USDT', 'AVAX/USDT', 'DOT/USDT', 'LINK/USDT', 'TRX/USDT',
    'DOGE/USDT', 'SHIB/USDT', 'PEPE/USDT', 'WIF/USDT', 'BONK/USDT',
    'SUI/USDT', 'SEI/USDT', 'TIA/USDT', 'APT/USDT', 'INJ/USDT',
    'RENDER/USDT', 'FET/USDT', 'AR/USDT', 'TAO/USDT', 'WLD/USDT',
    'STRK/USDT', 'ZRO/USDT', 'OP/USDT', 'ARB/USDT', 'USDC/USDT',
]

# Алиас для совместимости с arbitrage_engine.py
TRADING_PAIRS = SPOT_PAIRS

FUTURES_PAIRS = [
    'BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'XRP/USDT:USDT',
    'BNB/USDT:USDT', 'DOGE/USDT:USDT', 'ADA/USDT:USDT', 'AVAX/USDT:USDT',
    'LINK/USDT:USDT', 'TRX/USDT:USDT', 'DOT/USDT:USDT', 'SUI/USDT:USDT',
    'PEPE/USDT:USDT', 'WIF/USDT:USDT', 'BONK/USDT:USDT',
]

TRIANGULAR_SETS = [
    # === BTC-мост: USDT → BTC → ALT → USDT ===
    ('BTC/USDT', 'ETH/BTC', 'ETH/USDT'),
    ('BTC/USDT', 'SOL/BTC', 'SOL/USDT'),
    ('BTC/USDT', 'BNB/BTC', 'BNB/USDT'),
    ('BTC/USDT', 'ADA/BTC', 'ADA/USDT'),
    ('BTC/USDT', 'AVAX/BTC', 'AVAX/USDT'),
    ('BTC/USDT', 'DOT/BTC', 'DOT/USDT'),
    ('BTC/USDT', 'LINK/BTC', 'LINK/USDT'),
    ('BTC/USDT', 'TRX/BTC', 'TRX/USDT'),
    ('BTC/USDT', 'DOGE/BTC', 'DOGE/USDT'),
    ('BTC/USDT', 'XRP/BTC', 'XRP/USDT'),
    ('BTC/USDT', 'SHIB/BTC', 'SHIB/USDT'),
    ('BTC/USDT', 'PEPE/BTC', 'PEPE/USDT'),
    ('BTC/USDT', 'SUI/BTC', 'SUI/USDT'),
    ('BTC/USDT', 'APT/BTC', 'APT/USDT'),
    ('BTC/USDT', 'INJ/BTC', 'INJ/USDT'),
    ('BTC/USDT', 'FET/BTC', 'FET/USDT'),
    ('BTC/USDT', 'ARB/BTC', 'ARB/USDT'),
    ('BTC/USDT', 'OP/BTC', 'OP/USDT'),
    ('BTC/USDT', 'RENDER/BTC', 'RENDER/USDT'),
    ('BTC/USDT', 'WLD/BTC', 'WLD/USDT'),
    
    # === ETH-мост: USDT → ETH → ALT → USDT ===
    ('ETH/USDT', 'SOL/ETH', 'SOL/USDT'),
    ('ETH/USDT', 'BNB/ETH', 'BNB/USDT'),
    ('ETH/USDT', 'ADA/ETH', 'ADA/USDT'),
    ('ETH/USDT', 'LINK/ETH', 'LINK/USDT'),
    ('ETH/USDT', 'SHIB/ETH', 'SHIB/USDT'),
    ('ETH/USDT', 'PEPE/ETH', 'PEPE/USDT'),
    ('ETH/USDT', 'SUI/ETH', 'SUI/USDT'),
    ('ETH/USDT', 'INJ/ETH', 'INJ/USDT'),
    ('ETH/USDT', 'FET/ETH', 'FET/USDT'),
    ('ETH/USDT', 'OP/ETH', 'OP/USDT'),
    ('ETH/USDT', 'ARB/ETH', 'ARB/USDT'),
    ('ETH/USDT', 'RENDER/ETH', 'RENDER/USDT'),
    ('ETH/USDT', 'WLD/ETH', 'WLD/USDT'),
    
    # === USDC-мост: USDT → USDC → ALT → USDT ===
    ('USDT/USDC', 'BTC/USDC', 'BTC/USDT'),
    ('USDT/USDC', 'ETH/USDC', 'ETH/USDT'),
    ('USDT/USDC', 'SOL/USDC', 'SOL/USDT'),
    ('USDT/USDC', 'BNB/USDC', 'BNB/USDT'),
]

DEFAULT_TRADE_AMOUNT = 100
FUTURES_LEVERAGE = 1