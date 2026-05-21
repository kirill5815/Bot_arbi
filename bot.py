import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, MessageHandler, filters
)
from config import TELEGRAM_BOT_TOKEN, AUTHORIZED_USER_ID, SUPPORTED_EXCHANGES
from exchange_manager import ExchangeManager
from arbitrage_engine import ArbitrageEngine
from trade_executor import TradeExecutor

# Состояния для ConversationHandler
ADDING_API = range(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Глобальные объекты
exchange_manager = ExchangeManager()
arbitrage_engine = ArbitrageEngine(exchange_manager)
trade_executor = TradeExecutor(exchange_manager)

def check_auth(func):
    """Декоратор для проверки авторизации"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id != AUTHORIZED_USER_ID:
            await update.message.reply_text("⛔ Доступ запрещен.")
            return
        return await func(update, context)
    return wrapper

@check_auth
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Стартовое меню"""
    keyboard = [
        [InlineKeyboardButton("📊 Добавить API биржи", callback_data='add_api')],
        [InlineKeyboardButton("🔍 Сканировать рынок", callback_data='scan')],
        [InlineKeyboardButton("💼 Мои сделки", callback_data='trades')],
        [InlineKeyboardButton("💰 Баланс", callback_data='balance')],
        [InlineKeyboardButton("⚙️ Настройки", callback_data='settings')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🤖 *Arbitrage Bot*\n\n"
        "Бот для межбиржевого арбитража.\n"
        "Все сделки требуют вашего подтверждения.",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def add_api_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало добавления API"""
    query = update.callback_query
    await query.answer()
    
    # Формируем список бирж
    exchanges_text = "\n".join([f"• {ex}" for ex in SUPPORTED_EXCHANGES])
    
    await query.edit_message_text(
        f"Выберите биржу и отправьте данные в формате:\n\n"
        f"`биржа api_key api_secret [password]`\n\n"
        f"Доступные биржи:\n{exchanges_text}\n\n"
        f"Пример:\n`binance xxxxxxx yyyyyyy`",
        parse_mode='Markdown'
    )
    return ADDING_API

async def save_api(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение API ключей"""
    try:
        parts = update.message.text.split()
        if len(parts) < 3:
            raise ValueError("Недостаточно данных")
        
        exchange_id = parts[0].lower()
        api_key = parts[1]
        api_secret = parts[2]
        password = parts[3] if len(parts) > 3 else None
        
        exchange_manager.add_exchange(exchange_id, api_key, api_secret, password)
        await exchange_manager.connect(exchange_id)
        
        await update.message.reply_text(
            f"✅ API для `{exchange_id}` успешно добавлен и подключен!",
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
    
    return ConversationHandler.END

@check_auth
async def scan_market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручное сканирование рынка"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text("🔍 Сканирую рынок...")
    
    opportunities = await arbitrage_engine.scan_opportunities()
    
    if not opportunities:
        await query.edit_message_text(
            "😕 Арбитражных возможностей не найдено.\n"
            "Попробуйте позже или проверьте настройки."
        )
        return
    
    # Показываем топ-5 возможностей
    text = "📈 *Найдены возможности:*\n\n"
    keyboard = []
    
    for i, op in enumerate(opportunities[:5]):
        text += (
            f"*{i+1}. {op['symbol']}*\n"
            f"Покупка: `{op['buy_exchange']}` по {op['buy_price']:.2f}\n"
            f"Продажа: `{op['sell_exchange']}` по {op['sell_price']:.2f}\n"
            f"Спред: `{op['spread_percent']:.2f}%`\n"
            f"Чистая прибыль: `{op['profit_percent']:.3f}%`\n\n"
        )
        keyboard.append([InlineKeyboardButton(
            f"💸 Сделка #{i+1} ({op['symbol']})", 
            callback_data=f"trade_{i}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔁 Обновить", callback_data='scan')])
    
    await query.edit_message_text(
        text, 
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    
    # Сохраняем в контекст для обработки колбэков
    context.user_data['opportunities'] = opportunities

async def handle_trade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора сделки пользователем"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if not data.startswith('trade_'):
        return
    
    idx = int(data.split('_')[1])
    opportunities = context.user_data.get('opportunities', [])
    
    if idx >= len(opportunities):
        await query.edit_message_text("❌ Возможность устарела.")
        return
    
    op = opportunities[idx]
    
    # Подготавливаем сделку
    trade_id = await trade_executor.prepare_trade(op, amount_usdt=100)
    
    text = (
        f"⚠️ *Подтвердите сделку*\n\n"
        f"Пара: `{op['symbol']}`\n"
        f"Купить на: `{op['buy_exchange']}`\n"
        f"Продать на: `{op['sell_exchange']}`\n"
        f"Ожидаемая прибыль: `{op['net_profit_usd']:.4f} USDT`\n\n"
        f"Подтвердите для исполнения:"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_{trade_id}"),
            InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_{trade_id}")
        ]
    ]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def confirm_trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение и исполнение сделки"""
    query = update.callback_query
    await query.answer()
    
    trade_id = query.data.replace("confirm_", "")
    
    await query.edit_message_text("⏳ Исполняю сделку...")
    
    result = await trade_executor.execute_trade(trade_id)
    
    if result['success']:
        trade = result['trade']
        text = (
            f"✅ *Сделка выполнена!*\n\n"
            f"ID: `{trade['id']}`\n"
            f"Пара: `{trade['symbol']}`\n"
            f"Статус: {trade['status']}\n\n"
            f"📊 Детали:\n"
            f"Buy order: `{trade['buy_order']['id']}`\n"
            f"Sell order: `{trade['sell_order']['id']}`"
        )
    else:
        text = f"❌ *Ошибка исполнения:*\n`{result['error']}`"
    
    keyboard = [[InlineKeyboardButton("🔙 Меню", callback_data='menu')]]
    await query.edit_message_text(
        text, 
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def cancel_trade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена сделки"""
    query = update.callback_query
    await query.answer()
    
    trade_id = query.data.replace("cancel_", "")
    await trade_executor.cancel_trade(trade_id)
    
    await query.edit_message_text("❌ Сделка отменена.")

async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ балансов"""
    query = update.callback_query
    await query.answer()
    
    text = "💰 *Балансы:*\n\n"
    
    for ex_id in exchange_manager.exchanges:
        try:
            balance = await exchange_manager.get_balance(ex_id)
            usdt = balance.get('USDT', {}).get('free', 0)
            text += f"*{ex_id}:* `{usdt:.2f}` USDT\n"
        except Exception as e:
            text += f"*{ex_id}:* Ошибка загрузки\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Меню", callback_data='menu')]]
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def auto_notify(context: ContextTypes.DEFAULT_TYPE):
    """Фоновые уведомления о возможностях"""
    opportunities = await arbitrage_engine.scan_opportunities()
    
    good_opps = [op for op in opportunities if op['profit_percent'] > 1.0]
    
    if good_opps:
        text = "🚨 *Высокоприбыльный арбитраж найден!*\n\n"
        for op in good_opps[:3]:
            text += (
                f"• `{op['symbol']}`: {op['profit_percent']:.2f}% "
                f"({op['buy_exchange']} → {op['sell_exchange']})\n"
            )
        text += "\nИспользуйте /scan для подробностей."
        
        await context.bot.send_message(
            chat_id=AUTHORIZED_USER_ID,
            text=text,
            parse_mode='Markdown'
        )

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в меню"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📊 Добавить API биржи", callback_data='add_api')],
        [InlineKeyboardButton("🔍 Сканировать рынок", callback_data='scan')],
        [InlineKeyboardButton("💼 Мои сделки", callback_data='trades')],
        [InlineKeyboardButton("💰 Баланс", callback_data='balance')],
    ]
    await query.edit_message_text(
        "🤖 *Arbitrage Bot - Главное меню*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Conversation для добавления API
    api_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_api_callback, pattern='^add_api$')],
        states={
            ADDING_API: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_api)]
        },
        fallbacks=[CommandHandler('cancel', lambda u, c: u.message.reply_text("Отменено"))]
    )
    
    # Хендлеры
    application.add_handler(CommandHandler('start', start))
    application.add_handler(api_conv)
    application.add_handler(CallbackQueryHandler(scan_market, pattern='^scan$'))
    application.add_handler(CallbackQueryHandler(handle_trade_callback, pattern='^trade_'))
    application.add_handler(CallbackQueryHandler(confirm_trade, pattern='^confirm_'))
    application.add_handler(CallbackQueryHandler(cancel_trade_callback, pattern='^cancel_'))
    application.add_handler(CallbackQueryHandler(show_balance, pattern='^balance$'))
    application.add_handler(CallbackQueryHandler(back_to_menu, pattern='^menu$'))
    
    # Фоновый мониторинг (каждые 60 секунд)
    job_queue = application.job_queue
    job_queue.run_repeating(auto_notify, interval=60, first=10)
    
    application.run_polling()

if __name__ == '__main__':
    main()