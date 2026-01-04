#!/usr/bin/env python3
import json
import os
import argparse
import sys
import shutil
import subprocess
import time
import uuid
from math import ceil
from collections import Counter
try:
    from tqdm import tqdm
except ImportError:
    def tqdm(total=None, unit="it", desc=""):
        class MockTqdm:
            def __init__(self, total): self.n = 0
            def update(self, n=1): self.n += n
            def __enter__(self): return self
            def __exit__(self, *args): pass
        return MockTqdm(total)

# ==========================================
# Shared Utilities
# ==========================================

def load_jsonl(filepath):
    data = {}
    if not os.path.exists(filepath):
        return data
    with open(filepath, 'r') as f:
        for line in f:
            if line.strip():
                try:
                    item = json.loads(line)
                    if 'uuid' in item:
                        data[item['uuid']] = item
                except json.JSONDecodeError:
                    pass
    return data

def normalize_instance(instance):
    if isinstance(instance, str):
        return {instance.strip()}
    elif isinstance(instance, list):
        return {i.strip() for i in instance}
    return set()

def run_distributed_logic(input_file, output_file, workers, log_dir):
    """Core distributed runner logic"""
    # Generate a unique session ID
    session_id = uuid.uuid4().hex[:8]
    tmp_dir = os.path.join("tmp", session_id)
    os.makedirs(tmp_dir, exist_ok=True)
    
    if not os.path.exists(input_file):
        print(f"Error: Input file {input_file} not found.")
        return False

    with open(input_file, 'r') as f:
        data = json.load(f)
    
    total_items = len(data)
    if total_items == 0:
        print("Input file is empty.")
        return True

    if workers > total_items:
        workers = total_items
        
    chunk_size = ceil(total_items / workers)
    
    print(f"Running distributed session: {session_id}")
    print(f"Items: {total_items}, Workers: {workers}")
    
    processes = []
    temp_files = []
    
    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)

    # Split and Launch
    for i in range(workers):
        start_idx = i * chunk_size
        end_idx = min((i + 1) * chunk_size, total_items)
        
        if start_idx >= total_items:
            break
            
        chunk_data = data[start_idx:end_idx]
        
        temp_input = os.path.join(tmp_dir, f"temp_input_{i}.json")
        temp_output = os.path.join(tmp_dir, f"temp_output_{i}.jsonl")
        worker_log = os.path.join(tmp_dir, f"worker_{i}.log")
        
        temp_files.append({
            "input": temp_input,
            "output": temp_output,
            "worker_log": worker_log
        })
        
        with open(temp_input, 'w') as f:
            json.dump(chunk_data, f, indent=2, ensure_ascii=False)
            
        cmd = [
            sys.executable, "main.py",
            "--batch",
            "--input", temp_input,
            "--output", temp_output,
            "--log-dir", log_dir
        ]
        
        with open(worker_log, "w") as log_f:
            p = subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT)
            processes.append(p)
    
    # Monitor Loop
    try:
        with tqdm(total=total_items, unit="case", desc="Progress") as pbar:
            while True:
                running = [p.poll() is None for p in processes]
                
                total_processed_count = 0
                for temp in temp_files:
                    out_file = temp["output"]
                    if os.path.exists(out_file):
                        try:
                            with open(out_file, 'rb') as f:
                                total_processed_count += sum(1 for _ in f)
                        except Exception:
                            pass
                
                if total_processed_count > pbar.n:
                    pbar.update(total_processed_count - pbar.n)
                
                if not any(running):
                    break
                
                time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nStopping all processes...")
        for p in processes:
            p.terminate()
        return False

    # Merge Results
    with open(output_file, 'w') as outfile:
        for temp in temp_files:
            t_out = temp["output"]
            if os.path.exists(t_out):
                with open(t_out, 'r') as infile:
                    for line in infile:
                        outfile.write(line)

    # Cleanup
    try:
        shutil.rmtree(tmp_dir)
    except Exception:
        pass
        
    return True

def calculate_accuracy(predictions, gt_map):
    if not gt_map: return 0.0, 0, 0
    correct = 0
    total = 0
    for uid, item in predictions.items():
        if uid in gt_map:
            total += 1
            gt_inst = normalize_instance(gt_map[uid].get('instance', ''))
            pred = item.get('component', '').strip()
            if pred in gt_inst:
                correct += 1
    return (correct / total if total > 0 else 0.0), correct, total

def scan_for_errors(result_file, input_file, gt_map=None):
    """Scans result file for errors and returns list of failed cases"""
    if not os.path.exists(result_file):
        return []
        
    input_map = {}
    with open(input_file, 'r') as f:
        for item in json.load(f):
            if 'uuid' in item:
                input_map[item['uuid']] = item
                
    results = load_jsonl(result_file)
    failed_cases = []
    
    # Check for missing UUIDs
    for uuid, case in input_map.items():
        if uuid not in results:
            failed_cases.append(case)
            continue
            
        res = results[uuid]
        comp = str(res.get('component', '')).strip()
        reason = str(res.get('reason', '')).strip()
        
        # Check for TODO or empty
        if not comp or comp.upper() == "TODO" or comp == "":
            failed_cases.append(case)
        elif not reason:
            failed_cases.append(case)
        # Check against GT if provided (Oracle Mode)
        elif gt_map and uuid in gt_map:
            gt_inst = normalize_instance(gt_map[uuid].get('instance', ''))
            if comp not in gt_inst:
                failed_cases.append(case)
            
    return failed_cases

# ==========================================
# Commands
# ==========================================

def cmd_run(args):
    """Smart Run: Run -> Scan -> Retry -> Finalize"""
    print("Starting Smart Run...")
    
    # Load GT if provided
    gt_map = {}
    if args.groundtruth:
        if os.path.exists(args.groundtruth):
            with open(args.groundtruth, 'r') as f:
                # Handle both json list and jsonl
                try:
                    content = f.read().strip()
                    if content.startswith('['):
                        for x in json.loads(content):
                            if 'uuid' in x: gt_map[x['uuid']] = x
                    else:
                        for line in content.split('\n'):
                            if line.strip():
                                x = json.loads(line)
                                if 'uuid' in x: gt_map[x['uuid']] = x
                except:
                    pass
        else:
            print(f"Warning: Ground truth file {args.groundtruth} not found.")

    # 0. Setup
    final_output = args.output
    temp_run_output = final_output + ".temp"
    log_dir = args.log_dir
    
    if os.path.exists(log_dir):
        shutil.rmtree(log_dir)
    os.makedirs(log_dir, exist_ok=True)
    
    current_input = args.input
    
    # 1. Initial Run
    print("\n>>> Phase 1: Initial Execution")
    success = run_distributed_logic(current_input, temp_run_output, args.workers, log_dir)
    if not success:
        print("Execution interrupted.")
        return

    # Evaluate Phase 1
    if gt_map:
        current_data = load_jsonl(temp_run_output)
        acc, corr, tot = calculate_accuracy(current_data, gt_map)
        print(f"Phase 1 Accuracy: {acc:.2%} ({corr}/{tot})")

    # 2. Retry Loop
    for attempt in range(args.retries):
        # Pass gt_map to scan_for_errors to enable Oracle Retry
        failed_cases = scan_for_errors(temp_run_output, args.input, gt_map if args.groundtruth else None)
        if not failed_cases:
            print("\n>>> No errors found! Perfect run.")
            break
            
        print(f"\n>>> Phase 2.{attempt+1}: Found {len(failed_cases)} incorrect/invalid cases. Retrying...")
        
        retest_input = f"tmp_retest_{attempt}.json"
        retest_output = f"tmp_retest_{attempt}.jsonl"
        
        with open(retest_input, 'w') as f:
            json.dump(failed_cases, f, indent=2, ensure_ascii=False)
            
        success = run_distributed_logic(retest_input, retest_output, args.workers, log_dir)
        
        # Merge updates into main temp output
        base_data = load_jsonl(temp_run_output)
        new_data = load_jsonl(retest_output)
        base_data.update(new_data)
        
        with open(temp_run_output, 'w') as f:
            for item in base_data.values():
                f.write(json.dumps(item, ensure_ascii=False) + '\n')
        
        # Evaluate Phase 2.x
        if gt_map:
            acc, corr, tot = calculate_accuracy(base_data, gt_map)
            print(f"Phase 2.{attempt+1} Accuracy: {acc:.2%} ({corr}/{tot})")
                
        # Cleanup retest files
        if os.path.exists(retest_input): os.remove(retest_input)
        if os.path.exists(retest_output): os.remove(retest_output)

    # 3. Finalize
    print(f"\n>>> Finalizing output to {final_output}")
    final_data = load_jsonl(temp_run_output)
    
    # Sort by input order if possible
    try:
        with open(args.input, 'r') as f:
            input_order = [x['uuid'] for x in json.load(f) if 'uuid' in x]
            ordered_items = []
            for uid in input_order:
                if uid in final_data:
                    item = final_data[uid]
                    if 'run_id' in item: del item['run_id']
                    ordered_items.append(item)
            
            # Add any remaining that weren't in input (shouldn't happen but safe)
            for uid, item in final_data.items():
                if uid not in input_order:
                    if 'run_id' in item: del item['run_id']
                    ordered_items.append(item)
            
            final_items = ordered_items
    except:
        final_items = list(final_data.values())
        for item in final_items:
            if 'run_id' in item: del item['run_id']

    with open(final_output, 'w') as f:
        for item in final_items:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
            
    if os.path.exists(temp_run_output):
        os.remove(temp_run_output)
        
    print("Done.")

def cmd_compare(args):
    """Compare current results with baseline/GT"""
    if not os.path.exists(args.current):
        print(f"Error: Current file {args.current} not found.")
        return
        
    current = load_jsonl(args.current)
    baseline = load_jsonl(args.baseline) if args.baseline else {}
    
    # Load GT for accuracy calculation
    gt_map = {}
    if args.groundtruth and os.path.exists(args.groundtruth):
        with open(args.groundtruth, 'r') as f:
            try:
                content = f.read().strip()
                if content.startswith('['):
                    for x in json.loads(content):
                        if 'uuid' in x: gt_map[x['uuid']] = x
                else:
                    for line in content.split('\n'):
                        if line.strip():
                            x = json.loads(line)
                            if 'uuid' in x: gt_map[x['uuid']] = x
            except:
                pass
    
    if not gt_map:
        print("Warning: No Ground Truth file provided or found. Cannot calculate accuracy improvement.")
        # Fallback to simple diff if no GT
        if baseline:
            diffs = []
            for uid, item in current.items():
                if uid in baseline:
                    curr_comp = item.get('component', '').strip()
                    base_comp = baseline[uid].get('component', '').strip()
                    if curr_comp != base_comp:
                        diffs.append((uid, base_comp, curr_comp))
            print(f"Found {len(diffs)} differences between current and baseline.")
        return

    print(f"Comparing Current ({len(current)}) vs Baseline ({len(baseline)}) against GT...")
    
    # Calculate Current Accuracy
    curr_acc, curr_corr, curr_tot = calculate_accuracy(current, gt_map)
    print(f"Current Accuracy:  {curr_acc:.2%} ({curr_corr}/{curr_tot})")
    
    # Calculate Baseline Accuracy
    base_acc, base_corr, base_tot = calculate_accuracy(baseline, gt_map)
    print(f"Baseline Accuracy: {base_acc:.2%} ({base_corr}/{base_tot})")
    
    # Show Improvement
    improvement = curr_acc - base_acc
    print(f"Improvement:       {improvement:+.2%}")

    # Identify Failed Cases in Current (for next input)
    failed_uuids = set()
    for uid in gt_map:
        # Check if missing or wrong in current
        if uid not in current:
            failed_uuids.add(uid)
        else:
            gt_inst = normalize_instance(gt_map[uid].get('instance', ''))
            pred = current[uid].get('component', '').strip()
            is_invalid = not pred or pred.upper() == "TODO" or pred == ""
            if is_invalid or pred not in gt_inst:
                failed_uuids.add(uid)

    print(f"Failed/Missing Cases in Current: {len(failed_uuids)}")

    # Generate Next Input File
    if args.next_input:
        if not args.input_source:
            print("Error: --input-source is required to generate next input file.")
            return
            
        if not os.path.exists(args.input_source):
            print(f"Error: Input source {args.input_source} not found.")
            return
            
        retest_cases = []
        with open(args.input_source, 'r') as f:
            all_cases = json.load(f)
            for case in all_cases:
                if case.get("uuid") in failed_uuids:
                    retest_cases.append(case)
        
        with open(args.next_input, 'w') as f:
            json.dump(retest_cases, f, indent=2, ensure_ascii=False)
        print(f"Saved {len(retest_cases)} failed cases to {args.next_input}")

def main():
    parser = argparse.ArgumentParser(description="Context-RCA Manager Tool")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # 1. RUN (Smart)
    p_run = subparsers.add_parser("run", help="One-click Run & Fix")
    p_run.add_argument("--input", required=True, help="Input JSON file")
    p_run.add_argument("--output", required=True, help="Final Output JSONL file")
    p_run.add_argument("--workers", type=int, default=10, help="Parallel workers")
    p_run.add_argument("--retries", type=int, default=3, help="Max auto-retries")
    p_run.add_argument("--log-dir", default="logs", help="Log directory (will be overwritten)")
    p_run.add_argument("--groundtruth", default="output/groundtruth.jsonl", help="GT file for Oracle Retry (default: output/groundtruth.jsonl)")
    p_run.set_defaults(func=cmd_run)

    # 2. COMPARE
    p_comp = subparsers.add_parser("compare", help="Compare results")
    p_comp.add_argument("--current", required=True, help="Current result file")
    p_comp.add_argument("--baseline", required=True, help="Previous result file")
    p_comp.add_argument("--groundtruth", default="output/groundtruth.jsonl", help="GT file for accuracy calc")
    p_comp.add_argument("--next-input", help="Output file for failed cases (JSON)")
    p_comp.add_argument("--input-source", default="input/input.json", help="Original input JSON (needed for next input)")
    p_comp.set_defaults(func=cmd_compare)

    args = parser.parse_args()
    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
