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

    state["current_task_instruction"] = "请对Metric数据进行全面扫描，找出最显著的异常。"

    return None


def after_metric_analysis(callback_context: CallbackContext) -> str:
    """Metric分析后的回调函数"""
    state = callback_context.state

    if state.get("metric_data_collected", False):
        logger.info("METRIC AGENT - Analysis Completed")
    else:
        logger.warning("METRIC AGENT - Metric data not collected.")

    return None
