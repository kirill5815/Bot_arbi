import aiosqlite
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trades.db')

class Database:
    def __init__(self):
        self.db_path = DB_PATH
    
    async def init(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY,
                    symbol TEXT,
                    buy_exchange TEXT,
                    sell_exchange TEXT,
                    amount REAL,
                    profit REAL,
                    status TEXT,
                    created_at TEXT
                )
            ''')
            await db.commit()
    
    async def save_trade(self, trade_id, symbol, buy_ex, 
                         sell_ex, amount, profit, status):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                INSERT OR REPLACE INTO trades 
                (id, symbol, buy_exchange, sell_exchange, amount, profit, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (trade_id, symbol, buy_ex, sell_ex, amount, profit, status, datetime.now().isoformat()))
            await db.commit()
    
    async def get_stats(self):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('''
                SELECT COUNT(*), SUM(profit), AVG(profit) 
                FROM trades WHERE status = 'completed'
            ''')
            row = await cursor.fetchone()
            return {
                'total_trades': row[0] or 0,
                'total_profit': row[1] or 0,
                'avg_profit': row[2] or 0
            }