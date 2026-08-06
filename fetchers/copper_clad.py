"""
信号 3: 业绩空间"价" — 覆铜板/存储价 (MOM 涨幅)

数据源: 新浪 A 股 K 线 (国内可访问)
代理: 生益科技 (600183.SH) — 国内覆铜板龙头, 月度 K 线 MOM
(华泰报告用覆铜板出口单价, 海关数据需另查, 用生益科技股价作为公开可获取代理)

为什么 MOM 而不是价格绝对值:
- 华泰报告关注"涨价动能放缓" — 重点是价格变化率, 不是绝对价
- MOM 转负 = 涨价放缓 = 高位确认信号
- 6 月 MOM > 0 = 仍在涨价 (华泰报告 7 月观察: 仍在涨, 接受度下降)

存储侧: 兆易创新 (603986) 作为辅助指标 (已在 ai-bubble-dashboard 用)
"""
import re
import json
import logging
from datetime import datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import db

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

COPPER_CLAD_STOCK = {"code": "600183", "symbol": "sh600183", "name": "生益科技"}


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


def _fetch_kline(symbol: str, days: int = 200) -> list:
    """拉 A 股日 K 线 (腾讯 qfq 前复权, 避免除权跳空)
    返回: [{"date": "2026-07-03", "open":..., "close":..., "high":..., "low":..., "volume":...}, ...]
    """
    sess = _make_session()
    params = {"param": f"{symbol},day,,,{days},qfq"}
    try:
        resp = sess.get(TENCENT_KLINE_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            logger.warning(f"Tencent kline {symbol}: code={data.get('code')}")
            return []
        symbol_data = data.get("data", {}).get(symbol, {})
        # 优先 qfqday (前复权), 没有就用 day
        klines = symbol_data.get("qfqday") or symbol_data.get("day") or []
        out = []
        for row in klines:
            try:
                d, o, c, h, l, v = row[:6]
                close = float(c)
                if close <= 0:
                    continue
                out.append({
                    "date": d,
                    "close": close,
                    "open": float(o),
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


def _last_month_end(history: list) -> dict | None:
    """找最近一个月末 (>=25 日)"""
    for h in reversed(history):
        try:
            if int(h["date"].split("-")[2]) >= 25:
                return h
        except Exception:
            continue
    return None


def _prev_month_end(history: list, ref_end_date: str) -> dict | None:
    """找 ref_end_date 的前一个月末"""
    ref_dt = datetime.strptime(ref_end_date, "%Y-%m-%d").date()
    target_year = ref_dt.year
    target_month = ref_dt.month - 1
    if target_month == 0:
        target_month = 12
        target_year -= 1
    # 先精确找 (target_year, target_month) 月末
    for h in reversed(history):
        try:
            hd = datetime.strptime(h["date"], "%Y-%m-%d").date()
            if hd.year == target_year and hd.month == target_month and hd.day >= 25:
                return h
        except Exception:
            continue
    # 兜底: 任何在 ref 之前的最近月末
    for h in reversed(history):
        try:
            hd = datetime.strptime(h["date"], "%Y-%m-%d").date()
            if hd < ref_dt and hd.day >= 25:
                return h
        except Exception:
            continue
    return None


def fetch_copper_clad() -> dict:
    """拉生益科技 K 线, 算月环比 MOM"""
    logger.info(f"Fetching {COPPER_CLAD_STOCK['name']} ({COPPER_CLAD_STOCK['symbol']}) K线...")
    kline = _fetch_kline(COPPER_CLAD_STOCK["symbol"], days=200)
    if not kline or len(kline) < 30:
        return {"error": "kline fetch failed or too short", "len": len(kline) if kline else 0}

    last_month = _last_month_end(kline)
    if not last_month:
        return {"error": "no month-end found", "kline_len": len(kline)}
    prev_month = _prev_month_end(kline, last_month["date"])
    if not prev_month or prev_month["date"] == last_month["date"]:
        prev_month = kline[-30] if len(kline) >= 30 else kline[0]

    mom_pct = (last_month["close"] - prev_month["close"]) / prev_month["close"] * 100

    obs_date = last_month["date"]
    db.insert_data(
        "copper_clad_mom", mom_pct, obs_date=obs_date,
        source="sina_kline_生益科技",
        raw_payload={
            "stock": COPPER_CLAD_STOCK,
            "last_close": last_month["close"],
            "prev_close": prev_month["close"],
            "last_date": last_month["date"],
            "prev_date": prev_month["date"],
        },
    )

    logger.info(f"生益科技月环比: {mom_pct:.2f}% (last={last_month['date']} prev={prev_month['date']})")
    return {
        "metric_key": "copper_clad_mom",
        "value": mom_pct,
        "obs_date": obs_date,
        "mom_pct": mom_pct,
        "last_close": last_month["close"],
        "prev_close": prev_month["close"],
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    print(json.dumps(fetch_copper_clad(), indent=2, ensure_ascii=False, default=str))
