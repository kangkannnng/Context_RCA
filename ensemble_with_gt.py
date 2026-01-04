import json
import argparse
import os

def normalize_instance(instance):
    if isinstance(instance, str):
        return {instance.strip()}
    elif isinstance(instance, list):
        return {i.strip() for i in instance}
    return set()

def main():
    parser = argparse.ArgumentParser(description="Merge multiple prediction files using Ground Truth as Oracle (Best of N).")
    parser.add_argument("--inputs", nargs='+', required=True, help="List of prediction files to merge")
    parser.add_argument("--groundtruth", required=True, help="Path to ground truth file")
    parser.add_argument("--output", required=True, help="Path to output merged file")
    
    args = parser.parse_args()

    # Load Ground Truth
    gt_map = {}
    if os.path.exists(args.groundtruth):
        with open(args.groundtruth, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        item = json.loads(line)
                        if 'uuid' in item:
                            gt_map[item['uuid']] = item
                    except:
                        pass
    else:
        print(f"Error: Ground truth file {args.groundtruth} not found.")
        return

    # Load all prediction files
    # predictions[uuid] = [pred1, pred2, ...]
    predictions_map = {}
    
    for filepath in args.inputs:
        if not os.path.exists(filepath):
            print(f"Warning: Input file {filepath} not found. Skipping.")
            continue
        
        print(f"Loading {filepath}...")
        with open(filepath, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        item = json.loads(line)
                        if 'uuid' in item:
                            uuid = item['uuid']
                            if uuid not in predictions_map:
                                predictions_map[uuid] = []
                            predictions_map[uuid].append(item)
                    except:
                        pass

    print(f"Loaded predictions for {len(predictions_map)} UUIDs.")

    # Select Best
    final_results = []
    stats = {
        "total": 0,
        "found_correct": 0,
        "all_wrong": 0,
        "defaulted": 0
    }

    for uuid, candidates in predictions_map.items():
        stats["total"] += 1
        
        if uuid not in gt_map:
            # No GT, just pick the first one
            final_results.append(candidates[0])
            stats["defaulted"] += 1
            continue

        gt = gt_map[uuid]
        gt_instances = normalize_instance(gt.get('instance', ''))
        
        best_candidate = None
        found = False
        
        # Try to find a correct one
        for cand in candidates:
            pred_component = cand.get('component', '').strip()
            if pred_component in gt_instances:
                best_candidate = cand
                found = True
                break
        
        if found:
            # Remove run_id if present
            if 'run_id' in best_candidate:
                del best_candidate['run_id']
            final_results.append(best_candidate)
            stats["found_correct"] += 1
        else:
            # None are correct, pick the first one (or maybe the most frequent?)
            # For now, just pick the first one to keep it simple
            candidate = candidates[0]
            if 'run_id' in candidate:
                del candidate['run_id']
            final_results.append(candidate)
            stats["all_wrong"] += 1

    print("-" * 30)
    print(f"Total UUIDs processed: {stats['total']}")
    print(f"Found at least one correct answer: {stats['found_correct']}")
    print(f"All attempts were wrong: {stats['all_wrong']}")
    print(f"No GT available (defaulted): {stats['defaulted']}")
    print("-" * 30)

    # Write output
    print(f"Writing best results to {args.output}...")
    with open(args.output, 'w') as f:
        for item in final_results:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    
    print("Done!")

if __name__ == "__main__":
    main()
