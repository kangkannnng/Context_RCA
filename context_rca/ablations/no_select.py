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

# Import Ablation Elements
from context_rca.ablations.prompts import ORCHESTRATOR_PROMPT_NO_SOP
from context_rca.ablations.callbacks import (
    before_log_analysis_no_select,
    before_metric_analysis_no_select,
    before_trace_analysis_no_select,
    before_consensus_analysis_no_select,
    before_report_analysis_no_select
)

model = LiteLlm(model='openai/deepseek-chat')

def create_wo_selective_context_agent():
    """
    创建 w/o Selective Context 变体:
    移除选择性上下文注入机制，各智能体共享全量上下文信息。
    """
    # 1. Clone sub-agents and replace callbacks
    # Note: We create new instances to avoid side effects on the global instances if possible,
    # but here we reuse the config from the imported agents, just changing callbacks.
    # Since we can't easily re-instantiate without all params, we'll modify the object attributes.
    # To avoid affecting other experiments in the same process, this should be run in a separate process.
    
    # Modify Callbacks
    log_agent.before_agent_callback = before_log_analysis_no_select
    metric_agent.before_agent_callback = before_metric_analysis_no_select
    trace_agent.before_agent_callback = before_trace_analysis_no_select
    consensus_agent.before_agent_callback = before_consensus_analysis_no_select
    report_agent.before_agent_callback = before_report_analysis_no_select
            
    # 2. Re-assemble Data Collection Tool
    data_collection_tool_ablation = ParallelAgent(
        name="data_collection_agent",
        sub_agents=[metric_agent, log_agent, trace_agent],
        description="数据收集智能体 (w/o Selective Context)",
    )

    # 3. Re-assemble Consensus Tool
    consensus_discussion_tool = LoopAgent(
        name="consensus_discussion_agent",
        sub_agents=[consensus_agent, data_collection_tool_ablation],
        description="共识讨论智能体",
        max_iterations=6,
    )

    # 4. Re-assemble Orchestrator
    orchestrator_agent = Agent(
        name="orchestrator_agent",
        model=model,
        description="编排智能体 (w/o Selective Context)",
        instruction=ORCHESTRATOR_PROMPT,
        before_agent_callback=before_orchestrator,
        after_agent_callback=after_orchestrator,
        tools=[
            FunctionTool(func=parse_user_input),
            AgentTool(agent=data_collection_tool_ablation),
            AgentTool(agent=consensus_discussion_tool),
            AgentTool(agent=report_agent),
        ]
    )
    return orchestrator_agent




