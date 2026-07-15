"""
技能管理模型
三种技能形态：function_call(自定义函数)、mcp(MCP工具)、prompt(提示词模板)
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
from database.session import Base


class Skill(Base):
    __tablename__ = "skills"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)            # 技能名称
    skill_type = Column(String(20), nullable=False)       # function_call/mcp/prompt
    description = Column(Text, default="")                 # 技能描述
    # function_call: Python函数代码
    # mcp: JSON配置 {"server_url":"","tool_name":"","input_schema":{}}
    # prompt: 提示词模板内容
    config = Column(Text, default="")                      # 技能配置(JSON或代码)
    # OpenAI function calling 格式的参数定义
    parameters = Column(Text, default="[]")                # 参数schema JSON
    status = Column(String(20), default="active")         # active/disabled(熔断)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
