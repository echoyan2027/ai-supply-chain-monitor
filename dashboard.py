"""
仪表盘评估与生成模块 — 6 信号体系
- evaluate(): 评估 6 个信号 + 判断阶段
- render_dashboard(): 生成 HTML 仪表盘
"""
import os
import json
import logging
from datetime import date
from typing import Optional

import db
from config import (
    DASHBOARD_TITLE, DASHBOARD_SUBTITLE, COLORS, SIGNAL_THRESHOLDS, STAGE_RULES,
    LOG_DIR, LOG_FILE,
)

logger = logging.getLogger(__name__)

# 6 信号元数据
METRICS_META = [
    {
        "metric_key": "ttm_2nd_deriv",
        "signal_role": "1",
        "name_zh": "TTM 净利二阶导",
        "name_en": "TTM Net Income 2nd Derivative",
        "unit": "pp",
        "alert_value": SIGNAL_THRESHOLDS["ttm_2nd_deriv"]["alert_value"],
        "danger_value": SIGNAL_THRESHOLDS["ttm_2nd_deriv"]["danger_value"],
        "source": "SEC EDGAR XBRL (5 家 AI 硬件)",
        "direction": SIGNAL_THRESHOLDS["ttm_2nd_deriv"]["direction"],
        "update_freq": "quarterly",
        "category": "industry",
        "desc": SIGNAL_THRESHOLDS["ttm_2nd_deriv"]["source_desc"] +
                " 二阶导 = TTM 同比(t) - TTM 同比(t-1). 9.5pp 是华泰报告观察的 2021 新能源拐点值",
    },
    {
        "metric_key": "capex_2nd_deriv",
        "signal_role": "2",
        "name_zh": "CSP Capex 二阶导",
        "name_en": "CSP Capex 2nd Derivative (TTM YoY)",
        "unit": "pp",
        "alert_value": SIGNAL_THRESHOLDS["capex_2nd_deriv"]["alert_value"],
        "danger_value": SIGNAL_THRESHOLDS["capex_2nd_deriv"]["danger_value"],
        "source": "SEC EDGAR XBRL (MSFT/AMZN/GOOGL/META)",
        "direction": SIGNAL_THRESHOLDS["capex_2nd_deriv"]["direction"],
        "update_freq": "quarterly",
        "category": "industry",
        "desc": SIGNAL_THRESHOLDS["capex_2nd_deriv"]["source_desc"] +
                " 二阶导 = Capex 同比(t) - 同比(t-1). 华泰报告: 3Q26 或为高点",
    },
    {
        "metric_key": "copper_clad_mom",
        "signal_role": "3",
        "name_zh": "覆铜板 MOM (生益科技代理)",
        "name_en": "Copper Clad MoM (Shengyi Tech Proxy)",
        "unit": "%",
        "alert_value": SIGNAL_THRESHOLDS["copper_clad_mom"]["alert_value"],
        "danger_value": SIGNAL_THRESHOLDS["copper_clad_mom"]["danger_value"],
        "source": "新浪/腾讯 K 线 (600183.SH 前复权)",
        "direction": SIGNAL_THRESHOLDS["copper_clad_mom"]["direction"],
        "update_freq": "daily",
        "category": "industry",
        "desc": SIGNAL_THRESHOLDS["copper_clad_mom"]["source_desc"],
    },
    {
        "metric_key": "earnings_surprise",
        "signal_role": "1-衍生",
        "name_zh": "业绩季超额收益 (主线 - 非主线)",
        "name_en": "Earnings Season Excess Return",
        "unit": "pp",
        "alert_value": -5,
        "danger_value": -10,
        "source": "腾讯 K 线 (财报披露季窗口)",
        "direction": "lower_is_better",
        "update_freq": "quarterly",
        "category": "industry",
        "desc": "中报/年报披露季 (4-5月 / 7-8月) 半导体 ETF 超额收益. "
                "正值 = 正面反应 (定价有空间), 负值 = 钝化/负面 (定价充分)",
    },
    {
        "metric_key": "crowding_zscore",
        "signal_role": "5",
        "name_zh": "拥挤度 (主线 vs 非主线 z-score)",
        "name_en": "Crowding Z-Score (Mainline vs Non-Mainline)",
        "unit": "σ",
        "alert_value": SIGNAL_THRESHOLDS["crowding_zscore"]["alert_value"],
        "danger_value": SIGNAL_THRESHOLDS["crowding_zscore"]["danger_value"],
        "source": "腾讯 K 线 (sh159995 vs sh510310)",
        "direction": SIGNAL_THRESHOLDS["crowding_zscore"]["direction"],
        "update_freq": "daily",
        "category": "market",
        "desc": SIGNAL_THRESHOLDS["crowding_zscore"]["source_desc"] +
                " z = (3 月涨幅差 - 1 年均值) / 1 年 std. AI 当前 +4σ (2026-06)",
    },
    {
        "metric_key": "sharpe_120d",
        "signal_role": "6",
        "name_zh": "主线 120 日夏普比",
        "name_en": "Mainline 120d Rolling Sharpe",
        "unit": "x",
        "alert_high": SIGNAL_THRESHOLDS["sharpe_120d"]["alert_high"],
        "alert_low": SIGNAL_THRESHOLDS["sharpe_120d"]["alert_low"],
        "danger_high": SIGNAL_THRESHOLDS["sharpe_120d"]["danger_high"],
        "danger_low": SIGNAL_THRESHOLDS["sharpe_120d"]["danger_low"],
        "source": "腾讯 K 线 (sh159995 日对数收益)",
        "direction": SIGNAL_THRESHOLDS["sharpe_120d"]["direction"],
        "update_freq": "daily",
        "category": "market",
        "desc": SIGNAL_THRESHOLDS["sharpe_120d"]["source_desc"] +
                " 双向危险: 突破 2 = 抱团, 跌破 1 = 松动",
    },
]


def _judge_status(metric: dict, value: Optional[float]) -> str:
    """判断信号灯色 (红/黄/绿/灰)"""
    if value is None:
        return "gray"
    direction = metric.get("direction", "lower_is_better")

    # 双向危险 (sharpe)
    if direction == "two_sided":
        if "alert_high" in metric:
            if value >= metric["danger_high"] or value <= metric["danger_low"]:
                return "red"
            if value >= metric["alert_high"] or value <= metric["alert_low"]:
                return "yellow"
            return "green"
    elif direction == "lower_is_better":
        if value <= metric["danger_value"]:
            return "red"
        if value <= metric["alert_value"]:
            return "yellow"
        return "green"
    else:  # higher_is_better
        if value >= metric["danger_value"]:
            return "red"
        if value >= metric["alert_value"]:
            return "yellow"
        return "green"


def _judge_stage(metrics_status: list) -> dict:
    """根据 6 信号状态判断所处阶段 (华泰两阶段框架)"""
    by_key = {m["metric_key"]: m for m in metrics_status}
    ttm_2nd = by_key.get("ttm_2nd_deriv", {}).get("value")
    capex_2nd = by_key.get("capex_2nd_deriv", {}).get("value")
    crowding = by_key.get("crowding_zscore", {}).get("value")
    sharpe = by_key.get("sharpe_120d", {}).get("value")
    copper = by_key.get("copper_clad_mom", {}).get("value")

    # 阶段 1 高位: TTM 二阶导 ≤ -5 (拐点确认) + 拥挤已消化 + 夏普已松动
    if (ttm_2nd is not None and ttm_2nd <= -5
        and crowding is not None and crowding <= 1.0
        and sharpe is not None and sharpe <= 1.5):
        return {
            "stage": "stage_1_high",
            "label": STAGE_RULES["stage_1_high"]["label"],
            "advice": STAGE_RULES["stage_1_high"]["advice"],
            "color": "#ef4444",
        }
    # 阶段 1 消化中: 资金面已松动 (拥挤 ≤ 0, 夏普 ≤ 1, 覆铜板转负) + 但 TTM 二阶导仍未转负
    if (crowding is not None and crowding <= 0
        and sharpe is not None and sharpe <= 1.0
        and (copper is not None and copper < 0)
        and ttm_2nd is not None and ttm_2nd > 0):
        return {
            "stage": "stage_1_digest",
            "label": "业绩弹性消化中 (资金已松动, 基本面待验证)",
            "advice": "估值超调后反弹能见度提升. 等待 8 月中报确认 TTM 二阶导是否拐头, "
                      "或新需求场景 (应用落地/政策利好) 拉动. 主线跑输 -2σ 以下, 适度建仓业绩能见度高的环节",
            "color": "#f59e0b",
        }
    # 阶段 2 重新加速: TTM 二阶导 ≤ 0 (但) + Capex 二阶导 ≤ -10 (确认 Capex 拐点)
    if (ttm_2nd is not None and ttm_2nd <= 0
        and capex_2nd is not None and capex_2nd <= -10):
        return {
            "stage": "stage_2_renew",
            "label": STAGE_RULES["stage_2_renew"]["label"],
            "advice": STAGE_RULES["stage_2_renew"]["advice"],
            "color": "#3b82f6",
        }
    # 景气加速 (主升段): TTM 二阶导 ≥ 5 + Capex 二阶导 ≥ 5 + 夏普 ≥ 2
    if (ttm_2nd is not None and ttm_2nd >= 5
        and capex_2nd is not None and capex_2nd >= 5
        and sharpe is not None and sharpe >= 2):
        return {
            "stage": "stage_accelerating",
            "label": STAGE_RULES["stage_accelerating"]["label"],
            "advice": STAGE_RULES["stage_accelerating"]["advice"],
            "color": "#10b981",
        }
    # 业绩弹性定价充分 (未确认): 资金面松 + 基本面仍有二阶导 + 覆铜板放缓
    if (crowding is not None and abs(crowding) > 1.5
        and sharpe is not None and sharpe < 1.5
        and (copper is not None and copper < 0)):
        return {
            "stage": "stage_1_high_unconfirmed",
            "label": "业绩弹性定价相对充分 (资金 + 覆铜板已松动, 中报待验证)",
            "advice": "资金 + 板块情绪面 + 覆铜板价 三重信号松动, 但 TTM/Capex 二阶导仍未转负. "
                      "跟踪 8 月中报 (待 8 月底) 与 Capex 二阶导拐点 (3Q26 一致预期). "
                      "适度控制仓位, 主配业绩能见度高的环节 (PCB/光模块/电源)",
            "color": "#f59e0b",
        }
    # 观察期
    return {
        "stage": "stage_observation",
        "label": STAGE_RULES["stage_observation"]["label"],
        "advice": STAGE_RULES["stage_observation"]["advice"],
        "color": "#6b7280",
    }


def evaluate() -> dict:
    """评估 6 个信号 + 判断阶段"""
    metrics_status = []
    for meta in METRICS_META:
        latest = db.get_latest(meta["metric_key"])
        value = latest["value"] if latest else None
        status = _judge_status(meta, value)
        metrics_status.append({
            **meta,
            "value": value,
            "obs_date": latest["obs_date"] if latest else None,
            "obs_period": latest.get("obs_period") if latest else None,
            "status": status,
            "source_url": latest.get("source") if latest else None,
        })

    total_red = sum(1 for m in metrics_status if m["status"] == "red")
    total_yellow = sum(1 for m in metrics_status if m["status"] == "yellow")
    total_green = sum(1 for m in metrics_status if m["status"] == "green")
    total_gray = sum(1 for m in metrics_status if m["status"] == "gray")

    stage = _judge_stage(metrics_status)

    eval_date = date.today().isoformat()
    result = {
        "eval_date": eval_date,
        "total_red": total_red,
        "total_yellow": total_yellow,
        "total_green": total_green,
        "total_gray": total_gray,
        "stage": stage,
        "metrics": metrics_status,
    }
    db.log_signal(eval_date, total_red, total_yellow, total_green, total_gray,
                  stage["label"], {
                      "stage_code": stage["stage"],
                      "metrics": [
                          {"key": m["metric_key"], "value": m["value"], "status": m["status"]}
                          for m in metrics_status
                      ],
                  })
    return result


def render_dashboard(eval_data: dict, output_path: str = "data/dashboard.html"):
    """生成 HTML 仪表盘"""
    template_path = os.path.join("templates", "dashboard.html")
    if not os.path.exists(template_path):
        logger.error(f"Template not found: {template_path}")
        return

    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    # 准备每张图的历史数据
    chart_data = []
    for m in eval_data["metrics"]:
        history = db.get_history(m["metric_key"], limit=180)
        history.reverse()
        chart_data.append({
            "key": m["metric_key"],
            "name_zh": m["name_zh"],
            "history": [{"date": h["obs_date"], "value": h["value"]} for h in history],
            "current_value": m["value"],
            "unit": m["unit"],
            "status": m["status"],
        })

    html = template
    html = html.replace("{{ title }}", DASHBOARD_TITLE)
    html = html.replace("{{ subtitle }}", DASHBOARD_SUBTITLE)
    html = html.replace("{{ eval_date }}", eval_data["eval_date"])
    html = html.replace("{{ total_red }}", str(eval_data["total_red"]))
    html = html.replace("{{ total_yellow }}", str(eval_data["total_yellow"]))
    html = html.replace("{{ total_green }}", str(eval_data["total_green"]))
    html = html.replace("{{ total_gray }}", str(eval_data["total_gray"]))
    html = html.replace("{{ stage_label }}", eval_data["stage"]["label"])
    html = html.replace("{{ stage_advice }}", eval_data["stage"]["advice"])
    html = html.replace("{{ stage_color }}", eval_data["stage"]["color"])
    html = html.replace("{{ stage_code }}", eval_data["stage"]["stage"])
    html = html.replace("{{ metrics_json }}", json.dumps(eval_data["metrics"], ensure_ascii=False))
    html = html.replace("{{ chart_data_json }}", json.dumps(chart_data, ensure_ascii=False))

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info(f"Dashboard rendered: {output_path}")


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/dashboard.html")
    args = parser.parse_args()

    db.init_db()
    db.upsert_meta(METRICS_META)
    eval_data = evaluate()
    render_dashboard(eval_data, args.output)
    print(f"✓ Dashboard generated: {args.output}")
    print(f"  阶段: {eval_data['stage']['label']}")
    print(f"  建议: {eval_data['stage']['advice']}")
    print(f"  R{eval_data['total_red']} Y{eval_data['total_yellow']} G{eval_data['total_green']} N{eval_data['total_gray']}")
