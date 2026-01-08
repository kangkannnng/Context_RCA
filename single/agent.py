from google.adk.agents.llm_agent import LlmAgent as Agent
from google.adk.models.lite_llm import LiteLlm

from single.prompt import AGENT_PROMPT
from single.tools import agent_tools
from single.schemas import AnalysisReport

model = LiteLlm(model='openai/deepseek-chat')

root_agent = Agent(
    name="rca_agent",
    model=model,
    instruction=AGENT_PROMPT,
    tools=agent_tools,
    output_schema=AnalysisReport,
)
