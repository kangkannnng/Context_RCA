import json
import os
import subprocess
import argparse
import sys
import shutil
from math import ceil
import time

def main():
    parser = argparse.ArgumentParser(description="Run context_rca in distributed parallel processes")
    parser.add_argument("--input", type=str, required=True, help="Path to original input JSON")
    parser.add_argument("--output", type=str, required=True, help="Path to final merged output JSONL")
    parser.add_argument("--workers", type=int, default=10, help="Number of parallel processes")
    parser.add_argument("--log-base", type=str, default="logs_dist", help="Base name for log directories")
    parser.add_argument("--keep-temp", action="store_true", help="Keep temporary files after merging")
    
    args = parser.parse_args()
    
    # 1. Read Input
    if not os.path.exists(args.input):
        print(f"Error: Input file {args.input} not found.")
        return

    with open(args.input, 'r') as f:
        data = json.load(f)
    
    total_items = len(data)
    if total_items == 0:
        print("Input file is empty.")
        return

    # Adjust workers if data is small
    if args.workers > total_items:
        args.workers = total_items
        
    chunk_size = ceil(total_items / args.workers)
    
    print(f"Total items: {total_items}")
    print(f"Workers: {args.workers}")
    print(f"Chunk size: ~{chunk_size}")
    print("-" * 50)
    
    processes = []
    temp_files = []
    
    # Ensure output directory exists
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

    # 2. Split and Launch
    for i in range(args.workers):
        start_idx = i * chunk_size
        end_idx = min((i + 1) * chunk_size, total_items)
        
        if start_idx >= total_items:
            break
            
        chunk_data = data[start_idx:end_idx]
        
        # Define temporary paths
        temp_input = f"temp_input_{i}.json"
        temp_output = f"temp_output_{i}.jsonl"
        temp_log_dir = f"{args.log_base}_{i}"
        worker_log = f"worker_{i}.log" # Capture stdout/stderr here
        
        temp_files.append({
            "input": temp_input,
            "output": temp_output,
            "log_dir": temp_log_dir,
            "worker_log": worker_log
        })
        
        # Write temp input file
        with open(temp_input, 'w') as f:
            json.dump(chunk_data, f, indent=2, ensure_ascii=False)
            
        # Construct command
        # python main.py --batch --input temp_input_X.json --output temp_output_X.jsonl --log-dir logs_dist_X
        cmd = [
            sys.executable, "main.py",
            "--batch",
            "--input", temp_input,
            "--output", temp_output,
            "--log-dir", temp_log_dir
        ]
        
        print(f"[Worker {i}] Processing {len(chunk_data)} items (Index {start_idx}-{end_idx})")
        print(f"           Log: {worker_log}")
        print(f"           Dir: {temp_log_dir}")
        
        # Launch process, redirecting output to worker log file to avoid terminal clutter
        with open(worker_log, "w") as log_f:
            p = subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT)
            processes.append(p)
    
    print("-" * 50)
    print(f"All {len(processes)} processes launched. Waiting for completion...")
    
    # 3. Monitor Loop
    try:
        while True:
            running = [p.poll() is None for p in processes]
            if not any(running):
                break
            
            # Simple spinner or status update could go here
            time.sleep(2)
            
    except KeyboardInterrupt:
        print("\nStopping all processes...")
        for p in processes:
            p.terminate()
        sys.exit(1)

    print("All processes finished.")
    
    # Check exit codes
    failed_workers = []
    for i, p in enumerate(processes):
        if p.returncode != 0:
            failed_workers.append(i)
            print(f"Error: Worker {i} failed with exit code {p.returncode}. Check {temp_files[i]['worker_log']}")

    # 4. Merge Results
    print("-" * 50)
    print("Merging results...")
    
    merged_count = 0
    with open(args.output, 'w') as outfile:
        for i, temp in enumerate(temp_files):
            t_out = temp["output"]
            if os.path.exists(t_out):
                with open(t_out, 'r') as infile:
                    for line in infile:
                        outfile.write(line)
                        merged_count += 1
            else:
                if i not in failed_workers:
                    print(f"Warning: Output file {t_out} missing for successful worker {i}")

    print(f"Merged {merged_count} records into {args.output}")

    # 5. Cleanup
    if not args.keep_temp:
        print("Cleaning up temporary files...")
        for temp in temp_files:
            if os.path.exists(temp["input"]):
                os.remove(temp["input"])
            if os.path.exists(temp["output"]):
                os.remove(temp["output"])
            if os.path.exists(temp["worker_log"]):
                os.remove(temp["worker_log"])
            # We don't delete the log directories as they contain valuable debug info
            # shutil.rmtree(temp["log_dir"], ignore_errors=True) 
    else:
        print("Temporary files kept.")

if __name__ == "__main__":
    main()
