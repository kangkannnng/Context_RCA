from google.adk.tools.function_tool import FunctionTool

from context_rca.tools import parse_user_input
from context_rca.sub_agents.log_agent.tools import log_analysis_tool
from context_rca.sub_agents.metric_agent.tools import metric_analysis_tool
from context_rca.sub_agents.trace_agent.tools import trace_analysis_tool

agent_tools = [
    FunctionTool(func=parse_user_input),
    FunctionTool(func=log_analysis_tool),
    FunctionTool(func=metric_analysis_tool),
    FunctionTool(func=trace_analysis_tool),
]