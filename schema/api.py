"""
Pydantic 请求/响应模型
"""
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


# ===== 认证相关 =====
class RegisterIn(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=72)
    email: str = Field(..., max_length=255)

class LoginIn(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=72)

class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class RefreshIn(BaseModel):
    refresh_token: str

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    nickname: str
    email: str
    role: str
    avatar: str
    signature: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ===== 数据源 =====
class DataSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    resource_id: str
    name: str
    status: str
    frequency: str
    endpoint: str
    protocol: str

class DataSourceCreate(BaseModel):
    resource_id: str
    name: str
    frequency: str = ""
    endpoint: str = ""
    protocol: str = "http"


# ===== 数字员工 =====
class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    base_model: str
    persona_prompt: str
    skill_bindings: str
    status: str
    description: str

class AgentCreate(BaseModel):
    name: str
    avatar: str = ""
    base_model: str = "gpt-4o"
    model_id: int | None = None
    persona_prompt: str = ""
    skill_bindings: str = ""
    skill_ids: str = ""
    fallback_message: str = "系统繁忙，请稍后再试"
    description: str = ""


# ===== IM消息 =====
class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    msg_id: str = ""
    sender_id: int
    sender_name: str = ""
    receiver_id: int | None
    group_id: int | None
    content: str
    msg_type: str
    status: str = "sent"
    is_read: bool
    file_url: str = ""
    file_name: str = ""
    file_size: int = 0
    recall_at: datetime | None = None
    created_at: datetime

class MessageSend(BaseModel):
    receiver_id: int | None = None
    group_id: int | None = None
    content: str = ""
    msg_type: str = "text"  # text/emoji/image/file
    msg_id: str = ""  # 客户端生成UUID，用于幂等去重
    file_url: str = ""
    file_name: str = ""
    file_size: int = 0


# ===== 好友 =====
class FriendRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    from_user_id: int
    to_user_id: int
    status: str
    message: str
    created_at: datetime
    responded_at: datetime | None

class FriendRequestIn(BaseModel):
    to_user_id: int
    message: str = ""

class FriendOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    friend_id: int
    created_at: datetime


# ===== 群组 =====
class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    owner_id: int
    avatar: str = ""
    announcement: str = ""
    created_at: datetime

class GroupCreateIn(BaseModel):
    name: str
    member_ids: list[int] = []

class GroupMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    group_id: int
    user_id: int
    role: str
    joined_at: datetime

class UserSearchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    nickname: str
    avatar: str = ""
    signature: str = ""


# ===== 审计日志 =====
class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_type: str
    risk_level: str
    description: str
    operator: str
    created_at: datetime


# ===== 仪表盘 =====
class DashboardMetrics(BaseModel):
    active_pipelines: int
    crawl_success_rate: float
    data_ingress_24h: str
    active_threats: int
    today_messages: int
    active_users: int
    audit_high: int
    audit_medium: int
    audit_low: int
    sentiment_positive: int
    trust_score: float
    # 新字段
    active_agents: int = 0       # 已发布的数字员工数
    total_collected: int = 0     # 采集数据总量
    online_users: int = 0        # 在线用户数（简化：7天内活跃即可）
    risk_distribution: str = ""  # JSON: {"high":x, "medium":y, "low":z}


# ===== 大模型管理 =====
class AIModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    provider: str
    model_name: str
    endpoint: str
    context_length: int
    model_type: str  # chat/image/video/embedding/rerank
    is_default: bool
    is_active: bool
    temperature: str
    max_tokens: int
    created_at: datetime

class AIModelCreate(BaseModel):
    name: str
    provider: str = "openai"
    api_key: str
    model_name: str
    endpoint: str = "https://api.openai.com/v1"
    context_length: int = 4096
    model_type: str = "chat"  # chat/image/video/embedding/rerank
    temperature: str = "0.7"
    max_tokens: int = 2048

class AIModelUpdate(BaseModel):
    name: str | None = None
    provider: str | None = None
    api_key: str | None = None
    model_name: str | None = None
    endpoint: str | None = None
    context_length: int | None = None
    model_type: str | None = None
    is_active: bool | None = None
    temperature: str | None = None
    max_tokens: int | None = None


# ===== 技能管理 =====
class SkillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    skill_type: str  # function_call/mcp/prompt
    description: str
    config: str
    parameters: str
    status: str
    created_at: datetime

class SkillCreate(BaseModel):
    name: str
    skill_type: str  # function_call/mcp/prompt
    description: str = ""
    config: str = ""  # 代码/JSON配置/提示词
    parameters: str = "[]"  # 参数schema

class SkillUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    config: str | None = None
    parameters: str | None = None
    status: str | None = None

class AICreateSkillIn(BaseModel):
    model_id: int
    skill_type: str  # function_call/mcp/prompt
    description: str  # 技能描述


# ===== 数字员工（扩展） =====
class AgentOutExtended(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    avatar: str = ""
    base_model: str = ""
    model_id: int | None = None
    persona_prompt: str = ""
    skill_bindings: str = ""
    skill_ids: str = ""
    fallback_message: str = "系统繁忙，请稍后再试"
    status: str = "draft"
    description: str = ""

class AgentCreateExtended(BaseModel):
    name: str
    avatar: str = ""
    model_id: int | None = None
    persona_prompt: str = ""
    skill_ids: str = ""  # 逗号分隔skill ID
    fallback_message: str = "系统繁忙，请稍后再试"
    description: str = ""

class AgentUpdateExtended(BaseModel):
    name: str | None = None
    avatar: str | None = None
    model_id: int | None = None
    persona_prompt: str | None = None
    skill_ids: str | None = None
    fallback_message: str | None = None
    status: str | None = None
    description: str | None = None


# ===== 对话 =====
class ChatMessage(BaseModel):
    role: str  # user/assistant
    content: str

class DEChatIn(BaseModel):
    agent_id: int
    messages: list[ChatMessage]
    group_id: int | None = None  # 群聊场景

class DEChatOut(BaseModel):
    reply: str
    skill_calls: list[dict] = []
    agent_id: int
    agent_name: str = ""
