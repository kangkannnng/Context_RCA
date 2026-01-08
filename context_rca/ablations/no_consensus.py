from google.adk.agents.llm_agent import LlmAgent as Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.agent_tool import AgentTool
from google.adk.agents import ParallelAgent, LoopAgent

# Import Original Sub-Agents
from context_rca.sub_agents.metric_agent.agent import metric_agent
from context_rca.sub_agents.log_agent.agent import log_agent
from context_rca.sub_agents.trace_agent.agent import trace_agent
from context_rca.sub_agents.consensus_agent.agent import consensus_agent
from context_rca.sub_agents.report_agent.agent import report_agent

# Import Original Utils
from context_rca.prompt import ORCHESTRATOR_PROMPT
from context_rca.tools import parse_user_input
from context_rca.callbacks.orchestrator_callbacks import (
    before_orchestrator,
    after_orchestrator,
)

model = LiteLlm(model='openai/deepseek-chat')


def create_wo_consensus_iteration_agent():
    """
    创建 w/o Consensus Iteration 变体:
    移除迭代式共识验证，共识智能体仅进行单轮分析直接输出结论。
    """
    # Re-use original agents
    data_collection_tool = ParallelAgent(
        name="data_collection_agent",
        sub_agents=[metric_agent, log_agent, trace_agent],
        description="数据收集智能体",
    )

    # Modify Consensus Tool -> max_iterations=1
    consensus_discussion_tool_ablation = LoopAgent(
        name="consensus_discussion_agent",
        sub_agents=[consensus_agent, data_collection_tool],
        description="共识讨论智能体 (w/o Iteration)",
        max_iterations=1, # <--- CHANGED
    )

    orchestrator_agent = Agent(
        name="orchestrator_agent",
        model=model,
        description="编排智能体 (w/o Consensus Iteration)",
        instruction=ORCHESTRATOR_PROMPT,
        before_agent_callback=before_orchestrator,
        after_agent_callback=after_orchestrator,
        tools=[
            FunctionTool(func=parse_user_input),
            AgentTool(agent=data_collection_tool),
            AgentTool(agent=consensus_discussion_tool_ablation),
            AgentTool(agent=report_agent),
        ]
    )
    return orchestrator_agent