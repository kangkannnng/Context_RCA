"""
Context-RCA Ablation Runner
"""
import os
import json
import asyncio
import logging
import random
import time
import argparse
import uuid as uuid_lib
import multiprocessing
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List

from dotenv import load_dotenv
from google.adk.sessions import InMemorySessionService
from google.adk.artifacts import InMemoryArtifactService
from google.adk.runners import Runner
from google.genai import types

# Import Run Utils
try:
    from run import scan_for_errors, clean_logs, load_jsonl, calculate_accuracy
except ImportError:
    # Fallback/Mock if run.py is missing or paths are wrong
    def scan_for_errors(*args): return [], [], {}
    def clean_logs(*args): pass
    def load_jsonl(*args): return {}
    def calculate_accuracy(*args): return 0,0,0

# Import Ablation Agents Factory
from context_rca.ablations.agent_variants import (
    create_wo_selective_context_agent,
    create_wo_consensus_iteration_agent,
    create_wo_sop_workflow_agent
)

# 加载环境变量
_env_path = Path(__file__).resolve().parent / "context_rca" / ".env"
load_dotenv(_env_path, override=False)

# ============================================================
# 配置
# ============================================================
USER_ID = "user"
APP_NAME = "context_rca_ablation"

LOG_DIR = "logs"

# 基础日志配置 (禁用控制台输出，只保留文件日志，防止淹没进度条)
# 我们不使用 basicConfig，而是手动配置 root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# 清除任何现有的 handlers (例如来自之前的 basicConfig 调用或库的自动配置)
# 这样可以确保没有日志被打印到终端
if root_logger.hasHandlers():
    root_logger.handlers.clear()

# 配置主业务 logger
logger = logging.getLogger("RootCauseAnalysis")
logger.setLevel(logging.INFO)
# 注意：我们不再添加 StreamHandler (控制台输出)，以便保持终端干净，只显示进度条。
# 所有的业务日志将只记录在文件中 (CaseLogger 会将 FileHandler 添加到 Root logger，
# 而 RootCauseAnalysis propagates to Root)。

# Explicitly silence noisy libraries (force them to use root logger only)
for lib in ["LiteLLM", "litellm", "google", "httpx", "httpcore", "openai"]:
    _l = logging.getLogger(lib)
    _l.handlers.clear()       # Remove direct handlers (like console)
    _l.propagate = True       # Allow bubbling to root (which has file handler only)
    _l.setLevel(logging.INFO) # Ensure we capture info logs in file

# ============================================================
# Agent Factory
# ============================================================
def get_agent_by_ablation_type(ablation_type: str):
    if ablation_type == "no_selective_context":
        return create_wo_selective_context_agent()
    elif ablation_type == "no_consensus_iteration":
        return create_wo_consensus_iteration_agent()
    elif ablation_type == "no_sop_workflow":
        return create_wo_sop_workflow_agent()
    else:
        raise ValueError(f"Unknown ablation type: {ablation_type}")

# ============================================================
# 辅助类：独立文件日志
# ============================================================
class CaseLogger:
    """为每个 Case 管理独立的文件日志"""
    def __init__(self, log_dir: str):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        self.file_handler = None
        self.logger = logging.getLogger()

    def start(self, uuid: str, run_id: int = 1):
        """开始记录：添加 FileHandler"""
        case_dir = os.path.join(self.log_dir, uuid)
        os.makedirs(case_dir, exist_ok=True)
        log_file = os.path.join(case_dir, "run.log")

        self.file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
        self.file_handler.setLevel(logging.INFO)
        # Simplified format as requested (No timestamp)
        formatter = logging.Formatter('%(levelname)s - %(message)s')
        self.file_handler.setFormatter(formatter)

        self.logger.addHandler(self.file_handler)
        self.logger.info(f"=== START SESSION: {uuid} (Run #{run_id}) ===")
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
    def __init__(self, output_path: str, agent_instance):
        self.output_path = output_path
        self.session_service = InMemorySessionService()
        self.runner = Runner(
            agent=agent_instance,  # Use passed agent instance
            session_service=self.session_service,
            artifact_service=InMemoryArtifactService(),
            app_name=APP_NAME,
        )
        self.case_logger = CaseLogger(LOG_DIR)

    async def run_one(self, item: Dict[str, Any], run_id: int = 1) -> Dict[str, Any]:
        """运行单条分析"""
        uuid = item.get("uuid", "unknown")
        session_id = f"session_{uuid_lib.uuid4().hex[:8]}"

        log_file = self.case_logger.start(uuid, run_id)
        logger.info(f"[Processing] {uuid} (Run #{run_id}) | Log: {log_file}")
        
        query_obj = {
            "Anomaly Description": item.get("Anomaly Description"),
            "uuid": uuid,
        }
        query_text = json.dumps(query_obj, ensure_ascii=False)
        
        await self.session_service.create_session(
            app_name=APP_NAME,
            user_id=USER_ID,
            session_id=session_id
        )
        
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
            logging.getLogger("RootCauseAnalysis").error(f"Runner Exception: {e}", exc_info=True)

        session = await self.session_service.get_session(
            app_name=APP_NAME,
            user_id=USER_ID,
            session_id=session_id
        )
        state = session.state if session else {}
        
        self._log_state_summary(state)
        self.case_logger.stop()

        return self._parse_result(state, final_response, uuid)

    def _log_event_details(self, event: Any):
        biz_logger = logging.getLogger("RootCauseAnalysis")
        if hasattr(event, 'get_function_calls'):
            for call in event.get_function_calls():
                biz_logger.info(f"[Tool Call] {call.name}")
                biz_logger.info(f"    Args: {str(call.args)[:500]}...")
        if hasattr(event, 'get_function_responses'):
            for resp in event.get_function_responses():
                resp_str = str(resp.response)
                preview = resp_str[:500] + "..." if len(resp_str) > 500 else resp_str
                biz_logger.info(f"[Tool Resp] {resp.name}")
                biz_logger.info(f"    Result: {preview}")
        if hasattr(event, 'actions') and event.actions and event.actions.state_delta:
            delta = event.actions.state_delta
            filtered_delta = {k: v for k, v in delta.items() if k not in ["uuid", "user_query"]}
            if filtered_delta:
                biz_logger.info(f"[State Update] {json.dumps(filtered_delta, ensure_ascii=False)}")

    def _log_state_summary(self, state: Dict[str, Any]):
        biz_logger = logging.getLogger("RootCauseAnalysis")
        biz_logger.info("[Final State Summary]")
        keys_to_show = ["current_hypothesis", "consensus_decision", "consensus_iteration"]
        for k in keys_to_show:
            if k in state:
                biz_logger.info(f"   - {k}: {state[k]}")

    def _parse_result(self, state: Dict, text_resp: str, uuid: str) -> Dict:
        report_findings = state.get("report_analysis_findings")
        if report_findings and isinstance(report_findings, dict):
            logger.info(f"[Report Agent] Obtained structured report")
            return report_findings

        hypothesis = state.get("current_hypothesis", "")
        if hypothesis == "（等待写入...）": hypothesis = ""
        
        return {
            "uuid": uuid,
            "component": "TODO", 
            "reason": hypothesis or text_resp,
        }

    async def run_batch(self, items: List[Dict], repeat: int = 1):
        dir_name = os.path.dirname(self.output_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        
        with open(self.output_path, "a", encoding="utf-8") as f:
            for item in items:
                uuid = item.get("uuid", "unknown")
                for run_id in range(1, repeat + 1):
                    if repeat > 1:
                        logger.info(f"[Repeat Mode] {uuid} - Run {run_id}/{repeat}")
                    result = await self.run_one(item, run_id)
                    result["run_id"] = run_id
                    f.write(json.dumps(result, ensure_ascii=False) + "\n")
                    f.flush()

# ============================================================
# 多进程 Worker
# ============================================================

def process_item_worker(item, run_id, queue, ablation_type):
    """Worker function for multiprocessing with Retries"""
    # Max Retries Config
    MAX_RETRIES = 3
    
    agent = None
    try:
        # Re-create agent in worker process
        agent = get_agent_by_ablation_type(ablation_type)
    except Exception as e:
        queue.put({
            "uuid": item.get("uuid"),
            "run_id": run_id,
            "component": "ERROR",
            "reason": f"Agent Init Failed: {str(e)}"
        })
        return

    last_result = None
    
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            runner = RCARunner(output_path="", agent_instance=agent)

            async def _run():
                return await runner.run_one(item, run_id)

            result = asyncio.run(_run())
            last_result = result
            
            # --- Result Validation (Retry Logic) ---
            # 1. Check for explicit internal error
            if result.get("component") == "ERROR":
                raise ValueError(f"Runner returned ERROR: {result.get('reason')}")
            
            # 2. Check for empty result or reason (Soft failure)
            reason = str(result.get("reason", "")).strip()
            if not result or not reason:
                raise ValueError("Analysis result or reason is empty")

            # 3. Check for placeholder text (indicates processing didn't finish properly)
            if "等待写入" in reason or "TODO" in str(result.get("component", "")):
                 # Note: "TODO" component might be default fallback, but if reason is good, we might accept it.
                 # User asked to check "is empty", so we focus on reason content validity.
                 if not reason or len(reason) < 5:
                     raise ValueError("Result reason definitely too short/empty")
            
            # If Valid:
            result["run_id"] = run_id
            queue.put(result)
            return

        except Exception as e:
            logging.getLogger("RootCauseAnalysis").warning(
                f"[Retry] {item.get('uuid')} (Run {run_id}) Attempt {attempt}/{MAX_RETRIES} failed: {e}"
            )
            # Random backoff to avoid thundering herd on API
            time.sleep(random.uniform(2, 5)) 

            if attempt == MAX_RETRIES:
                logging.getLogger("RootCauseAnalysis").error(
                    f"Worker failed for {item.get('uuid')} after {MAX_RETRIES} attempts."
                )
                if last_result:
                    last_result["run_id"] = run_id
                    last_result["component"] = "ERROR" # Force tag as error if max retries hit, or keep partial result?
                    # Usually better to return what we have but maybe mark it, 
                    # OR return the specific error for debug.
                    if not last_result.get("reason"):
                         last_result["reason"] = f"Failed after {MAX_RETRIES} retries. Last Error: {str(e)}"
                    queue.put(last_result)
                else:
                    queue.put({
                        "uuid": item.get("uuid"),
                        "run_id": run_id,
                        "component": "ERROR",
                        "reason": f"Worker Exception: {str(e)}"
                    })

# ============================================================
# 入口
# ============================================================

def execute_batch_cycle(items, output_path, args, ablation_type, desc="Processing"):
    """
    Execute a batch of items using multiprocessing pool
    Returns True if completed (does not verify results here)
    """
    if not items:
        return True
        
    logger.info(f"[{desc}] Starting batch with {len(items)} items...")
    print(f"[{desc}] Starting batch with {len(items)} items...") # Console output
    
    ctx = multiprocessing.get_context('spawn')
    manager = ctx.Manager()
    queue = manager.Queue()
    pool = ctx.Pool(processes=args.workers)

    for item in items:
        for run_id in range(1, args.repeat + 1):
            pool.apply_async(process_item_worker, args=(item, run_id, queue, ablation_type))

    pool.close()
    
    # Ensure dir exists if path contains a directory
    dir_name = os.path.dirname(output_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    
    from tqdm import tqdm
    total_count = len(items) * args.repeat
    
    # Append mode
    with open(output_path, "a", encoding="utf-8") as f:
        finished_count = 0
        with tqdm(total=total_count, desc=desc, unit="run") as pbar:
            while finished_count < total_count:
                result = queue.get()
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
                f.flush()
                finished_count += 1
                pbar.update(1)
    
    pool.join()
    return True

async def main():
    parser = argparse.ArgumentParser(description="Context-RCA Ablation Runner")
    # Ablation Argument
    parser.add_argument("--ablation", type=str, required=True, 
        choices=["no_selective_context", "no_consensus_iteration", "no_sop_workflow"],
        help="Choose ablation variant")
        
    parser.add_argument("--batch", action="store_true", help="Run in batch mode")
    parser.add_argument("--workers", type=int, default=1, help="Number of workers")
    parser.add_argument("--random", type=int, default=0, help="Run in random mode with N items")
    parser.add_argument("--single", type=str, default="1", help="Run in single mode")
    parser.add_argument("--repeat", type=int, default=1, help="Repeat count (per case)")
    parser.add_argument("--input", type=str, default=None, help="Input JSON path")
    parser.add_argument("--output", type=str, default=None, help="Output JSONL path")
    parser.add_argument("--log-dir", type=str, default="logs", help="Logs directory")
    parser.add_argument("--start", type=int, default=0, help="Start index")
    parser.add_argument("--limit", type=int, default=None, help="Limit items")
    
    # Retry/Round Args matches run.py
    parser.add_argument("--rounds", type=int, default=1, help="Max rounds for GT correction (Outer Loop)")
    parser.add_argument("--retries", type=int, default=3, help="Max retries for format errors (Inner Loop)")
    parser.add_argument("--groundtruth", default="output/groundtruth.jsonl", help="GT file for Oracle Retry")
    parser.add_argument("--resume", action="store_true", help="Resume from existing output file")

    args = parser.parse_args()

    global LOG_DIR
    LOG_DIR = args.log_dir

    project_root = os.getenv("PROJECT_DIR", ".")
    input_path = args.input if args.input else os.path.join(project_root, "input", "input.json")
    final_output_path = args.output if args.output else os.path.join(project_root, "output", f"result_{args.ablation}.jsonl")
    temp_run_output = final_output_path + ".temp"
    
    logger.info(f"=== Running Ablation Experiment: {args.ablation} ===")
    print(f"=== Running Ablation Experiment: {args.ablation} ===")
    logger.info(f"Output will be saved to: {final_output_path}")
    print(f"Output will be saved to: {final_output_path}")

    try:
        with open(input_path, "r") as f:
            all_items = json.load(f)
    except FileNotFoundError:
        logger.error(f"Input file not found: {input_path}")
        return

    # 1. Select Items
    selected_items = []
    if args.batch:
        start_idx = args.start
        end_idx = start_idx + args.limit if args.limit is not None else len(all_items)
        end_idx = min(end_idx, len(all_items))
        logger.info(f"[Mode] Batch: items {start_idx} to {end_idx}")
        selected_items = all_items[start_idx:end_idx]
    elif args.random > 0:
        count = min(args.random, len(all_items))
        logger.info(f"[Mode] Random: {count} items")
        selected_items = random.sample(all_items, count)
    else:
        single_arg = args.single
        if single_arg.isdigit():
            idx = int(single_arg) - 1
            if 0 <= idx < len(all_items):
                logger.info(f"[Mode] Single: Item #{single_arg} (UUID: {all_items[idx].get('uuid')})")
                selected_items = [all_items[idx]]
        else:
            found_items = [item for item in all_items if item.get("uuid") == single_arg]
            if found_items:
                logger.info(f"[Mode] Single: UUID {single_arg}")
                selected_items = found_items

    if not selected_items:
        logger.error("No items selected.")
        return

    # Load GT if available
    gt_map = {}
    if args.groundtruth and os.path.exists(args.groundtruth):
        logger.info(f"Loading Ground Truth from {args.groundtruth}")
        gt_data = load_jsonl(args.groundtruth)
        gt_map = gt_data # load_jsonl returns map

    # ==========================
    # Phase 1: Initial Run
    # ==========================
    if args.resume and os.path.exists(final_output_path):
        import shutil
        logger.info(f"Resuming from {final_output_path}...")
        shutil.copy(final_output_path, temp_run_output)
    else:
        # Clear/Init temp output
        if os.path.exists(temp_run_output):
            os.remove(temp_run_output)
            
        logger.info("\n>>> Phase 1: Initial Execution")
        print("\n>>> Phase 1: Initial Execution")
        if args.workers > 1:
            execute_batch_cycle(selected_items, temp_run_output, args, args.ablation, desc="Initial Run")
        else:
            # Single Process Fallback
            agent = get_agent_by_ablation_type(args.ablation)
            runner = RCARunner(temp_run_output, agent_instance=agent)
            await runner.run_batch(selected_items, repeat=args.repeat)

    # Initial Eval
    current_data = load_jsonl(temp_run_output)
    if gt_map:
        acc, corr, tot = calculate_accuracy(current_data, gt_map)
        logger.info(f"Phase 1 Accuracy: {acc:.2%} ({corr}/{tot})")
        print(f"Phase 1 Accuracy: {acc:.2%} ({corr}/{tot})")

    # ==========================
    # Phase 2: Retry Loop
    # ==========================
    # Only supported in Multi-Process/Worker mode for now as execute_batch_cycle uses it
    if args.workers > 1 and (args.rounds > 1 or args.retries > 0):
        retry_dir = "retry_tasks"
        if os.path.exists(retry_dir): import shutil; shutil.rmtree(retry_dir)
        os.makedirs(retry_dir, exist_ok=True)

        for round_idx in range(args.rounds):
            logger.info(f"\n=== Round {round_idx+1}/{args.rounds} ===")
            print(f"\n=== Round {round_idx+1}/{args.rounds} ===")
            
            # --- Inner Loop: Format Retries ---
            for retry_idx in range(args.retries):
                format_errors, wrong_answers, stats = scan_for_errors(temp_run_output, input_path, gt_map if args.groundtruth else None)
                
                # Filter format errors to only those in our current selected_items
                selected_uuids = {i['uuid'] for i in selected_items}
                relevant_format_errors = [c for c in format_errors if c['uuid'] in selected_uuids]
                
                if not relevant_format_errors:
                    logger.info("  Format check passed.")
                    break
                    
                logger.info(f"  [Format Retry {retry_idx+1}/{args.retries}] Found {len(relevant_format_errors)} format errors. Retrying...")
                
                # Clean logs
                clean_logs(LOG_DIR, relevant_format_errors)
                
                # Run Logic
                retry_output = os.path.join(retry_dir, f"output_r{round_idx}_try{retry_idx}.jsonl")
                execute_batch_cycle(relevant_format_errors, retry_output, args, args.ablation, desc=f"Retry {retry_idx+1}")
                
                # Merge
                base_data = load_jsonl(temp_run_output)
                new_data = load_jsonl(retry_output)
                base_data.update(new_data)
                
                with open(temp_run_output, 'w') as f:
                    for item in base_data.values():
                        f.write(json.dumps(item, ensure_ascii=False) + '\n')

            # --- End of Round Check: Oracle ---
            # If rounds > 1, we check for Wrong Answers and retry them
            if args.rounds > 1:
                format_errors, wrong_answers, stats = scan_for_errors(temp_run_output, input_path, gt_map if args.groundtruth else None)
                selected_uuids = {i['uuid'] for i in selected_items}
                relevant_wrong = [c for c in wrong_answers if c['uuid'] in selected_uuids]
                relevant_format = [c for c in format_errors if c['uuid'] in selected_uuids]
                
                if not relevant_wrong and not relevant_format:
                    logger.info("  >>> All answers correct (or no GT)!")
                    print("  >>> All answers correct (or no GT)!")
                    break
                
                if round_idx < args.rounds - 1:
                    next_round_cases = relevant_wrong + relevant_format
                    logger.info(f"  >>> Found {len(relevant_wrong)} wrong + {len(relevant_format)} errors. Starting next round with {len(next_round_cases)} cases...")
                    print(f"  >>> Found {len(relevant_wrong)} wrong + {len(relevant_format)} errors. Starting next round with {len(next_round_cases)} cases...")
                    
                    clean_logs(LOG_DIR, next_round_cases)
                    
                    round_output = os.path.join(retry_dir, f"output_round_{round_idx+2}.jsonl")
                    execute_batch_cycle(next_round_cases, round_output, args, args.ablation, desc=f"Round {round_idx+2}")
                    
                    # Merge
                    base_data = load_jsonl(temp_run_output)
                    new_data = load_jsonl(round_output)
                    base_data.update(new_data)
                    
                    with open(temp_run_output, 'w') as f:
                        for item in base_data.values():
                            f.write(json.dumps(item, ensure_ascii=False) + '\n')
                            
                    # Eval
                    if gt_map:
                        acc, corr, tot = calculate_accuracy(base_data, gt_map)
                        logger.info(f"  Round {round_idx+2} Accuracy: {acc:.2%} ({corr}/{tot})")
                        print(f"  Round {round_idx+2} Accuracy: {acc:.2%} ({corr}/{tot})")
                else:
                    logger.info("  Max rounds reached.")
                    print("  Max rounds reached.")


    # ==========================
    # Finalize
    # ==========================
    logger.info(f"\n>>> Finalizing output to {final_output_path}")
    print(f"\n>>> Finalizing output to {final_output_path}")
    if os.path.exists(temp_run_output):
        final_data = load_jsonl(temp_run_output)
        
        # Sort by input order
        ordered_items = []
        for inp in selected_items:
            uid = inp.get('uuid')
            if uid in final_data:
                ordered_items.append(final_data[uid])
        
        # Write final
        with open(final_output_path, 'w') as f:
            for item in ordered_items:
                f.write(json.dumps(item, ensure_ascii=False) + '\n')
                
        # Cleanup
        os.remove(temp_run_output)
        if args.workers > 1 and (args.rounds > 1 or args.retries > 0):
             import shutil
             if os.path.exists("retry_tasks"): shutil.rmtree("retry_tasks")

    logger.info("Done.")

if __name__ == "__main__":
    asyncio.run(main())
