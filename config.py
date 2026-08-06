"""
配置 — 6 信号阈值 + 阶段判断
参照华泰证券《AI 行情的两阶段演绎推演》(2026-08-06)
"""
import os

# 仪表盘标题
DASHBOARD_TITLE = "AI 产业链监控 — 6 信号跟踪"
DASHBOARD_SUBTITLE = "华泰证券 6 信号框架 · 阶段判断 + 环节轮动"

# 颜色
COLORS = {
    "red": "#ef4444",
    "yellow": "#f59e0b",
    "green": "#10b981",
    "gray": "#6b7280",
    "blue": "#3b82f6",
    "purple": "#6366f1",
}

# 6 信号阈值定义
# 跟华泰报告: 单一指标不独立执行, 共振时置信度高
# threshold 含义:
#   alert = 突破此值 = 黄灯 (留意)
#   danger = 突破此值 = 红灯 (高位/危险)
# direction:
#   higher_is_better = 高位 = 危险 (拥挤度)
#   lower_is_better = 低位 = 危险 (夏普跌破 1)
SIGNAL_THRESHOLDS = {
    # 信号 1: 盈利兑现 (TTM 净利同比的二阶导)
    # 高位 = 二阶导从正转负, 或 9.5pp → 0
    # 单位: pp (percentage point)
    "ttm_2nd_deriv": {
        "alert_value": 0,      # 二阶导 ≤ 0 = 拐点 = 黄灯
        "danger_value": -5,    # 二阶导 ≤ -5pp = 持续下行 = 红灯
        "direction": "lower_is_better",
        "source_desc": "TTM 净利同比的二阶导 (差分). 9.5pp 拐点对应新能源 2021 年中报",
    },
    # 信号 2: 业绩空间"量" (Capex 二阶导)
    # 高位 = 二阶导从正转负
    "capex_2nd_deriv": {
        "alert_value": 0,
        "danger_value": -10,
        "direction": "lower_is_better",
        "source_desc": "MSFT/AMZN/GOOGL/META 季度 Capex 同比的二阶导",
    },
    # 信号 3: 业绩空间"价" (覆铜板/存储价 MOM)
    # 高位 = 价格涨幅放缓 (MOM 转负)
    # 用生益科技 (600183.SH) 股价 MOM 作为"覆铜板板块情绪"代理
    # 股价 MOM 比实物商品价更敏感, 但不等同于覆铜板出口单价
    # 华泰报告 6 月: 覆铜板出口单价仍上涨, 7 月: 接受度下降
    "copper_clad_mom": {
        "alert_value": 0,      # MOM ≤ 0 = 涨势放缓 = 黄灯
        "danger_value": -10,   # MOM ≤ -10% = 板块情绪反转 = 红灯
        "direction": "lower_is_better",
        "source_desc": "生益科技 (600183.SH) 月环比 (前复权). 覆铜板板块情绪代理, "
                       "股价 MOM 领先实物商品价 1-2 个月 (华泰 2020-22 新能源案例)",
    },
    # 信号 4: 预期透支 (股价 vs fwdPE 背离)
    # 高位 = 股价新高 + fwdPE 回落
    # 用简化代理: AI 硬件主线 PE 百分位
    "fwdpe_divergence": {
        "alert_value": 80,     # PE 百分位 ≥ 80% = 黄灯
        "danger_value": 90,    # PE 百分位 ≥ 90% = 红灯
        "direction": "higher_is_better",
        "source_desc": "AI 硬件主线前瞻 PE 历史百分位 (1 年)",
    },
    # 信号 5: 资金拥挤 (主线 vs 非主线 3 月涨幅差)
    # 高位 = 突破滚动 1 年均值 + 1σ (华泰报告: AI 当前 +4σ)
    "crowding_zscore": {
        "alert_value": 1,      # z-score ≥ 1 = 黄灯
        "danger_value": 2,     # z-score ≥ 2 = 红灯 (新能源历史最大 ~+2σ, AI 当前 ~+4σ)
        "direction": "higher_is_better",
        "source_desc": "(主线 3 月涨幅 - 非主线 3 月涨幅) / 滚动 1 年 std",
    },
    # 信号 6: 行为反馈 (主线 120d 滚动夏普)
    # 高位 = 夏普突破 2, 松动 = 夏普跌破 1
    # 双向危险: 太高 (抱团) 或太低 (共识松动)
    "sharpe_120d": {
        "alert_high": 2.0,     # 突破 2 = 黄灯 (高位抱团)
        "alert_low": 0.5,      # 跌破 0.5 = 黄灯 (抱团松动预警)
        "danger_high": 2.5,    # >= 2.5 = 红灯 (过度抱团)
        "danger_low": 0.0,     # <= 0 = 红灯 (共识完全松动)
        "direction": "two_sided",
        "source_desc": "AI 硬件主线 120 日滚动夏普. 突破 2 = 抱团, 跌破 1 = 松动",
    },
}

# 阶段判断 (华泰报告核心)
STAGE_RULES = {
    # 信号 1+2+3 都是"高位/放缓" + 信号 5+6 已消化 = 业绩弹性定价充分
    # 信号 2+6 重新加速 = 业绩持续性验证 (第二轮)
    "stage_1_high": {
        "trigger": "ttm_2nd_deriv.danger AND crowding_zscore<=1 AND sharpe_120d<=1.5",
        "label": "业绩弹性定价充分 (第一阶段高位)",
        "advice": "适度控制仓位, 主配业绩能见度高的环节, 跟踪 8 月中报验证",
    },
    "stage_1_digest": {
        "trigger": "ttm_2nd_deriv.alert AND crowding_zscore<=0 AND sharpe_120d<=1",
        "label": "业绩弹性消化中 (第一阶段回调)",
        "advice": "估值超调后反弹能见度提升, 等待二阶导重新拐头或新需求场景",
    },
    "stage_2_renew": {
        "trigger": "ttm_2nd_deriv.alert AND capex_2nd_deriv.danger",
        "label": "业绩持续性再定价 (第二阶段开启)",
        "advice": "若中报验证二阶导向上 + ARR 重新加速, 业绩空间再次打开",
    },
    "stage_accelerating": {
        "trigger": "ttm_2nd_deriv>=5 AND capex_2nd_deriv>=5 AND sharpe_120d>=2",
        "label": "景气加速 (主升段)",
        "advice": "保持高仓位, 关注拥挤度风险, 主线/非主线涨幅差接近 +1σ 时减仓",
    },
    "stage_observation": {
        "trigger": "default",
        "label": "观察期",
        "advice": "等待信号明朗, 跟踪中报披露 (8 月底) 和 Capex 二阶导拐点 (3Q26)",
    },
}

# 日志
LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "update.log")
