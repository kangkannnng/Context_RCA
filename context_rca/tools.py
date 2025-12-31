import json
from google.adk.tools import ToolContext

def parse_user_input(input_json: str, tool_context: ToolContext) -> dict:
    """解析用户输入，提取 uuid 和异常描述，并写入 state"""
    data = json.loads(input_json)
    
    uuid = data.get("uuid", "")
    user_query = data.get("Anomaly Description", "")
    
    # 写入 state
    tool_context.state["uuid"] = uuid
    tool_context.state["user_query"] = user_query
    tool_context.state["query_parsed_completed"] = True
    
    return {
        "uuid": uuid,
        "user_query": user_query
    }