# Context-RCA: Multi-Agent Root Cause Analysis System

基于 Google ADK 的多智能体根因分析系统，用于微服务架构的自动化故障诊断。

## 项目概览

Context-RCA 是一个用于微服务系统故障诊断的智能体系统，核心特性：

- **讨论式多智能体协作**: 各专家智能体提出假设、共享证据、达成共识
- **假设管理机制**: 动态管理假设的置信度、支持者和证据
- **共识检测**: 自动判断何时达成诊断共识
- **职责分离**: 数据 Agent 只负责提取数据和提出假设，Attribution Agent 负责最终归因
- **Callback 机制**: 通过 before/after callbacks 实现状态管理和讨论流程控制
- **结构化输出**: JSON 格式的根因分析报告

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    Orchestrator Agent                           │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 职责：                                                    │   │
│  │ 1. 协调各数据 Agent 顺序执行                              │   │
│  │ 2. 管理讨论状态（假设、证据、共识）                        │   │
│  │ 3. 调用 Attribution Agent 进行最终归因                    │   │
│  │ 4. 将归因结论传递给 Report Agent                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                  │
│         ┌────────────────────┼────────────────────┐            │
│         ▼                    ▼                    ▼            │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐        │
│  │ Trace Agent │    │Metric Agent │    │  Log Agent  │        │
│  │  提取调用链  │    │  提取指标    │    │  提取日志   │        │
│  │  提出假设    │    │  提出假设    │    │  提出假设   │        │
│  └─────────────┘    └─────────────┘    └─────────────┘        │
│         │                    │                    │            │
│         └──────────── 共识检查 ──────────────────┘            │
│                              │                                  │
│                              ▼                                  │
│                   ┌─────────────────────┐                      │
│                   │ Attribution Agent   │                      │
│                   │ 上下文融合 + 最终归因 │                      │
│                   └─────────────────────┘                      │
│                              │                                  │
│                              ▼                                  │
│                      ┌─────────────┐                           │
│                      │Report Agent │                           │
│                      │ 格式化输出   │                           │
│                      └─────────────┘                           │
└─────────────────────────────────────────────────────────────────┘
```

## 讨论式架构

### 假设管理

每个数据 Agent 在分析数据后会提出假设：

```python
{
    "id": "H1",
    "component": "productcatalogservice",
    "fault_type": "pod_kill",
    "confidence": 0.85,
    "supporters": ["trace_agent", "metric_agent"],
    "challengers": [],
    "evidence": [...]
}
```

### 共识检测规则

满足以下任一条件即达成共识：

1. **高置信度**: 某假设置信度 >= 0.8
2. **一致支持**: 某假设被所有 3 个分析师支持
3. **最大轮次**: 讨论轮次 >= 3（选择置信度最高的假设）

### 讨论流程

```
Round 0 (数据收集):
├── trace_agent: 分析 Trace → 提出假设 H1
├── metric_agent: 分析 Metric → 提出假设 H2 或支持 H1
├── log_agent: 分析 Log → 验证/质疑现有假设
└── 共识检查 → 若达成共识，进入归因；否则继续讨论

Round 1+ (讨论迭代):
├── 各 Agent 基于缓存数据讨论
├── 更新假设置信度
└── 共识检查
```

## 执行流程

```
Step 0: parse_user_input
   │    └── 解析用户输入，提取 UUID
   │
Step 1: trace_agent
   │    └── 提取调用链异常数据，提出假设
   │
Step 2: metric_agent
   │    └── 提取指标异常数据，提出假设，评价已有假设
   │
Step 3: log_agent
   │    └── 提取日志错误信息，验证假设
   │
Step 4: attribution_agent
   │    └── 上下文融合分析，确定 Component 和 Fault Type
   │
Step 5: report_agent
        └── 将归因结论格式化为 JSON 报告
```

## 项目结构

```
Context-RCA/
├── context_rca/
│   ├── agent.py                 # Orchestrator Agent 定义
│   ├── prompt.py                # Orchestrator Prompt
│   │
│   ├── callbacks/               # 回调函数模块
│   │   ├── orchestrator_callbacks.py   # 初始化讨论状态
│   │   ├── consensus_check.py          # 共识检查逻辑
│   │   ├── trace_agent_callbacks.py    # 假设解析
│   │   ├── metric_agent_callbacks.py   # 假设解析
│   │   ├── log_agent_callbacks.py      # 假设解析 + 轮次管理
│   │   └── ...
│   │
│   └── sub_agents/              # 子智能体模块
│       ├── trace_agent/         # 链路追踪上下文提取
│       ├── log_agent/           # 日志上下文提取
│       ├── metric_agent/        # 指标上下文提取
│       ├── attribution_agent/   # 上下文融合归因
│       └── report_agent/        # 报告格式化
│
├── input/                       # 输入数据
│   └── minimal_input.json       # 测试输入
│
├── output/                      # 输出目录
│   ├── test_results.json        # 测试结果
│   └── minimal_groundtruth.json # 标准答案
│
├── data/                        # 数据目录
│   └── processed/               # 预处理后的 Parquet 文件
│
├── main.py                      # 主程序
├── test.py                      # 测试脚本
└── evaluate.py                  # 评估脚本
```

## 核心机制

### 1. State 管理

通过 Callbacks 初始化和更新 State：

```python
# 讨论状态
callback_context.state["hypotheses"] = []           # 假设列表
callback_context.state["messages"] = []             # 讨论消息
callback_context.state["discussion_round"] = 0      # 当前轮次
callback_context.state["consensus_reached"] = False # 共识状态

# 数据缓存标志
callback_context.state["trace_data_collected"] = False
callback_context.state["metric_data_collected"] = False
callback_context.state["log_data_collected"] = False

# 证据缓存
callback_context.state["evidence"] = {
    "trace": [], "metric": [], "log": []
}
```

### 2. 假设解析

各 Agent 的输出会被自动解析为假设：

```markdown
## 假设提议
- **假设组件**: productcatalogservice-0
- **假设故障类型**: pod_kill
- **初始置信度**: 0.85
- **支持证据**: pod_processes 骤降到 0
```

### 3. Component 选择规则

| 故障类型 | Component 规则 |
|----------|----------------|
| **Node 故障** | Component = 异常节点名（如 `aiops-k8s-06`） |
| **网络故障** (delay/loss/corrupt) | Component = **Source（调用方）** |
| **Pod 故障** (failure/kill) | Component = **Destination（被调用方）** |
| **资源压力** (cpu/memory stress) | Component = 异常服务/Pod 名 |

## 快速开始

### 1. 安装依赖

```bash
pip install google-adk litellm pandas pyarrow pydantic python-dotenv
```

### 2. 配置环境

创建 `context_rca/.env` 文件：

```bash
OPENAI_API_KEY="your-api-key"
OPENAI_BASE_URL="https://api.openai.com/v1"
```

### 3. 运行分析

```bash
python main.py
```

### 4. 运行测试

```bash
# 随机测试 3 条
python test.py -r 3

# 指定 UUID 测试
python test.py -u 74a44ae7-81

# 查看帮助
python test.py -h
```

## 输出格式

最终报告为 JSON 格式：

```json
{
    "uuid": "345fbe93-80",
    "component": "checkoutservice",
    "reason": "rrt_max spike with network delay between checkoutservice and emailservice",
    "reasoning_trace": [
        {
            "step": 1,
            "action": "LoadMetrics(checkoutservice)",
            "observation": "rrt_max surged significantly indicating network latency issues."
        },
        {
            "step": 2,
            "action": "LogSearch(checkoutservice)",
            "observation": "Timeout errors found when connecting to downstream services."
        },
        {
            "step": 3,
            "action": "TraceAnalysis(345fbe93-80)",
            "observation": "Trace shows checkoutservice to emailservice calls experienced delay."
        }
    ]
}
```

## 支持的故障类型

系统支持 18 种故障类型的诊断：

| 类别 | 故障类型 | 关键指标 |
|------|----------|----------|
| Stress | cpu_stress | `pod_cpu_usage` |
| Stress | memory_stress | `pod_memory_working_set_bytes` |
| Network | network_delay | `rrt`, `rrt_max` |
| Network | network_loss | `rrt`, `rrt_max` |
| Network | network_corrupt | `rrt`, `rrt_max` |
| Pod | pod_failure | `pod_processes`, `error_ratio` |
| Pod | pod_kill | `pod_processes` |
| Node | node_cpu_stress | `node_cpu_usage_rate` |
| Node | node_memory_stress | `node_memory_usage_rate` |
| Node | node_disk_fill | `node_filesystem_usage_rate` |
| JVM | jvm_cpu, jvm_gc, jvm_exception, jvm_latency | 对应 JVM 指标 |
| DNS | dns_error | DNS 相关指标 |
| IO | io_fault | `region_pending`, `io_util` |
| Code | code_error | HTTP 状态码 |
| Config | target_port_misconfig | 端口配置 |

## 日志输出示例

```
============================================================
ORCHESTRATOR - Initializing
============================================================
  Completed initialize (with discussion state)

============================================================
TRACE ANALYSIS - Starting
  UUID: 74a44ae7-81
  Discussion Round: 0
============================================================
TRACE ANALYSIS COMPLETED - Findings length: 1777 characters
[假设管理] 创建新假设: H1 - checkoutservice/network_delay
[共识检查] 轮次=0, 假设数量=1
[共识检查] 达成共识: 高置信度 (0.85)
```

## 注意事项

1. **顺序执行**: Agent 必须按顺序执行，不能并行调用
2. **假设驱动**: 各 Agent 需要在分析后提出假设
3. **共识机制**: 当假设置信度达到 0.8 或获得 3 个支持者时达成共识
4. **Source vs Destination**: 网络故障选 Source，Pod 故障选 Destination

## 许可证

Apache 2.0 License
