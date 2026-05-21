#!/usr/bin/env python3
import logging
import sys
import os

# Добавляем директорию скрипта в путь для импортов
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, MessageHandler, filters
)

from config import TELEGRAM_BOT_TOKEN, AUTHORIZED_USER_ID, SUPPORTED_EXCHANGES
from exchange_manager import ExchangeManager
from arbitrage_engine import ArbitrageEngine
from trade_executor import TradeExecutor
from database import Database

# Состояния для ConversationHandler
ADDING_API = 1

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Глобальные объекты
exchange_manager = ExchangeManager()
arbitrage_engine = ArbitrageEngine(exchange_manager)
trade_executor = TradeExecutor(exchange_manager)
db = Database()

def check_auth(func):
    """Декоратор для проверки авторизации"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id != AUTHORIZED_USER_ID:
            if update.message:
                await update.message.reply_text("⛔ Доступ запрещен.")
            elif update.callback_query:
                await update.callback_query.answer("⛔ Доступ запрещен.", show_alert=True)
            return
        return await func(update, context)
    return wrapper

@check_auth
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Стартовое меню"""
    keyboard = [
        [InlineKeyboardButton("📊 Добавить API биржи", callback_data='add_api')],
        [InlineKeyboardButton("🔍 Сканировать рынок", callback_data='scan')],
        [InlineKeyboardButton("💼 История сделок", callback_data='history')],
        [InlineKeyboardButton("💰 Баланс", callback_data='balance')],
        [InlineKeyboardButton("📖 Помощь", callback_data='help')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🤖 *Arbitrage Bot*"
        "Бот для межбиржевого арбитража."
        "Все сделки требуют вашего подтверждения."
        f"Авторизованный ID: `{AUTHORIZED_USER_ID}`",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def add_api_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало добавления API"""
    query = update.callback_query
    await query.answer()

    exchanges_text = "\n".join([f"• `{ex}`" for ex in SUPPORTED_EXCHANGES])

    await query.edit_message_text(
        f"📊 *Добавление API биржи*\n\n"
        f"Отправьте данные в формате:\n"
        f"`биржа api_key api_secret [password]`\n\n"
        f"Доступные биржи:\n{exchanges_text}\n\n"
        f"Пример:\n`binance xxxxxxx yyyyyyy`\n\n"
        f"Для отмены: /cancel",
        parse_mode='Markdown'
    )
    return ADDING_API

async def save_api(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение API ключей"""
    try:
        parts = update.message.text.split()
        if len(parts) < 3:
            raise ValueError("Недостаточно данных. Нужно: биржа api_key api_secret")

        exchange_id = parts[0].lower()
        api_key = parts[1]
        api_secret = parts[2]
        password = parts[3] if len(parts) > 3 else None

        exchange_manager.add_exchange(exchange_id, api_key, api_secret, password)
        await exchange_manager.connect(exchange_id)

        await update.message.reply_text(
            f"✅ API для `{exchange_id}` успешно добавлен и подключен!\n\n"
            f"Теперь можно сканировать рынок.",
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: `{e}`", parse_mode='Markdown')

    return ConversationHandler.END

async def cancel_add_api(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена добавления API"""
    await update.message.reply_text("❌ Добавление API отменено.")
    return ConversationHandler.END

@check_auth
async def scan_market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручное сканирование рынка"""
    query = update.callback_query
    await query.answer()

    exchanges = list(exchange_manager.exchanges.keys())
    if len(exchanges) < 2:
        await query.edit_message_text(
            "⚠️ *Недостаточно бирж*\n\n"
            "Добавьте API минимум 2 бирж через меню.",
            parse_mode='Markdown'
        )
        return

    await query.edit_message_text("🔍 Сканирую рынок... Это может занять несколько секунд.")

    try:
        opportunities = await arbitrage_engine.scan_opportunities()
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка сканирования: `{e}`", parse_mode='Markdown')
        return

    if not opportunities:
        keyboard = [[InlineKeyboardButton("🔁 Обновить", callback_data='scan')],
                    [InlineKeyboardButton("🔙 Меню", callback_data='menu')]]
        await query.edit_message_text(
            "😕 Арбитражных возможностей не найдено.\n"
            "Попробуйте позже или проверьте настройки.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    text = "📈 *Найдены возможности:*\n\n"
    keyboard = []

    for i, op in enumerate(opportunities[:5]):
        text += (
            f"*{i+1}. {op['symbol']}*\n"
            f"Покупка: `{op['buy_exchange']}` по `{op['buy_price']:.4f}`\n"
            f"Продажа: `{op['sell_exchange']}` по `{op['sell_price']:.4f}`\n"
            f"Спред: `{op['spread_percent']:.2f}%` | Чистая прибыль: `{op['profit_percent']:.3f}%`\n\n"
        )
        keyboard.append([InlineKeyboardButton(
            f"💸 Сделка #{i+1} ({op['symbol']})", 
            callback_data=f"trade_{i}"
        )])

    keyboard.append([InlineKeyboardButton("🔁 Обновить", callback_data='scan')])
    keyboard.append([InlineKeyboardButton("🔙 Меню", callback_data='menu')])

    await query.edit_message_text(
        text, 
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

    context.user_data['opportunities'] = opportunities

async def handle_trade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора сделки"""
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
    trade_id = await trade_executor.prepare_trade(op, amount_usdt=100)

    text = (
        f"⚠️ *Подтвердите сделку*\n\n"
        f"Пара: `{op['symbol']}`\n"
        f"Купить на: `{op['buy_exchange']}`\n"
        f"Продать на: `{op['sell_exchange']}`\n"
        f"Сумма: `100 USDT`\n"
        f"Ожидаемая прибыль: `{op.get('net_profit_usd', 0):.4f} USDT`\n\n"
        f"⚡ Бот сам купит и продаст после вашего подтверждения."
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
    """Подтверждение и исполнение"""
    query = update.callback_query
    await query.answer()

    trade_id = query.data.replace("confirm_", "")

    await query.edit_message_text("⏳ Исполняю сделку...")

    result = await trade_executor.execute_trade(trade_id)

    if result['success']:
        trade = result['trade']

        # Сохраняем в БД
        try:
            await db.save_trade(
                trade_id=trade['id'],
                symbol=trade['symbol'],
                buy_ex=trade['buy_exchange'],
                sell_ex=trade['sell_exchange'],
                amount=trade['amount_usdt'],
                profit=trade.get('expected_profit', 0),
                status='completed'
            )
        except Exception as e:
            logger.error(f"DB save error: {e}")

        text = (
            f"✅ *Сделка выполнена!*\n\n"
            f"ID: `{trade['id']}`\n"
            f"Пара: `{trade['symbol']}`\n"
            f"Статус: `{trade['status']}`\n\n"
            f"📊 Ордера:\n"
            f"Buy: `{trade['buy_order'].get('id', 'N/A')}`\n"
            f"Sell: `{trade['sell_order'].get('id', 'N/A')}`"
        )
    else:
        text = f"❌ *Ошибка исполнения:*\n`{result.get('error', 'Unknown error')}`"

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

    keyboard = [[InlineKeyboardButton("🔙 Меню", callback_data='menu')]]
    await query.edit_message_text(
        "❌ Сделка отменена.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ балансов"""
    query = update.callback_query
    await query.answer()

    exchanges = list(exchange_manager.exchanges.keys())
    if not exchanges:
        await query.edit_message_text(
            "⚠️ Биржи не подключены. Добавьте API через меню.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Меню", callback_data='menu')]])
        )
        return

    text = "💰 *Балансы:*\n\n"

    for ex_id in exchanges:
        try:
            balance = await exchange_manager.get_balance(ex_id)
            usdt_free = balance.get('USDT', {}).get('free', 0)
            usdt_used = balance.get('USDT', {}).get('used', 0)
            usdt_total = balance.get('USDT', {}).get('total', 0)
            text += (
                f"*{ex_id}:*\n"
                f"  Доступно: `{usdt_free:.2f}` USDT\n"
                f"  В ордерах: `{usdt_used:.2f}` USDT\n"
                f"  Всего: `{usdt_total:.2f}` USDT\n\n"
            )
        except Exception as e:
            text += f"*{ex_id}:* Ошибка загрузки (`{e}`)\n\n"

    keyboard = [[InlineKeyboardButton("🔙 Меню", callback_data='menu')]]
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """История сделок"""
    query = update.callback_query
    await query.answer()

    try:
        stats = await db.get_stats()
        text = (
            f"💼 *История сделок*\n\n"
            f"Всего выполнено: `{stats['total_trades']}`\n"
            f"Общая прибыль: `{stats['total_profit']:.4f}` USDT\n"
            f"Средняя прибыль: `{stats['avg_profit']:.4f}` USDT"
        )
    except Exception as e:
        text = f"⚠️ База данных еще не инициализирована или ошибка: `{e}`"

    keyboard = [[InlineKeyboardButton("🔙 Меню", callback_data='menu')]]
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Помощь"""
    query = update.callback_query
    await query.answer()

    text = (
        "📖 *Инструкция*\n\n"
        "1. *Добавьте API* хотя бы 2 бирж\n"
        "2. *Сканируйте рынок* — бот найдет спреды\n"
        "3. *Выберите сделку* и подтвердите\n"
        "4. Бот *сам купит* на бирже A и *сам продаст* на бирже B\n\n"
        "⚠️ *Важно:*\n"
        "• Все сделки требуют ручного подтверждения\n"
        "• Проверяйте комиссии и ликвидность\n"
        "• Начинайте с маленьких сумм\n"
        "• API-ключи хранятся только в памяти процесса"
    )

    keyboard = [[InlineKeyboardButton("🔙 Меню", callback_data='menu')]]
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в меню"""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("📊 Добавить API биржи", callback_data='add_api')],
        [InlineKeyboardButton("🔍 Сканировать рынок", callback_data='scan')],
        [InlineKeyboardButton("💼 История сделок", callback_data='history')],
        [InlineKeyboardButton("💰 Баланс", callback_data='balance')],
        [InlineKeyboardButton("📖 Помощь", callback_data='help')],
    ]
    await query.edit_message_text(
        "🤖 *Arbitrage Bot — Главное меню*\n\n"
        f"Подключено бирж: `{len(exchange_manager.exchanges)}`",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def auto_notify(context: ContextTypes.DEFAULT_TYPE):
    """Фоновые уведомления"""
    try:
        opportunities = await arbitrage_engine.scan_opportunities()
        good_opps = [op for op in opportunities if op.get('profit_percent', 0) > 1.0]

        if good_opps:
            text = "🚨 *Высокоприбыльный арбитраж найден!*\n\n"
            for op in good_opps[:3]:
                text += (
                    f"• `{op['symbol']}`: `{op['profit_percent']:.2f}%` "
                    f"({op['buy_exchange']} → {op['sell_exchange']})\n"
                )
            text += "\nИспользуйте /start для подробностей."

            await context.bot.send_message(
                chat_id=AUTHORIZED_USER_ID,
                text=text,
                parse_mode='Markdown'
            )
    except Exception as e:
        logger.error(f"Auto notify error: {e}")

async def post_init(application: Application):
    """Инициализация при старте"""
    await db.init()
    logger.info("База данных инициализирована")

async def post_stop(application: Application):
    """Очистка при остановке"""
    await exchange_manager.close_all()
    logger.info("Соединения с биржами закрыты")

def main():
    # Проверка токена уже выполнена в config.py, но дублируем для ясности
    if not TELEGRAM_BOT_TOKEN or ":" not in TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не задан или неверен!")
        sys.exit(1)

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_stop(post_stop)
        .build()
    )

    # Conversation для добавления API
    api_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_api_callback, pattern='^add_api$')],
        states={
            ADDING_API: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_api)]
        },
        fallbacks=[CommandHandler('cancel', cancel_add_api)]
    )

    # Хендлеры
    application.add_handler(CommandHandler('start', start))
    application.add_handler(api_conv)
    application.add_handler(CallbackQueryHandler(scan_market, pattern='^scan$'))
    application.add_handler(CallbackQueryHandler(handle_trade_callback, pattern='^trade_'))
    application.add_handler(CallbackQueryHandler(confirm_trade, pattern='^confirm_'))
    application.add_handler(CallbackQueryHandler(cancel_trade_callback, pattern='^cancel_'))
    application.add_handler(CallbackQueryHandler(show_balance, pattern='^balance$'))
    application.add_handler(CallbackQueryHandler(show_history, pattern='^history$'))
    application.add_handler(CallbackQueryHandler(show_help, pattern='^help$'))
    application.add_handler(CallbackQueryHandler(back_to_menu, pattern='^menu$'))

    # Фоновый мониторинг (каждые 60 секунд)
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(auto_notify, interval=60, first=10)

    logger.info("Бот запущен. Ожидание сообщений...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()