"""
Context-RCA 批量运行器 (调试增强版)
"""

import os
import json
import asyncio
import logging
import random
import argparse
import uuid as uuid_lib
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List

from dotenv import load_dotenv
from google.adk.sessions import InMemorySessionService
from google.adk.artifacts import InMemoryArtifactService
from google.adk.runners import Runner
from google.genai import types

from context_rca.agent import orchestrator_agent

# 加载环境变量
_env_path = Path(__file__).resolve().parent / "context_rca" / ".env"
load_dotenv(_env_path, override=False)

# ============================================================
# 配置
# ============================================================
USER_ID = "user"
APP_NAME = "context_rca"

LOG_DIR = "logs"

# 基础日志配置 (控制台只输出 INFO)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt='%H:%M:%S'
)

logger = logging.getLogger("RootCauseAnalysis")

# ============================================================
# 辅助类：独立文件日志
# ============================================================
class CaseLogger:
    """为每个 Case 管理独立的文件日志"""
    def __init__(self, log_dir: str):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        self.file_handler = None
        self.logger = logging.getLogger("RootCauseAnalysis") # 绑定到业务 Logger

    def start(self, uuid: str):
        """开始记录：添加 FileHandler"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = os.path.join(self.log_dir, f"{timestamp}_{uuid}.log")
        
        self.file_handler = logging.FileHandler(log_file, encoding='utf-8')
        self.file_handler.setLevel(logging.INFO) # 文件记录详细信息
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.file_handler.setFormatter(formatter)
        
        self.logger.addHandler(self.file_handler)
        self.logger.info(f"=== START SESSION: {uuid} ===")
        return log_file

    def stop(self):
        """停止记录：移除 FileHandler"""
        if self.file_handler:
            self.logger.info("=== END SESSION ===")
            self.logger.removeHandler(self.file_handler)
            self.file_handler.close()
            self.file_handler = None

# ============================================================
# 核心逻辑
# ============================================================

class RCARunner:
    def __init__(self, output_path: str):
        self.output_path = output_path
        self.session_service = InMemorySessionService()
        self.runner = Runner(
            agent=orchestrator_agent,
            session_service=self.session_service,
            artifact_service=InMemoryArtifactService(),
            app_name=APP_NAME,
        )
        self.case_logger = CaseLogger(LOG_DIR)

    async def run_one(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """运行单条分析"""
        uuid = item.get("uuid", "unknown")
        session_id = f"session_{uuid_lib.uuid4().hex[:8]}"
        
        # 开启独立日志
        log_file = self.case_logger.start(uuid)
        logger.info(f"[Processing] {uuid} | Log: {log_file}")
        
        # 构建查询
        query_obj = {
            "Anomaly Description": item.get("Anomaly Description"),
            "uuid": uuid,
        }
        query_text = json.dumps(query_obj, ensure_ascii=False)
        
        # 创建会话
        await self.session_service.create_session(
            app_name=APP_NAME,
            user_id=USER_ID,
            session_id=session_id
        )
        
        # 运行 Agent
        content = types.Content(role="user", parts=[types.Part(text=query_text)])
        final_response = ""
        
        try:
            async for event in self.runner.run_async(
                user_id=USER_ID,
                session_id=session_id,
                new_message=content
            ):
                self._log_event_details(event)
                
                if event.is_final_response() and event.content:
                    final_response = event.content.parts[0].text
        except Exception as e:
            logger.error(f"Error in runner: {e}")
            # 记录到文件日志
            logging.getLogger("RootCauseAnalysis").error(f"Runner Exception: {e}", exc_info=True)

        # 获取最终 State
        session = await self.session_service.get_session(
            app_name=APP_NAME,
            user_id=USER_ID,
            session_id=session_id
        
        )
        state = session.state if session else {}
        
        self._log_state_summary(state)
        
        # 关闭独立日志
        self.case_logger.stop()

        return self._parse_result(state, final_response, uuid)

    def _log_event_details(self, event: Any):
        """记录详细事件到业务 Logger (会被写入文件)"""
        biz_logger = logging.getLogger("RootCauseAnalysis")
        
        # 1. 工具调用
        if hasattr(event, 'get_function_calls'):
            for call in event.get_function_calls():
                biz_logger.info(f"[Tool Call] {call.name}")
                biz_logger.info(f"    Args: {str(call.args)[:500]}...") # 记录更多参数细节
        
        # 2. 工具返回
        if hasattr(event, 'get_function_responses'):
            for resp in event.get_function_responses():
                resp_str = str(resp.response)
                preview = resp_str[:500] + "..." if len(resp_str) > 500 else resp_str
                biz_logger.info(f"[Tool Resp] {resp.name}")
                biz_logger.info(f"    Result: {preview}")

        # 3. 状态变更
        if hasattr(event, 'actions') and event.actions and event.actions.state_delta:
            delta = event.actions.state_delta
            filtered_delta = {k: v for k, v in delta.items() if k not in ["uuid", "user_query"]}
            if filtered_delta:
                biz_logger.info(f"[State Update] {json.dumps(filtered_delta, ensure_ascii=False)}")

    def _log_state_summary(self, state: Dict[str, Any]):
        """记录最终状态摘要"""
        biz_logger = logging.getLogger("RootCauseAnalysis")
        biz_logger.info("[Final State Summary]")
        keys_to_show = ["current_hypothesis", "consensus_decision", "consensus_iteration"]
        for k in keys_to_show:
            if k in state:
                biz_logger.info(f"   - {k}: {state[k]}")

    def _parse_result(self, state: Dict, text_resp: str, uuid: str) -> Dict:
        """解析结果"""
        # 优先从 report_agent 的输出中获取结果
        report_findings = state.get("report_analysis_findings")
        
        if report_findings and isinstance(report_findings, dict):
            logger.info(f"[Report Agent] Obtained structured report")
            return report_findings

        # 兜底逻辑
        hypothesis = state.get("current_hypothesis", "")
        if hypothesis == "（等待写入...）": hypothesis = ""
        
        return {
            "uuid": uuid,
            "component": "TODO", 
            "reason": hypothesis or text_resp,
        }

    async def run_batch(self, items: List[Dict]):
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
        # Append mode for safety
        with open(self.output_path, "a", encoding="utf-8") as f:
            for item in items:
                result = await self.run_one(item)
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
                f.flush()

# ============================================================
# 入口
# ============================================================

async def main():
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="Context-RCA Runner")
    parser.add_argument("--batch", action="store_true", help="Run in batch mode (process all items)")
    parser.add_argument("--random", type=int, default=0, help="Run in random mode with N items")
    parser.add_argument("--single", type=int, default=1, help="Run in single mode (process the N-th item, 1-based index, default: 1)")
    args = parser.parse_args()

    project_root = os.getenv("PROJECT_DIR", ".")
    input_path = os.path.join(project_root, "input", "minimal_input.json") 
    output_path = os.path.join(project_root, "output", "result.jsonl")
    
    # 加载数据
    try:
        with open(input_path, "r") as f:
            items = json.load(f)
    except FileNotFoundError:
        logger.error(f"Input file not found: {input_path}")
        return

    # 模式选择
    selected_items = []
    
    if args.batch:
        logger.info(f"[Batch Mode] Processing all {len(items)} items...")
        selected_items = items
    elif args.random > 0:
        count = min(args.random, len(items))
        logger.info(f"[Random Mode] Selecting {count} random items...")
        selected_items = random.sample(items, count)
    else:
        # Default to Single Mode
        idx = args.single - 1 # Convert 1-based to 0-based
        if 0 <= idx < len(items):
            logger.info(f"[Single Mode] Selecting item #{args.single} (UUID: {items[idx].get('uuid')})...")
            selected_items = [items[idx]]
        else:
            logger.error(f"Index {args.single} out of range (1-{len(items)})")
            return

    runner = RCARunner(output_path)
    await runner.run_batch(selected_items)

if __name__ == "__main__":
    asyncio.run(main())