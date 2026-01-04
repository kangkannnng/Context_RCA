import json

def load_jsonl(filepath):
    data = []
    with open(filepath, 'r') as f:
        for line in f:
            data.append(json.loads(line))
    return data

def main():
    results_data = load_jsonl('/home/kk/code/context_rca/output/result copy.jsonl')
    
    run1_results = []
    
    for res in results_data:
        if res.get('run_id') == 1:
            # Create a clean copy without run_id
            clean_res = res.copy()
            if 'run_id' in clean_res:
                del clean_res['run_id']
            run1_results.append(clean_res)
            
    # Write run1 results
    with open('/home/kk/code/context_rca/output/run1_result.jsonl', 'w') as f:
        for res in run1_results:
            f.write(json.dumps(res) + '\n')
            
    print(f"Processed {len(run1_results)} cases (Run ID 1). Saved to run1_result.jsonl")

if __name__ == "__main__":
    main()
