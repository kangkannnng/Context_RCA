import logging
from typing import Optional
from google.adk.agents.callback_context import CallbackContext
from google.genai import types

logger = logging.getLogger("RootCauseAnalysis")

def before_log_analysis(callback_context: CallbackContext) -> Optional[types.Content]:
    """Log分析前的回调函数"""
    state = callback_context.state
    logger.info("=" * 60)
    logger.info("LOG ANALYSIS - Starting")
    
    state = callback_context.state
    state["current_task_instruction"] = "请对 Log 数据进行全面扫描，找出最显著的异常。"

    return None


def after_log_analysis(callback_context: CallbackContext) -> str:
    """Log分析后的回调函数"""
    state = callback_context.state

    if state.get("log_data_collected", False):
        logger.info("LOG AGENT - Analysis Completed")
    else:
        logger.warning("LOG AGENT - Log data not collected.")

    return None
