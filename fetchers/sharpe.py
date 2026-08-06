"""
信号 6: 行为反馈 — 主线 120 日滚动夏普比

主线: sh159995 (华夏国证半导体芯片 ETF)
算法:
- 取过去 250 个交易日
- 每日 120 日滚动夏普 = (120 日均收益) / (120 日收益 std) * sqrt(252)
- 阈值: 突破 2 = 黄灯 (抱团), 跌破 1 = 红灯 (松动)

为什么 120d 滚动:
- 华泰报告: 120 日滚动夏普, "突破 2 后适度控制仓位, 跌破 1 = 松动确认"
- 120 个交易日约 6 个月, 适合捕捉中期资金共识
"""
import json
import logging
import math
from datetime import date, datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import db
from fetchers.crowding import _fetch_tencent_kline, MAINLINE

logger = logging.getLogger(__name__)

WINDOW_SHARPE = 120  # 120 日
WINDOW_1Y = 250      # 1 年滚动
TRADING_DAYS_YEAR = 252  # 年化


def _rolling_sharpe(closes: list, window: int) -> list:
    """计算滚动 window 日夏普 (年化)
    returns[i] = (mean(returns[i-window+1:i+1]) / std(returns[i-window+1:i+1])) * sqrt(252)
    returns = 日对数收益 = ln(close[t] / close[t-1])
    """
    # 日对数收益
    log_rets = [None]
    for i in range(1, len(closes)):
        if closes[i - 1] > 0 and closes[i] > 0:
            log_rets.append(math.log(closes[i] / closes[i - 1]))
        else:
            log_rets.append(None)

    sharpes = [None] * len(closes)
    for i in range(window, len(closes)):
        window_rets = [log_rets[j] for j in range(i - window + 1, i + 1) if log_rets[j] is not None]
        if len(window_rets) < window * 0.9:  # 允许 10% 缺失
            continue
        mean_r = sum(window_rets) / len(window_rets)
        var_r = sum((r - mean_r) ** 2 for r in window_rets) / len(window_rets)
        std_r = var_r ** 0.5
        if std_r > 0:
            sharpes[i] = (mean_r / std_r) * math.sqrt(TRADING_DAYS_YEAR)
    return sharpes


def fetch_sharpe() -> dict:
    """拉半导体 ETF K 线, 算 120 日滚动夏普"""
    logger.info(f"Fetching {MAINLINE['name']} ({MAINLINE['symbol']}) for 120d Sharpe...")
    kline = _fetch_tencent_kline(MAINLINE["symbol"], days=400)
    if not kline or len(kline) < WINDOW_SHARPE + WINDOW_1Y:
        return {"error": "insufficient kline", "len": len(kline) if kline else 0}

    kline.sort(key=lambda x: x["date"])
    closes = [k["close"] for k in kline]
    dates = [k["date"] for k in kline]
    sharpes = _rolling_sharpe(closes, WINDOW_SHARPE)
    # 取最后一点
    current_sharpe = sharpes[-1]
    if current_sharpe is None:
        return {"error": "current sharpe is None", "last_sharpes": sharpes[-5:]}

    obs_date = dates[-1]
    db.insert_data(
        "sharpe_120d", current_sharpe, obs_date=obs_date,
        source="tencent_kline",
        raw_payload={
            "mainline": MAINLINE,
            "window": WINDOW_SHARPE,
            "current_sharpe": current_sharpe,
            "annualized_factor": math.sqrt(TRADING_DAYS_YEAR),
            "kline_count": len(kline),
        },
    )
    logger.info(f"Sharpe 120d: {current_sharpe:.2f} (突破 2 = 抱团, 跌破 1 = 松动)")
    return {
        "metric_key": "sharpe_120d",
        "value": current_sharpe,
        "obs_date": obs_date,
        "sharpe": current_sharpe,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    print(json.dumps(fetch_sharpe(), indent=2, ensure_ascii=False, default=str))
