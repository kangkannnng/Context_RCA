import logging
from typing import Optional
from google.adk.agents.callback_context import CallbackContext
from google.genai import types

logger = logging.getLogger("RootCauseAnalysis")

def before_metric_analysis(callback_context: CallbackContext) -> Optional[types.Content]:
    """Metric分析前的回调函数"""
    logger.info("=" * 60)
    logger.info("METRIC ANALYSIS - Starting")
    logger.info("=" * 60)
    
    state = callback_context.state

    if state.get("metric_data_collected", False):
        current_hypothesis = state.get("current_hypothesis")
        logger.info(f"METRIC AGENT - Verifying Hypothesis: {current_hypothesis[:30]}...")
        state["current_task_instruction"] = (
            f"当前处于【假设验证阶段】。\n"
            f"待验证的根因假设是：'{current_hypothesis}'。\n"
            f"请基于 Metric 数据判断该假设是否成立。\n"
            f"重点：请在返回 JSON 的 'stance' 字段中明确标记 'SUPPORT' 或 'OPPOSE'。"
        )
    else:
        logger.info("METRIC AGENT - Initial Scanning")
        state["current_task_instruction"] = (
            "当前处于【初始扫描阶段】。\n"
            "请对 Metric 数据进行全面扫描，找出所有显著的异常指标。\n"
            "重点：请在返回 JSON 的 'stance' 字段中标记 'NEUTRAL'，并在 'hypotheses' 中列出你的发现。"
        )
    
    return None


def after_metric_analysis(callback_context: CallbackContext) -> Optional[types.Content]:
    """Metric分析后的回调函数"""
    state = callback_context.state

    if state.get("metric_data_collected", False):
        logger.info("METRIC AGENT - Analysis Completed")
    else:
        logger.warning("METRIC AGENT - Metric data not collected.")

    return None
