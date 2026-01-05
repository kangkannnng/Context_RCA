from google.adk.agents.llm_agent import LlmAgent as Agent
from google.adk.models.lite_llm import LiteLlm

from context_rca.sub_agents.consensus_agent.prompt import CONSENSUS_AGENT_PROMPT
from context_rca.callbacks.consensus_agent_callbacks import before_consensus_analysis, after_consensus_analysis

model = LiteLlm(model='openai/deepseek-chat')

consensus_agent = Agent(
    name="consensus_agent",
    model=model,
    description="共识智能体，负责评估分析结果并判断是否达成共识。",
    instruction=CONSENSUS_AGENT_PROMPT,
    output_key="consensus_decision",
    before_agent_callback=before_consensus_analysis,
    after_agent_callback=after_consensus_analysis,
)
