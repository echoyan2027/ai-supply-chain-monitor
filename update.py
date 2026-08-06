"""
主入口 — 拉取 6 信号 + 评估 + 渲染

用法:
    python update.py                  # 跑全部自动抓取 + 渲染
    python update.py --render-only    # 只重新渲染（用现有 DB 数据）
    python update.py --quiet          # 静默模式
"""
import sys
import os
import argparse
import logging
from datetime import date
import time

# 把项目根目录加到 sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db
import dashboard
from fetchers import (
    fetch_crowding, fetch_sharpe, fetch_ttm_2nd_deriv,
    fetch_copper_clad, fetch_capex_2nd_deriv, fetch_earnings_surprise,
)
from config import LOG_DIR, LOG_FILE


def setup_logging(verbose: bool = True):
    os.makedirs(LOG_DIR, exist_ok=True)
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def run_all():
    """拉取所有 6 信号数据"""
    logger = logging.getLogger("update")
    results = {}

    # === 产业维度 ===
    logger.info("[1/6] 拥挤度 (信号 5)...")
    try:
        results["crowding_zscore"] = fetch_crowding()
    except Exception as e:
        logger.error(f"  ✗ {e}")
        results["crowding_zscore"] = {"error": str(e)}

    logger.info("[2/6] 夏普比 (信号 6)...")
    try:
        results["sharpe_120d"] = fetch_sharpe()
    except Exception as e:
        logger.error(f"  ✗ {e}")
        results["sharpe_120d"] = {"error": str(e)}

    logger.info("[3/6] TTM 净利二阶导 (信号 1)...")
    try:
        results["ttm_2nd_deriv"] = fetch_ttm_2nd_deriv()
    except Exception as e:
        logger.error(f"  ✗ {e}")
        results["ttm_2nd_deriv"] = {"error": str(e)}

    logger.info("[4/6] CSP Capex 二阶导 (信号 2)...")
    try:
        results["capex_2nd_deriv"] = fetch_capex_2nd_deriv()
    except Exception as e:
        logger.error(f"  ✗ {e}")
        results["capex_2nd_deriv"] = {"error": str(e)}

    logger.info("[5/6] 覆铜板 MOM (信号 3)...")
    try:
        results["copper_clad_mom"] = fetch_copper_clad()
    except Exception as e:
        logger.error(f"  ✗ {e}")
        results["copper_clad_mom"] = {"error": str(e)}

    logger.info("[6/6] 业绩季超额收益 (信号 1 衍生)...")
    try:
        results["earnings_surprise"] = fetch_earnings_surprise()
    except Exception as e:
        logger.error(f"  ✗ {e}")
        results["earnings_surprise"] = {"error": str(e)}

    return results


def main():
    parser = argparse.ArgumentParser(description="AI 产业链监控 - 6 信号体系")
    parser.add_argument("--render-only", action="store_true",
                        help="只渲染仪表盘，不抓取")
    parser.add_argument("--output", default="data/dashboard.html",
                        help="仪表盘输出路径")
    parser.add_argument("--quiet", action="store_true", help="静默模式")
    args = parser.parse_args()

    # 关键修复: 不管用户从哪个目录运行, 都先把 CWD 切到脚本所在目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    setup_logging(verbose=not args.quiet)
    logger = logging.getLogger("update")

    # 1. 初始化 DB
    db.init_db()
    db.upsert_meta(dashboard.METRICS_META)

    # 2. 拉取数据
    if not args.render_only:
        logger.info("=" * 60)
        logger.info("开始拉取 6 信号数据...")
        logger.info("=" * 60)
        start = time.time()
        run_all()
        logger.info(f"数据拉取完成，耗时 {time.time() - start:.1f}s")
    else:
        logger.info("跳过数据拉取（--render-only）")

    # 3. 评估
    logger.info("评估 6 信号 + 阶段判断...")
    eval_data = dashboard.evaluate()
    logger.info(f"  R{eval_data['total_red']} Y{eval_data['total_yellow']} "
                f"G{eval_data['total_green']} N{eval_data['total_gray']}")
    logger.info(f"  阶段: {eval_data['stage']['label']}")

    # 4. 渲染
    logger.info(f"生成仪表盘: {args.output}")
    dashboard.render_dashboard(eval_data, args.output)

    logger.info("=" * 60)
    logger.info("✓ 完成")
    logger.info(f"  仪表盘路径: {os.path.abspath(args.output)}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
