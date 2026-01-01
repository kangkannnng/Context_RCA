import logging
import json
import re
from typing import Optional
from google.adk.agents.callback_context import CallbackContext
from google.genai import types

logger = logging.getLogger("RootCauseAnalysis")

def before_consensus_analysis(callback_context: CallbackContext) -> Optional[types.Content]:
    """共识分析前的回调函数"""
    state = callback_context.state
    
    # 增加轮次计数
    iteration = state.get("consensus_iteration", 0)
    state["consensus_iteration"] = iteration + 1
    
    current_hypothesis = state.get("current_hypothesis", "None")

    logger.info("=" * 60)
    logger.info(f"CONSENSUS ANALYSIS - Round {iteration}")
    logger.info(f"Current Hypothesis: {current_hypothesis}")
    logger.info("=" * 60)

    return None


def after_consensus_analysis(callback_context: CallbackContext) -> Optional[types.Content]:
    """共识分析后的回调函数"""
    state = callback_context.state
    agent_output = state.get("consensus_decision")
    
    try:
        # 1. 提取 JSON 字符串
        text = agent_output
        json_str = ""
        if "```json" in text:
            json_str = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            json_str = text.split("```")[1].split("```")[0].strip()
        else:
            # 尝试直接查找 { ... }
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                json_str = match.group(0)
            else:
                json_str = text

        # 2. 解析 JSON
        if json_str:
            result = json.loads(json_str)
            status = result.get("status", "UNKNOWN")
            new_hypothesis = result.get("hypothesis", "N/A")
            reasoning = result.get("reasoning", "N/A")

            # 3. 更新状态 (关键步骤！)
            state["consensus_decision"] = status
            state["current_hypothesis"] = new_hypothesis
            
            logger.info(f"CONSENSUS AGENT OUTPUT PARSED:")
            logger.info(f"  - Status: {status}")
            logger.info(f"  - New Hypothesis: {new_hypothesis}")
            logger.info(f"  - Reasoning: {reasoning}")

            # 4. 判断是否退出循环
            if status == "AGREED":
                logger.info(">>> CONSENSUS REACHED! Escalating to finish loop. <<<")
                # 设置escalate标志，通知LoopAgent退出
                if hasattr(callback_context, '_event_actions'):
                    callback_context._event_actions.escalate = True
            elif status == "DISAGREED":
                logger.info(">>> CONSENSUS NOT REACHED. Updating hypothesis and continuing loop. <<<")
                # 这里不需要做任何事，LoopAgent 会自动进入下一轮
                # 下一轮 Data Agent 会看到新的 current_hypothesis
            else:
                logger.warning(f"Unknown status '{status}'. Continuing loop...")
            
        else:
            logger.warning("CONSENSUS AGENT - No JSON found in output.")

    except Exception as e:
        logger.error(f"CONSENSUS AGENT - Failed to parse output: {e}")
        logger.error(f"Raw Output: {agent_output}")

    return None