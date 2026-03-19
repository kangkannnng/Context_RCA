#!/usr/bin/env python3
"""
根因分析结果统计工具
功能：
1. 统计共识迭代轮次分布
2. 分析故障类型准确率
"""

import json
import os
import re
from collections import defaultdict, Counter
from typing import Dict, List, Tuple
import argparse


def extract_consensus_iteration_from_log(log_file_path: str) -> int:
    """
    从日志文件中提取共识迭代轮次

    Args:
        log_file_path: 日志文件路径

    Returns:
        共识迭代轮次，如果未找到则返回-1
    """
    try:
        with open(log_file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 查找 consensus_iteration 的值
        match = re.search(r'consensus_iteration[:\s]+(\d+)', content)
        if match:
            return int(match.group(1))

        return -1
    except Exception as e:
        print(f"Error reading {log_file_path}: {e}")
        return -1


def analyze_consensus_iterations(logs_dir: str) -> Dict:
    """
    分析所有日志文件的共识迭代轮次

    Args:
        logs_dir: 日志目录路径

    Returns:
        统计结果字典
    """
    print("=" * 60)
    print("任务1: 共识迭代轮次分析")
    print("=" * 60)

    iterations = []
    failed_files = []

    # 遍历所有日志文件
    for subdir in os.listdir(logs_dir):
        log_file = os.path.join(logs_dir, subdir, 'run.log')
        if os.path.exists(log_file):
            iteration = extract_consensus_iteration_from_log(log_file)
            if iteration >= 0:
                iterations.append(iteration)
            else:
                failed_files.append(subdir)

    # 统计结果
    counter = Counter(iterations)
    total = len(iterations)

    print(f"\n总共分析了 {total} 个日志文件")
    print(f"无法提取迭代轮次的文件数: {len(failed_files)}")
    print("\n共识迭代轮次分布:")
    print("-" * 60)

    for iteration in sorted(counter.keys()):
        count = counter[iteration]
        percentage = (count / total * 100) if total > 0 else 0
        print(f"  {iteration} 轮: {count:4d} 次 ({percentage:5.2f}%)")

    # 计算统计指标
    if iterations:
        avg_iteration = sum(iterations) / len(iterations)
        max_iteration = max(iterations)
        min_iteration = min(iterations)

        print("\n统计指标:")
        print("-" * 60)
        print(f"  平均迭代轮次: {avg_iteration:.2f}")
        print(f"  最大迭代轮次: {max_iteration}")
        print(f"  最小迭代轮次: {min_iteration}")
        print(f"  1轮达成共识的比例: {counter.get(1, 0) / total * 100:.2f}%")

    return {
        'iterations': iterations,
        'counter': counter,
        'failed_files': failed_files,
        'total': total
    }


def load_jsonl(file_path: str) -> List[Dict]:
    """
    加载JSONL文件

    Args:
        file_path: JSONL文件路径

    Returns:
        字典列表
    """
    data = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                data.append(json.loads(line))
    return data


def check_component_match(predicted_component: str, gt_instances) -> bool:
    """
    检查预测的组件是否在ground truth的instance中

    Args:
        predicted_component: 预测的组件名称
        gt_instances: ground truth的instance（可能是字符串或列表）

    Returns:
        是否匹配
    """
    # 处理gt_instances为字符串的情况
    if isinstance(gt_instances, str):
        gt_instances = [gt_instances]

    # 检查预测的组件是否在任何一个gt_instance中
    for gt_instance in gt_instances:
        if gt_instance in predicted_component or predicted_component in gt_instance:
            return True

    return False


def analyze_fault_type_accuracy(result_file: str, groundtruth_file: str) -> Dict:
    """
    分析故障类型准确率

    Args:
        result_file: 结果文件路径（JSONL格式）
        groundtruth_file: ground truth文件路径（JSONL格式）

    Returns:
        统计结果字典
    """
    print("\n" + "=" * 60)
    print("任务2: 故障类型准确率分析")
    print("=" * 60)

    # 加载数据
    print(f"\n加载结果文件: {result_file}")
    results = load_jsonl(result_file)
    print(f"加载ground truth文件: {groundtruth_file}")
    groundtruths = load_jsonl(groundtruth_file)

    # 创建UUID到ground truth的映射
    gt_map = {gt['uuid']: gt for gt in groundtruths}

    # 统计变量
    total = 0
    correct = 0
    missing_gt = []
    fault_category_stats = defaultdict(lambda: {'total': 0, 'correct': 0})
    fault_type_stats = defaultdict(lambda: {'total': 0, 'correct': 0})
    error_cases = []

    print(f"\n开始分析 {len(results)} 条结果...")
    print("-" * 60)

    # 遍历每个结果
    for result in results:
        uuid = result.get('uuid')
        predicted_component = result.get('component', '')

        # 查找对应的ground truth
        if uuid not in gt_map:
            missing_gt.append(uuid)
            continue

        gt = gt_map[uuid]
        gt_instance = gt.get('instance', '')
        fault_category = gt.get('fault_category', 'unknown')
        fault_type = gt.get('fault_type', 'unknown')

        # 检查是否匹配
        is_correct = check_component_match(predicted_component, gt_instance)

        total += 1
        if is_correct:
            correct += 1
        else:
            error_cases.append({
                'uuid': uuid,
                'predicted': predicted_component,
                'ground_truth': gt_instance,
                'fault_category': fault_category,
                'fault_type': fault_type
            })

        # 按故障类别统计
        fault_category_stats[fault_category]['total'] += 1
        if is_correct:
            fault_category_stats[fault_category]['correct'] += 1

        # 按故障类型统计
        fault_type_stats[fault_type]['total'] += 1
        if is_correct:
            fault_type_stats[fault_type]['correct'] += 1

    # 输出总体准确率
    overall_accuracy = (correct / total * 100) if total > 0 else 0
    print(f"\n总体准确率:")
    print("-" * 60)
    print(f"  总样本数: {total}")
    print(f"  正确数: {correct}")
    print(f"  错误数: {total - correct}")
    print(f"  准确率: {overall_accuracy:.2f}%")

    if missing_gt:
        print(f"  缺失ground truth的UUID数: {len(missing_gt)}")

    # 输出按故障类别的准确率
    print(f"\n按故障类别的准确率:")
    print("-" * 60)
    for category in sorted(fault_category_stats.keys()):
        stats = fault_category_stats[category]
        accuracy = (stats['correct'] / stats['total'] * 100) if stats['total'] > 0 else 0
        print(f"  {category:25s}: {stats['correct']:3d}/{stats['total']:3d} ({accuracy:5.2f}%)")

    # 输出按故障类型的准确率
    print(f"\n按故障类型的准确率:")
    print("-" * 60)
    for fault_type in sorted(fault_type_stats.keys()):
        stats = fault_type_stats[fault_type]
        accuracy = (stats['correct'] / stats['total'] * 100) if stats['total'] > 0 else 0
        print(f"  {fault_type:30s}: {stats['correct']:3d}/{stats['total']:3d} ({accuracy:5.2f}%)")

    # 输出错误案例（可选，如果错误数量不多）
    if error_cases and len(error_cases) <= 20:
        print(f"\n错误案例详情 (共 {len(error_cases)} 个):")
        print("-" * 60)
        for i, case in enumerate(error_cases[:20], 1):
            print(f"\n  案例 {i}:")
            print(f"    UUID: {case['uuid']}")
            print(f"    预测组件: {case['predicted']}")
            print(f"    真实组件: {case['ground_truth']}")
            print(f"    故障类别: {case['fault_category']}")
            print(f"    故障类型: {case['fault_type']}")
    elif error_cases:
        print(f"\n错误案例数量较多 ({len(error_cases)} 个)，仅显示前20个:")
        print("-" * 60)
        for i, case in enumerate(error_cases[:20], 1):
            print(f"  {i}. UUID: {case['uuid']}, 预测: {case['predicted']}, 真实: {case['ground_truth']}")

    return {
        'total': total,
        'correct': correct,
        'overall_accuracy': overall_accuracy,
        'fault_category_stats': dict(fault_category_stats),
        'fault_type_stats': dict(fault_type_stats),
        'error_cases': error_cases,
        'missing_gt': missing_gt
    }


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='根因分析结果统计工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 运行所有分析
  python analyze_results.py

  # 仅运行共识迭代轮次分析
  python analyze_results.py --task consensus

  # 仅运行故障类型准确率分析
  python analyze_results.py --task accuracy

  # 指定自定义结果文件路径
  python analyze_results.py --task accuracy --result-file output/my_result.jsonl
        """
    )

    parser.add_argument(
        '--task',
        choices=['all', 'consensus', 'accuracy'],
        default='all',
        help='选择要执行的任务 (默认: all)'
    )
    parser.add_argument(
        '--logs-dir',
        default='logs',
        help='日志文件目录路径 (默认: logs)'
    )
    parser.add_argument(
        '--result-file',
        default='output/result.jsonl',
        help='结果文件路径 (默认: output/result.jsonl)'
    )
    parser.add_argument(
        '--groundtruth-file',
        default='output/groundtruth.jsonl',
        help='Ground truth文件路径 (默认: output/groundtruth.jsonl)'
    )

    args = parser.parse_args()

    # 执行任务
    if args.task in ['all', 'consensus']:
        # 任务1: 共识迭代轮次分析
        if os.path.exists(args.logs_dir):
            analyze_consensus_iterations(args.logs_dir)
        else:
            print(f"错误: 日志目录不存在: {args.logs_dir}")

    if args.task in ['all', 'accuracy']:
        # 任务2: 故障类型准确率分析
        if os.path.exists(args.result_file) and os.path.exists(args.groundtruth_file):
            analyze_fault_type_accuracy(args.result_file, args.groundtruth_file)
        else:
            if not os.path.exists(args.result_file):
                print(f"错误: 结果文件不存在: {args.result_file}")
            if not os.path.exists(args.groundtruth_file):
                print(f"错误: Ground truth文件不存在: {args.groundtruth_file}")

    print("\n" + "=" * 60)
    print("分析完成!")
    print("=" * 60)


if __name__ == '__main__':
    main()
