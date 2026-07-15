"""
工作流模型：编排节点与边
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Boolean
from database.session import Base


class Workflow(Base):
    __tablename__ = "workflows"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    description = Column(String(500), default="")
    status = Column(String(20), default="draft")  # draft/published/error
    created_by = Column(String(100), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class WorkflowNode(Base):
    __tablename__ = "workflow_nodes"
    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False, index=True)
    node_type = Column(String(50), nullable=False)  # start/end/llm/skill/condition/kb_search/http/code
    label = Column(String(200), default="")
    config = Column(Text, default="{}")              # JSON: 节点配置参数
    position_x = Column(Integer, default=0)
    position_y = Column(Integer, default=0)


class WorkflowEdge(Base):
    __tablename__ = "workflow_edges"
    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False, index=True)
    source_node_id = Column(Integer, nullable=False)
    target_node_id = Column(Integer, nullable=False)
    condition = Column(String(500), default="")       # 条件表达式（条件边）
    label = Column(String(100), default="")
