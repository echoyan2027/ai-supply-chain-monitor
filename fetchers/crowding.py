"""
信号 5: 资金拥挤 — 主线 vs 非主线 3 个月涨幅差 (滚动 1 年 z-score)

主线: sh159995 (华夏国证半导体芯片 ETF) — A 股 AI 硬件主线
非主线: sh510310 (沪深 300 ETF) — 大盘基准

数据源: 腾讯 K 线 A 股日 K
算法:
- 取过去 250 个交易日 (约 1 年滚动窗口)
- 计算每日 3 个月涨幅差 = (主线过去 63 日涨幅) - (非主线过去 63 日涨幅)
- z-score = (当前 3 月涨幅差 - 滚动 1 年均值) / 滚动 1 年 std
- 阈值: z-score ≥ 1 = 黄灯, ≥ 2 = 红灯 (华泰报告 AI 当前 +4σ)

为什么用 A 股 ETF 而非美股 Mag 7:
- 用户定位 A 股产业链深度内容
- A 股 ETF 直接反映国内资金对 AI 主线的定价
- 拥挤度的核心是"资金聚集效应", A 股 ETF 成交量/资金流更直接
"""
import json
import logging
from datetime import date, datetime, timedelta
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import db

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

# 主线 = A 股半导体 ETF, 非主线 = 沪深 300 ETF
MAINLINE = {"symbol": "sh159995", "name": "半导体ETF"}
NONMAINLINE = {"symbol": "sh510310", "name": "沪深300ETF"}

# 3 个月窗口 (交易日)
WINDOW_3M = 63
# 滚动 1 年窗口 (交易日)
WINDOW_1Y = 250


def _make_session() -> requests.Session:
    sess = requests.Session()
    retry = Retry(
        total=3, backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=5, pool_maxsize=5)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    sess.headers.update({"User-Agent": UA, "Referer": "https://gu.qq.com/"})
    return sess


def _fetch_tencent_kline(symbol: str, days: int = 365) -> list:
    """拉 A 股日 K 线 (用腾讯)
    返回: [{"date": "2026-07-03", "open":..., "close":..., "high":..., "low":..., "volume":...}, ...]
    注: 腾讯 K 线 API 只返回 2 个边界点 (前 + 后), 历史数据用 daily fqKLine 接口
    """
    sess = _make_session()
    # 用 fqDay 参数拉长历史
    url = TENCENT_KLINE_URL
    params = {
        "param": f"{symbol},day,,,{days},qfq",
    }
    try:
        resp = sess.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        # data = {"code":0, "data":{"sh159995":{"qfqday":[[date,open,close,high,low,vol],...], "day":..., "qfqday":...}}}
        if data.get("code") != 0:
            logger.warning(f"Tencent kline {symbol}: code={data.get('code')}")
            return []
        symbol_data = data.get("data", {}).get(symbol, {})
        # 优先用 qfqday (前复权), 没有就用 day
        klines = symbol_data.get("qfqday") or symbol_data.get("day") or []
        out = []
        for row in klines:
            try:
                d, o, c, h, l, v = row[:6]
                out.append({
                    "date": d,
                    "open": float(o),
                    "close": float(c),
                    "high": float(h),
                    "low": float(l),
                    "volume": float(v),
                })
            except Exception:
                continue
        return out
    except Exception as e:
        logger.warning(f"Tencent kline {symbol} failed: {e}")
        return []


def _rolling_return(closes: list, window: int) -> list:
    """计算滚动 window 日收益率 (每点对应 (close[t] - close[t-window]) / close[t-window])"""
    out = [None] * window
    for i in range(window, len(closes)):
        if closes[i - window] > 0:
            out.append((closes[i] - closes[i - window]) / closes[i - window])
        else:
            out.append(None)
    return out


def fetch_crowding() -> dict:
    """
    拉主线 + 非主线 K 线, 计算 3 月涨幅差的 z-score
    输出: zscore, main_ret_3m, nonmain_ret_3m, diff_pp
    """
    logger.info(f"Fetching {MAINLINE['name']} ({MAINLINE['symbol']}) K线...")
    main_kline = _fetch_tencent_kline(MAINLINE["symbol"], days=400)
    logger.info(f"Fetching {NONMAINLINE['name']} ({NONMAINLINE['symbol']}) K线...")
    nonmain_kline = _fetch_tencent_kline(NONMAINLINE["symbol"], days=400)

    if not main_kline or not nonmain_kline:
        return {"error": "tencent kline fetch failed",
                "main_count": len(main_kline),
                "nonmain_count": len(nonmain_kline)}

    # 对齐日期 (取交集)
    main_map = {k["date"]: k["close"] for k in main_kline}
    nonmain_map = {k["date"]: k["close"] for k in nonmain_kline}
    common_dates = sorted(set(main_map.keys()) & set(nonmain_map.keys()))
    if len(common_dates) < WINDOW_1Y + WINDOW_3M:
        return {"error": "insufficient common dates",
                "common_count": len(common_dates),
                "min_required": WINDOW_1Y + WINDOW_3M}

    main_closes = [main_map[d] for d in common_dates]
    nonmain_closes = [nonmain_map[d] for d in common_dates]

    # 3 月涨幅差序列
    main_ret_3m = _rolling_return(main_closes, WINDOW_3M)
    nonmain_ret_3m = _rolling_return(nonmain_closes, WINDOW_3M)
    diff_seq = []
    for i in range(len(common_dates)):
        if main_ret_3m[i] is not None and nonmain_ret_3m[i] is not None:
            diff_seq.append(main_ret_3m[i] - nonmain_ret_3m[i])

    if len(diff_seq) < WINDOW_1Y:
        return {"error": "diff_seq too short", "len": len(diff_seq)}

    # 当前 3 月涨幅差 (最后一点)
    current_diff = diff_seq[-1]
    # 滚动 1 年均值 + std
    window_seq = diff_seq[-WINDOW_1Y:]
    rolling_mean = sum(window_seq) / len(window_seq)
    rolling_var = sum((x - rolling_mean) ** 2 for x in window_seq) / len(window_seq)
    rolling_std = rolling_var ** 0.5 if rolling_var > 0 else 1e-6
    zscore = (current_diff - rolling_mean) / rolling_std if rolling_std > 0 else 0

    obs_date = common_dates[-1]
    # 写 DB
    db.insert_data(
        "crowding_zscore", zscore, obs_date=obs_date,
        source="tencent_kline",
        raw_payload={
            "current_diff_pp": current_diff * 100,
            "rolling_mean_pp": rolling_mean * 100,
            "rolling_std_pp": rolling_std * 100,
            "mainline": MAINLINE,
            "nonmainline": NONMAINLINE,
            "main_ret_3m_pp": main_ret_3m[-1] * 100 if main_ret_3m[-1] is not None else None,
            "nonmain_ret_3m_pp": nonmain_ret_3m[-1] * 100 if nonmain_ret_3m[-1] is not None else None,
            "common_dates_count": len(common_dates),
        },
    )
    # 也存 diff_pp 原始值
    db.insert_data(
        "crowding_diff_pp", current_diff * 100, obs_date=obs_date,
        source="tencent_kline",
        raw_payload={"zscore": zscore},
    )

    logger.info(f"Crowding: diff={current_diff*100:.1f}pp mean={rolling_mean*100:.1f}pp "
                f"std={rolling_std*100:.1f}pp zscore={zscore:.2f}")
    return {
        "metric_key": "crowding_zscore",
        "value": zscore,
        "obs_date": obs_date,
        "zscore": zscore,
        "current_diff_pp": current_diff * 100,
        "rolling_mean_pp": rolling_mean * 100,
        "rolling_std_pp": rolling_std * 100,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    print(json.dumps(fetch_crowding(), indent=2, ensure_ascii=False, default=str))
