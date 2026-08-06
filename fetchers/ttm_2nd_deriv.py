"""
信号 1: 盈利兑现 — TTM 净利同比的二阶导

数据源: SEC EDGAR XBRL companyfacts
- AI 硬件主线 5 家: NVDA / AVGO / AMAT / LRCX / KLAC (篮子口径)
- 季度 TTM = 最近 4 个单季净利润合计
- 二阶导 = TTM 同比(t) - TTM 同比(t-1) (即差分)

华泰报告: "新能源 2021 年中报确认盈利二阶导拐点, 领先第一轮行情结束"
"AI 2026 年一季报, TTM 同比续创新高, 二阶导已降至 9.5pp"

数据单独存 ttm_yoy (同比) 和 ttm_2nd_deriv (二阶导) 两套 key.
"""
import json
import time
import logging
from datetime import date, datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import db

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "AI Supply Chain Monitor research@example.com",
    "Accept-Encoding": "gzip, deflate",
}
EDGAR_BASE = "https://data.sec.gov"

# AI 硬件主线 5 家 (华泰报告同口径)
AI_HARDWARE_CIKS = {
    "NVDA": "0001045810",
    "AVGO": "0001730168",
    "AMAT": "0000006951",
    "LRCX": "0000707549",
    "KLAC": "0000319201",
}
NETINCOME_TAGS = [
    "NetIncomeLoss",
    "ProfitLoss",
    "NetIncomeLossAvailableToCommonStockholdersBasic",
    "NetIncomeLossAvailableToCommonStockholdersDiluted",
]


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
    sess.headers.update(HEADERS)
    return sess


def _fetch_company_facts(cik: str, sess: requests.Session) -> dict | None:
    cik_padded = cik.zfill(10)
    url = f"{EDGAR_BASE}/api/xbrl/companyfacts/CIK{cik_padded}.json"
    try:
        r = sess.get(url, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"EDGAR companyfacts {cik} failed: {e}")
        return None


def _find_netincome(facts: dict) -> tuple | None:
    """找 netincome USD units, 返回 (tag, units)
    策略: 优先选 count 最多的 tag (覆盖时间最长)"""
    if not facts:
        return None
    candidates = []
    for ns, ns_facts in facts.get("facts", {}).items():
        for tag in NETINCOME_TAGS:
            if tag in ns_facts:
                units = ns_facts[tag].get("units", {}).get("USD", [])
                if units and len(units) >= 10:
                    candidates.append((tag, units))
    for ns, ns_facts in facts.get("facts", {}).items():
        for tag in ns_facts:
            if any(k in tag for k in ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailable"]):
                units = ns_facts[tag].get("units", {}).get("USD", [])
                if units and len(units) >= 10:
                    candidates.append((tag, units))
    if not candidates:
        return None
    candidates.sort(key=lambda x: -len(x[1]))
    return candidates[0]


def _split_to_quarters(units: list) -> list:
    """YTD → 单季净利润. 跟 ai-bubble-dashboard 的 ai_upstream_profit.py 同样算法"""
    deduped = {}
    for u in units:
        form = u.get("form")
        if form not in ("10-K", "10-Q"):
            continue
        try:
            start = u.get("start", "")
            end = u.get("end", "")
            if not start or not end:
                continue
            start_dt = datetime.strptime(start, "%Y-%m-%d").date()
            end_dt = datetime.strptime(end, "%Y-%m-%d").date()
            months = round((end_dt - start_dt).days / 30.4)
            if months not in (3, 6, 9, 12):
                continue
            if form == "10-K" and months != 12:
                continue
            if form == "10-Q" and months == 12:
                continue
            if end_dt > date.today():
                continue
            key = (end, months)
            prev = deduped.get(key)
            if prev is None or abs(u["val"]) > abs(prev["value"]):
                deduped[key] = {
                    "end": end, "end_dt": end_dt, "months": months, "value": u["val"],
                }
        except Exception:
            continue

    records = sorted(deduped.values(), key=lambda x: x["end_dt"])
    by_end = {}
    for r in records:
        e = r["end"]
        if e not in by_end or r["months"] > by_end[e]["months"]:
            by_end[e] = r

    ends_sorted = sorted(by_end.keys())
    quarters = []
    used_3m = set()
    for e in ends_sorted:
        r = by_end[e]
        e_dt = r["end_dt"]
        if r["months"] == 3:
            if e not in used_3m:
                quarters.append({"end": e, "value": r["value"]})
                used_3m.add(e)
        elif r["months"] == 6:
            q1 = None
            for prev_e in ends_sorted:
                if prev_e >= e: break
                pr = by_end[prev_e]
                if pr["months"] != 3: continue
                diff = (e_dt - pr["end_dt"]).days
                if 60 <= diff <= 130:
                    q1 = pr; break
            if q1:
                quarters.append({"end": e, "value": r["value"] - q1["value"]})
                used_3m.add(q1["end"])
        elif r["months"] == 9:
            h1 = None
            for prev_e in ends_sorted:
                if prev_e >= e: break
                pr = by_end[prev_e]
                if pr["months"] != 6: continue
                diff = (e_dt - pr["end_dt"]).days
                if 60 <= diff <= 130:
                    h1 = pr; break
            if h1:
                quarters.append({"end": e, "value": r["value"] - h1["value"]})
        elif r["months"] == 12:
            ytd9 = None
            for prev_e in ends_sorted:
                if prev_e >= e: break
                pr = by_end[prev_e]
                if pr["months"] != 9: continue
                diff = (e_dt - pr["end_dt"]).days
                if 60 <= diff <= 130:
                    ytd9 = pr; break
            if ytd9:
                quarters.append({"end": e, "value": r["value"] - ytd9["value"]})
            else:
                q1_list = []
                for prev_e in ends_sorted:
                    if prev_e >= e: break
                    pr = by_end[prev_e]
                    if pr["months"] != 3: continue
                    diff = (e_dt - pr["end_dt"]).days
                    if 60 <= diff <= 130:
                        q1_list.append(pr)
                    if len(q1_list) == 1: break
                if q1_list:
                    quarters.append({"end": e, "value": r["value"] - 4 * q1_list[0]["value"]})
    quarters.sort(key=lambda x: x["end"])
    seen = set()
    out = []
    for q in quarters:
        if q["end"] not in seen:
            out.append(q)
            seen.add(q["end"])
    return out


def _fetch_company_quarterly(cik: str, label: str) -> list:
    sess = _make_session()
    facts = _fetch_company_facts(cik, sess)
    if not facts: return []
    result = _find_netincome(facts)
    if not result: return []
    tag, units = result
    quarters = _split_to_quarters(units)
    quarters.sort(key=lambda x: x["end"])
    logger.info(f"{label} ({cik}): {len(quarters)} quarterly records (tag={tag})")
    return quarters


def _calc_ttm(quarters: list, as_of: str) -> float | None:
    """算 as_of 时点的 TTM (最近 4 个单季)"""
    valid = [q for q in quarters if q["end"] <= as_of]
    if len(valid) < 4: return None
    return sum(q["value"] for q in valid[-4:])


def _latest_calendar_quarter_end(today: date | None = None) -> str:
    today = today or date.today()
    for m, d in [(3, 31), (6, 30), (9, 30), (12, 31)]:
        try:
            qe = date(today.year, m, d)
            if qe <= today:
                return qe.strftime("%Y-%m-%d")
        except Exception:
            continue
    return f"{today.year - 1}-12-31"


def _prev_calendar_quarter_end(as_of: str) -> str:
    """算 as_of 的前一个 quarter end"""
    dt = datetime.strptime(as_of, "%Y-%m-%d").date()
    if dt.month == 3:
        return f"{dt.year - 1}-12-31"
    if dt.month == 6:
        return f"{dt.year}-03-31"
    if dt.month == 9:
        return f"{dt.year}-06-30"
    return f"{dt.year}-09-30"


def fetch_ttm_2nd_deriv() -> dict:
    """
    拉 AI 硬件 5 家 TTM 净利, 算同比和二阶导
    """
    quarterly_data = {}
    for label, cik in AI_HARDWARE_CIKS.items():
        try:
            q = _fetch_company_quarterly(cik, label)
            if q:
                quarterly_data[label] = q
        except Exception as e:
            logger.warning(f"{label} fetch failed: {e}")
        time.sleep(0.3)

    if len(quarterly_data) < 3:
        return {"error": "insufficient data", "available": list(quarterly_data.keys())}

    as_of = _latest_calendar_quarter_end()
    prev_q = _prev_calendar_quarter_end(as_of)
    logger.info(f"Computing TTM as of {as_of} (vs {prev_q} for 同比)")

    # 当前 TTM 5 家合计
    ttm_now = 0
    breakdown_now = {}
    for label, qs in quarterly_data.items():
        ttm = _calc_ttm(qs, as_of)
        if ttm is not None:
            ttm_now += ttm
            breakdown_now[label] = ttm / 1e9

    # 上一年同期 TTM (4 个季度前)
    ttm_prev_year = 0
    breakdown_prev = {}
    for label, qs in quarterly_data.items():
        # "去年同期" = 上一年的同 quarter end
        dt = datetime.strptime(as_of, "%Y-%m-%d").date()
        yoy_end = f"{dt.year - 1}-{dt.month:02d}-{dt.day:02d}"
        ttm_yoy = _calc_ttm(qs, yoy_end)
        if ttm_yoy is not None and ttm_yoy > 0:
            ttm_prev_year += ttm_yoy
            breakdown_prev[label] = ttm_yoy / 1e9

    if ttm_now == 0 or ttm_prev_year == 0:
        return {"error": "TTM data missing",
                "as_of": as_of,
                "ttm_now_b": ttm_now / 1e9,
                "ttm_prev_year_b": ttm_prev_year / 1e9}

    # TTM 同比
    yoy_pct = (ttm_now - ttm_prev_year) / ttm_prev_year * 100

    # TTM 同比的前一季度 (3 个月前)
    dt = datetime.strptime(as_of, "%Y-%m-%d").date()
    prev_3m_end = ""
    if dt.month >= 4:
        prev_3m_end = f"{dt.year}-{dt.month-3:02d}-{dt.day:02d}"
    else:
        prev_3m_end = f"{dt.year-1}-{dt.month+9:02d}-{dt.day:02d}"
    ttm_prev_3m = 0
    ttm_prev_3m_yoy_ref = 0
    for label, qs in quarterly_data.items():
        ttm = _calc_ttm(qs, prev_3m_end)
        if ttm is not None: ttm_prev_3m += ttm
        # 前一季度对应的"去年同期"
        pdt = datetime.strptime(prev_3m_end, "%Y-%m-%d").date()
        yoy_ref = f"{pdt.year - 1}-{pdt.month:02d}-{pdt.day:02d}"
        ttm_yoy_ref = _calc_ttm(qs, yoy_ref)
        if ttm_yoy_ref is not None and ttm_yoy_ref > 0:
            ttm_prev_3m_yoy_ref += ttm_yoy_ref

    yoy_prev_3m_pct = ((ttm_prev_3m - ttm_prev_3m_yoy_ref) / ttm_prev_3m_yoy_ref * 100) if ttm_prev_3m_yoy_ref > 0 else 0

    # 二阶导 = 当前同比 - 前一季度同比 (单位: pp)
    second_deriv = yoy_pct - yoy_prev_3m_pct

    # 写 DB
    db.insert_data(
        "ttm_2nd_deriv", second_deriv, obs_date=as_of,
        source="sec_edgar_ttm",
        raw_payload={
            "as_of": as_of,
            "ttm_now_b": ttm_now / 1e9,
            "ttm_prev_year_b": ttm_prev_year / 1e9,
            "yoy_pct": yoy_pct,
            "yoy_prev_3m_pct": yoy_prev_3m_pct,
            "second_deriv_pp": second_deriv,
            "breakdown_now_b": breakdown_now,
            "breakdown_prev_b": breakdown_prev,
        },
    )
    # 也存 yoy_pct 单独 series
    db.insert_data(
        "ttm_yoy_pct", yoy_pct, obs_date=as_of,
        source="sec_edgar_ttm",
        raw_payload={"second_deriv_pp": second_deriv},
    )

    logger.info(f"TTM 同比: {yoy_pct:.1f}%, 1Q 前同比: {yoy_prev_3m_pct:.1f}%, "
                f"二阶导: {second_deriv:.2f}pp")
    return {
        "metric_key": "ttm_2nd_deriv",
        "value": second_deriv,
        "obs_date": as_of,
        "second_deriv_pp": second_deriv,
        "yoy_pct": yoy_pct,
        "yoy_prev_3m_pct": yoy_prev_3m_pct,
        "ttm_now_b": ttm_now / 1e9,
        "ttm_prev_year_b": ttm_prev_year / 1e9,
        "breakdown_now_b": breakdown_now,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    print(json.dumps(fetch_ttm_2nd_deriv(), indent=2, ensure_ascii=False, default=str))
