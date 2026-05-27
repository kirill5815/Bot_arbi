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
from paper_trade_executor import PaperTradeExecutor
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
db = Database()
bm = BalanceManager(em)

# === РЕЖИМ ТОРГОВЛИ ===
PAPER_MODE = True
te = PaperTradeExecutor(em)


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


def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Быстрый скан", callback_data='scan_quick'),
         InlineKeyboardButton("💱 Спот арб", callback_data='scan_spot')],
        [InlineKeyboardButton("🔺 Треугольник", callback_data='scan_tri'),
         InlineKeyboardButton("📉 Скальпинг", callback_data='scan_scalp')],
        [InlineKeyboardButton("📈 Фьючерсы", callback_data='scan_futures'),
         InlineKeyboardButton("📊 Добавить API", callback_data='add_api')],
        [InlineKeyboardButton("⚙️ Настройки", callback_data='settings'),
         InlineKeyboardButton("💰 Балансы", callback_data='balance')],
        [InlineKeyboardButton("📈 Статистика", callback_data='stats'),
         InlineKeyboardButton("💼 История", callback_data='history')],
        [InlineKeyboardButton("📖 Помощь", callback_data='help')]
    ])


# === ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ РЕНДЕРА НАСТРОЕК ===
# Определена ДО settings_menu и adjust_setting
async def _render_settings(q):
    """Рендерит меню настроек."""
    global PAPER_MODE

    if PAPER_MODE:
        mode_emoji = "📝"
        mode_text = "БУМАЖНАЯ"
        balance_text = f"Вирт. баланс: {te.balance_usdt:.2f} USDT" if hasattr(te, 'balance_usdt') else "Бумажный режим"
    else:
        mode_emoji = "💰"
        mode_text = "РЕАЛЬНАЯ"
        balance_text = "Реальные деньги на бирже"

    text = (
        f"⚙️ *Настройки*\n\n"
        f"{mode_emoji} *Режим: {mode_text}*\n"
        f"{balance_text}\n\n"
        f"Порог треуг: `{tri.min_profit_percent}%`\n"
        f"Сумма: `{tri.trade_amount}` USDT\n"
        f"TP: `+{sc.tp_percent*100}%` | SL: `−{sc.sl_percent*100}%`"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Бумажная", callback_data='mode_paper'),
         InlineKeyboardButton("💰 Реальная", callback_data='mode_real')],
        [InlineKeyboardButton("➖ Порог −0.1%", callback_data='set_thresh_down'),
         InlineKeyboardButton("➕ Порог +0.1%", callback_data='set_thresh_up')],
        [InlineKeyboardButton("➖ Сумма −10", callback_data='set_amt_down'),
         InlineKeyboardButton("➕ Сумма +10", callback_data='set_amt_up')],
        [InlineKeyboardButton("🔙 Главное меню", callback_data='menu_main')]
    ])

    await q.edit_message_text(text, reply_markup=kb, parse_mode='Markdown')


# === СТАРТ / МЕНЮ ===
@check_auth
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode_emoji = "📝" if PAPER_MODE else "💰"
    mode_text = "БУМАЖНАЯ" if PAPER_MODE else "РЕАЛЬНАЯ"

    text = (
        f"🤖 *Arbitrage Bot Pro v3.3*\n\n"
        f"{mode_emoji} *Режим: {mode_text}*\n"
        f"• Бирж: `{len(em.exchanges)}` | Спот: `{len(SPOT_PAIRS)}` | Фьюч: `{len(FUTURES_PAIRS)}`\n"
        f"• Треугольников: `авто` | Скальпинг: `DIP+PUMP`\n\n"
        f"⚙️ Порог: `{tri.min_profit_percent}%` | Сумма: `{tri.trade_amount}` USDT"
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=main_menu_keyboard(), parse_mode='Markdown')
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=main_menu_keyboard(), parse_mode='Markdown')


# === НАСТРОЙКИ ===
async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await _render_settings(q)


async def adjust_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global PAPER_MODE, te
    q = update.callback_query
    data = q.data

    changed = False
    if data == 'mode_paper':
        PAPER_MODE = True
        te = PaperTradeExecutor(em)
        changed = True
        logger.info("БУМАЖНАЯ торговля")
    elif data == 'mode_real':
        if not em.exchanges:
            await q.answer("❌ Сначала добавьте API!", show_alert=True)
            return
        PAPER_MODE = False
        te = TradeExecutor(em, scalp_engine=sc)
        changed = True
        logger.info("РЕАЛЬНАЯ торговля")
    elif data == 'set_thresh_down':
        tri.min_profit_percent = max(0.05, round(tri.min_profit_percent - 0.1, 2))
        changed = True
    elif data == 'set_thresh_up':
        tri.min_profit_percent = min(5.0, round(tri.min_profit_percent + 0.1, 2))
        changed = True
    elif data == 'set_amt_down':
        tri.trade_amount = max(10, tri.trade_amount - 10)
        changed = True
    elif data == 'set_amt_up':
        tri.trade_amount = min(10000, tri.trade_amount + 10)
        changed = True

    if changed:
        await q.answer()
        await _render_settings(q)


# === API ===
async def add_api_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    exs = "\n".join([f"• `{e}`" for e in SUPPORTED_EXCHANGES])
    text = (
        f"📊 *Добавление API*\n\n"
        f"Отправьте одной строкой:\n"
        f"`биржа api_key api_secret [password]`\n\n"
        f"Доступные:\n{exs}\n\n"
        f"Пример: `binance xxx yyy`\n"
        f"Для отмены: /cancel"
    )
    await q.edit_message_text(text, parse_mode='Markdown')
    return ADDING_API


async def save_api(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.split()
        if len(parts) < 3:
            raise ValueError("Нужно: биржа api_key api_secret")
        pwd = parts[3] if len(parts) > 3 else None
        em.add_exchange(parts[0], parts[1], parts[2], pwd)
        await em.connect(parts[0].lower())
        await update.message.reply_text(f"✅ API `{parts[0]}` добавлено!", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ `{e}`", parse_mode='Markdown')
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
        await q.edit_message_text("⚠️ Нет бирж.", reply_markup=main_menu_keyboard(), parse_mode='Markdown')
        return
    await q.edit_message_text("⚡ Скан...", parse_mode='Markdown')
    try:
        ops = await tri.scan_all_exchanges()
    except Exception as e:
        await q.edit_message_text(f"❌ `{e}`", reply_markup=main_menu_keyboard(), parse_mode='Markdown')
        return
    await show_opportunities(q, context, ops, 'triangular')


@check_auth
async def scan_spot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not em.exchanges:
        await q.edit_message_text("⚠️ Нет бирж.", reply_markup=main_menu_keyboard(), parse_mode='Markdown')
        return
    if len(em.exchanges) < 2:
        await q.edit_message_text("⚠️ Нужно минимум 2 биржи для спот-арбитража.", reply_markup=main_menu_keyboard(), parse_mode='Markdown')
        return
    await q.edit_message_text("💱 Скан спот-арбитража...", parse_mode='Markdown')
    try:
        ops = await ae.scan_opportunities()
    except Exception as e:
        await q.edit_message_text(f"❌ `{e}`", reply_markup=main_menu_keyboard(), parse_mode='Markdown')
        return
    await show_opportunities(q, context, ops, 'spot')


@check_auth
async def scan_tri(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not em.exchanges:
        await q.edit_message_text("⚠️ Нет бирж.", reply_markup=main_menu_keyboard(), parse_mode='Markdown')
        return
    await q.edit_message_text("🔺 Скан треугольников...", parse_mode='Markdown')
    try:
        ops = await tri.scan_all_exchanges()
    except Exception as e:
        await q.edit_message_text(f"❌ `{e}`", reply_markup=main_menu_keyboard(), parse_mode='Markdown')
        return
    await show_opportunities(q, context, ops, 'triangular')


@check_auth
async def scan_futures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not em.exchanges:
        await q.edit_message_text("⚠️ Нет бирж.", reply_markup=main_menu_keyboard(), parse_mode='Markdown')
        return
    await q.edit_message_text("📈 Скан фьючерсов...", parse_mode='Markdown')
    all_ops = []
    for eid in em.exchanges:
        try:
            ops = await fut.scan_basis(eid)
            all_ops.extend(ops)
        except Exception:
            continue
    all_ops.sort(key=lambda x: x.get('profit_percent', 0), reverse=True)
    await show_opportunities(q, context, all_ops[:15], 'mixed')


@check_auth
async def scan_scalp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not em.exchanges:
        await q.edit_message_text("⚠️ Нет бирж.", reply_markup=main_menu_keyboard(), parse_mode='Markdown')
        return
    await q.edit_message_text("📉 Скан скальпинга...", parse_mode='Markdown')
    try:
        ops = await sc.scan_all_exchanges()
    except Exception as e:
        await q.edit_message_text(f"❌ `{e}`", reply_markup=main_menu_keyboard(), parse_mode='Markdown')
        return
    await show_opportunities(q, context, ops, 'scalping')


async def show_opportunities(q, context, ops, scan_type):
    if not ops:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Обновить", callback_data={'triangular': 'scan_quick', 'scalping': 'scan_scalp'}.get(scan_type, 'scan_deep'))],
            [InlineKeyboardButton("🔙 Меню", callback_data='menu_main')]
        ])
        await q.edit_message_text("😕 Ничего не найдено.", reply_markup=kb, parse_mode='Markdown')
        return

    type_names = {
        'spot': 'Спот', 'triangular': '🔺 Треуг',
        'futures_basis': '📈 Базис', 'futures_funding': '💰 Фандинг',
        'mixed': '🔥 Комбо', 'scalping': '📉 Скальпинг'
    }
    tname = type_names.get(scan_type, scan_type)
    txt = f"📈 *{tname} — {len(ops)}:*\n\n"
    kb = []

    for i, o in enumerate(ops[:10]):
        otype = o.get('type', '')
        if otype in ('scalp_dip', 'scalp_pump'):
            emoji = "📉" if otype == 'scalp_dip' else "📈"
            strategy = "Отскок" if o['strategy'] == 'buy_dip' else "Импульс"
            txt += (
                f"*{i+1}. {emoji} {o['symbol']}* @ `{o['exchange']}`\n"
                f"`{strategy}` | `{o['change_percent']:+.2f}%`\n"
                f"TP: `{o['tp_price']:.6f}` | SL: `{o['sl_price']:.6f}`\n\n"
            )
        elif otype == 'triangular':
            txt += (
                f"*{i+1}. 🔺 {o['exchange']}*\n"
                f"`{o['path']}`\n"
                f"`{o['profit_percent']:.2f}%` | `+{o['profit_usdt']:.2f}` USDT\n\n"
            )
        elif otype.startswith('futures'):
            strategy = "Шорт" if 'sell' in o.get('strategy', '') else "Лонг" if 'buy' in o.get('strategy', '') else "Шорт+фандинг"
            txt += (
                f"*{i+1}. 📈 {o['symbol']}* @ `{o['exchange']}`\n"
                f"Базис: `{o.get('basis_percent', 0):.2f}%` | `{strategy}`\n"
                f"Прибыль: `{o['profit_percent']:.2f}%`\n\n"
            )
        else:
            txt += (
                f"*{i+1}. 💱 {o['symbol']}*\n"
                f"`{o['buy_exchange']}` ➜ `{o['sell_exchange']}`\n"
                f"Спред: `{o['spread_percent']:.2f}%`\n\n"
            )
        symbol_short = o.get('symbol', o.get('path', 'unknown'))[:12]
        kb.append([InlineKeyboardButton(f"💸 #{i+1} {symbol_short}", callback_data=f"trade_{i}")])

    refresh_map = {'spot': 'scan_spot', 'triangular': 'scan_tri', 'scalping': 'scan_scalp', 'mixed': 'scan_futures'}
    kb.append([InlineKeyboardButton("🔄 Обновить", callback_data=refresh_map.get(scan_type, 'scan_deep'))])
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
    ops = context.user_data.get('opportunities', [])
    if idx >= len(ops):
        await q.edit_message_text("❌ Устарело.", reply_markup=main_menu_keyboard())
        return
    op = ops[idx]
    context.user_data['selected_op'] = op

    global PAPER_MODE
    mode_warn = "📝 *БУМАЖНАЯ*\n\n" if PAPER_MODE else "💰 *РЕАЛЬНАЯ*\n\n"

    otype = op.get('type', '')
    if otype in ('scalp_dip', 'scalp_pump'):
        strategy = "Отскок" if op['strategy'] == 'buy_dip' else "Импульс"
        txt = (
            f"{mode_warn}"
            f"⚠️ *Скальпинг*\n\n"
            f"`{op['symbol']}` @ `{op['exchange']}`\n"
            f"Стратегия: `{strategy}` | `{op['change_percent']:+.2f}%`\n\n"
            f"Вход: `{op['entry_price']:.6f}`\n"
            f"TP: `{op['tp_price']:.6f}` (+{op['tp_percent']:.1f}%)\n"
            f"SL: `{op['sl_price']:.6f}` (−{op['sl_percent']:.1f}%)\n\n"
            f"Введите сумму или /default (`{tri.trade_amount}`):"
        )
    elif otype == 'triangular':
        txt = (
            f"{mode_warn}"
            f"⚠️ *Треугольник*\n\n"
            f"`{op['path']}` @ `{op['exchange']}`\n"
            f"Прибыль: `{op['profit_percent']:.2f}%` (`{op['profit_usdt']:.2f}` USDT)\n\n"
            f"Введите сумму или /default (`{tri.trade_amount}`):"
        )
    elif otype.startswith('futures'):
        txt = (
            f"{mode_warn}"
            f"⚠️ *Фьючерсы*\n\n"
            f"`{op['symbol']}` @ `{op['exchange']}`\n"
            f"Стратегия: `{op['strategy']}`\n"
            f"Прибыль: `{op['profit_percent']:.2f}%`\n\n"
            f"Введите сумму или /default:"
        )
    else:
        txt = (
            f"{mode_warn}"
            f"⚠️ *Спот*\n\n"
            f"`{op['symbol']}`\n"
            f"`{op['buy_exchange']}` ➜ `{op['sell_exchange']}`\n"
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
            await update.message.reply_text("❌ Введите число или /default")
            return ADDING_AMOUNT

    op = context.user_data.get('selected_op')
    if not op:
        await update.message.reply_text("❌ Устарело.")
        return ConversationHandler.END

    tid = await te.prepare(op, amount)
    context.user_data['trade_id'] = tid

    global PAPER_MODE
    otype = op.get('type', '')

    if PAPER_MODE and hasattr(te, 'balance_usdt'):
        bal = f"📝 Баланс: `{te.balance_usdt:.2f}` USDT\n\n"
    else:
        bal = ""

    if otype in ('scalp_dip', 'scalp_pump'):
        exp_profit = amount * sc.tp_percent
        exp_loss = amount * sc.sl_percent
        txt = (
            f"{bal}"
            f"⚠️ *Подтвердите скальпинг*\n\n"
            f"`{op['symbol']}` | Сумма: `{amount}` USDT\n"
            f"TP: `+{exp_profit:.2f}` | SL: `−{exp_loss:.2f}`\n\n"
            f"⚡ Market Buy + Limit TP\n"
            f"🛡 SL: авто-мониторинг"
        )
    else:
        exp_profit = op.get('profit_percent', 0) * amount / 100
        txt = (
            f"{bal}"
            f"⚠️ *Подтвердите*\n\n"
            f"Сумма: `{amount}` USDT\n"
            f"Прибыль: `~{exp_profit:.2f}` USDT\n\n"
            f"⚡ Рыночные ордера"
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
    await q.edit_message_text("⏳ Исполнение...", parse_mode='Markdown')
    res = await te.execute(tid)

    global PAPER_MODE
    emoji = "📝" if PAPER_MODE else "💰"

    if res['success']:
        tr = res['trade']
        profit = tr.get('profit', 0) or tr.get('expected_profit', 0)
        ttype = tr.get('trade_type', 'spot')

        try:
            await db.save_trade(tr['id'], tr['symbol'], tr['buy_exchange'], tr['sell_exchange'],
                              tr['amount_usdt'], profit, 'completed', ttype)
        except Exception as e:
            logger.error(f"DB: {e}")

        if PAPER_MODE and hasattr(te, 'balance_usdt'):
            bal = f"\n📝 Баланс: `{te.balance_usdt:.2f}` USDT"
        else:
            bal = ""

        if ttype in ('scalp_dip', 'scalp_pump'):
            txt = (
                f"{emoji} *Позиция открыта!*{bal}\n\n"
                f"ID: `{tr['id']}`\n"
                f"`{tr['symbol']}` @ `{tr['buy_exchange']}`\n"
                f"Вход: `{tr.get('entry_price', 0):.6f}`\n"
                f"TP: `{tr.get('tp_price', 0):.6f}` | SL: `{tr.get('sl_price', 0):.6f}`\n\n"
                f"🛡 *Авто-мониторинг*"
            )
        else:
            txt = (
                f"{emoji} *Выполнено!*{bal}\n\n"
                f"ID: `{tr['id']}`\n"
                f"Тип: `{ttype}`\n"
                f"`{tr['symbol']}` | `{tr['amount_usdt']}` USDT\n"
                f"Прибыль: `{profit:.4f}` USDT"
            )
    else:
        txt = f"❌ *Ошибка:*\n`{res.get('error', 'Unknown')}`"

    await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Меню", callback_data='menu_main')]]), parse_mode='Markdown')


async def cancel_trade_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await te.cancel(q.data.replace("cancel_", ""))
    await q.edit_message_text("❌ Отменено.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Меню", callback_data='menu_main')]]))


# === БАЛАНС ===
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    global PAPER_MODE

    if PAPER_MODE:
        if hasattr(te, 'balance_usdt'):
            txt = f"📝 *Бумажный баланс*\n\nUSDT: `{te.balance_usdt:.2f}`\n"
            if hasattr(te, 'positions') and te.positions:
                txt += "\n*Позиции:*\n"
                for sym, qty in te.positions.items():
                    txt += f"  `{sym}`: `{qty:.6f}`\n"
            if hasattr(te, 'get_stats'):
                s = te.get_stats()
                txt += f"\n📊 Сделок: `{s['total_trades']}` | Прибыль: `{s['total_profit']:.2f}` USDT"
        else:
            txt = "📝 Бумажный режим"
        await q.edit_message_text(txt, reply_markup=main_menu_keyboard(), parse_mode='Markdown')
        return

    if not em.exchanges:
        await q.edit_message_text("⚠️ Биржи не подключены.", reply_markup=main_menu_keyboard())
        return

    txt = "💰 *Балансы:*\n\n"
    total_free = 0
    for eid in em.exchanges:
        try:
            b = await em.get_balance(eid)
            u = b.get('USDT', {})
            free = u.get('free', 0)
            total_free += free
            txt += f"*{eid}:* `{free:.2f}` USDT\n"
        except Exception as e:
            txt += f"*{eid}:* ошибка\n"
    txt += f"\n📊 Итого: `{total_free:.2f}` USDT"
    await q.edit_message_text(txt, reply_markup=main_menu_keyboard(), parse_mode='Markdown')


# === СТАТИСТИКА ===
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    global PAPER_MODE

    try:
        if PAPER_MODE and hasattr(te, 'get_stats'):
            s = te.get_stats()
            txt = (
                f"📝 *Бумажная статистика*\n\n"
                f"Сделок: `{s['total_trades']}`\n"
                f"Прибыль: `{s['total_profit']:.4f}` USDT\n"
                f"Win rate: `{s['win_rate']:.1f}%`\n"
                f"Баланс: `{s['current_balance']:.2f}` USDT"
            )
        else:
            s = await db.get_stats()
            txt = (
                f"📈 *Статистика*\n\n"
                f"Сделок: `{s['total_trades']}`\n"
                f"Прибыль: `{s['total_profit']:.4f}` USDT\n"
                f"Средняя: `{s['avg_profit']:.4f}` USDT"
            )
    except Exception as e:
        txt = f"⚠️ `{e}`"

    await q.edit_message_text(txt, reply_markup=main_menu_keyboard(), parse_mode='Markdown')


# === ИСТОРИЯ ===
async def history_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        s = await db.get_stats()
        txt = f"💼 *История*\n\nСделок: `{s['total_trades']}`\nПрибыль: `{s['total_profit']:.4f}` USDT"
    except Exception as e:
        txt = f"⚠️ `{e}`"
    await q.edit_message_text(txt, reply_markup=main_menu_keyboard(), parse_mode='Markdown')


# === ПОМОЩЬ ===
async def help_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    global PAPER_MODE
    mode = "📝 БУМАЖНАЯ" if PAPER_MODE else "💰 РЕАЛЬНАЯ"
    txt = (
        f"📖 *Помощь*\n\n"
        f"Режим: *{mode}*\n\n"
        f"*⚡ Быстрый скан* — треугольники, 1–2 сек\n"
        f"*🔍 Глубокий* — всё одновременно\n"
        f"*📉 Скальпинг* — DIP/PUMP с авто TP/SL\n\n"
        f"*⚙️ Настройки:*\n"
        f"• Порог прибыли\n"
        f"• Сумма сделки\n"
        f"• **Режим торговли**\n\n"
        f"💡 BNB = скидка 25%, торгуйте 14:00–16:00 UTC"
    )
    await q.edit_message_text(txt, reply_markup=main_menu_keyboard(), parse_mode='Markdown')


# === УВЕДОМЛЕНИЯ ===
async def notify(context: ContextTypes.DEFAULT_TYPE):
    try:
        ops = await tri.scan_all_exchanges()
        good = [o for o in ops if o.get('profit_percent', 0) > 0.5]
        if good:
            txt = "🚨 *Арбитраж!*\n\n" + "\n".join([f"• `{o['path']}`: `{o['profit_percent']:.2f}%`" for o in good[:3]]) + "\n\n/start"
            await context.bot.send_message(chat_id=AUTHORIZED_USER_ID, text=txt, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Notify: {e}")


# === INIT / STOP ===
async def post_init(app):
    await db.init()
    sc.start_monitor()
    logger.info(f"Бот запущен. Режим: {'БУМАЖНЫЙ' if PAPER_MODE else 'РЕАЛЬНЫЙ'}")


async def post_stop(app):
    sc.stop_monitor()
    await em.close_all()
    logger.info("Бот остановлен.")


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
    app.add_handler(CallbackQueryHandler(scan_spot, pattern='^scan_spot$'))
    app.add_handler(CallbackQueryHandler(scan_tri, pattern='^scan_tri$'))
    app.add_handler(CallbackQueryHandler(scan_futures, pattern='^scan_futures$'))
    app.add_handler(CallbackQueryHandler(scan_scalp, pattern='^scan_scalp$'))
    app.add_handler(CallbackQueryHandler(settings_menu, pattern='^settings$'))
    app.add_handler(CallbackQueryHandler(adjust_setting, pattern='^set_(thresh|amt)_(up|down)$'))
    app.add_handler(CallbackQueryHandler(adjust_setting, pattern='^mode_(paper|real)$'))

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
