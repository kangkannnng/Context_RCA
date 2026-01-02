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

## 模块职责说明

| 模块 | 核心职责 | 实现路径 |
| :--- | :--- | :--- |
| **Orchestrator** | 流程编排与状态管理 | `agent.py`, `prompt.py` |
| **Log Agent** | 异常堆栈与错误模式识别 | `sub_agents/log_agent` |
| **Metric Agent** | 黄金指标（Golden Signals）异常检测 | `sub_agents/metric_agent` |
| **Trace Agent** | 调用链延迟分析与拓扑依赖梳理 | `sub_agents/trace_agent` |
| **Consensus Agent** | 跨域证据校验与冲突消解 | `sub_agents/consensus_agent` |
| **Report Agent** | 结论汇总与格式化输出 | `sub_agents/report_agent` |

## 快速开始

### 1. 环境依赖

项目基于 Python 3.10+ 构建。

```bash
pip install -r requirements.txt
```

### 2. 配置

在项目根目录 `context_rca/` 下创建 `.env` 文件，配置 LLM 服务端点：

```ini
OPENAI_API_KEY = "your_api_key_here"
OPENAI_BASE_URL = "your_base_url_here"
```

### 3. 执行分析

通过 `main.py` 入口脚本执行分析任务。

**单例调试 (Single Mode)**
适用于开发调试，默认执行输入集的第一条数据。支持按索引或 UUID 指定。
```bash
python main.py                           # 执行第 1 条
python main.py --single 5                # 执行第 5 条（1-based 索引）
python main.py --single "your-uuid-here" # 按 UUID 执行指定条目
```

**随机抽样 (Random Mode)**
随机抽取指定数量的样本进行稳定性测试。
```bash
python main.py --random 3
```

**批量执行 (Batch Mode)**
全量处理输入数据集，适用于最终评测。
```bash
python main.py --batch
```

## 项目结构

```
context_rca/
├── context_rca/
│   ├── agent.py                 # Orchestrator 定义
│   ├── prompt.py                # 全局 SOP 提示词
│   ├── tools.py                 # 公共工具函数
│   ├── sub_agents/              # 领域 Agent 实现
│   ├── callbacks/               # 生命周期回调与状态管理
│   └── schemas/                 # Pydantic 数据模型
├── data/                        # 预处理后的监控数据 (Parquet)
├── input/                       # 故障注入案例 (JSON)
├── output/                      # 分析结果产出
├── logs/                        # 运行日志 (按 Case 独立记录)
├── models/                      # 模型相关文件
└── main.py                      # 启动入口
```

## 常见问题排查

*   **分析超时或卡顿**：通常由于共识阶段未能收敛。系统默认最大迭代轮次为 6 轮，可在 `agent.py` 中调整 `max_iterations`。
*   **结论偏差**：若特定类型的故障识别率低，建议检查对应领域 Agent 的 `prompt.py`，优化其对特定指标或错误日志的敏感度配置。
