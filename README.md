# Context-RCA: Multi-Agent Root Cause Analysis System

Context-RCA 是一个基于大语言模型（LLM）和多智能体协作（Multi-Agent Collaboration）架构的微服务故障根因分析系统。它模拟了一支由资深 SRE 专家组成的”虚拟作战室”，通过严谨的 SOP（标准作业程序）和多轮辩论机制，自动化完成从现象发现、证据搜集到根因定性的全过程。

## 系统架构与方法论

### 1. 架构分层

*   **Orchestration Layer (编排层)**
    *   **Orchestrator Agent**: 作为中央状态机，强制执行标准作业程序 (SOP)。负责解析用户查询并管理分析会话的全生命周期，确保数据流在各阶段间的正确流转。

*   **Expert Layer (专家层)**
    *   **Metric Agent**: 专注于时序数据分析，识别延迟突增、错误率异常，并区分 Pod 级与 Node 级资源争用。
    *   **Log Agent**: 分析结构化与非结构化日志，定位异常堆栈与关键错误模式（如 DNS 失败）。
    *   **Trace Agent**: 基于分布式追踪数据构建服务依赖图，定位瓶颈服务与故障传播路径。

*   **Reasoning Layer (推理层)**
    *   **Consensus Agent**: 系统的核心引擎。作为”法官”评估专家层的证词，通过挑战-应答机制和多轮迭代（最多 6 轮），解决跨模态的证据冲突。

*   **Reporting Layer (报告层)**
    *   **Report Agent**: 将最终达成的共识综合为结构化的诊断报告，包含根因、证据链及影响范围。

### 2. 诊断工作流

分析过程遵循严格的三阶段 SOP：

*   **Phase I: 多视角证据挖掘**
    Orchestrator 调度 Data Collection Agent 并行启动三位领域专家 (Metric, Log, Trace)。各专家独立从各自的数据源中提取局部证据和异常发现。

*   **Phase II: 协作推理与共识**
    Consensus Discussion Agent 启动辩论循环：
    1.  假设生成：基于聚合的发现提出初始假设
    2.  交叉验证：检查证据对齐情况
    3.  冲突解决：当专家意见不一致时，触发模式匹配逻辑进行裁决
    4.  循环直至达成共识或达到最大轮次

*   **Phase III: 最终裁决报告**
    Orchestrator 将最终共识上下文传递给 Report Agent，生成人类可读的最终报告。

```mermaid
graph TD
    User((User Input)) --> Orch[Orchestrator Agent]

    subgraph “Phase I: Evidence Mining”
        Orch -->|Dispatch| DC[Data Collection Agent]
        DC -->|Parallel| M[Metric Agent]
        DC -->|Parallel| L[Log Agent]
        DC -->|Parallel| T[Trace Agent]
    end

    subgraph “Phase II: Collaborative Reasoning”
        M & L & T -->|Findings| Context[Shared Context]
        Context --> Consensus[Consensus Agent]

        Consensus -->|Challenge/Query| DC
        DC -->|Refined Evidence| Context

        note[Loop until Verdict] -.-> Consensus
    end

    subgraph “Phase III: Reporting”
        Consensus -->|Final Verdict| Report[Report Agent]
        Report --> Result[JSON Report]
    end

    classDef agent fill:#e1f5fe,stroke:#01579b,stroke-width:2px;
    class Orch,M,L,T,Consensus,Report agent
```

### 3. 方法论亮点

*   **专家知识注入**: 在 Consensus Agent 中注入显式的故障模式（如 DNS 故障特征、Node vs Pod 资源归因逻辑），显著减少幻觉。
*   **证据驱动裁决**: 多模态对齐机制确保任何因果结论都必须在至少两个模态（如 Metric + Log）中得到相互印证。

## 快速开始

### 1. 环境准备

本项目使用 `uv` 进行依赖管理：

```bash
# 安装依赖
uv sync

# 激活环境
source .venv/bin/activate
```

### 2. 配置

在 `context_rca/.env` 文件中配置 LLM API：

```bash
OPENAI_API_KEY=”sk-...”
# 或其他 LLM 提供商的配置
```

### 3. 运行方式

#### 批量运行（推荐）

使用 `main.py` 进行批量分析，支持多进程并行：

```bash
# 批量运行所有案例，使用 10 个并发进程
python main.py --batch --workers 10

# 随机选择 5 个案例，每个重复运行 3 次
python main.py --random 5 --repeat 3 --workers 4
```

**参数说明**：
- `--batch`: 批量运行模式，处理 `input/input.json` 中的所有案例
- `--workers N`: 并发进程数（默认 1，单进程模式）
- `--random N`: 随机选择 N 个案例运行
- `--repeat N`: 每个案例重复运行 N 次（默认 1）
- `--output PATH`: 指定输出文件路径（默认 `output/result.jsonl`）

#### 单案例调试

开发调试时，使用单案例模式快速验证：

```bash
# 运行指定 UUID 的案例
python main.py --single “31392fda-93-...”

# 运行列表中的第 N 个案例（索引从 1 开始）
python main.py --single 1
```

### 4. 输出说明

- **结果文件**: 输出为 JSONL 格式，默认保存在 `output/result.jsonl`
- **日志文件**: 每个案例的详细日志保存在 `logs/<uuid>/run.log`
- **进度显示**: 多进程模式下自动显示进度条

## 输出格式

系统输出标准的 JSONL 格式，每行包含一个案例的完整分析结果：

```json
{
  “uuid”: “31392fda-93-...”,
  “root_cause”: “shippingservice”,
  “fault_type”: “pod_restart”,
  “reasoning”: “Metric Agent detected a restart in shippingservice-0 (pod_processes drop). Log Agent confirmed startup logs at the same timestamp. Although CartService showed high latency, it was identified as a downstream effect...”,
  “score”: {
    “accuracy”: 0.95,
    “confidence”: 0.87
  }
}
```

## 项目结构

```
context_rca/
├── context_rca/           # 核心代码
│   ├── agent.py          # Orchestrator Agent 定义
│   ├── prompt.py         # Agent 提示词
│   ├── tools.py          # 工具函数
│   ├── callbacks/        # Agent 回调函数
│   ├── schemas/          # 数据模式定义
│   ├── sub_agents/       # 子 Agent 实现
│   │   ├── metric_agent/
│   │   ├── log_agent/
│   │   ├── trace_agent/
│   │   ├── consensus_agent/
│   │   └── report_agent/
│   └── ablations/        # 消融实验变体
├── main.py               # 主运行脚本
├── analyze_results.py    # 结果分析工具
├── input/                # 输入数据
│   └── input.json        # 测试案例集
├── output/               # 输出结果
├── logs/                 # 运行日志
└── models/               # 预训练模型（Drain、Isolation Forest）
```

## 依赖项

核心依赖：
- `google-adk`: Google Agent Development Kit，多智能体框架
- `litellm`: 统一的 LLM API 接口
- `drain3`: 日志解析
- `scikit-learn`: 异常检测（Isolation Forest）
- `networkx`: 服务依赖图分析
- `pandas`: 数据处理

完整依赖列表见 `pyproject.toml`。

## 结果分析

使用 `analyze_results.py` 分析批量运行结果：

```bash
python analyze_results.py output/result.jsonl
```

输出包括：
- 准确率统计
- 故障类型分布
- 平均推理时间
- 失败案例分析

