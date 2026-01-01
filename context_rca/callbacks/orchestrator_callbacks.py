"""Orchestrator Agent Callbacks for initialization and completion."""
import logging
from typing import Optional
from google.adk.agents.callback_context import CallbackContext
from google.genai import types

logger = logging.getLogger("RootCauseAnalysis")

def before_orchestrator(callback_context: CallbackContext) -> Optional[types.Content]:
    """Orchestrator 启动前初始化 state"""
    logger.info("=" * 60)
    logger.info("ORCHESTRATOR AGENT - Initializing")
    logger.info("=" * 60)

    state = callback_context.state

    if "uuid" not in state:
        state["uuid"] = "（等待写入...）"
    if "user_query" not in state:
        state["user_query"] = "（等待写入...）"
    if "query_parsed_completed" not in state:
        state["query_parsed_completed"] = False

    if "raw_metric_result" not in state:
        state["raw_metric_result"] = "（等待写入...）"
    if "metric_data_collected" not in state:
        state["metric_data_collected"] = False

    if "raw_log_result" not in state:
        state["raw_log_result"] = "（等待写入...）"
    if "log_data_collected" not in state:
        state["log_data_collected"] = False

    if "raw_trace_result" not in state:
        state["raw_trace_result"] = "（等待写入...）"
    if "trace_data_collected" not in state:
        state["trace_data_collected"] = False

    if "current_hypothesis" not in state:
        state["current_hypothesis"] = "（等待写入...）"

    # 初始化专家反馈变量，防止并行调用时的 KeyError
    if "log_analysis_findings" not in state:
        state["log_analysis_findings"] = "（等待数据收集...）"
    if "metric_analysis_findings" not in state:
        state["metric_analysis_findings"] = "（等待数据收集...）"
    if "trace_analysis_findings" not in state:
        state["trace_analysis_findings"] = "（等待数据收集...）"
    
    return None


def after_orchestrator(callback_context: CallbackContext) -> Optional[types.Content]:
    """Orchestrator 执行后处理"""

    state = callback_context.state

    if state.get("query_parsed_completed", False):
        logger.info("ORCHESTRATOR AGENT - Execution Completed")
    else:
        logger.warning("ORCHESTRATOR AGENT - User query parsing not completed.")
        
    return None
