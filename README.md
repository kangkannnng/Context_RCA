# Context-RCA: Multi-Agent Root Cause Analysis System

Context-RCA 是基于 Google ADK 开发的微服务故障根因分析系统。该系统通过编排多个专用智能体（Agents），模拟 SRE 团队的协作流程，自动化完成从数据采集、异常检测到根因定位的完整诊断过程。

## 核心设计理念

系统设计遵循以下技术原则，以确保分析的准确性与鲁棒性：

1.  **SOP 驱动编排 (SOP-Driven Orchestration)**
    Orchestrator 严格执行预定义的标准作业程序（Standard Operating Procedure）。通过强制性的阶段划分（初始化 -> 并行采集 -> 共识研判 -> 报告生成），规避 LLM 的幻觉问题，确保诊断流程的确定性。

2.  **并行数据流 (Parallel Data Processing)**
    解耦日志（Log）、指标（Metric）和链路（Trace）的分析任务。各领域 Agent 并行执行数据提取与初步研判，显著降低端到端分析时延。

3.  **共识决策机制 (Consensus Mechanism)**
    引入 Consensus Agent 作为决策核心，执行“提出假设-交叉验证-挑战辩驳”的闭环流程。仅依靠单一模态数据（如仅有 Metric 异常但无 Log 报错）无法形成最终结论，必须通过多方证据对齐（Alignment）才能达成共识。

4.  **结构化交付 (Structured Output)**
    分析结果统一标准化为 JSON 格式，包含故障组件、根因描述及完整的推理轨迹（Reasoning Trace），便于下游系统集成或自动化评测。

## 系统架构

```mermaid
graph TD
    User[用户输入] --> Orch[Orchestrator (总控)]
    
    subgraph "Phase 1: Data Collection"
        Orch --> DC[Data Collection Agent]
        DC --> Log[Log Agent]
        DC --> Metric[Metric Agent]
        DC --> Trace[Trace Agent]
    end
    
    subgraph "Phase 2: Consensus Discussion"
        Orch --> ConsensusLoop[Consensus Discussion Agent]
        ConsensusLoop --> Chair[Consensus Agent (决策)]
        Chair <--> DC
    end
    
    subgraph "Phase 3: Reporting"
        Orch --> Report[Report Agent]
    end
    
    Report --> Result[JSON Report]
```

## 快速开始

### 1. 环境准备

本项目使用 `uv` 进行依赖管理。

```bash
# 激活虚拟环境
source .venv/bin/activate

# 安装依赖
uv sync
```

### 2. 配置环境变量

在 `context_rca/` 目录下创建 `.env` 文件，配置必要的 API Key 和其他设置：

```bash
# context_rca/.env
OPENAI_API_KEY="sk-..."
# 其他相关配置...
```

### 3. 数据准备

请确保数据文件放置在以下目录结构中：

- **输入数据**: `input/input.json` (包含待分析的案例列表)
- **原始数据**: `data/raw/YYYY-MM-DD/`
- **处理后数据**: `data/processed/YYYY-MM-DD/` (包含 log-parquet, metric-parquet, trace-parquet)

## 使用指南

`main.py` 是系统的统一入口，支持多种运行模式。

### 命令行参数

| 参数 | 说明 | 示例 |
| :--- | :--- | :--- |
| `--batch` | **批量模式**：运行 `input.json` 中的所有案例 | `python main.py --batch` |
| `--workers` | **并发数**：配合批量模式使用，指定并行进程数 | `python main.py --batch --workers 10` |
| `--single` | **单例模式**：运行指定序号（从1开始）或 UUID 的案例 | `python main.py --single 1` 或 `python main.py --single "uuid-123"` |
| `--random` | **随机模式**：随机抽取 N 个案例运行 | `python main.py --random 5` |

### 运行示例

**1. 运行单个案例（调试用）**
运行输入文件中的第 1 个案例：
```bash
python main.py --single 1
```
或者指定 UUID：
```bash
python main.py --single "a1b2c3d4"
```

**2. 批量运行所有案例（生产用）**
使用 10 个 Worker 并行处理所有案例：
```bash
python main.py --batch --workers 10
```
> **注意**：批量运行时，结果会实时写入 `output/result.jsonl`，每个 Worker 的详细日志会保存在 `logs/` 目录下。

**3. 随机抽样测试**
随机抽取 5 个案例进行快速验证：
```bash
python main.py --random 5
```

## 项目结构

```plaintext
.
├── main.py                 # 程序入口
├── context_rca/            # 核心代码
│   ├── agent.py            # Orchestrator 定义
│   ├── sub_agents/         # 子智能体实现 (Log, Metric, Trace, Consensus, Report)
│   ├── callbacks/          # 回调函数
│   ├── schemas/            # 数据结构定义
│   └── tools.py            # 通用工具
├── data/                   # 数据目录
│   ├── processed/          # 处理后的 Parquet 数据
│   └── raw/                # 原始数据
├── input/                  # 输入案例文件
├── output/                 # 分析结果输出
├── logs/                   # 运行日志
└── models/                 # 辅助模型 (Drain3 等)
```

## 输出说明

- **运行结果**: `output/result.jsonl` (JSON Lines 格式)
- **详细日志**: `logs/YYYYMMDD_HHMMSS_{UUID}.log` (每个案例独立日志)
