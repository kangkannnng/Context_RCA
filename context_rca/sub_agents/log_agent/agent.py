from google.adk.agents.llm_agent import LlmAgent as Agent
from google.adk.models.lite_llm import LiteLlm

from context_rca.sub_agents.log_agent.tools import log_analysis_tool
from context_rca.sub_agents.log_agent.prompt import LOG_AGENT_PROMPT
from context_rca.callbacks.log_agent_callbacks import before_log_analysis, after_log_analysis

model = LiteLlm(model='openai/deepseek-chat')

log_agent = Agent(
    name="log_agent",
    model=model,
    description="日志数据解读智能体，提取错误关键词和涉及的服务。",
    instruction=LOG_AGENT_PROMPT,
    tools=[log_analysis_tool],
    output_key="log_analysis_findings",
    before_agent_callback=before_log_analysis,
    after_agent_callback=after_log_analysis,
)