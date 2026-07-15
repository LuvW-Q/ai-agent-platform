"""
数字员工管理路由：列表/创建/发布/更新/删除（扩展版）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from database.session import SessionLocal, get_db
from schema.api import AgentOut, AgentCreate
from dao.base_dao import list_agents, create_agent, get_agent, log_action
from dao.model_dao import get_model
from dao.skill_dao import get_skills_by_ids
from models.agent import Agent
from core.security import get_current_user
from models.user import User

agent_router = APIRouter(prefix="/api/agents", tags=["数字员工"])


class AgentUpdateIn(BaseModel):
    name: str | None = None
    avatar: str | None = None
    base_model: str | None = None
    model_id: int | None = None
    persona_prompt: str | None = None
    skill_bindings: str | None = None
    skill_ids: str | None = None
    fallback_message: str | None = None
    description: str | None = None
    status: str | None = None  # draft/published
    agent_type: str | None = None  # model/api
    api_id: int | None = None


@agent_router.get("")
def list_all(db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    agents = list_agents(db)
    result = []
    for a in agents:
        model_name = ""
        if a.model_id:
            m = get_model(a.model_id, db)
            if m:
                model_name = m.name
        # 获取技能名称
        skill_names = []
        if a.skill_ids:
            ids = [int(x) for x in a.skill_ids.split(",") if x.strip()]
            for s in get_skills_by_ids(ids, db):
                skill_names.append(s.name)
        result.append({
            "id": a.id, "name": a.name, "avatar": a.avatar or "",
            "base_model": a.base_model or "", "model_id": a.model_id,
            "model_name": model_name,
            "persona_prompt": a.persona_prompt or "",
            "skill_bindings": a.skill_bindings or "",
            "skill_ids": a.skill_ids or "",
            "skill_names": skill_names,
            "fallback_message": a.fallback_message or "系统繁忙，请稍后再试",
            "status": a.status, "description": a.description or "",
            "agent_type": a.agent_type or "model",
            "api_id": a.api_id,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        })
    return result


@agent_router.post("", status_code=201)
def create(body: AgentCreate, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    agent = Agent(
        name=body.name,
        avatar=body.avatar or "",
        base_model=body.base_model,
        model_id=body.model_id,
        persona_prompt=body.persona_prompt,
        skill_bindings=body.skill_bindings,
        skill_ids=body.skill_ids,
        fallback_message=body.fallback_message or "系统繁忙，请稍后再试",
        description=body.description,
        status="draft",
        agent_type=body.agent_type or "model",
        api_id=body.api_id,
    )
    saved = create_agent(agent, db)
    if not saved:
        raise HTTPException(status_code=500, detail="创建失败")
    log_action("agent_create", f"创建数字员工: {body.name}", user.username, db)
    return {
        "id": saved.id, "name": saved.name, "avatar": saved.avatar or "",
        "base_model": saved.base_model, "model_id": saved.model_id,
        "persona_prompt": saved.persona_prompt, "skill_bindings": saved.skill_bindings,
        "skill_ids": saved.skill_ids, "fallback_message": saved.fallback_message,
        "status": saved.status, "description": saved.description,
        "agent_type": saved.agent_type or "model",
        "api_id": saved.api_id,
    }


@agent_router.put("/{agent_id}")
def update_agent(agent_id: int, body: AgentUpdateIn, db: SessionLocal = Depends(get_db),
                 user: User = Depends(get_current_user)):
    agent = get_agent(agent_id, db)
    if not agent:
        raise HTTPException(status_code=404, detail="数字员工不存在")
    old_status = agent.status
    if body.name is not None:
        agent.name = body.name
    if body.avatar is not None:
        agent.avatar = body.avatar
    if body.base_model is not None:
        agent.base_model = body.base_model
    if body.model_id is not None:
        agent.model_id = body.model_id
    if body.persona_prompt is not None:
        agent.persona_prompt = body.persona_prompt
    if body.skill_bindings is not None:
        agent.skill_bindings = body.skill_bindings
    if body.skill_ids is not None:
        agent.skill_ids = body.skill_ids
    if body.fallback_message is not None:
        agent.fallback_message = body.fallback_message
    if body.description is not None:
        agent.description = body.description
    if body.status is not None:
        agent.status = body.status
    if body.agent_type is not None:
        agent.agent_type = body.agent_type
    if body.api_id is not None:
        agent.api_id = body.api_id
    db.commit()
    db.refresh(agent)

    if body.status == "published" and old_status != "published":
        log_action("agent_publish", f"数字员工 [{agent.name}] 已发布上线", user.username, db)
    elif body.status == "draft" and old_status == "published":
        log_action("agent_unpublish", f"数字员工 [{agent.name}] 已下线", user.username, db)
    else:
        log_action("agent_update", f"更新数字员工: {agent.name}", user.username, db)

    model_name = ""
    if agent.model_id:
        m = get_model(agent.model_id, db)
        if m:
            model_name = m.name
    return {
        "id": agent.id, "name": agent.name, "avatar": agent.avatar or "",
        "base_model": agent.base_model, "model_id": agent.model_id,
        "model_name": model_name,
        "persona_prompt": agent.persona_prompt, "skill_bindings": agent.skill_bindings,
        "skill_ids": agent.skill_ids, "fallback_message": agent.fallback_message,
        "status": agent.status, "description": agent.description,
        "agent_type": agent.agent_type or "model",
        "api_id": agent.api_id,
    }


@agent_router.delete("/{agent_id}")
def delete_agent(agent_id: int, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    agent = get_agent(agent_id, db)
    if not agent:
        raise HTTPException(status_code=404, detail="数字员工不存在")
    name = agent.name
    db.delete(agent)
    db.commit()
    log_action("agent_delete", f"删除数字员工: {name}", user.username, db, risk_level="medium")
    return {"deleted": True}
