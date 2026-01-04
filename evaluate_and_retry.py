import json
import argparse
import os

def normalize_instance(instance):
    """
    Normalize instance names for comparison.
    Handles lists and strings.
    Returns a set of normalized strings.
    """
    if isinstance(instance, str):
        return {instance.strip()}
    elif isinstance(instance, list):
        return {i.strip() for i in instance}
    return set()

def main():
    parser = argparse.ArgumentParser(description="Evaluate results and prepare next retest batch.")
    parser.add_argument("--prediction", required=True, help="Path to the full prediction file (e.g., output/final_submission.jsonl)")
    parser.add_argument("--groundtruth", default="output/groundtruth.jsonl", help="Path to ground truth file")
    parser.add_argument("--input-source", default="input/input.json", help="Path to original input.json")
    parser.add_argument("--output-failures", default="output/failures_next.jsonl", help="Path to save failure details")
    parser.add_argument("--output-retest", default="input/retest_next.json", help="Path to save next retest input")
    parser.add_argument("--compare-with", help="Optional: Path to a previous prediction file to compare improvement")
    
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

    # Load Previous Predictions (if provided)
    prev_predictions = {}
    if args.compare_with and os.path.exists(args.compare_with):
        print(f"Loading previous predictions from {args.compare_with}...")
        with open(args.compare_with, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        item = json.loads(line)
                        if 'uuid' in item:
                            prev_predictions[item['uuid']] = item
                    except:
                        pass

    # Load Predictions
    predictions = {}
    if os.path.exists(args.prediction):
        with open(args.prediction, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        item = json.loads(line)
                        if 'uuid' in item:
                            predictions[item['uuid']] = item
                    except:
                        pass
    else:
        print(f"Error: Prediction file {args.prediction} not found.")
        return

    # Evaluate
    correct_count = 0
    total_count = 0
    failed_uuids = set()
    failures_details = []
    
    # Comparison stats
    improved_count = 0
    regressed_count = 0
    still_wrong_count = 0
    still_correct_count = 0

    print(f"Evaluating {len(predictions)} predictions against {len(gt_map)} ground truth records...")

    for uuid, pred in predictions.items():
        if uuid not in gt_map:
            continue
        
        total_count += 1
        gt = gt_map[uuid]
        
        # Logic for comparison
        gt_instances = normalize_instance(gt.get('instance', ''))
        pred_component = pred.get('component', '').strip()
        
        is_correct = False
        if pred_component in gt_instances:
            is_correct = True
        
        # Check previous status if available
        was_correct = False
        if uuid in prev_predictions:
            prev_pred = prev_predictions[uuid]
            prev_component = prev_pred.get('component', '').strip()
            if prev_component in gt_instances:
                was_correct = True
            
            if is_correct and not was_correct:
                improved_count += 1
            elif not is_correct and was_correct:
                regressed_count += 1
            elif is_correct and was_correct:
                still_correct_count += 1
            else:
                still_wrong_count += 1

        if is_correct:
            correct_count += 1
        else:
            failed_uuids.add(uuid)
            failures_details.append({
                "uuid": uuid,
                "groundtruth_instance": gt.get('instance'),
                "predicted_component": pred_component,
                "reason": pred.get('reason')
            })

    accuracy = correct_count / total_count if total_count > 0 else 0
    print(f"Accuracy: {accuracy:.2%} ({correct_count}/{total_count})")
    
    if args.compare_with:
        print(f"--- Comparison with {args.compare_with} ---")
        print(f"Improved (Wrong -> Correct): {improved_count}")
        print(f"Regressed (Correct -> Wrong): {regressed_count}")
        print(f"Net Improvement: {improved_count - regressed_count}")
    
    print(f"Found {len(failed_uuids)} failures.")

    # Write failures details
    with open(args.output_failures, 'w') as f:
        for item in failures_details:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    print(f"Failure details saved to {args.output_failures}")

    # Generate Retest Input
    if os.path.exists(args.input_source):
        retest_cases = []
        with open(args.input_source, 'r') as f:
            all_cases = json.load(f)
            for case in all_cases:
                if case.get("uuid") in failed_uuids:
                    retest_cases.append(case)
        
        with open(args.output_retest, 'w') as f:
            json.dump(retest_cases, f, indent=2, ensure_ascii=False)
        print(f"Prepared {len(retest_cases)} cases for next retest in {args.output_retest}")
    else:
        print(f"Warning: Input source {args.input_source} not found. Cannot generate retest input.")

if __name__ == "__main__":
    main()
