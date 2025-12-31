import logging
from typing import Optional
from google.adk.agents.callback_context import CallbackContext
from google.genai import types

logger = logging.getLogger("RootCauseAnalysis")

def before_trace_analysis(callback_context: CallbackContext) -> Optional[types.Content]:
    """Trace分析前的回调函数"""
    logger.info("=" * 60)
    logger.info("TRACE ANALYSIS - Starting")
    logger.info("=" * 60)

    state = callback_context.state
    
    state["current_task_instruction"] = "请对 Trace 数据进行全面扫描，找出最显著的异常。"

    return None


def after_trace_analysis(callback_context: CallbackContext) -> str:
    """Trace分析后的回调函数"""
    state = callback_context.state

    if state.get("trace_data_collected", False):
        logger.info("TRACE AGENT - Analysis Completed")
    else:
        logger.warning("TRACE AGENT - Trace data not collected.")
    
    return None
