"""
接口管理路由：接口注册表 CRUD + 在线测试 + 从接口生成数字员工
"""
from __future__ import annotations

import json

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from core.security import get_current_user
from core.rbac import require_role
from core.url_guard import assert_public_url
from core.safe_http import request_public_url
from dao.base_dao import log_action
from database.session import SessionLocal, get_db
from models.agent import Agent
from models.api_registry import ApiRegistry
from models.user import User

api_registry_router = APIRouter(prefix="/api/apis", tags=["接口管理"])


class ApiCreateIn(BaseModel):
    name: str
    code: str
    base_url: str
    method: str = "GET"
    headers: str = "{}"
    body_template: str = ""
    response_path: str = ""
    auth_type: str = "query"
    auth_key: str = ""
    description: str = ""


class ApiUpdateIn(BaseModel):
    name: str | None = None
    code: str | None = None
    base_url: str | None = None
    method: str | None = None
    headers: str | None = None
    body_template: str | None = None
    response_path: str | None = None
    auth_type: str | None = None
    auth_key: str | None = None
    description: str | None = None


def _serialize(api: ApiRegistry) -> dict:
    return {
        "id": api.id,
        "name": api.name,
        "code": api.code,
        "base_url": api.base_url,
        "method": api.method,
        "headers": api.headers or "{}",
        "body_template": api.body_template or "",
        "response_path": api.response_path or "",
        "auth_type": api.auth_type or "query",
        "auth_key": "",
        "auth_key_configured": bool(api.auth_key),
        "description": api.description or "",
        "created_at": api.created_at.isoformat() if api.created_at else None,
        "updated_at": api.updated_at.isoformat() if api.updated_at else None,
    }


@api_registry_router.get("")
def list_apis(db: SessionLocal = Depends(get_db),
              user: User = Depends(require_role("ROOT", "OPS", "ADMIN"))):
    apis = db.query(ApiRegistry).order_by(ApiRegistry.created_at.desc()).all()
    return [_serialize(a) for a in apis]


@api_registry_router.post("", status_code=201)
def create_api(body: ApiCreateIn, db: SessionLocal = Depends(get_db),
               user: User = Depends(require_role("ROOT", "ADMIN"))):
    if db.query(ApiRegistry).filter(ApiRegistry.code == body.code).first():
        raise HTTPException(400, "接口编码已存在")
    api = ApiRegistry(**body.model_dump())
    db.add(api)
    db.commit()
    db.refresh(api)
    log_action("api_create", f"创建接口: {body.name}({body.code})", user.username, db)
    return _serialize(api)


@api_registry_router.put("/{api_id}")
def update_api(api_id: int, body: ApiUpdateIn, db: SessionLocal = Depends(get_db),
                user: User = Depends(require_role("ROOT", "ADMIN"))):
    api = db.query(ApiRegistry).filter(ApiRegistry.id == api_id).first()
    if not api:
        raise HTTPException(404, "接口不存在")
    data = body.model_dump(exclude_unset=True)
    if "code" in data and data["code"] and data["code"] != api.code:
        if db.query(ApiRegistry).filter(ApiRegistry.code == data["code"]).first():
            raise HTTPException(400, "接口编码已存在")
    for k, v in data.items():
        if v is not None and not (k == "auth_key" and v == ""):
            setattr(api, k, v)
    db.commit()
    db.refresh(api)
    log_action("api_update", f"更新接口: {api.name}", user.username, db)
    return _serialize(api)


@api_registry_router.delete("/{api_id}")
def delete_api(api_id: int, db: SessionLocal = Depends(get_db),
               user: User = Depends(require_role("ROOT", "ADMIN"))):
    api = db.query(ApiRegistry).filter(ApiRegistry.id == api_id).first()
    if not api:
        raise HTTPException(404, "接口不存在")
    name = api.name
    db.delete(api)
    db.commit()
    log_action("api_delete", f"删除接口: {name}", user.username, db, risk_level="medium")
    return {"deleted": True}


@api_registry_router.post("/{api_id}/test")
async def test_api(api_id: int, params: str = Query("{}"),
                   db: SessionLocal = Depends(get_db),
                   user: User = Depends(require_role("ROOT", "OPS", "ADMIN"))):
    """在线测试接口：以 params JSON 字符串替换占位符 {params}"""
    api = db.query(ApiRegistry).filter(ApiRegistry.id == api_id).first()
    if not api:
        raise HTTPException(404, "接口不存在")
    # SSRF 防护：在请求前校验目标 URL。HTTPException 直接传播给调用者。
    if api.method.upper() == "POST":
        resolved_url = api.base_url
    else:
        resolved_url = api.base_url
        if params and "{params}" in resolved_url:
            resolved_url = resolved_url.replace("{params}", params)
    assert_public_url(resolved_url)
    try:
        headers = json.loads(api.headers) if api.headers else {}
        if auth := _build_auth_headers(api):
            headers.update(auth)
        async with httpx.AsyncClient(timeout=30) as client:
            if api.method.upper() == "POST":
                body = api.body_template or ""
                if params and "{params}" in body:
                    body = body.replace("{params}", params)
                resp = await request_public_url(
                    client, "POST", resolved_url, content=body, headers=headers
                )
            else:
                resp = await request_public_url(
                    client,
                    "GET",
                    resolved_url,
                    headers=headers,
                    params=_build_query_params(api, params),
                )
        result_text = resp.text[:2000]
        extracted = _extract_response_path(result_text, api.response_path)
        return {
            "success": resp.status_code < 500,
            "status_code": resp.status_code,
            "response": result_text,
            "extracted": extracted,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _build_auth_headers(api: ApiRegistry) -> dict:
    if not api.auth_key:
        return {}
    if api.auth_type == "header":
        return {"Authorization": f"Bearer {api.auth_key}"}
    return {}


def _build_query_params(api: ApiRegistry, params: str) -> dict:
    if api.auth_type == "query" and api.auth_key:
        try:
            base = json.loads(params) if params and params != "{}" else {}
        except Exception:
            base = {}
        base.setdefault("key", api.auth_key)
        return base
    return {}


def _extract_response_path(text: str, path: str) -> str:
    """简易 JSONPath 取值：data.result -> result data['data']['result']"""
    if not path or not text:
        return ""
    try:
        data = json.loads(text)
    except Exception:
        return ""
    current = data
    for seg in path.split("."):
        if isinstance(current, dict) and seg in current:
            current = current[seg]
        else:
            return ""
    if isinstance(current, (dict, list)):
        return json.dumps(current, ensure_ascii=False)[:1000]
    return str(current)[:500]


@api_registry_router.post("/{api_id}/create-agent")
def create_agent_from_api(api_id: int, agent_name: str = Query(""),
                          db: SessionLocal = Depends(get_db),
                          user: User = Depends(require_role("ROOT", "ADMIN"))):
    """从接口生成数字员工：自动绑定 agent_type=api 与 api_id"""
    api = db.query(ApiRegistry).filter(ApiRegistry.id == api_id).first()
    if not api:
        raise HTTPException(404, "接口不存在")
    existing = db.query(Agent).filter(
        Agent.agent_type == "api", Agent.api_id == api_id
    ).first()
    if existing:
        raise HTTPException(409, f"该接口已生成数字员工：{existing.name}")
    name = agent_name or f"{api.name}员工"
    agent = Agent(
        name=name,
        base_model="",
        model_id=None,
        persona_prompt=(
            f"你是一个接口助手，负责调用 {api.name} 接口回答用户问题。\n"
            f"接口URL: {api.base_url}\n方法: {api.method}\n当用户询问相关内容时，"
            f"调用该接口并返回结果。"
        ),
        skill_bindings=f"api_{api.id}",
        skill_ids="",
        status="draft",
        description=f"由接口 [{api.name}] 自动生成的数字员工",
        agent_type="api",
        api_id=api.id,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    log_action("agent_create", f"从接口生成数字员工: {name}", user.username, db)
    return {
        "id": agent.id,
        "name": agent.name,
        "api_name": api.name,
        "api_id": api.id,
        "agent_type": "api",
    }


def migrate_agents_table_extensions():
    """
    为agents表添加 agent_type 和 api_id 列（SQLite 兼容写法）。
    必须在 main.py 中 Base.metadata.create_all 之后调用，因为 SQLAlchemy 的
    create_all 只创建新表，不会 ALTER 已有表添加新列。
    """
    from sqlalchemy import inspect
    from database.session import engine

    inspector = inspect(engine)
    existing_cols = {c["name"] for c in inspector.get_columns("agents")}
    add_cols = {
        # model(默认，对话型) / api(接口型，调用 api_registries)
        "agent_type": text("ALTER TABLE agents ADD COLUMN agent_type VARCHAR(20) DEFAULT 'model'"),
        "api_id": text("ALTER TABLE agents ADD COLUMN api_id INTEGER"),
    }
    with engine.connect() as conn:
        for col, statement in add_cols.items():
            if col not in existing_cols:
                try:
                    conn.execute(statement)
                    conn.commit()
                    print(f"[migrate] Added column {col} to agents table")
                except Exception as e:
                    print(f"[migrate] Column {col} error: {e}")


# 注意：迁移不在模块导入时执行；由 main.py 在 Base.metadata.create_all 之后调用
# migrate_agents_table_extensions() —— 避免在 engine 尚未建表前 ALTER 旧表
