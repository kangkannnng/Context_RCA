import json

result_file = 'output/minimal_result.jsonl'
check_num = 18

# 读取新结果
with open(result_file, 'r') as f:
    new_results = [json.loads(line) for line in f]

# 读取标准答案
with open('output/minimal_groundtruth.json', 'r') as f:
    truths = json.load(f)
    # truths = [json.loads(line) for i, line in enumerate(f) if i < check_num]

correct_component = 0
correct_reason_metrics = 0

for i, (result, truth) in enumerate(zip(new_results, truths)):
    uuid = result['uuid']
    your_comp = result['component']
    your_reason = result['reason']
    
    truth_instance = truth['instance']
    truth_source = truth.get('source', '')
    truth_fault = truth['fault_type']
    truth_key_metrics = truth.get('key_metrics', [])
    
    # 判断 component 是否正确
    if isinstance(truth_instance, list):
        # 网络故障：检查是否是 source
        comp_correct = (your_comp == truth_source)
    else:
        comp_correct = (your_comp == truth_instance)
    
    # 判断 reason 是否包含关键指标
    reason_correct = any(metric in your_reason for metric in truth_key_metrics)
    
    if comp_correct:
        correct_component += 1
    if reason_correct:
        correct_reason_metrics += 1
    
    status = "✅" if (comp_correct and reason_correct) else "❌"
    
    print(f"\n{status} 案例 {i+1}: UUID {uuid}")
    print(f"  故障类型: {truth_fault}")
    print(f"  你的 component: {your_comp}")
    if isinstance(truth_instance, list):
        print(f"  正确 instance: {truth_instance}, source: {truth_source}")
    else:
        print(f"  正确 instance: {truth_instance}")
    print(f"  Component {'✅' if comp_correct else '❌'}")
    print(f"  你的 reason: {your_reason[:80]}...")
    print(f"  关键指标: {truth_key_metrics[:3]}")
    print(f"  Reason包含指标 {'✅' if reason_correct else '❌'}")

print("\n" + "=" * 80)
print(f"总体统计:")
print(f"  Component 正确率: {correct_component}/18 ({correct_component*100/18:.1f}%)")
print(f"  Reason 包含关键指标: {correct_reason_metrics}/18 ({correct_reason_metrics*100/18:.1f}%)")
print(f"  预估得分: {(correct_component + correct_reason_metrics) / 36 * 100:.1f}%")
print("=" * 80)