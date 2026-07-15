"""
大模型管理路由：CRUD + 设默认 + 测试
"""
from fastapi import APIRouter, Depends, HTTPException
from database.session import SessionLocal, get_db
from schema.api import AIModelOut, AIModelCreate, AIModelUpdate
from dao.model_dao import list_models, get_model, create_model, update_model, delete_model, set_default
from core.security import get_current_user
from core.openai_client import OpenAIClient, OpenAIError
from dao.base_dao import log_action
from models.user import User
from models.ai_model import AIModel
import asyncio

model_router = APIRouter(prefix="/api/models", tags=["大模型管理"])


@model_router.get("", response_model=list[AIModelOut])
def list_all(db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    return list_models(db)


@model_router.post("", response_model=AIModelOut, status_code=201)
def create(body: AIModelCreate, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    m = AIModel(
        name=body.name, provider=body.provider, api_key=body.api_key,
        model_name=body.model_name, endpoint=body.endpoint,
        context_length=body.context_length, model_type=body.model_type,
        temperature=body.temperature, max_tokens=body.max_tokens,
    )
    saved = create_model(m, db)
    if not saved:
        raise HTTPException(500, "创建失败")
    log_action("model_create", f"创建模型: {body.name} ({body.model_name})", user.username, db)
    return saved


@model_router.get("/{model_id}", response_model=AIModelOut)
def get_one(model_id: int, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    m = get_model(model_id, db)
    if not m:
        raise HTTPException(404, "模型不存在")
    return m


@model_router.put("/{model_id}", response_model=AIModelOut)
def update(model_id: int, body: AIModelUpdate, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    m = update_model(model_id, updates, db)
    if not m:
        raise HTTPException(404, "模型不存在")
    log_action("model_update", f"更新模型: {m.name}", user.username, db)
    return m


@model_router.delete("/{model_id}")
def delete(model_id: int, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    m = get_model(model_id, db)
    if not m:
        raise HTTPException(404, "模型不存在")
    name = m.name
    ok = delete_model(model_id, db)
    if not ok:
        raise HTTPException(500, "删除失败")
    log_action("model_delete", f"删除模型: {name}", user.username, db, risk_level="medium")
    return {"deleted": True}


@model_router.post("/{model_id}/default", response_model=AIModelOut)
def set_as_default(model_id: int, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    m = set_default(model_id, db)
    if not m:
        raise HTTPException(404, "模型不存在")
    log_action("model_set_default", f"设置默认模型: {m.name}", user.username, db)
    return m


@model_router.post("/{model_id}/test")
async def test_model(model_id: int, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """测试模型可用性"""
    m = get_model(model_id, db)
    if not m:
        raise HTTPException(404, "模型不存在")
    try:
        client = OpenAIClient(
            api_key=m.api_key,
            endpoint=m.endpoint,
            model_name=m.model_name,
            temperature=m.temperature,
            max_tokens=100,
            timeout=15,
        )
        resp = await client.chat_completion([
            {"role": "user", "content": "Hello, please respond with 'OK' to confirm you are working."}
        ])
        content = OpenAIClient.extract_content(resp)
        await client.close()
        return {"success": True, "response": content}
    except OpenAIError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"未知错误: {e}"}
