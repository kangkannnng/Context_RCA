from google.adk.agents.llm_agent import LlmAgent as Agent
from google.adk.models.lite_llm import LiteLlm

from context_rca.sub_agents.trace_agent.tools import trace_analysis_tool
from context_rca.sub_agents.trace_agent.prompt import TRACE_AGENT_PROMPT
from context_rca.callbacks.trace_agent_callbacks import before_trace_analysis, after_trace_analysis

model = LiteLlm(model='openai/deepseek-chat')

trace_agent = Agent(
    name="trace_agent",
    model=model,
    description="链路追踪数据解读智能体，提取异常调用边和可疑服务。",
    instruction=TRACE_AGENT_PROMPT,
    tools=[trace_analysis_tool],
    output_key="trace_analysis_findings",
    before_agent_callback=before_trace_analysis,
    after_agent_callback=after_trace_analysis,
)

