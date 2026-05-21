#!/usr/bin/env python3
import logging, sys
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters
from config import TELEGRAM_BOT_TOKEN, AUTHORIZED_USER_ID, SUPPORTED_EXCHANGES, SPOT_PAIRS, FUTURES_PAIRS, TRIANGULAR_SETS, DEFAULT_TRADE_AMOUNT
from exchange_manager import ExchangeManager
from arbitrage_engine import ArbitrageEngine
from triangular_engine import TriangularEngine
from futures_engine import FuturesEngine
from trade_executor import TradeExecutor
from database import Database
from balance_manager import BalanceManager

ADDING_API = 1
ADDING_AMOUNT = 2
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

em = ExchangeManager(); ae = ArbitrageEngine(em); te = TradeExecutor(em); db = Database(); bm = BalanceManager(em)
tri = TriangularEngine(em); fut = FuturesEngine(em)

def check_auth(func):
    async def wrapper(update, context):
        if update.effective_user.id != AUTHORIZED_USER_ID:
            if update.message: await update.message.reply_text("⛔ Доступ запрещен.")
            elif update.callback_query: await update.callback_query.answer("⛔ Доступ запрещен.", show_alert=True)
            return
        return await func(update, context)
    return wrapper

@check_auth
async def start(update, context):
    kb = [
        [InlineKeyboardButton("📊 Добавить API", callback_data='add_api')],
        [InlineKeyboardButton("🔍 Спот арбитраж", callback_data='scan_spot')],
        [InlineKeyboardButton("🔺 Треугольный", callback_data='scan_tri')],
        [InlineKeyboardButton("📈 Фьючерсы", callback_data='scan_fut')],
        [InlineKeyboardButton("💰 Баланс", callback_data='balance')],
        [InlineKeyboardButton("⚖️ Балансировка", callback_data='rebalance')],
        [InlineKeyboardButton("💼 История", callback_data='history')],
        [InlineKeyboardButton("📖 Помощь", callback_data='help')],
    ]
    await update.message.reply_text("🤖 *Arbitrage Bot Pro*\n\n3 типа арбитража:\n• Спот (межбиржевой)\n• Треугольный (внутри биржи)\n• Фьючерсный (базис + фандинг)", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def add_api_cb(update, context):
    q = update.callback_query; await q.answer()
    exs = "\n".join([f"• `{e}`" for e in SUPPORTED_EXCHANGES])
    await q.edit_message_text(f"📊 *Добавление API*\n\nОтправьте: `биржа api_key api_secret [password]`\n\nДоступные:
{exs}\n\nПример:
`okx xxx yyy`\n\n/cancel — отмена", parse_mode='Markdown')
    return ADDING_API

async def save_api(update, context):
    try:
        p = update.message.text.split()
        if len(p) < 3: raise ValueError("Нужно: биржа api_key api_secret")
        em.add_exchange(p[0], p[1], p[2], p[3] if len(p) > 3 else None)
        await em.connect(p[0].lower())
        await update.message.reply_text(f"✅ API для `{p[0]}` добавлено!", parse_mode='Markdown')
    except Exception as e: await update.message.reply_text(f"❌ `{e}`", parse_mode='Markdown')
    return ConversationHandler.END

async def cancel_api(update, context): await update.message.reply_text("❌ Отменено."); return ConversationHandler.END

# === СПОТ АРБИТРАЖ ===
@check_auth
async def scan_spot(update, context):
    q = update.callback_query; await q.answer()
    if len(em.exchanges) < 2:
        await q.edit_message_text("⚠️ *Нужно минимум 2 биржи.*", parse_mode='Markdown'); return
    await q.edit_message_text("🔍 Сканирую спот... (30 пар)")
    try: ops = await ae.scan()
    except Exception as e: await q.edit_message_text(f"❌ `{e}`", parse_mode='Markdown'); return
    await show_opportunities(q, context, ops, 'spot')

# === ТРЕУГОЛЬНЫЙ АРБИТРАЖ ===
@check_auth
async def scan_tri(update, context):
    q = update.callback_query; await q.answer()
    if not em.exchanges:
        await q.edit_message_text("⚠️ *Нужна минимум 1 биржа.*", parse_mode='Markdown'); return
    await q.edit_message_text("🔺 Сканирую треугольные пары...")
    all_ops = []
    for eid in em.exchanges:
        try:
            ops = await tri.scan_triangular(eid)
            all_ops.extend(ops)
        except Exception as e: logger.error(f"Tri scan {eid}: {e}")
    await show_opportunities(q, context, all_ops, 'triangular')

# === ФЬЮЧЕРСНЫЙ АРБИТРАЖ ===
@check_auth
async def scan_fut(update, context):
    q = update.callback_query; await q.answer()
    if not em.exchanges:
        await q.edit_message_text("⚠️ *Нужна минимум 1 биржа.*", parse_mode='Markdown'); return
    await q.edit_message_text("📈 Сканирую фьючерсы...")
    all_ops = []
    for eid in em.exchanges:
        try:
            ops = await fut.scan_basis(eid)
            all_ops.extend(ops)
        except Exception as e: logger.error(f"Fut scan {eid}: {e}")
    await show_opportunities(q, context, all_ops, 'futures')

async def show_opportunities(q, context, ops, scan_type):
    if not ops:
        kb = [[InlineKeyboardButton("🔁 Обновить", callback_data=f'scan_{scan_type[:3]}')], [InlineKeyboardButton("🔙 Меню", callback_data='menu')]]
        await q.edit_message_text("😕 Возможностей не найдено.", reply_markup=InlineKeyboardMarkup(kb))
        return

    type_names = {'spot': 'Спот', 'triangular': '🔺 Треугольный', 'futures_basis': '📈 Базис', 'futures_funding': '💰 Фандинг'}
    tname = type_names.get(scan_type, scan_type)

    txt = f"📈 *{tname} — {len(ops)} возможностей:*\n\n"; kb = []
    for i, o in enumerate(ops[:7]):
        if o['type'] == 'triangular':
            txt += f"*{i+1}. {o['exchange']}*\nПуть: `{o['path']}`\nПрибыль: `{o['profit_percent']:.3f}%`\n\n"
        elif o['type'].startswith('futures'):
            strategy = "Шорт фьючерс" if 'sell' in o.get('strategy', '') else "Лонг фьючерс" if 'buy' in o.get('strategy', '') else "Шорт + фандинг"
            txt += f"*{i+1}. {o['symbol']}* @ `{o['exchange']}`\nБазис: `{o['basis_percent']:.3f}%` | Фандинг: `{o.get('funding_rate', 0):.4f}%`\nСтратегия: `{strategy}`\nПрибыль: `{o['profit_percent']:.3f}%`\n\n"
        else:
            txt += f"*{i+1}. {o['symbol']}*\n`{o['buy_exchange']}` → `{o['sell_exchange']}`\nПрибыль: `{o['profit_percent']:.3f}%`\n\n"
        kb.append([InlineKeyboardButton(f"💸 #{i+1} ({o.get('symbol', o.get('path', 'unknown'))[:10]})", callback_data=f"trade_{scan_type}_{i}")])
    kb += [[InlineKeyboardButton("🔁 Обновить", callback_data=f'scan_{scan_type[:3]}')], [InlineKeyboardButton("🔙 Меню", callback_data='menu')]]
    await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    context.user_data['opportunities'] = ops
    context.user_data['scan_type'] = scan_type

async def trade_cb(update, context):
    q = update.callback_query; await q.answer()
    parts = q.data.split('_')
    idx = int(parts[2]); scan_type = parts[1]
    ops = context.user_data.get('opportunities', [])
    if idx >= len(ops): await q.edit_message_text("❌ Устарело."); return
    op = ops[idx]
    context.user_data['selected_op'] = op
    context.user_data['scan_type'] = scan_type

    if op['type'] == 'triangular':
        txt = (f"⚠️ *Треугольная сделка*\n\nПуть: `{op['path']}`\nБиржа: `{op['exchange']}`\n"
               f"Прибыль: `{op['profit_percent']:.3f}%`\n\nВведите сумму USDT или /default:")
    elif op['type'].startswith('futures'):
        txt = (f"⚠️ *Фьючерсная сделка*\n\n{op['symbol']} @ `{op['exchange']}`\n"
               f"Стратегия: `{op['strategy']}`\nБазис: `{op['basis_percent']:.3f}%`\n"
               f"Фандинг: `{op.get('funding_rate', 0):.4f}%`\nПрибыль: `{op['profit_percent']:.3f}%`\n\n"
               f"⚠️ Требуется маржинальный счет!\nВведите сумму USDT или /default:")
    else:
        txt = (f"⚠️ *Спот сделка*\n\nПара: `{op['symbol']}`\n"
               f"Купить: `{op['buy_exchange']}`\nПродать: `{op['sell_exchange']}`\n"
               f"Прибыль: `{op['profit_percent']:.3f}%`\n\nВведите сумму USDT или /default:")
    await q.edit_message_text(txt, parse_mode='Markdown')
    return ADDING_AMOUNT

async def set_amount(update, context):
    text = update.message.text.strip()
    if text == '/default': amount = DEFAULT_TRADE_AMOUNT
    else:
        try:
            amount = float(text)
            if amount <= 0: raise ValueError("Сумма > 0")
        except ValueError:
            await update.message.reply_text("❌ Введите число или /default")
            return ADDING_AMOUNT

    op = context.user_data.get('selected_op')
    if not op:
        await update.message.reply_text("❌ Данные устарели.")
        return ConversationHandler.END

    tid = await te.prepare(op, amount)
    context.user_data['trade_id'] = tid

    txt = (f"⚠️ *Подтвердите*\n\nСумма: `{amount}` USDT\n"
           f"Ожидаемая прибыль: ~`{op.get('profit_percent', 0) * amount / 100:.4f}` USDT\n\n"
           f"⚡ Бот исполнит автоматически.")
    kb = [[InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_{tid}"), InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_{tid}")]]
    await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return ConversationHandler.END

async def confirm(update, context):
    q = update.callback_query; await q.answer(); tid = q.data.replace("confirm_", "")
    await q.edit_message_text("⏳ Исполняю...")
    res = await te.execute(tid)
    if res['success']:
        tr = res['trade']
        try: await db.save_trade(tr['id'], tr['symbol'], tr['buy_exchange'], tr['sell_exchange'], tr['amount_usdt'], tr.get('expected_profit', 0), 'completed', tr.get('trade_type', 'spot'))
        except Exception as e: logger.error(f"DB: {e}")
        txt = f"✅ *Выполнено!*\n\nID: `{tr['id']}`\nТип: `{tr.get('trade_type', 'spot')}`\nПара: `{tr['symbol']}`"
        if 'orders' in tr: txt += f"\nОрдеров: `{len(tr['orders'])}`"
        else: txt += f"\nBuy: `{tr.get('buy_order', {}).get('id', 'N/A')}`\nSell: `{tr.get('sell_order', {}).get('id', 'N/A')}`"
    else: txt = f"❌ *Ошибка:*\n`{res.get('error', 'Unknown')}`"
    await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Меню", callback_data='menu')]]), parse_mode='Markdown')

async def cancel_trade_cb(update, context):
    q = update.callback_query; await q.answer(); await te.cancel(q.data.replace("cancel_", ""))
    await q.edit_message_text("❌ Отменено.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Меню", callback_data='menu')]]))

async def balance(update, context):
    q = update.callback_query; await q.answer()
    if not em.exchanges: await q.edit_message_text("⚠️ Биржи не подключены.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Меню", callback_data='menu')]])); return
    txt = "💰 *Балансы:*\n\n"
    for eid in em.exchanges:
        try:
            b = await em.get_balance(eid); u = b.get('USDT', {})
            txt += f"*{eid}:*\n  Свободно: `{u.get('free', 0):.2f}` USDT\n  Всего: `{u.get('total', 0):.2f}` USDT\n\n"
        except Exception as e: txt += f"*{eid}:* ошибка (`{e}`)\n\n"
    await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Меню", callback_data='menu')]]), parse_mode='Markdown')

@check_auth
async def rebalance(update, context):
    q = update.callback_query; await q.answer()
    await q.edit_message_text("⚖️ Анализирую...")
    try:
        analysis = await bm.analyze_distribution()
    except Exception as e:
        await q.edit_message_text(f"❌ `{e}`", parse_mode='Markdown'); return
    if 'error' in analysis:
        await q.edit_message_text(f"⚠️ {analysis['error']}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Меню", callback_data='menu')]])); return
    txt = f"📊 *Распределение*\n\nВсего: `{analysis['total_usdt']}` USDT\nЦель: `{analysis['target_per_exchange']}`\n\n*Балансы:*\n"
    for eid, amt in analysis['balances'].items():
        dev = ((amt - analysis['target_per_exchange']) / analysis['target_per_exchange'] * 100) if analysis['target_per_exchange'] > 0 else 0
        arrow = "📈" if dev > 10 else "📉" if dev < -10 else "⚖️"
        txt += f"{arrow} `{eid}`: `{amt:.2f}` ({dev:+.1f}%)\n"
    if analysis['needs_rebalancing']:
        txt += "\n🔄 *Переводы:*\n"; kb = []
        for i, t in enumerate(analysis['recommended_transfers']):
            txt += f"{i+1}. `{t['from']}` → `{t['to']}`: `{t['amount']}` USDT\n"
            kb.append([InlineKeyboardButton(f"💸 Перевод {i+1}", callback_data=f"transfer_{i}")])
        kb.append([InlineKeyboardButton("🔙 Меню", callback_data='menu')])
        await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        context.user_data['transfers'] = analysis['recommended_transfers']
    else:
        txt += "\n✅ Балансы в норме."
        await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Меню", callback_data='menu')]]), parse_mode='Markdown')

async def transfer_cb(update, context):
    q = update.callback_query; await q.answer()
    idx = int(q.data.split('_')[1]); transfers = context.user_data.get('transfers', [])
    if idx >= len(transfers): await q.edit_message_text("❌ Устарело."); return
    t = transfers[idx]
    txt = (f"⚠️ *Ручной перевод*\n\nСумма: `{t['amount']}` USDT\nОткуда: `{t['from']}`\nКуда: `{t['to']}`\n\n"
           f"📋 Действия:\n1. `{t['from']}` → Вывод\n2. USDT (сеть TRC20/BEP20)\n3. Адрес с `{t['to']}`")
    await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Меню", callback_data='menu')]]), parse_mode='Markdown')

async def history(update, context):
    q = update.callback_query; await q.answer()
    try:
        s = await db.get_stats()
        txt = f"💼 *История*\n\nСделок: `{s['total_trades']}`\nПрибыль: `{s['total_profit']:.4f}` USDT\nСредняя: `{s['avg_profit']:.4f}` USDT"
    except Exception as e: txt = f"⚠️ `{e}`"
    await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Меню", callback_data='menu')]]), parse_mode='Markdown')

async def help_cb(update, context):
    q = update.callback_query; await q.answer()
    txt = ("📖 *Инструкция*\n\n"
           "*1. Спот арбитраж*\nКупить на бирже A, продать на B\n\n"
           "*2. Треугольный*\nВнутри одной биржи: USDT→BTC→ETH→USDT\n"
           "Не требует вывода между биржами!\n\n"
           "*3. Фьючерсный*\nБазис: спот vs перпетуал\n"
           "Фандинг: заработок на шорте с положительным фандингом\n\n"
           "⚠️ Все сделки требуют подтверждения.")
    await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Меню", callback_data='menu')]]), parse_mode='Markdown')

async def menu(update, context):
    q = update.callback_query; await q.answer()
    kb = [
        [InlineKeyboardButton("📊 Добавить API", callback_data='add_api')],
        [InlineKeyboardButton("🔍 Спот", callback_data='scan_spo')],
        [InlineKeyboardButton("🔺 Треугольный", callback_data='scan_tri')],
        [InlineKeyboardButton("📈 Фьючерсы", callback_data='scan_fut')],
        [InlineKeyboardButton("💰 Баланс", callback_data='balance')],
        [InlineKeyboardButton("⚖️ Балансировка", callback_data='rebalance')],
        [InlineKeyboardButton("💼 История", callback_data='history')],
        [InlineKeyboardButton("📖 Помощь", callback_data='help')],
    ]
    await q.edit_message_text(f"🤖 *Arbitrage Bot Pro*\n\nБирж: `{len(em.exchanges)}` | Спот: `{len(SPOT_PAIRS)}` | Фьюч: `{len(FUTURES_PAIRS)}` | Три: `{len(TRIANGULAR_SETS)}`", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def notify(context):
    try:
        ops = await ae.scan()
        good = [o for o in ops if o.get('profit_percent', 0) > 0.5]
        if good:
            txt = "🚨 *Спот арбитраж!*\n\n" + "\n".join([f"• `{o['symbol']}`: `{o['profit_percent']:.2f}%`" for o in good[:3]]) + "\n\n/start"
            await context.bot.send_message(chat_id=AUTHORIZED_USER_ID, text=txt, parse_mode='Markdown')
    except Exception as e: logger.error(f"Notify: {e}")

async def post_init(app): await db.init(); logger.info("БД инициализирована")
async def post_stop(app): await em.close_all(); logger.info("Соединения закрыты")

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).post_stop(post_stop).build()

    api_conv = ConversationHandler(entry_points=[CallbackQueryHandler(add_api_cb, pattern='^add_api$')], states={ADDING_API: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_api)]}, fallbacks=[CommandHandler('cancel', cancel_api)])
    amount_conv = ConversationHandler(entry_points=[CallbackQueryHandler(trade_cb, pattern='^trade_')], states={ADDING_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_amount)]}, fallbacks=[CommandHandler('cancel', cancel_api)])

    app.add_handler(CommandHandler('start', start))
    app.add_handler(api_conv)
    app.add_handler(amount_conv)
    app.add_handler(CallbackQueryHandler(scan_spot, pattern='^scan_spo$'))
    app.add_handler(CallbackQueryHandler(scan_tri, pattern='^scan_tri$'))
    app.add_handler(CallbackQueryHandler(scan_fut, pattern='^scan_fut$'))
    app.add_handler(CallbackQueryHandler(confirm, pattern='^confirm_'))
    app.add_handler(CallbackQueryHandler(cancel_trade_cb, pattern='^cancel_'))
    app.add_handler(CallbackQueryHandler(balance, pattern='^balance$'))
    app.add_handler(CallbackQueryHandler(rebalance, pattern='^rebalance$'))
    app.add_handler(CallbackQueryHandler(transfer_cb, pattern='^transfer_'))
    app.add_handler(CallbackQueryHandler(history, pattern='^history$'))
    app.add_handler(CallbackQueryHandler(help_cb, pattern='^help$'))
    app.add_handler(CallbackQueryHandler(menu, pattern='^menu$'))

    if app.job_queue: app.job_queue.run_repeating(notify, interval=60, first=10)
    logger.info("Бот запущен.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()