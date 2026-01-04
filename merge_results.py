import json
import argparse
import os

def load_jsonl(filepath):
    data = {}
    with open(filepath, 'r') as f:
        for line in f:
            if line.strip():
                try:
                    item = json.loads(line)
                    if 'uuid' in item:
                        data[item['uuid']] = item
                except json.JSONDecodeError:
                    print(f"Warning: Skipping invalid JSON line in {filepath}")
    return data

def main():
    parser = argparse.ArgumentParser(description="Merge retest results into the original result set.")
    parser.add_argument("--base", required=True, help="Path to the original full result file (e.g., output/acc@1.jsonl)")
    parser.add_argument("--update", required=True, help="Path to the retest result file (e.g., output/retest_result_final.jsonl)")
    parser.add_argument("--output", required=True, help="Path to the output merged file")
    parser.add_argument("--input-order", help="Optional: Path to input.json to enforce order")
    
    args = parser.parse_args()

    if not os.path.exists(args.base):
        print(f"Error: Base file {args.base} not found.")
        return
    
    if not os.path.exists(args.update):
        print(f"Error: Update file {args.update} not found.")
        return

    print(f"Loading base results from {args.base}...")
    base_data = load_jsonl(args.base)
    print(f"Loaded {len(base_data)} records from base.")

    print(f"Loading update results from {args.update}...")
    update_data = load_jsonl(args.update)
    print(f"Loaded {len(update_data)} records from update.")

    # Merge
    merged_count = 0
    for uuid, item in update_data.items():
        if uuid in base_data:
            base_data[uuid] = item
            merged_count += 1
        else:
            # If it wasn't in base, we add it (though this shouldn't happen if base is full)
            base_data[uuid] = item
            print(f"Warning: UUID {uuid} from update was not in base.")

    print(f"Merged {merged_count} records.")

    # Determine output order
    output_items = list(base_data.values())
    if args.input_order and os.path.exists(args.input_order):
        print(f"Reordering based on {args.input_order}...")
        try:
            with open(args.input_order, 'r') as f:
                input_list = json.load(f)
                ordered_items = []
                for case in input_list:
                    uuid = case.get('uuid')
                    if uuid in base_data:
                        ordered_items.append(base_data[uuid])
                    else:
                        print(f"Warning: UUID {uuid} from input.json missing in results.")
                output_items = ordered_items
        except Exception as e:
            print(f"Error reading input order file: {e}")

    # Write output
    print(f"Writing merged results to {args.output}...")
    with open(args.output, 'w') as f:
        for item in output_items:
            # Clean up run_id if present
            if 'run_id' in item:
                del item['run_id']
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    
    print("Done!")

if __name__ == "__main__":
    # python merge_results.py \
    # --base output/acc@3.jsonl \
    # --update output/retest_result_final.jsonl \
    # --output output/final_submission.jsonl \
    # --input-order input/input.json
    main()
