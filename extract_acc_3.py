import json
import difflib

def load_jsonl(filepath):
    data = []
    with open(filepath, 'r') as f:
        for line in f:
            data.append(json.loads(line))
    return data

def calculate_score(result, groundtruth):
    # 1. Component Score (40%)
    gt_instance = groundtruth.get('instance')
    pred_component = result.get('component')
    
    component_match = False
    if isinstance(gt_instance, list):
        if pred_component in gt_instance:
            component_match = True
    else:
        if pred_component == gt_instance:
            component_match = True
            
    if not component_match:
        return 0.0
        
    component_score = 40.0
    
    # 2. Reason Score (40%)
    gt_metrics = groundtruth.get('key_metrics', [])
    gt_descriptions = groundtruth.get('fault_description', [])
    pred_reason = result.get('reason', "")
    
    reason_score = 0.0
    metric_found = False
    
    # Check key_metrics
    for metric in gt_metrics:
        if metric in pred_reason:
            metric_found = True
            break
            
    if metric_found:
        reason_score = 40.0
    else:
        # Check fault_description similarity
        max_similarity = 0.0
        for desc in gt_descriptions:
            # Simple ratio might be too strict for long strings, but let's try it
            # Or maybe token overlap?
            # Let's use SequenceMatcher for now as a proxy for "similarity"
            ratio = difflib.SequenceMatcher(None, pred_reason, desc).ratio()
            if ratio > max_similarity:
                max_similarity = ratio
        reason_score = max_similarity * 40.0
        
    # 3. Reasoning Trace Score (20%)
    gt_observations = groundtruth.get('key_observations', [])
    all_gt_keywords = set()
    for obs in gt_observations:
        keywords = obs.get('keyword', [])
        for k in keywords:
            all_gt_keywords.add(k)
            
    pred_trace = result.get('reasoning_trace', [])
    pred_observations_text = " ".join([step.get('observation', "") for step in pred_trace])
    
    found_keywords = 0
    for kw in all_gt_keywords:
        if kw in pred_observations_text:
            found_keywords += 1
            
    if len(all_gt_keywords) > 0:
        trace_score = (found_keywords / len(all_gt_keywords)) * 20.0
    else:
        trace_score = 0.0 # Or 20 if no keywords to find? Assuming 0 for now if empty.
        
    total_score = component_score + reason_score + trace_score
    return total_score

def main():
    groundtruth_data = load_jsonl('/home/kk/code/context_rca/output/groundtruth.jsonl')
    groundtruth_map = {item['uuid']: item for item in groundtruth_data}
    
    results_data = load_jsonl('/home/kk/code/context_rca/output/result.jsonl')
    
    # Group by UUID
    grouped_results = {}
    for res in results_data:
        uuid = res['uuid']
        if uuid not in grouped_results:
            grouped_results[uuid] = []
        grouped_results[uuid].append(res)
        
    best_results = []
    
    for uuid, runs in grouped_results.items():
        if uuid not in groundtruth_map:
            print(f"Warning: UUID {uuid} not found in groundtruth")
            continue
            
        gt = groundtruth_map[uuid]
        best_run = None
        max_score = -1.0
        
        for run in runs:
            score = calculate_score(run, gt)
            # print(f"UUID: {uuid}, Run: {run.get('run_id')}, Score: {score}")
            if score > max_score:
                max_score = score
                best_run = run
        
        if best_run:
            # Remove run_id before saving if needed, or keep it. 
            # The user didn't specify format, but usually we want the clean object.
            # I'll keep it as is for now, or maybe remove 'run_id' to match the requested format?
            # The requested format AnalysisReport doesn't have run_id.
            # But I'll just keep the dict as is, maybe pop run_id if I want to be clean.
            best_run_clean = best_run.copy()
            if 'run_id' in best_run_clean:
                del best_run_clean['run_id']
            best_results.append(best_run_clean)
            
    # Write best results
    with open('/home/kk/code/context_rca/output/best_result.jsonl', 'w') as f:
        for res in best_results:
            f.write(json.dumps(res) + '\n')
            
    print(f"Processed {len(best_results)} cases. Saved to best_result.jsonl")

if __name__ == "__main__":
    main()
