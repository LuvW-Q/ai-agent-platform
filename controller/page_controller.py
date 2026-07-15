"""
页面路由：返回各HTML页面
"""
from fastapi import APIRouter
from fastapi.responses import FileResponse
import os

page_router = APIRouter(tags=["页面"])

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")


@page_router.get("/", include_in_schema=False)
def index():
    """默认跳转登录页"""
    return FileResponse(os.path.join(STATIC_DIR, "login.html"))


@page_router.get("/login", include_in_schema=False)
def login_page():
    return FileResponse(os.path.join(STATIC_DIR, "login.html"))


@page_router.get("/dashboard", include_in_schema=False)
def dashboard_page():
    """数据治理"""
    return FileResponse(os.path.join(STATIC_DIR, "data-governance.html"))


@page_router.get("/screen", include_in_schema=False)
def screen_page():
    """数字大屏"""
    return FileResponse(os.path.join(STATIC_DIR, "digital-screen.html"))


@page_router.get("/agents", include_in_schema=False)
def agents_page():
    """数字员工编排"""
    return FileResponse(os.path.join(STATIC_DIR, "agent-orchestration.html"))


@page_router.get("/permissions", include_in_schema=False)
def permissions_page():
    """权限管控"""
    return FileResponse(os.path.join(STATIC_DIR, "permissions.html"))


@page_router.get("/audit", include_in_schema=False)
def audit_page():
    """审计中心"""
    return FileResponse(os.path.join(STATIC_DIR, "audit-center.html"))


@page_router.get("/messages", include_in_schema=False)
def messages_page():
    """移动端消息"""
    return FileResponse(os.path.join(STATIC_DIR, "messages.html"))


@page_router.get("/im", include_in_schema=False)
def im_console_page():
    """IM控制台"""
    return FileResponse(os.path.join(STATIC_DIR, "im-console.html"))


@page_router.get("/im/chat", include_in_schema=False)
def im_chat_page():
    """IM聊天"""
    return FileResponse(os.path.join(STATIC_DIR, "im-chat.html"))


@page_router.get("/settings", include_in_schema=False)
def settings_page():
    """个人设置"""
    return FileResponse(os.path.join(STATIC_DIR, "settings.html"))


@page_router.get("/query", include_in_schema=False)
def query_page():
    """智能问数"""
    return FileResponse(os.path.join(STATIC_DIR, "smart-query.html"))


@page_router.get("/models", include_in_schema=False)
def models_page():
    """模型管理"""
    return FileResponse(os.path.join(STATIC_DIR, "model-management.html"))


@page_router.get("/skills", include_in_schema=False)
def skills_page():
    """技能管理"""
    return FileResponse(os.path.join(STATIC_DIR, "skill-management.html"))


@page_router.get("/agent-management", include_in_schema=False)
def agent_mgmt_page():
    """数字员工管理"""
    return FileResponse(os.path.join(STATIC_DIR, "agent-management.html"))


@page_router.get("/de", include_in_schema=False)
def de_chat_page():
    """数字员工对话"""
    return FileResponse(os.path.join(STATIC_DIR, "de-chat.html"))


@page_router.get("/rag", include_in_schema=False)
def rag_page():
    """RAG 知识库管理"""
    return FileResponse(os.path.join(STATIC_DIR, "rag-management.html"))


@page_router.get("/workflows", include_in_schema=False)
def workflows_page():
    """工作流编排"""
    return FileResponse(os.path.join(STATIC_DIR, "workflow-editor.html"))


@page_router.get("/data-collection", include_in_schema=False)
def dc_page():
    """数据采集"""
    return FileResponse(os.path.join(STATIC_DIR, "data-collection.html"))


@page_router.get("/smart-audit", include_in_schema=False)
def smart_audit_page():
    """智能审计"""
    return FileResponse(os.path.join(STATIC_DIR, "smart-audit.html"))


@page_router.get("/admin-login", include_in_schema=False)
def admin_login_page():
    """管理端登录"""
    return FileResponse(os.path.join(STATIC_DIR, "admin-login.html"))


@page_router.get("/chat-management", include_in_schema=False)
def chat_mgmt_page():
    """聊天管理"""
    return FileResponse(os.path.join(STATIC_DIR, "chat-management.html"))


@page_router.get("/creative", include_in_schema=False)
def creative_page():
    """创意工坊"""
    return FileResponse(os.path.join(STATIC_DIR, "creative-workshop.html"))


@page_router.get("/api-registry", include_in_schema=False)
def api_registry_page():
    """接口管理"""
    return FileResponse(os.path.join(STATIC_DIR, "api-registry.html"))
