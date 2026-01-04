import json
import argparse
import os

def main():
    parser = argparse.ArgumentParser(description="Scan results for invalid formats (TODO, empty fields, missing UUIDs) and prepare retest.")
    parser.add_argument("--prediction", required=True, help="Path to the prediction file (e.g., output/submission_v2.jsonl)")
    parser.add_argument("--input-source", default="input/input.json", help="Path to original input.json")
    parser.add_argument("--output-retest", default="input/retest_invalid.json", help="Path to save retest input")
    
    args = parser.parse_args()

    # Load Input Source to verify UUIDs
    valid_uuids = set()
    input_cases_map = {}
    if os.path.exists(args.input_source):
        with open(args.input_source, 'r') as f:
            input_data = json.load(f)
            for case in input_data:
                if 'uuid' in case:
                    valid_uuids.add(case['uuid'])
                    input_cases_map[case['uuid']] = case
    else:
        print(f"Error: Input source {args.input_source} not found.")
        return

    # Scan Predictions
    invalid_uuids = set()
    processed_uuids = set()
    
    print(f"Scanning {args.prediction}...")
    
    if not os.path.exists(args.prediction):
        print(f"Error: Prediction file {args.prediction} not found.")
        return

    with open(args.prediction, 'r') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            
            try:
                item = json.loads(line)
                uuid = item.get('uuid')
                component = item.get('component')
                reason = item.get('reason')
                
                # Check 1: UUID validity
                if not uuid:
                    print(f"Line {line_num}: Missing UUID")
                    continue
                
                if uuid not in valid_uuids:
                    # UUID exists but not in our input list (maybe from a different dataset?)
                    # We skip adding it to processed_uuids so it doesn't count as "done" for our input set
                    continue
                
                processed_uuids.add(uuid)

                # Check 2: Invalid Content
                is_invalid = False
                
                # Check for "TODO" or empty component
                if not component or str(component).strip().upper() == "TODO" or str(component).strip() == "":
                    print(f"Line {line_num}: Invalid component '{component}' for UUID {uuid}")
                    is_invalid = True
                
                # Check for empty reason
                if not reason or str(reason).strip() == "":
                    print(f"Line {line_num}: Empty reason for UUID {uuid}")
                    is_invalid = True
                
                if is_invalid:
                    invalid_uuids.add(uuid)

            except json.JSONDecodeError:
                print(f"Line {line_num}: Invalid JSON")
    
    # Check 3: Missing Cases (UUIDs in input but not in output)
    missing_uuids = valid_uuids - processed_uuids
    if missing_uuids:
        print(f"Found {len(missing_uuids)} missing cases (present in input but not in output).")
        invalid_uuids.update(missing_uuids)

    print(f"Total invalid/missing cases found: {len(invalid_uuids)}")

    if invalid_uuids:
        retest_cases = []
        for uuid in invalid_uuids:
            if uuid in input_cases_map:
                retest_cases.append(input_cases_map[uuid])
        
        with open(args.output_retest, 'w') as f:
            json.dump(retest_cases, f, indent=2, ensure_ascii=False)
        
        print(f"Saved {len(retest_cases)} cases to {args.output_retest}")
        print("-" * 40)
        print("Suggested Command:")
        print(f"python run_distributed.py --input {args.output_retest} --output output/retest_invalid_result.jsonl --workers 10 --log-base logs_invalid")
    else:
        print("No invalid cases found! All formats look good.")

if __name__ == "__main__":
    main()
