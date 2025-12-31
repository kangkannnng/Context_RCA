"""
Context-RCA 批量运行器
读取 input/input.json，调用 orchestrator_agent 进行根因分析，输出到 output/output.jsonl
支持详细的执行日志记录，包括 agent 调用链、工具调用、状态变化等
"""

import os
import json
import asyncio
import warnings
import logging
import random
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
import uuid as uuid_lib

from dotenv import load_dotenv
from google.adk.sessions import InMemorySessionService
from google.adk.artifacts import InMemoryArtifactService
from google.adk.runners import Runner
from google.genai import types

from context_rca.agent import orchestrator_agent

# 加载环境变量（从 context_rca/.env）
_env_path = Path(__file__).resolve().parent / "context_rca" / ".env"
load_dotenv(_env_path, override=False)

# ============================================================
# 配置常量
# ============================================================

USER_ID = "user"
APP_NAME = "context_rca"

# 运行模式: single | test | batch
RUN_MODE = "batch"
TEST_COUNT = 10  # test 模式下随机抽取的条目数

# 日志配置
LOG_TO_FILE = True  # 是否保存日志到文件
LOG_LEVEL = logging.INFO  # 日志级别
LOG_DIR = "logs"  # 日志目录

# ============================================================
# 日志系统
# ============================================================


class RCALogger:
    """RCA 专用日志记录器，支持文件和控制台输出"""

    def __init__(self, log_dir: str = LOG_DIR, log_to_file: bool = LOG_TO_FILE):
        self.log_dir = log_dir
        self.log_to_file = log_to_file
        self.current_log_file: Optional[str] = None
        self.file_handler: Optional[logging.FileHandler] = None

        # 创建日志目录
        if log_to_file:
            os.makedirs(log_dir, exist_ok=True)

        # 配置根日志记录器
        self.logger = logging.getLogger("RootCauseAnalysis")
        self.logger.setLevel(LOG_LEVEL)
        self.logger.handlers.clear()

        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_format = logging.Formatter(
            '%(asctime)s | %(levelname)-7s | %(message)s',
            datefmt='%H:%M:%S'
        )
        console_handler.setFormatter(console_format)
        self.logger.addHandler(console_handler)

    def start_session(self, uuid: str, session_id: str) -> str:
        """开始新的分析会话，创建对应的日志文件"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = f"{timestamp}_{uuid}.log"
        self.current_log_file = os.path.join(self.log_dir, log_filename)

        # 移除旧的文件处理器
        if self.file_handler:
            self.logger.removeHandler(self.file_handler)
            self.file_handler.close()

        # 创建新的文件处理器
        if self.log_to_file:
            self.file_handler = logging.FileHandler(
                self.current_log_file, encoding='utf-8'
            )
            self.file_handler.setLevel(LOG_LEVEL)
            file_format = logging.Formatter(
                '%(asctime)s | %(levelname)-7s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            self.file_handler.setFormatter(file_format)
            self.logger.addHandler(self.file_handler)

        self.logger.info("=" * 80)
        self.logger.info(f"RCA 分析会话开始")
        self.logger.info(f"  UUID: {uuid}")
        self.logger.info(f"  Session ID: {session_id}")
        self.logger.info(f"  Log File: {self.current_log_file}")
        self.logger.info("=" * 80)

        return self.current_log_file

    def end_session(self, result: Dict[str, Any]) -> None:
        """结束分析会话"""
        self.logger.info("=" * 80)
        self.logger.info("RCA 分析会话结束")
        self.logger.info(f"  Component: {result.get('component', 'N/A')}")
        self.logger.info(f"  Reason: {result.get('reason', 'N/A')[:100]}")
        self.logger.info("=" * 80)

    def log_event(self, event: Any, event_index: int) -> None:
        """记录单个事件的详细信息"""
        separator = "-" * 60

        # 基本信息
        author = getattr(event, 'author', 'unknown')
        event_id = getattr(event, 'id', 'N/A')
        invocation_id = getattr(event, 'invocation_id', 'N/A')
        is_partial = getattr(event, 'partial', False)

        self.logger.debug(separator)
        self.logger.debug(f"Event #{event_index}")
        self.logger.debug(f"  Author: {author}")
        self.logger.debug(f"  Event ID: {event_id}")
        self.logger.debug(f"  Invocation ID: {invocation_id}")
        self.logger.debug(f"  Partial: {is_partial}")

        # Agent 调用（非用户消息）
        if author and author != "user":
            self.logger.info(f"[Agent] {author}")

        # 工具调用请求
        function_calls = event.get_function_calls() if hasattr(event, 'get_function_calls') else []
        if function_calls:
            for call in function_calls:
                tool_name = getattr(call, 'name', 'unknown')
                tool_args = getattr(call, 'args', {})

                # 简化参数显示
                args_preview = str(tool_args)
                if len(args_preview) > 200:
                    args_preview = args_preview[:200] + "..."

                self.logger.info(f"  [Tool Call] {tool_name}")
                self.logger.debug(f"    Args: {args_preview}")

        # 工具调用响应
        function_responses = event.get_function_responses() if hasattr(event, 'get_function_responses') else []
        if function_responses:
            for response in function_responses:
                resp_name = getattr(response, 'name', 'unknown')
                resp_response = getattr(response, 'response', {})

                # 简化响应显示
                resp_preview = str(resp_response)
                if len(resp_preview) > 500:
                    resp_preview = resp_preview[:500] + "..."

                self.logger.info(f"  [Tool Response] {resp_name}")
                self.logger.debug(f"    Response: {resp_preview}")

        # 文本内容
        if event.content and event.content.parts:
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    text = part.text
                    preview = text[:200].replace("\n", " ")
                    if len(text) > 200:
                        preview += "..."

                    status = "[Streaming]" if is_partial else "[Response]"
                    self.logger.info(f"  {status} {preview}")

                    # 详细日志记录完整文本
                    self.logger.debug(f"  Full Text ({len(text)} chars):")
                    for line in text.split('\n')[:20]:  # 最多记录前20行
                        self.logger.debug(f"    {line}")
                    if text.count('\n') > 20:
                        self.logger.debug(f"    ... ({text.count(chr(10)) - 20} more lines)")

        # Actions（状态变化、转移等）
        if hasattr(event, 'actions') and event.actions:
            actions = event.actions

            # 状态变化
            if hasattr(actions, 'state_delta') and actions.state_delta:
                self.logger.info(f"  [State Delta] {list(actions.state_delta.keys())}")
                self.logger.debug(f"    Details: {actions.state_delta}")

            # Agent 转移
            if hasattr(actions, 'transfer_to_agent') and actions.transfer_to_agent:
                self.logger.info(f"  [Transfer] → {actions.transfer_to_agent}")

            # 升级/终止
            if hasattr(actions, 'escalate') and actions.escalate:
                self.logger.info(f"  [Escalate] Terminating execution")

        # Final Response 标记
        if event.is_final_response():
            self.logger.info(f"  [Final Response]")

    def log_session_state(self, session: Any) -> None:
        """记录 session 状态"""
        if session and session.state:
            self.logger.info("Session State Summary:")
            for key, value in session.state.items():
                if isinstance(value, str) and len(value) > 100:
                    self.logger.info(f"  {key}: ({len(value)} chars)")
                elif isinstance(value, dict):
                    self.logger.info(f"  {key}: {json.dumps(value, ensure_ascii=False)[:100]}...")
                else:
                    self.logger.info(f"  {key}: {value}")


# 全局日志记录器
rca_logger = RCALogger()


# ============================================================
# 工具函数
# ============================================================


def setup_environment() -> tuple[str, str, str]:
    """初始化环境，返回 (project_root, input_path, output_path)"""
    warnings.filterwarnings(
        "ignore", category=RuntimeWarning, message=".*close_litellm_async_clients.*"
    )

    repo_root_default = Path(__file__).resolve().parent
    project_root = os.getenv("PROJECT_DIR", str(repo_root_default))

    # input_path = os.path.join(project_root, "input", "input.json")
    input_path = os.path.join(project_root, "input", "minimal_input.json")
    output_dir = os.path.join(project_root, "output")
    output_path = os.path.join(output_dir, "result.jsonl")

    os.makedirs(output_dir, exist_ok=True)

    print(f"项目根目录: {project_root}")
    return project_root, input_path, output_path


def load_input_items(input_path: str) -> List[Dict[str, Any]]:
    """加载输入 JSON 文件"""
    with open(input_path, "r", encoding="utf-8") as f:
        try:
            items = json.load(f)
        except json.JSONDecodeError as e:
            raise SystemExit(f"无法解析 {input_path}: {e}")

    if not isinstance(items, list):
        raise SystemExit(f"输入文件 {input_path} 不是数组，请提供对象数组。")

    return items


def parse_response(resp_text: str, fallback_uuid: str) -> Dict[str, Any]:
    """解析响应文本，返回标准化的结果字典"""
    # 尝试从响应中提取 JSON
    try:
        # 尝试直接解析
        parsed = json.loads(resp_text)
        return {
            "component": parsed.get("component", ""),
            "uuid": parsed.get("uuid", fallback_uuid),
            "reason": parsed.get("reason", ""),
            "reasoning_trace": parsed.get("reasoning_trace", []),
        }
    except (json.JSONDecodeError, TypeError):
        # 尝试从文本中提取 JSON 块
        import re
        json_match = re.search(r'\{[^{}]*"component"[^{}]*\}', resp_text, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                return {
                    "component": parsed.get("component", ""),
                    "uuid": parsed.get("uuid", fallback_uuid),
                    "reason": parsed.get("reason", ""),
                    "reasoning_trace": parsed.get("reasoning_trace", []),
                }
            except json.JSONDecodeError:
                pass

        return {
            "component": "",
            "uuid": fallback_uuid,
            "reason": "",
            "reasoning_trace": [],
        }


def build_query(item: Dict[str, Any]) -> str:
    """构建查询字符串，供 user_proxy 解析"""
    query_obj = {
        "Anomaly Description": item.get("Anomaly Description"),
        "uuid": item.get("uuid"),
    }
    return json.dumps(query_obj, ensure_ascii=False)


# ============================================================
# 核心运行逻辑
# ============================================================


class RCARunner:
    """RCA 批量运行器"""

    def __init__(self, output_path: str):
        self.output_path = output_path
        self.output_dir = os.path.dirname(output_path)
        self.session_service = InMemorySessionService()
        self.artifact_service = InMemoryArtifactService()
        self.runner = Runner(
            agent=orchestrator_agent,
            session_service=self.session_service,
            artifact_service=self.artifact_service,
            app_name=APP_NAME,
        )

    def _generate_session_id(self) -> str:
        """生成唯一的 session ID"""
        return f"session_{uuid_lib.uuid4().hex[:8]}"

    async def create_session(self, session_id: str) -> None:
        """创建新会话"""
        await self.session_service.create_session(
            app_name=APP_NAME,
            user_id=USER_ID,
            session_id=session_id,
        )

    async def run_one(self, query_text: str, session_id: str, item_uuid: str) -> str:
        """运行单条查询，返回响应文本"""
        content = types.Content(role="user", parts=[types.Part(text=query_text)])
        final_response_text = ""
        event_index = 0

        rca_logger.logger.info("开始处理请求...")
        rca_logger.logger.debug(f"Query: {query_text}")

        async for event in self.runner.run_async(
            user_id=USER_ID, session_id=session_id, new_message=content
        ):
            event_index += 1
            rca_logger.log_event(event, event_index)

            # 收集最终响应（不要 break，继续处理所有事件）
            if event.is_final_response():
                if event.content and event.content.parts:
                    final_response_text = event.content.parts[0].text or ""
                elif event.actions and event.actions.escalate:
                    final_response_text = event.error_message or ""

        rca_logger.logger.info(f"共处理 {event_index} 个事件")

        # 获取并记录 session state
        session = await self.session_service.get_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=session_id
        )

        if session:
            rca_logger.log_session_state(session)

            # 从 session state 获取 report_analysis_findings（优先使用）
            if session.state:
                report_findings = session.state.get("report_analysis_findings")
                if report_findings:
                    # report_findings 可能是 dict 或 str
                    if isinstance(report_findings, dict):
                        return json.dumps(report_findings, ensure_ascii=False)
                    elif isinstance(report_findings, str):
                        return report_findings

        return final_response_text.strip()

    async def run_batch(self, items: List[Dict[str, Any]]) -> int:
        """批量运行，返回处理条目数"""
        count = 0
        total = len(items)

        with open(self.output_path, "a", encoding="utf-8") as out_f:
            for idx, item in enumerate(items, 1):
                if not isinstance(item, dict):
                    rca_logger.logger.warning("跳过非对象条目。")
                    continue

                item_uuid = item.get("uuid")
                if not item_uuid:
                    rca_logger.logger.warning("跳过缺少 uuid 的条目。")
                    continue

                # 每个查询使用新的 session（确保 state 干净）
                session_id = self._generate_session_id()
                await self.create_session(session_id)

                # 开始日志会话
                log_file = rca_logger.start_session(item_uuid, session_id)

                query_text = build_query(item)
                rca_logger.logger.info(f"[{idx}/{total}] 处理 UUID: {item_uuid}")

                try:
                    resp_text = await self.run_one(query_text, session_id, item_uuid)

                    result = parse_response(resp_text, item_uuid)

                    # 结束日志会话
                    rca_logger.end_session(result)

                    out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
                    out_f.flush()  # 及时写入
                    count += 1

                    rca_logger.logger.info(f"结果已保存: component={result.get('component', 'N/A')}")

                except Exception as e:
                    rca_logger.logger.error(f"处理 {item_uuid} 失败: {e}")
                    import traceback
                    rca_logger.logger.debug(traceback.format_exc())

                    # 写入空结果
                    result = {
                        "component": "",
                        "uuid": item_uuid,
                        "reason": f"Error: {str(e)}",
                        "reasoning_trace": [],
                    }
                    rca_logger.end_session(result)
                    out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
                    out_f.flush()

        rca_logger.logger.info(f"批量处理完成，共写入 {count} 条结果到 {self.output_path}")
        return count

    async def run_single(self, item: Dict[str, Any]) -> None:
        """运行单条测试"""
        item_uuid = item.get("uuid")
        query_text = build_query(item)

        # 创建新 session
        session_id = self._generate_session_id()
        await self.create_session(session_id)

        # 开始日志会话
        log_file = rca_logger.start_session(item_uuid, session_id)

        rca_logger.logger.info(f"单条测试 UUID: {item_uuid}")
        result_text = await self.run_one(query_text, session_id, item_uuid)

        # 解析结果
        result = parse_response(result_text, item_uuid)
        rca_logger.end_session(result)

        # 保存结果
        single_output_path = os.path.join(self.output_dir, "single_output.jsonl")
        with open(single_output_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")

        rca_logger.logger.info(f"最终响应:")
        rca_logger.logger.info(f"  Component: {result.get('component', 'N/A')}")
        rca_logger.logger.info(f"  Reason: {result.get('reason', 'N/A')}")

        if result["component"]:
            rca_logger.logger.info(f"单条结果已保存到: {single_output_path}")
            if log_file:
                rca_logger.logger.info(f"详细日志已保存到: {log_file}")
        else:
            rca_logger.logger.warning(f"响应解析失败，已保存空结构到: {single_output_path}")


# ============================================================
# 主入口
# ============================================================


async def main():
    """主函数"""
    _, input_path, output_path = setup_environment()
    items = load_input_items(input_path)

    runner = RCARunner(output_path)

    if RUN_MODE == "batch":
        print(f"\n[Batch Mode] 处理全部 {len(items)} 条数据")
        await runner.run_batch(items)

    elif RUN_MODE == "test":
        print(f"\n[Test Mode] 从 {len(items)} 条数据中随机抽取 {TEST_COUNT} 条")
        selected_items = random.sample(items, min(TEST_COUNT, len(items)))
        await runner.run_batch(selected_items)

    else:  # single
        print("\n[Single Mode] 单条测试")
        await runner.run_single(items[0])


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n用户中断运行")
    except Exception as e:
        print(f"运行时出错: {e}")
        import traceback
        traceback.print_exc()
