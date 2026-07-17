"""
应用入口
启动 FastAPI，注册所有路由，初始化数据库，种子数据
"""
import uvicorn
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from core.config import config

from database.session import Base, engine, SessionLocal
from controller.auth_controller import auth_router
from controller.dashboard_controller import dashboard_router
from controller.data_controller import data_router
from controller.agent_controller import agent_router
from controller.im_controller import im_router
from controller.audit_controller import audit_router
from controller.permission_controller import permission_router
from controller.query_controller import query_router
from controller.friend_controller import friend_router
from controller.group_controller import group_router
from controller.ws_controller import ws_router
from controller.model_controller import model_router
from controller.skill_controller import skill_router
from controller.de_controller import de_router
from controller.page_controller import page_router
from controller.kb_controller import kb_router
from controller.wf_controller import wf_router
from controller.dc_controller import dc_router
from controller.smart_audit_controller import smart_audit as smart_audit_router
from controller.setting_controller import setting_router
from controller.creative_controller import creative_router
from controller.api_registry_controller import api_registry_router, migrate_agents_table_extensions
from controller.upload_controller import upload_router

# 导入新模型，确保建表时创建
from models.ai_model import AIModel
from models.skill import Skill
from models.skill_call_log import SkillCallLog
from models.sensitive_word import SensitiveWord
from models.de_message import DEMessage
from models.knowledge_base import KnowledgeBase, KBDocument
from models.workflow import Workflow, WorkflowNode, WorkflowEdge
from models.data_collection import DataSourceConfig, CleanRule, CollectedData
from models.collection_task import CollectionTask
from models.menu import Menu
from models.setting import Setting
from models.api_registry import ApiRegistry
from models.permission import FunctionPoint, RoleFunctionPermission
from models.user_preference import UserPreference

# 建表
Base.metadata.create_all(bind=engine)


def migrate_users_face_descriptor():
    """为已有 SQLite 用户表补充加密人脸特征字段。"""
    from sqlalchemy import inspect, text

    columns = [column["name"] for column in inspect(engine).get_columns("users")]
    if "face_descriptor" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN face_descriptor TEXT DEFAULT ''"))
        print("[migrate] Added column face_descriptor to users table")


migrate_users_face_descriptor()

# 数据库迁移：为messages表添加新列（SQLite不支持IF NOT EXISTS语法，用try/except）
def migrate_messages_table():
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    columns = [c["name"] for c in inspector.get_columns("messages")]
    new_cols = {
        "msg_id": text("ALTER TABLE messages ADD COLUMN msg_id VARCHAR(64) DEFAULT ''"),
        "status": text("ALTER TABLE messages ADD COLUMN status VARCHAR(20) DEFAULT 'sent'"),
        "file_url": text("ALTER TABLE messages ADD COLUMN file_url VARCHAR(500) DEFAULT ''"),
        "file_name": text("ALTER TABLE messages ADD COLUMN file_name VARCHAR(255) DEFAULT ''"),
        "file_size": text("ALTER TABLE messages ADD COLUMN file_size INTEGER DEFAULT 0"),
        "recall_at": text("ALTER TABLE messages ADD COLUMN recall_at DATETIME"),
    }
    with engine.connect() as conn:
        for col, statement in new_cols.items():
            if col not in columns:
                try:
                    conn.execute(statement)
                    conn.commit()
                    print(f"[migrate] Added column {col} to messages table")
                except Exception as e:
                    print(f"[migrate] Column {col} already exists or error: {e}")

migrate_messages_table()


def migrate_agents_table():
    """为agents表添加新列"""
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    columns = [c["name"] for c in inspector.get_columns("agents")]
    new_cols = {
        "avatar": text("ALTER TABLE agents ADD COLUMN avatar VARCHAR(500) DEFAULT ''"),
        "model_id": text("ALTER TABLE agents ADD COLUMN model_id INTEGER"),
        "skill_ids": text("ALTER TABLE agents ADD COLUMN skill_ids VARCHAR(500) DEFAULT ''"),
        "fallback_message": text("ALTER TABLE agents ADD COLUMN fallback_message VARCHAR(500) DEFAULT '系统繁忙，请稍后再试'"),
    }
    with engine.connect() as conn:
        for col, statement in new_cols.items():
            if col not in columns:
                try:
                    conn.execute(statement)
                    conn.commit()
                    print(f"[migrate] Added column {col} to agents table")
                except Exception as e:
                    print(f"[migrate] Column {col} already exists or error: {e}")

migrate_agents_table()


def migrate_de_messages_table():
    """创建或补齐 de_messages 表。"""
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    if "de_messages" not in inspector.get_table_names():
        try:
            DEMessage.__table__.create(bind=engine)
            print("[migrate] Created de_messages table")
        except Exception as e:
            print(f"[migrate] de_messages table creation error: {e}")
        return
    columns = {column["name"] for column in inspector.get_columns("de_messages")}
    if "session_id" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE de_messages ADD COLUMN session_id VARCHAR(64) NOT NULL DEFAULT ''"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_de_messages_session_id ON de_messages (session_id)"))
        print("[migrate] Added column session_id to de_messages table")


def migrate_agent_model_binding():
    """按base_model名称匹配，自动修正Agent的model_id绑定"""
    db = SessionLocal()
    try:
        from models.agent import Agent
        from models.ai_model import AIModel
        models = {m.model_name: m.id for m in db.query(AIModel).all()}
        # base_model名称 → model_name 映射
        name_map = {
            "gpt-4o": "gpt-4o",
            "deepseek-v3": "deepseek-chat",
            "claude-3.5-sonnet": "claude-3-5-sonnet-20241022",
        }
        updated = 0
        # 修复所有Agent（不仅是model_id为None的）
        for agent in db.query(Agent).all():
            target_model_name = name_map.get(agent.base_model, agent.base_model)
            expected_model_id = models.get(target_model_name)
            if expected_model_id and agent.model_id != expected_model_id:
                agent.model_id = expected_model_id
                updated += 1
        if updated:
            db.commit()
            print(f"[migrate] Corrected model binding for {updated} agents")
    except Exception as e:
        db.rollback()
        print(f"[migrate] Agent model binding failed: {e}")
    finally:
        db.close()


migrate_de_messages_table()
migrate_agent_model_binding()


def migrate_ds_configs_template():
    """为ds_configs表添加template列（数据源模板：baidu/rss/custom）"""
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    cols = [c["name"] for c in inspector.get_columns("ds_configs")]
    if "template" not in cols:
        with engine.connect() as conn:
            try:
                conn.execute(text("ALTER TABLE ds_configs ADD COLUMN template VARCHAR(50) DEFAULT ''"))
                conn.commit()
                print("[migrate] Added column template to ds_configs table")
            except Exception as e:
                print(f"[migrate] Column template error: {e}")

migrate_ds_configs_template()

# 数据库迁移：为agents表添加 agent_type 和 api_id 列（接口型数字员工支持）
migrate_agents_table_extensions()


# 写入种子数据
from seed import run_seed
run_seed()

app = FastAPI(title="智能数据瞭望系统", version="1.0.0")


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    accepts_html = "text/html" in request.headers.get("accept", "")
    if exc.status_code == 404 and not request.url.path.startswith("/api/") and accepts_html:
        return FileResponse(
            Path(__file__).resolve().parent / "static" / "404.html",
            status_code=404,
        )
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)

# CORS中间件：允许源由部署环境显式配置，默认仅本地开发地址。
from fastapi.middleware.cors import CORSMiddleware

_cors_origins = [o.strip() for o in config.CORS_ORIGINS.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def disable_static_cache(request, call_next):
    response = await call_next(request)
    script_policy = "'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net"
    if request.url.path == "/screen":
        # ECharts-GL 2 uses Function() to parse internal expr(...) texture sizes.
        script_policy += " 'unsafe-eval'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(self), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' https: data: blob:; "
        f"script-src {script_policy}; "
        "style-src 'self' 'unsafe-inline' https:; "
        "connect-src 'self' https: wss:; frame-ancestors 'none'; base-uri 'self'"
    )
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# 静态资源
app.mount("/static", StaticFiles(directory="static"), name="static")

# API路由
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(data_router)
app.include_router(agent_router)
app.include_router(im_router)
app.include_router(audit_router)
app.include_router(permission_router)
app.include_router(query_router)
app.include_router(friend_router)
app.include_router(group_router)
app.include_router(model_router)
app.include_router(skill_router)
app.include_router(de_router)
app.include_router(kb_router)
app.include_router(wf_router)
app.include_router(dc_router)
app.include_router(smart_audit_router)
app.include_router(setting_router)
app.include_router(creative_router)
app.include_router(api_registry_router)
app.include_router(upload_router)

# WebSocket路由
app.include_router(ws_router)

# 页面路由
app.include_router(page_router)


if __name__ == "__main__":
    uvicorn.run(app, host=config.APP_HOST, port=config.APP_PORT)
