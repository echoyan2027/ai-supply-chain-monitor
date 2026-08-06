# AI 产业链监控 — 6 信号体系

华泰证券 2026-08-06 报告《AI 行情的两阶段演绎推演》复刻版。

> **与 [ai-bubble-dashboard](https://github.com/echoyan2027/ai-bubble-dashboard) 的定位差异：**
> - `bubble-dashboard` = 宏观 0-100 泡沫指数（仓位管理）
> - `supply-chain-monitor` = 产业链 6 信号阶段判断（阶段判断 + 环节轮动）

## 6 信号体系

### 产业维度
1. **TTM 净利二阶导** — SEC EDGAR 拉 5 家 AI 硬件 (NVDA/AVGO/AMAT/LRCX/KLAC) 季度净利
2. **CSP Capex 二阶导** — SEC EDGAR 拉 4 家 CSP (MSFT/AMZN/GOOGL/META) 季度 Capex
3. **覆铜板 MOM** — 新浪/腾讯 K 线 (生益科技 600183 前复权)
4. **业绩季超额收益** (信号 1 衍生) — 财报披露季半导体 vs 沪深 300 超额收益

### 市场维度
5. **拥挤度 (z-score)** — 半导体 ETF (sh159995) vs 沪深 300 ETF (sh510310) 3 月涨幅差滚动 1 年 z-score
6. **主线 120 日夏普** — 半导体 ETF 120 日滚动夏普 (突破 2 = 抱团, 跌破 1 = 松动)

## 阶段判断 (华泰两阶段框架)

| 阶段 | 触发条件 | 建议 |
|---|---|---|
| 景气加速 (主升段) | TTM 二阶导 ≥ 5 + Capex 二阶导 ≥ 5 + 夏普 ≥ 2 | 保持高仓位, 关注拥挤度风险 |
| 业绩弹性定价充分 (第一阶段高位) | TTM 二阶导 ≤ -5 + 拥挤 ≤ 1σ + 夏普 ≤ 1.5 | 适度控制仓位, 跟踪中报 |
| 业绩弹性消化中 | TTM 二阶导 ≤ 0 + 拥挤 ≤ 0 + 夏普 ≤ 1 | 等待反弹或新需求场景 |
| 业绩持续性再定价 (第二阶段) | TTM 二阶导 ≤ 0 + Capex 二阶导 ≤ -10 | 业绩空间再次打开 |
| 观察期 | 默认 | 等待信号明朗 |

## 数据源

| Fetcher | 数据源 | 频率 |
|---|---|---|
| crowding.py | 腾讯 K 线 (sh159995 + sh510310) | daily |
| sharpe.py | 腾讯 K 线 (sh159995) | daily |
| ttm_2nd_deriv.py | SEC EDGAR XBRL | quarterly |
| capex_2nd_deriv.py | SEC EDGAR XBRL | quarterly |
| copper_clad.py | 新浪/腾讯 K 线 (sh600183) | daily |
| earnings_surprise.py | 腾讯 K 线 (财报披露季窗口) | quarterly |

## 本地运行

```bash
D:\python.exe update.py
```

输出:
- `data/dashboard.html` — 静态 HTML 仪表盘
- `data/ai_supply_chain.db` — SQLite 历史数据

## 部署

GitHub Pages 自动部署 `data/dashboard.html` 到 https://echoyan2027.github.io/ai-supply-chain-monitor/

每天北京时间 09:00 (UTC 01:00) 自动跑一次 `update.yml`。

## 报告原文

华泰证券《AI 行情的两阶段演绎推演——构建产业趋势行情跟踪信号体系》2026-08-06
作者: 孙瀚文, 王伟光, 何康
