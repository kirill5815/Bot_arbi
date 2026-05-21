#!/usr/bin/env python3
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes,
    ConversationHandler, MessageHandler, filters
)
from config import (
    TELEGRAM_BOT_TOKEN, AUTHORIZED_USER_ID, SUPPORTED_EXCHANGES,
    SPOT_PAIRS, FUTURES_PAIRS, TRIANGULAR_SETS, DEFAULT_TRADE_AMOUNT
)
from exchange_manager import ExchangeManager
from arbitrage_engine import ArbitrageEngine
from triangular_engine import TriangularEngine
from futures_engine import FuturesEngine
from scalping_engine import ScalpingEngine
from trade_executor import TradeExecutor
from database import Database
from balance_manager import BalanceManager

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# === Состояния ===
ADDING_API = 1
ADDING_AMOUNT = 2

# === Глобальные объекты ===
em = ExchangeManager()
ae = ArbitrageEngine(em)
tri = TriangularEngine(em, min_profit_percent=0.3, trade_amount=100)
fut = FuturesEngine(em)
sc = ScalpingEngine(em)
te = TradeExecutor(em, scalp_engine=sc)
db = Database()
bm = BalanceManager(em)


def check_auth(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id if update.effective_user else None
        if user_id != AUTHORIZED_USER_ID:
            if update.message:
                await update.message.reply_text("⛔ Доступ запрещён.")
            elif update.callback_query:
                await update.callback_query.answer("⛔ Доступ запрещён.", show_alert=True)
            return
        return await func(update, context)
    return wrapper


# === КЛАВИАТУРЫ ===
def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Быстрый скан", callback_data='scan_quick'),
         InlineKeyboardButton("🔍 Глубокий скан", callback_data='scan_deep')],
        [InlineKeyboardButton("📉 Скальпинг", callback_data='scan_scalp'),
         InlineKeyboardButton("📊 Добавить API", callback_data='add_api')],
        [InlineKeyboardButton("⚙️ Настройки", callback_data='settings'),
         InlineKeyboardButton("💰 Балансы", callback_data='balance')],
        [InlineKeyboardButton("📈 Статистика", callback_data='stats'),
         InlineKeyboardButton("💼 История", callback_data='history')],
        [InlineKeyboardButton("📖 Помощь", callback_data='help')]
    ])


def back_menu():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Главное меню", callback_data='menu_main')]])


# === СТАРТ / МЕНЮ ===
@check_auth
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *Arbitrage Bot Pro v3.0*\n\n"
        f"• Бирж подключено: `{len(em.exchanges)}`\n"
        f"• Спот пар: `{len(SPOT_PAIRS)}`\n"
        f"• Фьючерсов: `{len(FUTURES_PAIRS)}`\n"
        f"• Треугольников: `авто`\n"
        f"• Скальпинг: `DIP+PUMP`\n\n"
        f"💡 *Режимы:*\n"
        f"⚡ Быстрый — треугольники, 1–2 сек\n"
        f"🔍 Глубокий — всё одновременно\n"
        f"📉 Скальпинг — авто TP/SL\n\n"
        f"⚙️ Порог треуг: `{tri.min_profit_percent}%` | Сумма: `{tri.trade_amount}` USDT"
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=main_menu_keyboard(), parse_mode='Markdown')
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=main_menu_keyboard(), parse_mode='Markdown')


# === НАСТРОЙКИ ===
async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    text = (
        "⚙️ *Настройки*\n\n"
        f"Порог треугольника: `{tri.min_profit_percent}%`\n"
        f"Сумма сделки: `{tri.trade_amount}` USDT\n"
        f"Скальпинг TP: `+{sc.tp_percent*100}%` | SL: `−{sc.sl_percent*100}%`\n\n"
        f"_Прибыль треугольника считается: спред − 3×комиссия_"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➖ Порог −0.1%", callback_data='set_thresh_down'),
         InlineKeyboardButton("➕ Порог +0.1%", callback_data='set_thresh_up')],
        [InlineKeyboardButton("➖ Сумма −10", callback_data='set_amt_down'),
         InlineKeyboardButton("➕ Сумма +10", callback_data='set_amt_up')],
        [InlineKeyboardButton("🔙 Главное меню", callback_data='menu_main')]
    ])
    await q.edit_message_text(text, reply_markup=kb, parse_mode='Markdown')


async def adjust_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if 'thresh_down' in data:
        tri.min_profit_percent = max(0.05, round(tri.min_profit_percent - 0.1, 2))
    elif 'thresh_up' in data:
        tri.min_profit_percent = min(5.0, round(tri.min_profit_percent + 0.1, 2))
    elif 'amt_down' in data:
        tri.trade_amount = max(10, tri.trade_amount - 10)
    elif 'amt_up' in data:
        tri.trade_amount = min(10000, tri.trade_amount + 10)
    await settings_menu(update, context)


# === API ===
async def add_api_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    exs = "\n".join([f"• `{e}`" for e in SUPPORTED_EXCHANGES])
    text = (
        f"📊 *Добавление API*\n\n"
        f"Отправьте одной строкой:\n"
        f"`биржа api_key api_secret [password]`\n\n"
        f"Доступные биржи:\n{exs}\n\n"
        f"Пример: `binance xxx yyy`\n"
        f"Для отмены: /cancel"
    )
    await q.edit_message_text(text, parse_mode='Markdown')
    return ADDING_API


async def save_api(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.split()
        if len(parts) < 3:
            raise ValueError("Нужно: биржа api_key api_secret [password]")
        pwd = parts[3] if len(parts) > 3 else None
        em.add_exchange(parts[0], parts[1], parts[2], pwd)
        await em.connect(parts[0].lower())
        await update.message.reply_text(f"✅ API для `{parts[0]}` добавлено и подключено!", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: `{e}`", parse_mode='Markdown')
    return ConversationHandler.END


async def cancel_api(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Отменено.")
    return ConversationHandler.END


# === СКАНИРОВАНИЕ ===
@check_auth
async def scan_quick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not em.exchanges:
        await q.edit_message_text("⚠️ *Нет подключённых бирж.*\n\nДобавьте API в меню.", reply_markup=main_menu_keyboard(), parse_mode='Markdown')
        return
    await q.edit_message_text("⚡ *Быстрый скан треугольников...*", parse_mode='Markdown')
    start_time = asyncio.get_event_loop().time()
    try:
        ops = await tri.scan_all_exchanges()
    except Exception as e:
        logger.error(f"Quick scan error: {e}")
        await q.edit_message_text(f"❌ Ошибка сканирования:\n`{e}`", reply_markup=main_menu_keyboard(), parse_mode='Markdown')
        return
    elapsed = round(asyncio.get_event_loop().time() - start_time, 2)
    await show_opportunities(q, context, ops, 'triangular', elapsed)


@check_auth
async def scan_deep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not em.exchanges:
        await q.edit_message_text("⚠️ *Нет подключённых бирж.*", reply_markup=main_menu_keyboard(), parse_mode='Markdown')
        return
    await q.edit_message_text(
        "🔍 *Глубокий скан:*\n• Спот (межбиржевой)\n• Треугольный\n• Фьючерсный\n• Скальпинг\n\n⏳ Ждите ~5–10 сек...",
        parse_mode='Markdown'
    )
    all_ops = []
    tasks = []
    if len(em.exchanges) >= 2:
        tasks.append(ae.scan_opportunities())
    tasks.append(tri.scan_all_exchanges())
    tasks.append(sc.scan_all_exchanges())
    for eid in em.exchanges:
        tasks.append(fut.scan_basis(eid))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for res in results:
        if isinstance(res, list):
            all_ops.extend(res)
    all_ops.sort(key=lambda x: x.get('profit_percent', 0), reverse=True)
    await show_opportunities(q, context, all_ops[:15], 'mixed', None)


@check_auth
async def scan_scalp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not em.exchanges:
        await q.edit_message_text("⚠️ *Нет подключённых бирж.*", reply_markup=main_menu_keyboard(), parse_mode='Markdown')
        return
    await q.edit_message_text("📉 *Сканирую скальпинг-сигналы...*", parse_mode='Markdown')
    start_time = asyncio.get_event_loop().time()
    try:
        ops = await sc.scan_all_exchanges()
    except Exception as e:
        logger.error(f"Scalp scan error: {e}")
        await q.edit_message_text(f"❌ Ошибка: `{e}`", reply_markup=main_menu_keyboard(), parse_mode='Markdown')
        return
    elapsed = round(asyncio.get_event_loop().time() - start_time, 2)
    await show_opportunities(q, context, ops, 'scalping', elapsed)


async def show_opportunities(q, context, ops, scan_type, elapsed=None):
    if not ops:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Обновить", callback_data=scan_type if scan_type != 'mixed' else 'scan_deep')],
            [InlineKeyboardButton("🔙 Меню", callback_data='menu_main')]
        ])
        await q.edit_message_text(
            "😕 *Возможностей не найдено.*\n\nПопробуйте снизить порог в настройках или подождите волатильности.",
            reply_markup=kb, parse_mode='Markdown'
        )
        return

    type_names = {
        'spot': 'Спот', 'triangular': '🔺 Треугольный',
        'futures_basis': '📈 Базис', 'futures_funding': '💰 Фандинг',
        'mixed': '🔥 Комбо', 'scalping': '📉 Скальпинг'
    }
    tname = type_names.get(scan_type, scan_type)
    header = f"📈 *{tname} — найдено {len(ops)}:*"
    if elapsed:
        header += f"\n⏱ Скан за `{elapsed}` сек"
    header += "\n\n"
    txt = header
    kb = []

    for i, o in enumerate(ops[:10]):
        otype = o.get('type', '')
        if otype in ('scalp_dip', 'scalp_pump'):
            emoji = "📉" if otype == 'scalp_dip' else "📈"
            strategy = "Отскок" if o['strategy'] == 'buy_dip' else "Импульс"
            txt += (
                f"*{i+1}. {emoji} {o['symbol']}* @ `{o['exchange']}`\n"
                f"Стратегия: `{strategy}` | Изменение: `{o['change_percent']:+.2f}%`\n"
                f"Вход: `{o['entry_price']:.6f}` | TP: `{o['tp_price']:.6f}` | SL: `{o['sl_price']:.6f}`\n"
                f"TP: `+{o['tp_percent']:.1f}%` | SL: `−{o['sl_percent']:.1f}%`\n\n"
            )
        elif otype == 'triangular':
            txt += (
                f"*{i+1}. 🔺 {o['exchange']}*\n"
                f"`{o['path']}`\n"
                f"Прибыль: `{o['profit_percent']:.2f}%` | `+{o['profit_usdt']:.2f}` USDT\n\n"
            )
        elif otype.startswith('futures'):
            strategy = "Шорт фьюч" if 'sell' in o.get('strategy', '') else "Лонг фьюч" if 'buy' in o.get('strategy', '') else "Шорт+фандинг"
            txt += (
                f"*{i+1}. 📈 {o['symbol']}* @ `{o['exchange']}`\n"
                f"Базис: `{o.get('basis_percent', 0):.2f}%` | Фандинг: `{o.get('funding_rate', 0):.4f}%`\n"
                f"Стратегия: `{strategy}` | Прибыль: `{o['profit_percent']:.2f}%`\n\n"
            )
        else:
            txt += (
                f"*{i+1}. 💱 {o['symbol']}*\n"
                f"`{o['buy_exchange']}` ➜ `{o['sell_exchange']}`\n"
                f"Спред: `{o['spread_percent']:.2f}%` | Чистая: `{o['profit_percent']:.2f}%`\n\n"
            )
        symbol_short = o.get('symbol', o.get('path', 'unknown'))[:12]
        kb.append([InlineKeyboardButton(f"💸 #{i+1} {symbol_short}", callback_data=f"trade_{scan_type}_{i}")])

    refresh_map = {'triangular': 'scan_quick', 'scalping': 'scan_scalp', 'mixed': 'scan_deep'}
    kb.append([InlineKeyboardButton("🔄 Обновить", callback_data=refresh_map.get(scan_type, 'scan_quick'))])
    kb.append([InlineKeyboardButton("🔙 Меню", callback_data='menu_main')])
    await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    context.user_data['opportunities'] = ops
    context.user_data['scan_type'] = scan_type


# === ТОРГОВЛЯ ===
async def trade_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    parts = q.data.split('_')
    idx = int(parts[-1])
    scan_type = context.user_data.get('scan_type', 'mixed')
    ops = context.user_data.get('opportunities', [])
    if idx >= len(ops):
        await q.edit_message_text("❌ Данные устарели.", reply_markup=main_menu_keyboard())
        return
    op = ops[idx]
    context.user_data['selected_op'] = op
    context.user_data['scan_type'] = scan_type

    otype = op.get('type', '')
    if otype in ('scalp_dip', 'scalp_pump'):
        strategy = "Отскок после падения" if op['strategy'] == 'buy_dip' else "Покупка импульса"
        txt = (
            f"⚠️ *Скальпинг-сделка*\n\n"
            f"Пара: `{op['symbol']}` @ `{op['exchange']}`\n"
            f"Стратегия: `{strategy}`\n"
            f"Изменение: `{op['change_percent']:+.2f}%`\n\n"
            f"📊 *Параметры:*\n"
            f"Вход: `{op['entry_price']:.6f}`\n"
            f"TP: `{op['tp_price']:.6f}` (+{op['tp_percent']:.1f}%)\n"
            f"SL: `{op['sl_price']:.6f}` (−{op['sl_percent']:.1f}%)\n\n"
            f"⚡ Бот купит по рынку и поставит лимитный TP.\n"
            f"🛡 SL мониторится автоматически каждые 5 сек.\n\n"
            f"Введите сумму USDT или /default (`{tri.trade_amount}`):"
        )
    elif otype == 'triangular':
        txt = (
            f"⚠️ *Треугольная сделка*\n\n"
            f"Биржа: `{op['exchange']}`\n"
            f"Путь: `{op['path']}`\n"
            f"Ожидаемая прибыль: `{op['profit_percent']:.2f}%` (`{op['profit_usdt']:.2f}` USDT)\n\n"
            f"Введите сумму USDT или /default (`{tri.trade_amount}`):"
        )
    elif otype.startswith('futures'):
        txt = (
            f"⚠️ *Фьючерсная сделка*\n\n"
            f"{op['symbol']} @ `{op['exchange']}`\n"
            f"Стратегия: `{op['strategy']}`\n"
            f"Прибыль: `{op['profit_percent']:.2f}%`\n\n"
            f"⚠️ Требуется маржинальный счёт!\n"
            f"Введите сумму или /default:"
        )
    else:
        txt = (
            f"⚠️ *Спот сделка*\n\n"
            f"Пара: `{op['symbol']}`\n"
            f"Купить: `{op['buy_exchange']}`\n"
            f"Продать: `{op['sell_exchange']}`\n"
            f"Прибыль: `{op['profit_percent']:.2f}%`\n\n"
            f"Введите сумму или /default:"
        )
    await q.edit_message_text(txt, parse_mode='Markdown')
    return ADDING_AMOUNT


async def set_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == '/default':
        amount = tri.trade_amount
    else:
        try:
            amount = float(text)
            if amount <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Введите положительное число или /default")
            return ADDING_AMOUNT

    op = context.user_data.get('selected_op')
    if not op:
        await update.message.reply_text("❌ Данные устарели.")
        return ConversationHandler.END

    tid = await te.prepare(op, amount)
    context.user_data['trade_id'] = tid

    otype = op.get('type', '')
    if otype in ('scalp_dip', 'scalp_pump'):
        exp_profit = amount * sc.tp_percent
        exp_loss = amount * sc.sl_percent
        txt = (
            f"⚠️ *Подтвердите скальпинг*\n\n"
            f"Пара: `{op['symbol']}`\n"
            f"Сумма: `{amount}` USDT\n"
            f"TP: `+{exp_profit:.2f}` USDT (+{sc.tp_percent*100:.1f}%)\n"
            f"SL: `−{exp_loss:.2f}` USDT (−{sc.sl_percent*100:.1f}%)\n\n"
            f"⚡ Market Buy + Limit Sell TP\n"
            f"🛡 SL: авто-продажа при падении"
        )
    else:
        exp_profit = op.get('profit_percent', 0) * amount / 100
        txt = (
            f"⚠️ *Подтвердите сделку*\n\n"
            f"Сумма: `{amount}` USDT\n"
            f"Ожидаемая прибыль: `~{exp_profit:.2f}` USDT\n\n"
            f"⚡ Бот отправит рыночные ордера мгновенно."
        )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_{tid}"),
         InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_{tid}")]
    ])
    await update.message.reply_text(txt, reply_markup=kb, parse_mode='Markdown')
    return ConversationHandler.END


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    tid = q.data.replace("confirm_", "")
    await q.edit_message_text("⏳ *Исполнение ордеров...*", parse_mode='Markdown')
    res = await te.execute(tid)

    if res['success']:
        tr = res['trade']
        profit = tr.get('expected_profit', 0)
        ttype = tr.get('trade_type', 'spot')

        try:
            await db.save_trade(
                tr['id'], tr['symbol'], tr['buy_exchange'], tr['sell_exchange'],
                tr['amount_usdt'], profit, 'completed', ttype
            )
        except Exception as e:
            logger.error(f"DB save error: {e}")

        if ttype in ('scalp_dip', 'scalp_pump'):
            txt = (
                f"✅ *Позиция открыта!*\n\n"
                f"ID: `{tr['id']}`\n"
                f"Пара: `{tr['symbol']}` @ `{tr['buy_exchange']}`\n"
                f"Вход: `{tr.get('entry_price', 0):.6f}`\n"
                f"Количество: `{tr.get('qty', 0):.4f}`\n"
                f"TP: `{tr.get('tp_price', 0):.6f}` (+{sc.tp_percent*100:.1f}%)\n"
                f"SL: `{tr.get('sl_price', 0):.6f}` (−{sc.sl_percent*100:.1f}%)\n\n"
                f"🛡 *Авто-мониторинг активирован*\n"
                f"Бот следит за ценой каждые 5 сек.\n"
                f"Вы получите уведомление при закрытии."
            )
        else:
            txt = (
                f"✅ *Сделка выполнена!*\n\n"
                f"ID: `{tr['id']}`\n"
                f"Тип: `{ttype}`\n"
                f"Пара: `{tr['symbol']}`\n"
                f"Сумма: `{tr['amount_usdt']}` USDT\n"
                f"Прибыль: `{profit:.4f}` USDT"
            )
            if 'orders' in tr:
                txt += f"\nОрдеров: `{len(tr['orders'])}`"
    else:
        txt = f"❌ *Ошибка исполнения:*\n`{res.get('error', 'Unknown')}`"

    await q.edit_message_text(
        txt,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Меню", callback_data='menu_main')]]),
        parse_mode='Markdown'
    )


async def cancel_trade_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await te.cancel(q.data.replace("cancel_", ""))
    await q.edit_message_text(
        "❌ Сделка отменена.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Меню", callback_data='menu_main')]])
    )


# === БАЛАНС ===
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not em.exchanges:
        await q.edit_message_text("⚠️ Биржи не подключены.", reply_markup=main_menu_keyboard())
        return
    txt = "💰 *Балансы:*\n\n"
    total_free = 0
    total_total = 0
    for eid in em.exchanges:
        try:
            b = await em.get_balance(eid)
            u = b.get('USDT', {})
            free = u.get('free', 0)
            total = u.get('total', 0)
            total_free += free
            total_total += total
            txt += f"*{eid}:*\n  Свободно: `{free:.2f}` USDT\n  Всего: `{total:.2f}` USDT\n\n"
        except Exception as e:
            txt += f"*{eid}:* ошибка (`{e}`)\n\n"
    txt += f"📊 *Итого:*\n  Свободно: `{total_free:.2f}` USDT\n  Всего: `{total_total:.2f}` USDT"
    await q.edit_message_text(txt, reply_markup=main_menu_keyboard(), parse_mode='Markdown')


# === СТАТИСТИКА ===
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        s = await db.get_stats()
        txt = (
            f"📈 *Статистика*\n\n"
            f"Сделок выполнено: `{s['total_trades']}`\n"
            f"Общая прибыль: `{s['total_profit']:.4f}` USDT\n"
            f"Средняя сделка: `{s['avg_profit']:.4f}` USDT\n\n"
            f"💡 *Совет:* Используйте реинвест для роста капитала."
        )
    except Exception as e:
        txt = f"⚠️ Ошибка статистики: `{e}`"
    await q.edit_message_text(txt, reply_markup=main_menu_keyboard(), parse_mode='Markdown')


# === ИСТОРИЯ ===
async def history_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        s = await db.get_stats()
        txt = (
            f"💼 *История*\n\n"
            f"Сделок: `{s['total_trades']}`\n"
            f"Прибыль: `{s['total_profit']:.4f}` USDT\n"
            f"Средняя: `{s['avg_profit']:.4f}` USDT"
        )
    except Exception as e:
        txt = f"⚠️ `{e}`"
    await q.edit_message_text(txt, reply_markup=main_menu_keyboard(), parse_mode='Markdown')


# === ПОМОЩЬ ===
async def help_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    txt = (
        "📖 *Инструкция*\n\n"
        "*1. ⚡ Быстрый скан*\n"
        "Только треугольный арбитраж внутри бирж. "
        "Самый быстрый (1–2 сек) и подходит для малого капитала.\n\n"
        "*2. 🔍 Глубокий скан*\n"
        "Спот + треугольник + фьючерсы + скальпинг одновременно.\n\n"
        "*3. 📉 Скальпинг*\n"
        "Авто-вход при резком падении (DIP) или импульсе (PUMP). "
        "Бот сам ставит TP лимитным ордером и следит за SL.\n\n"
        "*4. ⚙️ Настройки*\n"
        "• Порог прибыли — минимальный % для треугольника\n"
        "• Сумма сделки — сколько USDT использовать\n\n"
        "*5. 💡 Советы*\n"
        "• Держите BNB на Binance для скидки 25% на комиссии\n"
        "• Торгуйте в 14:00–16:00 UTC (фандинг, америка)\n"
        "• Скальпинг: не входите на >50% депозита за раз"
    )
    await q.edit_message_text(txt, reply_markup=main_menu_keyboard(), parse_mode='Markdown')


# === УВЕДОМЛЕНИЯ ===
async def notify(context: ContextTypes.DEFAULT_TYPE):
    try:
        ops = await tri.scan_all_exchanges()
        good = [o for o in ops if o.get('profit_percent', 0) > 0.5]
        if good:
            txt = (
                "🚨 *Треугольный арбитраж!*\n\n"
                + "\n".join([f"• `{o['path']}` @ {o['exchange']}: `{o['profit_percent']:.2f}%`" for o in good[:3]])
                + "\n\n/start — открыть бота"
            )
            await context.bot.send_message(chat_id=AUTHORIZED_USER_ID, text=txt, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Notify error: {e}")


# === INIT / STOP ===
async def post_init(app):
    await db.init()
    sc.start_monitor()
    logger.info("БД инициализирована, мониторинг TP/SL запущен")


async def post_stop(app):
    sc.stop_monitor()
    await em.close_all()
    logger.info("Мониторинг остановлен, соединения закрыты")


# === MAIN ===
def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).post_stop(post_stop).build()

    api_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_api_cb, pattern='^add_api$')],
        states={ADDING_API: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_api)]},
        fallbacks=[CommandHandler('cancel', cancel_api)]
    )
    amount_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(trade_cb, pattern='^trade_')],
        states={ADDING_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_amount)]},
        fallbacks=[CommandHandler('cancel', cancel_api)]
    )

    app.add_handler(CommandHandler('start', start))
    app.add_handler(api_conv)
    app.add_handler(amount_conv)

    app.add_handler(CallbackQueryHandler(start, pattern='^menu_main$'))
    app.add_handler(CallbackQueryHandler(scan_quick, pattern='^scan_quick$'))
    app.add_handler(CallbackQueryHandler(scan_deep, pattern='^scan_deep$'))
    app.add_handler(CallbackQueryHandler(scan_scalp, pattern='^scan_scalp$'))
    app.add_handler(CallbackQueryHandler(settings_menu, pattern='^settings$'))
    app.add_handler(CallbackQueryHandler(adjust_setting, pattern='^set_(thresh|amt)_(up|down)$'))

    app.add_handler(CallbackQueryHandler(confirm, pattern='^confirm_'))
    app.add_handler(CallbackQueryHandler(cancel_trade_cb, pattern='^cancel_'))

    app.add_handler(CallbackQueryHandler(balance, pattern='^balance$'))
    app.add_handler(CallbackQueryHandler(stats, pattern='^stats$'))
    app.add_handler(CallbackQueryHandler(history_cb, pattern='^history$'))
    app.add_handler(CallbackQueryHandler(help_cb, pattern='^help$'))

    if app.job_queue:
        app.job_queue.run_repeating(notify, interval=60, first=10)

    logger.info("Бот запущен.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()