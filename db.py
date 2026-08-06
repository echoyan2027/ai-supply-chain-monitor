"""
SQLite 数据库封装 — 6 信号产业链监控
- 三张表: metric_meta / metric_data / signal_log
- 跟 ai-bubble-dashboard 一样的模式
"""
import sqlite3
import os
import json
from datetime import datetime, date
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)

# 用 __file__ 锁定 DB 绝对路径, 不受 CWD 影响
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_THIS_DIR, "data", "ai_supply_chain.db")

SCHEMA = """
-- 6 信号指标元数据
CREATE TABLE IF NOT EXISTS metric_meta (
    metric_key TEXT PRIMARY KEY,
    name_zh TEXT NOT NULL,
    name_en TEXT NOT NULL,
    unit TEXT,
    alert_value REAL,
    danger_value REAL,
    source TEXT,
    direction TEXT,           -- lower_is_better / higher_is_better
    update_freq TEXT,         -- daily / weekly / monthly / quarterly
    category TEXT,            -- industry / market
    signal_role TEXT,         -- huatai_signal_1/2/3/4/5/6
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 指标历史值
CREATE TABLE IF NOT EXISTS metric_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_key TEXT NOT NULL,
    obs_date TEXT NOT NULL,
    obs_period TEXT,
    value REAL NOT NULL,
    raw_payload TEXT,
    source TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(metric_key, obs_date, obs_period)
);

-- 信号评估历史
CREATE TABLE IF NOT EXISTS signal_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    eval_date TEXT NOT NULL,
    total_red INTEGER NOT NULL,
    total_yellow INTEGER NOT NULL,
    total_green INTEGER NOT NULL,
    total_gray INTEGER NOT NULL,
    stage_recommendation TEXT NOT NULL,    -- 业绩弹性高位/业绩持续性验证/景气加速/...
    details TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def get_conn():
    """获取 DB 连接 (确保父目录存在)"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_conn_ctx():
    """with 语句版本的连接"""
    conn = get_conn()
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    """初始化 DB schema"""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
    logger.info(f"DB initialized at {DB_PATH}")


def upsert_meta(metric_meta_list: list):
    """upsert 指标元数据"""
    with get_conn() as conn:
        for m in metric_meta_list:
            cols = ["metric_key", "name_zh", "name_en", "unit",
                    "alert_value", "danger_value", "source",
                    "direction", "update_freq", "category", "signal_role"]
            values = [m.get(c) for c in cols]
            placeholders = ", ".join(["?"] * len(cols))
            col_list = ", ".join(cols)
            update_set = ", ".join([f"{c}=excluded.{c}" for c in cols if c != "metric_key"])
            conn.execute(
                f"INSERT INTO metric_meta ({col_list}) VALUES ({placeholders}) "
                f"ON CONFLICT(metric_key) DO UPDATE SET {update_set}",
                values,
            )
    logger.info(f"Upserted {len(metric_meta_list)} metric meta records")


def insert_data(metric_key: str, value: float, obs_date: str = None,
                obs_period: str = None, raw_payload: dict = None,
                source: str = None):
    """插入一条指标数据 (同 metric_key+date+period 会替换)"""
    if obs_date is None:
        obs_date = date.today().isoformat()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO metric_data
              (metric_key, obs_date, obs_period, value, raw_payload, source)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                metric_key, obs_date, obs_period, value,
                json.dumps(raw_payload, ensure_ascii=False) if raw_payload else None,
                source,
            ),
        )
    logger.info(f"Inserted {metric_key} = {value} on {obs_date} (period={obs_period})")


def get_latest(metric_key: str) -> dict | None:
    """取某指标最新一条"""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM metric_data
            WHERE metric_key = ?
            ORDER BY obs_date DESC, id DESC LIMIT 1
            """,
            (metric_key,),
        ).fetchone()
        return dict(row) if row else None


def get_history(metric_key: str, limit: int = 180) -> list:
    """取某指标历史"""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM metric_data
            WHERE metric_key = ?
            ORDER BY obs_date DESC
            LIMIT ?
            """,
            (metric_key, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_meta() -> list:
    """取所有指标元数据"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM metric_meta ORDER BY signal_role, metric_key"
        ).fetchall()
        return [dict(r) for r in rows]


def log_signal(eval_date: str, total_red: int, total_yellow: int,
               total_green: int, total_gray: int, stage_recommendation: str,
               details: dict):
    """记录一次信号评估"""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO signal_log
              (eval_date, total_red, total_yellow, total_green, total_gray,
               stage_recommendation, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (eval_date, total_red, total_yellow, total_green, total_gray,
             stage_recommendation, json.dumps(details, ensure_ascii=False, default=str)),
        )
    logger.info(f"Logged signal: {stage_recommendation} (R{total_red} Y{total_yellow} G{total_green} N{total_gray})")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    print(f"DB ready at: {DB_PATH}")
