"""
数字员工用户端：对话 + 技能调用 + 降级 + 熔断 + 敏感词过滤 + 对话历史持久化
"""
import json
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from database.session import SessionLocal, get_db
from schema.api import DEChatIn, DEChatOut
from dao.base_dao import get_agent, log_action
from dao.model_dao import get_model
from dao.skill_dao import get_skill, get_skills_by_ids
from core.security import get_current_user
from core.openai_client import OpenAIClient, OpenAIError
from core.sandbox import sandbox
from core.builtin_skills import execute_builtin_skill
from core.safe_http import request_public_url
from core.circuit_breaker import circuit_breaker
from core.sensitive_filter import sensitive_filter
from models.user import User
from models.agent import Agent
from models.skill import Skill
from models.skill_call_log import SkillCallLog
from models.de_message import DEMessage
import httpx

de_router = APIRouter(prefix="/api/de", tags=["数字员工-用户端"])

# 群聊排队锁：{agent_id: {group_id: is_busy}}
_group_locks: dict[int, dict[int, bool]] = {}


@de_router.get("/list")
def list_published(db=Depends(get_db), user: User = Depends(get_current_user)):
    """获取已发布的数字员工列表"""
    agents = db.query(Agent).filter(Agent.status == "published").all()
    result = []
    for a in agents:
        # 获取绑定模型名称
        model_name = ""
        if a.model_id:
            m = get_model(a.model_id, db)
            if m:
                model_name = m.name
        result.append({
            "id": a.id,
            "name": a.name,
            "avatar": a.avatar or "",
            "description": a.description or "",
            "persona_prompt": a.persona_prompt or "",
            "model_name": model_name,
            "skill_ids": a.skill_ids or "",
        })
    return result


@de_router.get("/{agent_id}/history")
def get_chat_history(agent_id: int, db=Depends(get_db), user: User = Depends(get_current_user)):
    """获取与指定数字员工的对话历史"""
    agent = get_agent(agent_id, db)
    if not agent:
        raise HTTPException(404, "数字员工不存在")
    msgs = db.query(DEMessage).filter(
        DEMessage.user_id == user.id,
        DEMessage.agent_id == agent_id,
    ).order_by(DEMessage.created_at.asc()).limit(100).all()
    return [{"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()} for m in msgs]


@de_router.get("/{agent_id}")
def get_de_detail(agent_id: int, db=Depends(get_db), user: User = Depends(get_current_user)):
    """获取数字员工详情"""
    a = get_agent(agent_id, db)
    if not a:
        raise HTTPException(404, "数字员工不存在")
    model_name = ""
    if a.model_id:
        m = get_model(a.model_id, db)
        if m:
            model_name = m.name
    # 获取技能列表
    skills = []
    if a.skill_ids:
        skill_id_list = [int(x) for x in a.skill_ids.split(",") if x.strip()]
        for s in get_skills_by_ids(skill_id_list, db):
            skills.append({"id": s.id, "name": s.name, "skill_type": s.skill_type, "description": s.description})
    return {
        "id": a.id, "name": a.name, "avatar": a.avatar or "",
        "description": a.description or "", "persona_prompt": a.persona_prompt or "",
        "model_name": model_name, "skills": skills,
        "status": a.status,
    }


@de_router.post("/chat", response_model=DEChatOut)
async def chat(body: DEChatIn, db=Depends(get_db), user: User = Depends(get_current_user)):
    """与数字员工对话 — 支持多轮技能调用、降级、熔断、敏感词过滤"""
    agent = get_agent(body.agent_id, db)
    if not agent:
        raise HTTPException(404, "数字员工不存在")
    if agent.status != "published":
        raise HTTPException(403, "该数字员工未发布")

    # 群聊排队检查
    if body.group_id:
        locks = _group_locks.setdefault(body.agent_id, {})
        if locks.get(body.group_id, False):
            return DEChatOut(
                reply="当前咨询人数较多，请稍后",
                skill_calls=[],
                agent_id=agent.id,
                agent_name=agent.name,
            )
        locks[body.group_id] = True

    try:
        return await _do_chat(agent, body, db, user)
    finally:
        if body.group_id:
            _group_locks.get(body.agent_id, {}).pop(body.group_id, None)


async def _do_chat(agent: Agent, body: DEChatIn, db, user: User) -> DEChatOut:
    """执行对话核心逻辑"""
    # 获取绑定模型
    ai_model = None
    is_mock = True  # 默认mock模式

    if agent.model_id:
        ai_model = get_model(agent.model_id, db)
        if ai_model and ai_model.is_active:
            # 检测API key是否为占位符
            if ai_model.api_key and "placeholder" not in ai_model.api_key and len(ai_model.api_key) > 20:
                is_mock = False

    # ===== 加载对话历史（服务端持久化） =====
    # 从DB加载最近的历史消息，与前端传入的messages合并
    db_history = db.query(DEMessage).filter(
        DEMessage.user_id == user.id,
        DEMessage.agent_id == agent.id,
    ).order_by(DEMessage.created_at.asc()).limit(30).all()

    # 将DB历史转为消息列表
    history_messages = [{"role": m.role, "content": m.content} for m in db_history]

    # 前端传入的消息（当前会话的）
    frontend_messages = [{"role": m.role, "content": m.content} for m in body.messages] if body.messages else []

    # 合并：DB历史 + 前端消息（去重：如果前端消息的最后一条用户消息和DB最后一条相同，则去重）
    if history_messages and frontend_messages:
        # 找到DB最后一条用户消息
        last_db_user = None
        for m in reversed(history_messages):
            if m["role"] == "user":
                last_db_user = m["content"]
                break
        # 找到前端第一条用户消息
        first_fe_user = None
        for m in frontend_messages:
            if m["role"] == "user":
                first_fe_user = m["content"]
                break
        # 如果相同，说明前端已包含DB历史，使用前端消息即可
        if last_db_user and first_fe_user and last_db_user.strip() == first_fe_user.strip():
            merged_messages = frontend_messages
        else:
            # 否则拼接：DB历史 + 前端消息
            merged_messages = history_messages + frontend_messages
    elif history_messages:
        merged_messages = history_messages
    else:
        merged_messages = frontend_messages

    # 加载绑定的技能
    skills_map = {}  # func_name → Skill (同时用中文名和 skill_{id} 两种key)
    if agent.skill_ids:
        skill_id_list = [int(x) for x in agent.skill_ids.split(",") if x.strip()]
        for s in get_skills_by_ids(skill_id_list, db):
            if s.status != "active":
                continue
            if circuit_breaker.is_tripped(s.id):
                continue
            # DeepSeek等严格API要求函数名只能是 ^[a-zA-Z0-9_-]+$
            skills_map[f"skill_{s.id}"] = s
            skills_map[s.name] = s  # 保留中文key兼容mock模式

    # 获取用户最后一条消息
    last_msg = ""
    if merged_messages:
        last_msg = merged_messages[-1].get("content", "")

    # 敏感词检查（输入侧）
    filtered_input, input_blocked = sensitive_filter.filter(last_msg, db)
    if input_blocked:
        return DEChatOut(
            reply="您的输入包含敏感信息，已被拦截。",
            skill_calls=[], agent_id=agent.id, agent_name=agent.name,
        )

    # ===== Mock 模式：无真实API key时使用模拟回复 =====
    if is_mock:
        result = await _mock_chat(agent, last_msg, skills_map, db, user)
        # 保存对话到DB
        _save_de_message(user.id, agent.id, "user", last_msg, db)
        _save_de_message(user.id, agent.id, "assistant", result.reply, db)
        return result

    # ===== 真实 API 调用模式 =====
    client = OpenAIClient(
        api_key=ai_model.api_key,
        endpoint=ai_model.endpoint,
        model_name=ai_model.model_name,
        temperature=ai_model.temperature,
        max_tokens=ai_model.max_tokens,
        timeout=30,
    )

    # 转换为OpenAI tools格式 (用 skill_{id} 作为安全函数名，兼容DeepSeek)
    tools = []
    seen_ids = set()
    for s in skills_map.values():
        safe_name = f"skill_{s.id}"
        if safe_name in seen_ids:
            continue
        seen_ids.add(safe_name)
        try:
            func_params = json.loads(s.parameters) if s.parameters else {"type": "object", "properties": {}}
        except json.JSONDecodeError:
            func_params = {"type": "object", "properties": {}}
        # 把中文名放进description，便于模型理解
        desc = f"[{s.name}] {s.description or ''}"
        tools.append({
            "type": "function",
            "function": {
                "name": safe_name,
                "description": desc.strip(),
                "parameters": func_params,
            },
        })

    # 构建消息（使用合并后的messages）
    messages = []
    if agent.persona_prompt:
        messages.append({"role": "system", "content": agent.persona_prompt})
    for msg in merged_messages:
        messages.append({"role": msg["role"], "content": msg["content"]})

    skill_calls_log = []
    max_rounds = 5

    try:
        content = ""
        for _ in range(max_rounds):
            resp = await client.chat_completion(messages, tools=tools if tools else None)
            content = OpenAIClient.extract_content(resp)
            tool_calls = OpenAIClient.extract_tool_calls(resp)

            if not tool_calls:
                break

            messages.append({"role": "assistant", "content": content or "", "tool_calls": tool_calls})

            for tc in tool_calls:
                func_name = tc.get("function", {}).get("name", "")
                func_args_str = tc.get("function", {}).get("arguments", "{}")
                tool_call_id = tc.get("id", "")
                try:
                    func_args = json.loads(func_args_str)
                except json.JSONDecodeError:
                    func_args = {}

                skill = skills_map.get(func_name)
                if not skill:
                    messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": f"技能 {func_name} 不存在"})
                    continue
                if circuit_breaker.is_tripped(skill.id):
                    messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": f"技能 {func_name} 已被熔断，暂时不可用"})
                    continue

                result = await _execute_skill(skill, func_args, agent.id, user.id, db)
                skill_calls_log.append({"skill": func_name, "success": result.get("success"), "result": str(result.get("result", ""))[:200]})
                _log_skill_call(skill.id, agent.id, user.id, result.get("success", False), result.get("error", ""), db)
                messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(result.get("result", result.get("error", "")), ensure_ascii=False)})
        else:
            content = content or "已达到最大技能调用次数。"

        await client.close()

        # 敏感词过滤（输出侧）
        filtered, blocked = sensitive_filter.filter(content or "", db)
        if blocked:
            filtered = "回复内容包含违规信息，已被拦截。"

        # ===== 持久化对话历史 =====
        _save_de_message(user.id, agent.id, "user", last_msg, db)
        _save_de_message(user.id, agent.id, "assistant", filtered, db)

        log_action("de_chat", f"用户 {user.username} 与数字员工 [{agent.name}] 对话", user.username, db)
        return DEChatOut(reply=filtered, skill_calls=skill_calls_log, agent_id=agent.id, agent_name=agent.name)

    except (OpenAIError, Exception) as e:
        await client.close()
        _log_de_error(agent.id, user.id, str(e), db)
        # ===== API调用失败时，优先使用Agent配置的降级话术 =====
        fallback = (agent.fallback_message or "").strip()
        if fallback and fallback != "系统繁忙，请稍后再试":
            reply = fallback
        else:
            # 降级话术为空或为默认值，退到mock模式
            reply = f"系统繁忙，请稍后再试。\n\n提示：{str(e)[:100]}"
        # 保存对话到DB
        _save_de_message(user.id, agent.id, "user", last_msg, db)
        _save_de_message(user.id, agent.id, "assistant", reply, db)
        return DEChatOut(reply=reply, skill_calls=[], agent_id=agent.id, agent_name=agent.name)


async def _mock_chat(agent: Agent, last_msg: str, skills_map: dict, db, user: User) -> DEChatOut:
    """Mock模式：无真实API key时的模拟对话逻辑

    策略：
    1. 关键词匹配 → 执行对应技能并返回结果
    2. 无匹配 → 基于persona_prompt生成通用回复
    3. 最后兜底 → 使用agent.fallback_message
    """
    skill_calls_log = []

    # 关键词→技能映射 (匹配用户消息中的关键词，中英文都支持)
    keyword_map = {
        "时间": ["获取当前时间", "当前时间", "时间", "time", "几点", "日期", "date"],
        "计算": ["数据计算器", "计算器", "calculate", "计算", "算一下", "等于"],
        "天气": ["天气查询", "weather", "气温", "温度", "下雨", "晴天"],
        "音乐": ["随机音乐推荐", "随机音乐", "音乐", "music", "歌曲"],
        "新闻": ["新闻检索", "新闻", "news", "资讯"],
        "审计": ["审计报告模板", "报告"],
    }

    # 检查用户消息是否匹配某个技能关键词（同时检查关键词和技能名）
    matched_skill = None
    matched_keyword = None
    msg_lower = last_msg.lower()
    for keyword, skill_names in keyword_map.items():
        # 关键词匹配 OR 技能名直接出现在消息中
        if keyword.lower() in msg_lower or any(sn.lower() in msg_lower for sn in skill_names):
            # 在skills_map中查找匹配的技能
            for sname, skill in skills_map.items():
                if sname in skill_names or any(sn in sname for sn in skill_names):
                    matched_skill = skill
                    matched_keyword = keyword
                    break
            if matched_skill:
                break

    if matched_skill:
        # 执行匹配的技能
        # 从用户消息中提取参数
        args = _extract_args_from_msg(last_msg, matched_skill)

        result = await _execute_skill(matched_skill, args, agent.id, user.id, db)
        skill_calls_log.append({
            "skill": matched_skill.name,
            "success": result.get("success"),
            "result": str(result.get("result", ""))[:200],
        })
        _log_skill_call(matched_skill.id, agent.id, user.id, result.get("success", False), result.get("error", ""), db)

        if result.get("success"):
            skill_result = result.get("result")
            if isinstance(skill_result, dict):
                # 格式化dict结果
                parts = []
                for k, v in skill_result.items():
                    parts.append(f"{k}: {v}")
                reply_text = f"我为您执行了【{matched_skill.name}】技能，结果是：\n" + "\n".join(parts)
            else:
                reply_text = f"我为您执行了【{matched_skill.name}】技能，结果是：{skill_result}"
        else:
            reply_text = f"技能【{matched_skill.name}】执行失败：{result.get('error', '未知错误')}"

        # 敏感词过滤
        filtered, blocked = sensitive_filter.filter(reply_text, db)
        if blocked:
            filtered = "回复内容包含违规信息，已被拦截。"

        log_action("de_chat", f"用户 {user.username} 与数字员工 [{agent.name}] 对话(mock)", user.username, db)
        return DEChatOut(reply=filtered, skill_calls=skill_calls_log, agent_id=agent.id, agent_name=agent.name)

    # 无技能匹配：基于persona生成回复，并降级到fallback_message
    reply_text = _generate_persona_reply(agent, last_msg)

    # 敏感词过滤
    filtered, blocked = sensitive_filter.filter(reply_text, db)
    if blocked:
        filtered = "回复内容包含违规信息，已被拦截。"

    log_action("de_chat", f"用户 {user.username} 与数字员工 [{agent.name}] 对话(mock)", user.username, db)
    return DEChatOut(reply=filtered, skill_calls=skill_calls_log, agent_id=agent.id, agent_name=agent.name)


def _extract_args_from_msg(msg: str, skill: Skill) -> dict:
    """从用户消息中提取技能参数 (parameters 为 JSON Schema 格式)"""
    try:
        schema = json.loads(skill.parameters) if skill.parameters else {}
    except json.JSONDecodeError:
        schema = {}

    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    args = {}
    for pname in properties:
        # 简单提取：对于expression类型，取"计算"后面的内容
        if pname == "expression":
            expr = msg
            for prefix in ["计算", "帮我计算", "算一下", "算算"]:
                if expr.startswith(prefix):
                    expr = expr[len(prefix):].strip()
                    break
            expr = expr.replace("=", "").replace("等于多少", "").replace("等于", "").strip()
            args[pname] = expr
        elif pname == "city":
            # 提取城市名：支持 "北京天气" "查成都天气" "上海天气怎么样"
            import re
            for kw in ["天气怎么样", "天气如何", "天气预报", "的天气", "天气"]:
                if kw in msg:
                    city = msg.replace(kw, "").strip()
                    # 去掉动词前缀
                    for prefix in ["查", "查一下", "查询", "帮我查", "我想查", "我想知道", "告诉我"]:
                        if city.startswith(prefix):
                            city = city[len(prefix):].strip()
                            break
                    if city:
                        args[pname] = city
                        break
        elif pname == "logs":
            args[pname] = msg
        elif pname == "keyword":
            keyword = msg
            for token in ["帮我查", "查询", "搜索", "最新", "新闻", "资讯"]:
                keyword = keyword.replace(token, " ")
            args[pname] = " ".join(keyword.split())
    return args


def _generate_persona_reply(agent: Agent, user_msg: str) -> str:
    """基于persona_prompt生成模拟回复，最终降级到fallback_message"""
    persona = agent.persona_prompt or ""
    name = agent.name or "数字员工"
    desc = agent.description or ""
    # 获取自定义降级话术
    fallback = (agent.fallback_message or "").strip()
    has_custom_fallback = fallback and fallback != "系统繁忙，请稍后再试"

    # 问候类
    greetings = ["你好", "您好", "hi", "hello", "在吗", "在不在", "hey"]
    if any(g in user_msg.lower() for g in greetings):
        return f"您好！我是{name}。{desc}请问有什么可以帮助您的？"

    # 自我介绍类
    if "你是谁" in user_msg or "自我介绍" in user_msg or "你能做什么" in user_msg or "功能" in user_msg:
        skills_part = ""
        if agent.skill_ids:
            skills_part = "我目前配备了多项技能，可以帮您获取当前时间、进行数学计算等。"
        return f"我是{name}，{desc}{persona[:100] + '...' if len(persona) > 100 else persona}。{skills_part}请告诉我您的需求，我会尽力为您提供帮助。"

    # 谢谢类
    if "谢谢" in user_msg or "感谢" in user_msg or "thanks" in user_msg.lower():
        return f"不客气！我是{name}，随时为您服务。如果有其他问题，请随时告诉我。"

    # 基于persona的通用回复
    if "金融" in persona or "数据分析师" in persona:
        return f"作为{name}，我可以帮您分析金融数据、解读市场趋势。您具体想了解哪方面的内容呢？比如可以问我当前的日期时间，或者让我帮您做一些数学计算。"
    elif "舆情" in persona or "监控" in persona:
        return f"我是{name}，负责舆情监控和情感分析。目前我可以帮您查询当前时间或进行数据计算。请告诉我您的具体需求。"
    elif "审计" in persona or "报告" in persona:
        return f"我是{name}，擅长审计报告生成。我可以帮您获取当前时间、进行计算或生成审计报告模板。请问您需要什么帮助？"
    elif "运维" in persona or "巡检" in persona:
        return f"我是{name}，负责系统运维巡检。目前可以帮您查询时间、进行数学计算等。请告诉我您的需求。"
    else:
        # 最终降级：优先使用自定义降级话术
        if has_custom_fallback:
            return fallback
        return f'我是{name}。{desc}我收到了您的消息：「{user_msg[:50]}」。目前我处于演示模式，可以帮您获取当前时间、进行数学计算等。请尝试问我「现在几点」或「帮我计算3+5」。'


async def _execute_skill(skill: Skill, args: dict, agent_id: int, user_id: int, db) -> dict:
    """执行单个技能调用"""
    try:
        if skill.skill_type == "builtin":
            config = json.loads(skill.config) if skill.config else {}
            result = execute_builtin_skill(config.get("handler", ""), args, db)
            circuit_breaker.record_success(skill.id)
            return {"success": True, "result": result}

        if skill.skill_type == "function_call":
            # 沙箱执行
            result = sandbox.execute_function(skill.config, "execute", args)
            if result.get("success"):
                circuit_breaker.record_success(skill.id)
                return {"success": True, "result": result.get("result")}
            else:
                circuit_breaker.record_failure(skill.id)
                return {"success": False, "error": result.get("error", "执行失败")}

        elif skill.skill_type == "mcp":
            config = json.loads(skill.config) if skill.config else {}
            # 兼容 server_url 和 url 两种配置key
            server_url = config.get("server_url") or config.get("url", "")
            method = (config.get("method", "POST") or "POST").upper()
            if not server_url:
                return {"success": False, "error": "MCP配置缺少server_url/url"}
            async with httpx.AsyncClient(timeout=15) as http_client:
                if method == "GET":
                    resp = await request_public_url(
                        http_client, "GET", server_url, params=args
                    )
                else:
                    resp = await request_public_url(
                        http_client, "POST", server_url, json=args
                    )
                result = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"text": resp.text}
                circuit_breaker.record_success(skill.id)
                return {"success": True, "result": result}

        elif skill.skill_type == "prompt":
            # 提示词技能：替换变量后返回
            template = skill.config or ""
            for k, v in args.items():
                template = template.replace("{" + k + "}", str(v))
            circuit_breaker.record_success(skill.id)
            return {"success": True, "result": {"prompt": template}}

        else:
            return {"success": False, "error": f"未知技能类型: {skill.skill_type}"}

    except httpx.TimeoutException:
        circuit_breaker.record_failure(skill.id)
        return {"success": False, "error": "请求超时"}
    except Exception as e:
        circuit_breaker.record_failure(skill.id)
        return {"success": False, "error": str(e)}


def _log_skill_call(skill_id: int, agent_id: int, user_id: int, success: bool, error: str, db):
    """记录技能调用日志"""
    try:
        log = SkillCallLog(
            skill_id=skill_id, agent_id=agent_id, user_id=user_id,
            success=success, error_msg=error[:500],
        )
        db.add(log)
        db.commit()
    except Exception:
        db.rollback()


def _log_de_error(agent_id: int, user_id: int, error: str, db):
    """记录数字员工错误"""
    try:
        log_action("de_error", f"数字员工调用失败 agent_id={agent_id}: {error[:200]}", "system", db, risk_level="medium")
    except Exception:
        pass


def _save_de_message(user_id: int, agent_id: int, role: str, content: str, db):
    """持久化DE对话消息"""
    if not content:
        return
    try:
        msg = DEMessage(
            user_id=user_id,
            agent_id=agent_id,
            role=role,
            content=content[:4000],  # 截断过长内容
        )
        db.add(msg)
        db.commit()
    except Exception:
        db.rollback()
