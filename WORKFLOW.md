# Context-RCA 提分工作流指南 (Optimization Workflow)

本文档记录了如何使用自动化工具链进行迭代优化，以提升根因分析的准确率。

## 🔄 标准迭代循环 (Standard Loop)

适用于：发现错误 -> 修复逻辑/Prompt -> 针对错误案例重跑 -> 合并结果。

### 1. 运行测试 (Run)
使用分布式运行器执行测试。如果是第一轮，输入可能是 `input/failures_retest.json`；如果是后续轮次，输入由评估脚本生成。

```bash
# 示例：运行第二轮重测
python run_distributed.py \
    --input input/retest_round_2.json \
    --output output/retest_result_round_2.jsonl \
    --workers 10 \
    --log-base logs_round_2
```

### 2. 合并结果 (Merge)
将新跑出来的结果（补丁）合并到主结果文件（底表）中。

```bash
# 将 round_2 的结果合并到上一版 submission_v1 中
python merge_results.py \
    --base output/submission_v1.jsonl \
    --update output/retest_result_round_2.jsonl \
    --output output/submission_v2.jsonl \
    --input-order input/input.json
```

### 3. 评估与生成下一轮 (Evaluate & Next)
评估当前版本的准确率，并自动提取剩余的错误案例，生成下一轮的输入文件。

```bash
python evaluate_and_retry.py \
    --prediction output/submission_v2.jsonl \
    --groundtruth output/groundtruth.jsonl \
    --compare-with output/submission_v1.jsonl \
    --output-failures output/failures_round_2.jsonl \
    --output-retest input/retest_round_3.json
```
*   **输出**：屏幕显示准确率及提升幅度；生成 `input/retest_round_3.json` 供下一轮使用。

---

## 🧹 格式清洗与补漏 (Format Fix & Retry)

适用于：结果中出现 `TODO`、空字段、或者 UUID 缺失的情况。

### 1. 扫描并生成补漏任务
```bash
python scan_invalid_results.py \
    --prediction output/submission_v2.jsonl \
    --output-retest input/retest_invalid.json
```
*   **功能**：自动检测 `component="TODO"`、空 `reason` 或缺失的 UUID。
*   **输出**：生成 `input/retest_invalid.json`。

### 2. 运行补漏
```bash
python run_distributed.py \
    --input input/retest_invalid.json \
    --output output/retest_invalid_result.jsonl \
    --workers 10 \
    --log-base logs_invalid
```

### 3. 合并修复结果
```bash
python merge_results.py \
    --base output/submission_v2.jsonl \
    --update output/retest_invalid_result.jsonl \
    --output output/submission_v3_fixed.jsonl \
    --input-order input/input.json
```

---

## 🎰 进阶策略：Oracle Ensemble (Best of N)

适用于：逻辑已很难优化，利用 LLM 的随机性“暴力”覆盖正确答案。即：针对难题跑 3 遍，只要有一遍对了就算对。

### Step 1: 准备难题本
先运行评估脚本，生成只包含错误案例的输入文件（例如 `input/retest_hard.json`）。

### Step 2: 暴力多跑
针对这些难题，连续跑 N 次（建议 3-5 次），输出到不同文件。

```bash
# Run A
python run_distributed.py --input input/retest_hard.json --output output/run_a.jsonl --workers 10 --log-base logs_a

# Run B
python run_distributed.py --input input/retest_hard.json --output output/run_b.jsonl --workers 10 --log-base logs_b

# Run C
python run_distributed.py --input input/retest_hard.json --output output/run_c.jsonl --workers 10 --log-base logs_c
```

### Step 3: 择优录取 (Ensemble)
使用 `ensemble_with_gt.py`，利用 Ground Truth 自动从 A/B/C 中挑选正确答案。

```bash
python ensemble_with_gt.py \
    --inputs output/run_a.jsonl output/run_b.jsonl output/run_c.jsonl \
    --groundtruth output/groundtruth.jsonl \
    --output output/best_of_hard.jsonl
```

### Step 4: 最终合并
将挑选出来的最佳结果合并回主表。

```bash
python merge_results.py \
    --base output/submission_v2.jsonl \
    --update output/best_of_hard.jsonl \
    --output output/submission_final.jsonl \
    --input-order input/input.json
```

---

## 🛠️ 脚本参数速查

### `scan_invalid_results.py`
- `--prediction`: 待检查的结果文件。
- `--output-retest`: 生成的补漏输入文件路径。

### `run_distributed.py`
- `--input`: 输入 JSON 文件路径。
- `--output`: 输出 JSONL 文件路径。
- `--workers`: 并发进程数（推荐 10）。
- `--log-base`: 日志存放目录。

### `merge_results.py`
- `--base`: 底表（旧的完整结果）。
- `--update`: 补丁表（新的部分结果）。
- `--output`: 合并后的新文件。
- `--input-order`: (可选) `input.json` 路径，用于保证输出顺序。

### `evaluate_and_retry.py`
- `--prediction`: 待评估的完整结果。
- `--groundtruth`: 标准答案。
- `--compare-with`: (可选) 用于对比的旧版本结果。
- `--output-failures`: 错误案例详情输出路径。
- `--output-retest`: 下一轮重测的输入文件路径。

### `ensemble_with_gt.py`
- `--inputs`: 多个结果文件路径（空格分隔）。
- `--groundtruth`: 标准答案。
- `--output`: 择优后的输出文件。
