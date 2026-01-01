import json
import logging
import os
from typing import Optional
from google.adk.agents.callback_context import CallbackContext
from google.genai import types


logger = logging.getLogger("RootCauseAnalysis")

# 输出目录
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "output")


def before_report_analysis(callback_context: CallbackContext) -> Optional[types.Content]:
    """Report分析前的回调函数，准备 Prompt 变量"""
    logger.info("=" * 60)
    logger.info("REPORT ANALYSIS - Starting")
    
    state = callback_context.state
    
    state["hypotheses_summary"]= state.get("current_hypothesis", "N/A")

    state["log_analysis_findings"] = state.get("log_analysis_findings", "无日志证据")
    state["metric_analysis_findings"] = state.get("metric_analysis_findings", "无指标证据")
    state["trace_analysis_findings"] = state.get("trace_analysis_findings", "无调用链证据")
    
    return None


async def after_report_analysis(callback_context: CallbackContext) -> Optional[types.Content]:
    """Report分析后的回调函数，记录Report分析的完成信息，并保存成制品。"""
    findings = callback_context.state.get("report_analysis_findings", {})

    if findings:
        try:
            json_str = json.dumps(findings, indent=2, default=str)
            json_artifact = types.Part.from_bytes(
                data=json_str.encode("utf-8"),
                mime_type="application/json",
            )
            await callback_context.save_artifact("report_analysis_output.json", json_artifact)
            logger.info("REPORT ANALYSIS COMPLETED - Saved results in report_analysis_output.json")
        except Exception as e:
            logger.error(f"Failed to save report analysis findings: {e}")

    # 标记完成状态
    callback_context.state["report_analysis_completed"] = True

    return None