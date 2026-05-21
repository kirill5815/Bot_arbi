import aiosqlite, os
from datetime import datetime
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trades.db')
class Database:
    def __init__(self): self.db_path = DB_PATH
    async def init(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''CREATE TABLE IF NOT EXISTS trades (id TEXT PRIMARY KEY, symbol TEXT, buy_exchange TEXT, sell_exchange TEXT, amount REAL, profit REAL, status TEXT, trade_type TEXT, created_at TEXT)''')
            await db.commit()
    async def save_trade(self, tid, sym, bx, sx, am, pr, st, ttype='spot'):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('INSERT OR REPLACE INTO trades VALUES (?,?,?,?,?,?,?,?,?)', (tid, sym, bx, sx, am, pr, st, ttype, datetime.now().isoformat()))
            await db.commit()
    async def get_stats(self):
        async with aiosqlite.connect(self.db_path) as db:
            c = await db.execute('SELECT COUNT(*), SUM(profit), AVG(profit) FROM trades WHERE status="completed"')
            r = await c.fetchone()
            return {'total_trades': r[0] or 0, 'total_profit': r[1] or 0, 'avg_profit': r[2] or 0}