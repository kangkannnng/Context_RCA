from google.adk.agents.llm_agent import LlmAgent as Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.agent_tool import AgentTool
from google.adk.agents import ParallelAgent, LoopAgent

from context_rca.sub_agents.metric_agent.agent import metric_agent
from context_rca.sub_agents.log_agent.agent import log_agent
from context_rca.sub_agents.trace_agent.agent import trace_agent
from context_rca.sub_agents.consensus_agent.agent import consensus_agent
from context_rca.sub_agents.report_agent.agent import report_agent

from context_rca.prompt import ORCHESTRATOR_PROMPT
from context_rca.tools import parse_user_input

from context_rca.callbacks.orchestrator_callbacks import (
    before_orchestrator,
    after_orchestrator,
)

data_collection_tool = ParallelAgent(
    name="data_collection_agent",
    sub_agents=[metric_agent, log_agent, trace_agent],
    description="数据收集智能体，负责并行调用各子智能体收集所需数据",
)

consensus_discussion_tool = LoopAgent(
    name="consensus_discussion_agent",
    sub_agents=[consensus_agent, data_collection_tool],
    description="共识讨论智能体，负责在各子智能体间进行多轮讨论以达成最终结论",
    max_iterations=6,
)

model = LiteLlm(model='openai/deepseek-chat')

orchestrator_agent = Agent(
    name="orchestrator_agent",
    model=model,
    description="编排智能体，负责管理和协调根因分析任务流程",
    instruction=ORCHESTRATOR_PROMPT,
    before_agent_callback=before_orchestrator,
    after_agent_callback=after_orchestrator,
    tools=[
        FunctionTool(func=parse_user_input),
        AgentTool(agent=data_collection_tool),
        AgentTool(agent=consensus_discussion_tool),
        AgentTool(agent=report_agent),
    ]
)

root_agent = orchestrator_agent
