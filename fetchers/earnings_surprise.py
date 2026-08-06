"""
信号 1 衍生: 业绩超预期反应 — 财报披露 N 天后股价表现

数据源: 腾讯 K 线 A 股
代理: AI 硬件主线 (sh159995 半导体 ETF) 月度涨跌幅 vs 沪深 300
简化: 不追踪单只个股财报日 (数据难拿), 用"中报披露季前后的板块超额收益"作为
      "市场对业绩季的反应"代理

算法:
- 取 A 股中报披露期 (7-8月) 和年报披露期 (3-4月)
- 期间超额收益 = 半导体 ETF 涨幅 - 沪深 300 ETF 涨幅
- 数值 > 0 = 业绩季正面反应, < 0 = 钝化/负面反应

简化阈值: 正反应 vs 负反应 vs 中性
"""
import json
import logging
from datetime import date, datetime, timedelta
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import db
from fetchers.crowding import _fetch_tencent_kline, MAINLINE, NONMAINLINE

logger = logging.getLogger(__name__)


def _period_return(kline: list, start_date: str, end_date: str) -> float | None:
    """算 kline 在 [start, end] 期间的累计涨幅"""
    if not kline:
        return None
    kline_map = {k["date"]: k["close"] for k in kline}
    # 找最接近 start 的日期
    sorted_dates = sorted(kline_map.keys())
    if not sorted_dates:
        return None
    actual_start = None
    actual_end = None
    for d in sorted_dates:
        if d >= start_date and actual_start is None:
            actual_start = d
        if d <= end_date:
            actual_end = d
    if not actual_start or not actual_end or actual_start == actual_end:
        return None
    return (kline_map[actual_end] - kline_map[actual_start]) / kline_map[actual_start]


def fetch_earnings_surprise() -> dict:
    """算最近一个财报披露季的主线 vs 非主线超额收益"""
    today = date.today()
    year = today.year

    # 财报披露季:
    # - 年报 + 一季报: 4-5月披露
    # - 半年报: 7-8月披露
    # - 三季报: 10月披露
    if today.month >= 4 and today.month <= 5:
        period_label = f"{year}年报+1Q"
        start = f"{year}-04-01"
        end = f"{year}-05-31"
    elif today.month >= 7 and today.month <= 9:
        period_label = f"{year}中报"
        start = f"{year}-07-01"
        end = f"{year}-08-31"
    elif today.month >= 10 and today.month <= 11:
        period_label = f"{year}3Q报"
        start = f"{year}-10-01"
        end = f"{year}-10-31"
    else:
        # 1-3月: 用上一个中报季 (因为当季还未开始)
        period_label = f"{year - 1}中报"
        start = f"{year - 1}-07-01"
        end = f"{year - 1}-08-31"

    logger.info(f"Earnings surprise period: {period_label} ({start} to {end})")

    main_kline = _fetch_tencent_kline(MAINLINE["symbol"], days=400)
    nonmain_kline = _fetch_tencent_kline(NONMAINLINE["symbol"], days=400)
    if not main_kline or not nonmain_kline:
        return {"error": "kline fetch failed", "period": period_label}

    main_ret = _period_return(main_kline, start, end)
    nonmain_ret = _period_return(nonmain_kline, start, end)
    if main_ret is None or nonmain_ret is None:
        return {"error": "no data in period", "period": period_label}

    excess_return = (main_ret - nonmain_ret) * 100  # pp

    db.insert_data(
        "earnings_surprise", excess_return, obs_date=f"{end}",
        source="tencent_kline",
        raw_payload={
            "period_label": period_label,
            "period_start": start,
            "period_end": end,
            "main_ret_pct": main_ret * 100,
            "nonmain_ret_pct": nonmain_ret * 100,
            "excess_return_pp": excess_return,
        },
    )

    # 解读
    if excess_return > 5:
        signal = "正面 (市场对利好积极反应)"
        status = "green"
    elif excess_return > 0:
        signal = "温和正面"
        status = "green"
    elif excess_return > -5:
        signal = "钝化 (反应不及预期)"
        status = "yellow"
    else:
        signal = "负面 (利好利空均抛售)"
        status = "red"

    logger.info(f"Earnings surprise: {period_label} 超额收益 {excess_return:.1f}pp → {signal}")
    return {
        "metric_key": "earnings_surprise",
        "value": excess_return,
        "obs_date": end,
        "excess_return_pp": excess_return,
        "period_label": period_label,
        "signal": signal,
        "status": status,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    print(json.dumps(fetch_earnings_surprise(), indent=2, ensure_ascii=False, default=str))
