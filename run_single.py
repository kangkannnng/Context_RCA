import asyncio
import json
import os
import sys
import argparse
import subprocess
import math
import shutil
import time
from pathlib import Path
from dotenv import load_dotenv
from google.genai import types

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.artifacts import InMemoryArtifactService

from single.agent import root_agent

# 加载环境变量
_env_path = Path(__file__).resolve().parent / "context_rca" / ".env"
load_dotenv(_env_path, override=False)

APP_NAME = "context_rca"
USER_ID = "user"

async def run_single_case(uuid: str, description: str, session_service, artifact_service):
    """运行单个Case"""
    # print(f"Starting analysis for UUID: {uuid}") # Reduce log noise in parallel
    
    runner = Runner(
        agent=root_agent,
        session_service=session_service,
        artifact_service=artifact_service,
        app_name=APP_NAME,
    )

    input_data = {
        "uuid": uuid,
        "Anomaly Description": description
    }
    
    # 构造消息
    content = types.Content(role="user", parts=[types.Part(text=json.dumps(input_data))])

    # 先创建 Session
    await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=uuid
    )


    # 准备日志目录
    log_dir = os.path.join("single", "logs", uuid)
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "analysis.log")

    # 运行
    final_response = ""
    with open(log_file, "w", encoding="utf-8") as f_log:
        f_log.write(f"Starting analysis for UUID: {uuid}\n")
        f_log.write(f"Description: {description}\n\n")
        
        async for event in runner.run_async(
            session_id=uuid,
            user_id=USER_ID,
            new_message=content
        ):
            # 记录工具调用和响应
            if hasattr(event, 'get_function_calls'):
                for call in event.get_function_calls():
                    f_log.write(f"[Tool Call] {call.name}\nArgs: {call.args}\n\n")
                    f_log.flush()
            
            if hasattr(event, 'get_function_responses'):
                for resp in event.get_function_responses():
                    f_log.write(f"[Tool Response] {resp.name}\nResult: {resp.response}\n\n")
                    f_log.flush()

            if hasattr(event, 'is_final_response') and event.is_final_response() and event.content:
                text = event.content.parts[0].text
                if text:
                    final_response = text
                    f_log.write(f"[Final Response]\n{text}\n")
                    f_log.flush()
    
    return final_response

async def worker_loop(input_file, output_file):
    """Worker process logic: process a subset of cases"""
    if not os.path.exists(input_file):
        print(f"Error: Input file {input_file} not found.")
        return
    
    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    total_cases = len(data)
    # print(f"[Worker] Processing {total_cases} cases from {input_file} -> {output_file}")
    
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    
    session_service = InMemorySessionService()
    artifact_service = InMemoryArtifactService()
    
    for index, item in enumerate(data):
        uuid = item.get('uuid')
        description = item.get('Anomaly Description')
        
        if not uuid:
            continue
            
        try:
            response_str = await run_single_case(uuid, description, session_service, artifact_service)
            
            try:
                response_data = json.loads(response_str)
            except json.JSONDecodeError:
                response_data = {"raw_response": response_str}
            
            if isinstance(response_data, dict):
                if "uuid" not in response_data:
                    response_data["uuid"] = uuid
                final_record = response_data
            else:
                final_record = {
                    "uuid": uuid,
                    "response": response_data
                }

            with open(output_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(final_record, ensure_ascii=False) + "\n")
            
            # print(f"[Worker] Finished {uuid}")
            
        except Exception as e:
            print(f"[Worker] Error processing {uuid}: {e}")
            error_record = {
                "uuid": uuid,
                "error": str(e)
            }
            with open(output_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(error_record, ensure_ascii=False) + "\n")

def manager_logic(args):
    """Manager logic: split work and spawn workers"""
    input_file = args.input
    output_file = args.output
    workers = args.workers

    if not os.path.exists(input_file):
        print(f"Error: Input file {input_file} not found.")
        return

    with open(input_file, 'r') as f:
        data = json.load(f)
    
    total_items = len(data)
    if workers > total_items:
        workers = total_items

    chunk_size = math.ceil(total_items / workers)
    print(f"Starting manager: {total_items} items, {workers} workers, ~{chunk_size} items/worker")

    # Temp directories
    tmp_dir = "tmp/single_run"
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir, exist_ok=True)
    
    processes = []
    temp_files = []

    for i in range(workers):
        start_idx = i * chunk_size
        end_idx = min((i + 1) * chunk_size, total_items)
        if start_idx >= total_items:
            break
            
        chunk_data = data[start_idx:end_idx]
        
        temp_input = os.path.join(tmp_dir, f"input_{i}.json")
        temp_output = os.path.join(tmp_dir, f"output_{i}.jsonl")
        
        with open(temp_input, 'w') as f:
            json.dump(chunk_data, f, indent=2)
            
        temp_files.append(temp_output)
        
        cmd = [
            sys.executable, __file__,
            "--worker",
            "--input", temp_input,
            "--output", temp_output
        ]
        
        p = subprocess.Popen(cmd)
        processes.append(p)
        print(f"Launched worker {i} (PID {p.pid})")

    # Monitor with progress bar
    try:
        from tqdm import tqdm
    except ImportError:
        # Fallback dummy tqdm
        class tqdm:
            def __init__(self, total=None, unit="it", desc=""): self.n=0
            def update(self, n=1): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass


    with tqdm(total=total_items, unit="case", desc="Progress") as pbar:
        last_count = 0
        while True:
            # Check if potential zombies or finished
            all_dead = all(p.poll() is not None for p in processes)
            
            # Count lines in output files
            current_count = 0
            for temp_out in temp_files:
                if os.path.exists(temp_out):
                    try:
                        # Simple line counting
                        with open(temp_out, 'rb') as f:
                            current_count += sum(1 for _ in f)
                    except Exception:
                        pass
            
            delta = current_count - last_count
            if delta > 0:
                pbar.update(delta)
                last_count = current_count

            if all_dead:
                # One last check
                current_count = 0
                for temp_out in temp_files:
                    if os.path.exists(temp_out):
                        try:
                            with open(temp_out, 'rb') as f:
                                current_count += sum(1 for _ in f)
                        except Exception:
                            pass
                delta = current_count - last_count
                if delta > 0:
                     pbar.update(delta)
                break
            
            time.sleep(1)
        
    print("All workers finished. Merging results...")
    
    # Merge
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, 'w') as outfile:
        for temp_out in temp_files:
            if os.path.exists(temp_out):
                with open(temp_out, 'r') as infile:
                    outfile.write(infile.read())
                    # Ensure newline if missing (though jsonl typically has it)
                    # outfile.write("\n") 
    
    print(f"Done. Results saved to {output_file}")
    # Cleanup
    # shutil.rmtree(tmp_dir) # Optional: keep for debugging

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Single Agent Runner")
    parser.add_argument("--input", default="input/input.json", help="Input JSON file")
    parser.add_argument("--output", default="single/result.jsonl", help="Output JSONL file")
    parser.add_argument("--workers", type=int, default=1, help="Number of parallel workers")
    parser.add_argument("--worker", action="store_true", help="Run in worker mode (internal use)")
    
    args = parser.parse_args()

    if args.worker:
        asyncio.run(worker_loop(args.input, args.output))
    else:
        if args.workers > 1:
            manager_logic(args)
        else:
            # Single process mode directly
            asyncio.run(worker_loop(args.input, args.output))
