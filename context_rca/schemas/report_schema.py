"""结构化根因分析报告"""
from typing import List
from pydantic import BaseModel, Field


class ReasoningStep(BaseModel):
    """单个推理步骤，包含动作和观察结果。"""
    step: int = Field(description="步骤编号，从1开始")
    action: str = Field(
        description="执行的动作，格式如 'LoadMetrics(<component>)'、'LogSearch(<component>)'、'TraceAnalysis(<uuid>)'"
    )
    observation: str = Field(
        description="观察结果，前20词必须包含关键证据（指标名/日志关键词/trace路径）"
    )


class AnalysisReport(BaseModel):
    """根因分析报告的输出格式，用于比赛提交。"""
    uuid: str = Field(description="故障案例的唯一标识符，如 '345fbe93-80'")
    component: str = Field(
        description="""根因组件名称:
        service级故障：服务名如 'emailservice'；
        pod级故障：Pod名如 'shippingservice-0'；
        node级故障：节点名如 'aiops-k8s-06'；
        网络故障：source（调用方）如 'checkoutservice'
        """
    )
    reason: str = Field(
        description="故障原因描述，前20词必须包含关键证据（指标名/日志关键词/trace路径）"
    )
    reasoning_trace: List[ReasoningStep] = Field(
        description="完整推理轨迹，3步最优"
    )
