from google.adk.agents.llm_agent import LlmAgent as Agent
from google.adk.models.lite_llm import LiteLlm

from context_rca.sub_agents.metric_agent.tools import metric_analysis_tool
from context_rca.sub_agents.metric_agent.prompt import METRIC_AGENT_PROMPT
from context_rca.callbacks.metric_agent_callbacks import before_metric_analysis, after_metric_analysis

model = LiteLlm(model='gpt-4o')

metric_agent = Agent(
    name="metric_agent",
    model=model,
    description="指标数据解读智能体，提取异常指标和受影响实体，识别问题类型。",
    instruction=METRIC_AGENT_PROMPT,
    tools=[metric_analysis_tool],
    output_key="metric_analysis_findings",
    before_agent_callback=before_metric_analysis,
    after_agent_callback=after_metric_analysis,
)