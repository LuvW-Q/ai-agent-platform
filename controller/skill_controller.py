"""
技能管理路由：CRUD + AI创建 + 测试
"""
import json
from fastapi import APIRouter, Depends, HTTPException
from database.session import SessionLocal, get_db
from schema.api import SkillOut, SkillCreate, SkillUpdate, AICreateSkillIn
from dao.skill_dao import list_skills, get_skill, create_skill, update_skill, delete_skill
from dao.model_dao import get_model
from core.rbac import require_role
from core.openai_client import OpenAIClient, OpenAIError
from core.sandbox import sandbox
from core.builtin_skills import execute_builtin_skill
from core.safe_http import request_public_url
from core.circuit_breaker import circuit_breaker
from dao.base_dao import log_action
from models.user import User
from models.skill import Skill
import httpx

skill_router = APIRouter(prefix="/api/skills", tags=["技能管理"])


@skill_router.get("", response_model=list[SkillOut])
def list_all(db: SessionLocal = Depends(get_db),
             user: User = Depends(require_role("ROOT", "OPS", "ADMIN"))):
    return list_skills(db)


@skill_router.post("", response_model=SkillOut, status_code=201)
def create(body: SkillCreate, db: SessionLocal = Depends(get_db),
           user: User = Depends(require_role("ROOT", "OPS", "ADMIN"))):
    s = Skill(
        name=body.name, skill_type=body.skill_type,
        description=body.description, config=body.config,
        parameters=body.parameters,
    )
    saved = create_skill(s, db)
    if not saved:
        raise HTTPException(500, "创建失败")
    log_action("skill_create", f"创建技能: {body.name} ({body.skill_type})", user.username, db)
    return saved


@skill_router.get("/{skill_id}", response_model=SkillOut)
def get_one(skill_id: int, db: SessionLocal = Depends(get_db),
            user: User = Depends(require_role("ROOT", "OPS", "ADMIN"))):
    s = get_skill(skill_id, db)
    if not s:
        raise HTTPException(404, "技能不存在")
    return s


@skill_router.put("/{skill_id}", response_model=SkillOut)
def update(skill_id: int, body: SkillUpdate, db: SessionLocal = Depends(get_db),
           user: User = Depends(require_role("ROOT", "OPS", "ADMIN"))):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    s = update_skill(skill_id, updates, db)
    if not s:
        raise HTTPException(404, "技能不存在")
    log_action("skill_update", f"更新技能: {s.name}", user.username, db)
    return s


@skill_router.delete("/{skill_id}")
def delete(skill_id: int, db: SessionLocal = Depends(get_db),
           user: User = Depends(require_role("ROOT", "OPS", "ADMIN"))):
    s = get_skill(skill_id, db)
    if not s:
        raise HTTPException(404, "技能不存在")
    name = s.name
    ok = delete_skill(skill_id, db)
    if not ok:
        raise HTTPException(500, "删除失败")
    log_action("skill_delete", f"删除技能: {name}", user.username, db, risk_level="medium")
    return {"deleted": True}


@skill_router.post("/ai-create")
async def ai_create(body: AICreateSkillIn, db: SessionLocal = Depends(get_db),
                    user: User = Depends(require_role("ROOT", "OPS", "ADMIN"))):
    """AI创建技能：选模型→选类型→输入描述→生成参数"""
    m = get_model(body.model_id, db)
    if not m:
        raise HTTPException(404, "模型不存在")

    # 构建提示词
    type_desc = {
        "function_call": "一个Python函数，函数名为execute，接收一个dict参数args，返回dict结果。请生成完整的Python函数代码。",
        "mcp": "一个MCP工具配置，包含server_url、tool_name、input_schema字段。请生成JSON配置。",
        "prompt": "一个提示词模板，用{variable}表示变量占位符。请生成模板文本。",
    }
    type_format = type_desc.get(body.skill_type, type_desc["function_call"])

    system_prompt = f"""你是一个技能生成助手。请根据用户描述生成技能配置。

技能类型: {body.skill_type}
技能格式要求: {type_format}

请返回JSON格式，包含以下字段:
- name: 技能名称(简短中文)
- config: 技能配置内容(根据类型生成对应的代码/JSON/模板)
- parameters: 参数schema，JSON数组格式，每个参数包含name、type、description
- description: 技能描述

只返回JSON，不要其他文字。"""

    try:
        client = OpenAIClient(
            api_key=m.api_key, endpoint=m.endpoint,
            model_name=m.model_name, temperature="0.3", max_tokens=2000, timeout=30,
        )
        resp = await client.chat_completion([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请为以下需求创建技能: {body.description}"},
        ])
        content = OpenAIClient.extract_content(resp)
        await client.close()

        # 尝试解析JSON
        # 去除可能的markdown代码块标记
        clean = content.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()
        if clean.startswith("json"):
            clean = clean[4:].strip()

        result = json.loads(clean)
        return {"success": True, "data": result}
    except json.JSONDecodeError:
        return {"success": False, "error": "模型返回内容无法解析为JSON", "raw": content}
    except OpenAIError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"未知错误: {e}"}


@skill_router.post("/{skill_id}/test")
async def test_skill(skill_id: int, test_args: dict = None, db: SessionLocal = Depends(get_db),
                     user: User = Depends(require_role("ROOT", "OPS", "ADMIN"))):
    """测试技能"""
    s = get_skill(skill_id, db)
    if not s:
        raise HTTPException(404, "技能不存在")

    # 检查熔断状态
    if circuit_breaker.is_tripped(skill_id):
        status = circuit_breaker.get_status(skill_id)
        return {"success": False, "error": f"技能已被熔断，剩余冷却时间: {status['remaining_time']}秒"}

    args = test_args or {}

    try:
        if s.skill_type == "builtin":
            config = json.loads(s.config) if s.config else {}
            result = execute_builtin_skill(config.get("handler", ""), args, db)
            circuit_breaker.record_success(skill_id)
            return {"success": True, "result": result}

        if s.skill_type == "function_call":
            # 在沙箱中执行函数
            result = sandbox.execute_function(s.config, "execute", args)
            if result.get("success"):
                circuit_breaker.record_success(skill_id)
                return {"success": True, "result": result.get("result"), "stdout": result.get("stdout", "")}
            else:
                circuit_breaker.record_failure(skill_id)
                return {"success": False, "error": result.get("error", "执行失败")}

        elif s.skill_type == "mcp":
            # MCP: 解析配置，调用API
            config = json.loads(s.config) if s.config else {}
            server_url = config.get("server_url", "")
            if not server_url:
                return {"success": False, "error": "MCP配置缺少server_url"}
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await request_public_url(client, "POST", server_url, json=args)
                result = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text
                circuit_breaker.record_success(skill_id)
                return {"success": True, "result": result, "status_code": resp.status_code}

        elif s.skill_type == "prompt":
            # Prompt: 直接返回模板
            circuit_breaker.record_success(skill_id)
            return {"success": True, "result": s.config, "note": "提示词模板"}

        else:
            return {"success": False, "error": f"未知技能类型: {s.skill_type}"}

    except httpx.TimeoutException:
        circuit_breaker.record_failure(skill_id)
        return {"success": False, "error": "请求超时"}
    except Exception as e:
        circuit_breaker.record_failure(skill_id)
        return {"success": False, "error": str(e)}
