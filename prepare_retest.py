import json
import os

def main():
    failures_path = "output/failures_component.jsonl"
    input_path = "input/input.json"
    output_path = "input/failures_retest.json"

    if not os.path.exists(failures_path):
        print(f"Error: {failures_path} not found.")
        return

    if not os.path.exists(input_path):
        print(f"Error: {input_path} not found.")
        return

    # Get failed UUIDs
    failed_uuids = set()
    with open(failures_path, "r") as f:
        for line in f:
            if line.strip():
                try:
                    data = json.loads(line)
                    if "uuid" in data:
                        failed_uuids.add(data["uuid"])
                except json.JSONDecodeError:
                    pass
    
    print(f"Found {len(failed_uuids)} failed cases.")

    # Filter input
    retest_cases = []
    with open(input_path, "r") as f:
        all_cases = json.load(f)
        for case in all_cases:
            if case.get("uuid") in failed_uuids:
                retest_cases.append(case)
    
    print(f"Extracted {len(retest_cases)} cases for retest.")

    # Write to file
    with open(output_path, "w") as f:
        json.dump(retest_cases, f, indent=2, ensure_ascii=False)
    
    print(f"Saved to {output_path}")

if __name__ == "__main__":
    main()
