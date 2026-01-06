import logging
import json
from typing import Optional
from google.adk.agents.callback_context import CallbackContext
from google.genai import types

logger = logging.getLogger("RootCauseAnalysis")

def _format_full_context(state: dict) -> str:
    """Helper to format all available context from state accurately."""
    context_parts = []
    
    # 1. User Info & Basics
    context_parts.append(f"UUID: {state.get('uuid', 'N/A')}")
    context_parts.append(f"User Query: {state.get('user_query', 'N/A')}")
    
    # 2. Raw Data (The "noisy" part)
    # Include raw tool outputs if available
    raw_log = state.get("raw_log_result", "Not collected yet")
    raw_metric = state.get("raw_metric_result", "Not collected yet")
    raw_trace = state.get("raw_trace_result", "Not collected yet")
    node_mapping = state.get("node_pod_mapping", "Unknown mapping")

    context_parts.append(f"\n[RAW DATA CONTEXT]")
    context_parts.append(f"--- Raw Log Data ---\n{str(raw_log)}") 
    context_parts.append(f"--- Raw Metric Data ---\n{str(raw_metric)}")
    context_parts.append(f"--- Raw Trace Data ---\n{str(raw_trace)}")
    context_parts.append(f"--- Node Pod Mapping ---\n{str(node_mapping)}")

    # 3. Current Analysis State
    current_hypothesis = state.get("current_hypothesis", "None")
    context_parts.append(f"\n[ANALYSIS STATE]")
    context_parts.append(f"Current Hypothesis: {current_hypothesis}")
    context_parts.append(f"Current Iteration: {state.get('current_iteration', 0)}")
    
    # 4. Agent Recent Findings
    log_findings = state.get("log_analysis_findings", "No findings")
    metric_findings = state.get("metric_analysis_findings", "No findings")
    trace_findings = state.get("trace_analysis_findings", "No findings")
    
    context_parts.append(f"\n[AGENT FINDINGS HISTORY]")
    context_parts.append(f"--- Log Agent Findings ---\n{log_findings}")
    context_parts.append(f"--- Metric Agent Findings ---\n{metric_findings}")
    context_parts.append(f"--- Trace Agent Findings ---\n{trace_findings}")
    
    # 5. Consensus Decision
    consensus = state.get("consensus_decision", "No consensus yet")
    context_parts.append(f"--- Previous Consensus Decision ---\n{consensus}")
    
    return "\n\n".join(context_parts)

def before_log_analysis_no_select(callback_context: CallbackContext) -> Optional[types.Content]:
    """Log分析前的回调函数 (w/o Selective Context)"""
    logger.info("=" * 60)
    logger.info("LOG ANALYSIS (No Selective Context) - Starting")
    logger.info("=" * 60)

    state = callback_context.state
    full_context = _format_full_context(state)

    state["current_task_instruction"] = (
        f"当前处于【分析阶段】。\n"
        f"以下是你可以访问的全量上下文信息，包含了用户输入、当前假设、以及其他所有智能体的历史发现：\n"
        f"================================\n"
        f"{full_context}\n"
        f"================================\n"
        f"请基于上述全量信息以及你的 Log 数据，对当前故障进行分析。\n"
        f"重点：请在返回 JSON 的 'stance' 字段中明确标记 'SUPPORT', 'OPPOSE' 或 'NEUTRAL'。"
    )
    return None

def before_metric_analysis_no_select(callback_context: CallbackContext) -> Optional[types.Content]:
    """Metric分析前的回调函数 (w/o Selective Context)"""
    logger.info("=" * 60)
    logger.info("METRIC ANALYSIS (No Selective Context) - Starting")
    logger.info("=" * 60)
    
    state = callback_context.state
    full_context = _format_full_context(state)

    state["current_task_instruction"] = (
        f"当前处于【分析阶段】。\n"
        f"以下是你可以访问的全量上下文信息，包含了用户输入、当前假设、以及其他所有智能体的历史发现：\n"
        f"================================\n"
        f"{full_context}\n"
        f"================================\n"
        f"请基于上述全量信息以及你的 Metric 数据，对当前故障进行分析。\n"
        f"重点：请在返回 JSON 的 'stance' 字段中明确标记 'SUPPORT', 'OPPOSE' 或 'NEUTRAL'。"
    )
    return None

def before_trace_analysis_no_select(callback_context: CallbackContext) -> Optional[types.Content]:
    """Trace分析前的回调函数 (w/o Selective Context)"""
    logger.info("=" * 60)
    logger.info("TRACE ANALYSIS (No Selective Context) - Starting")
    logger.info("=" * 60)

    state = callback_context.state
    full_context = _format_full_context(state)

    state["current_task_instruction"] = (
        f"当前处于【分析阶段】。\n"
        f"以下是你可以访问的全量上下文信息，包含了用户输入、当前假设、以及其他所有智能体的历史发现：\n"
        f"================================\n"
        f"{full_context}\n"
        f"================================\n"
        f"请基于上述全量信息以及你的 Trace 数据，对当前故障进行分析。\n"
        f"重点：请在返回 JSON 的 'stance' 字段中明确标记 'SUPPORT', 'OPPOSE' 或 'NEUTRAL'。"
    )
    return None

def before_consensus_analysis_no_select(callback_context: CallbackContext) -> Optional[types.Content]:
    """共识分析前的回调函数 (w/o Selective Context)"""
    state = callback_context.state
    
    # Increase iteration counter similar to original
    iteration = state.get("consensus_iteration", 0)
    state["consensus_iteration"] = iteration + 1
    
    logger.info("=" * 60)
    logger.info(f"CONSENSUS ANALYSIS (No Selective Context) - Round {iteration}")
    logger.info("=" * 60)
    
    full_context = _format_full_context(state)
    
    # We can inject this full context into the prompt placeholder if the prompt supports it, 
    # OR we can just append it to a specific state variable that the prompt uses.
    # The original CONSENSUS_AGENT_PROMPT uses {log_analysis_findings}, {metric_...}, etc.
    # To simulate "seeing everything", we can overload one of the fields or provide a new instruction.
    # However, since the Prompt Template is fixed in the Agent definition (in agent_variants.py),
    # we might need to modify the prompt there or just rely on the fact that we can manipulate state variables.
    
    # Strategy: We will OVERWRITE the specific findings with the FULL context.
    # This ensures the Agent sees EVERYTHING when it looks for "log_findings".
    # It's a bit hacky but guarantees the prompt gets the full info.
    
    # NOTE: The agent relies on specific variables being present in the prompt.
    # We will backup original findings first if we want to be safe, but since this is stateless per round effectively:
    
    state["log_analysis_findings"] = f"[FULL CONTEXT INJECTION]\n{full_context}"
    state["metric_analysis_findings"] = "See Log Findings for Full Context"
    state["trace_analysis_findings"] = "See Log Findings for Full Context"
    
    return None

def before_report_analysis_no_select(callback_context: CallbackContext) -> Optional[types.Content]:
    """报告分析前的回调函数 (w/o Selective Context)"""
    logger.info("=" * 60)
    logger.info("REPORT ANALYSIS (No Selective Context) - Starting")
    logger.info("=" * 60)
    
    state = callback_context.state
    full_context = _format_full_context(state)
    
    # Similar strategy: Overload the variables used in REPORT_AGENT_PROMPT
    # The prompt uses {hypotheses_summary}, {trace_...}, {metric_...}, {log_...}
    
    state["hypotheses_summary"] = f"[FULL CONTEXT INJECTION]\n{full_context}"
    state["log_analysis_findings"] = "See Hypotheses Summary for Full Context"
    state["metric_analysis_findings"] = "See Hypotheses Summary for Full Context"
    state["trace_analysis_findings"] = "See Hypotheses Summary for Full Context"
    
    return None
