from google.adk.agents.llm_agent import LlmAgent as Agent
from google.adk.models.lite_llm import LiteLlm

from context_rca.sub_agents.report_agent.prompt import REPORT_AGENT_PROMPT
from context_rca.schemas.report_schema import AnalysisReport
from context_rca.callbacks.report_agent_callbacks import before_report_analysis, after_report_analysis

model = LiteLlm(model='openai/deepseek-chat')

report_agent = Agent(
    name="report_agent",
    model=model,
    description="报告格式化智能体，将归因Agent的结论格式化为标准 JSON 输出。",
    instruction=REPORT_AGENT_PROMPT,
    output_schema=AnalysisReport,
    output_key="report_analysis_findings",
    before_agent_callback=before_report_analysis,
    after_agent_callback=after_report_analysis,
)