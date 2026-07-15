"""
智能问数路由：AI NL2SQL + 安全校验 + 图表推荐
"""
from __future__ import annotations

import json, re
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from core.security import get_current_user
from core.openai_client import OpenAIClient
from dao.model_dao import get_model, get_default_model, list_models as dao_list_models
from database.session import SessionLocal, get_db
from models.user import User
from models.ai_model import AIModel

query_router = APIRouter(prefix="/api/query", tags=["智能问数"])


class QueryIn(BaseModel):
    question: str
    model_id: int | None = None  # 选择的模型ID，不选则用默认chat模型


class QueryOut(BaseModel):
    sql: str = ""
    explanation: str = ""
    rows: list[dict] = []
    chart_type: str = ""  # bar/line/pie/scatter/table
    chart_title: str = ""
    chart_data: dict | None = None  # {labels:[], series:[{name,data}]}


# 数据库表结构描述（给 LLM 参考）
DB_SCHEMA = """Tables:
- users(id, username, nickname, email, role, avatar, signature, is_active, created_at, updated_at)
- messages(id, msg_id, sender_id, receiver_id, group_id, content, msg_type, status, is_read, file_url, file_name, file_size, recall_at, created_at)
- agents(id, name, avatar, base_model, model_id, persona_prompt, skill_ids, fallback_message, status, description, created_at)
- ai_models(id, name, provider, model_name, endpoint, context_length, model_type, is_default, is_active, temperature, max_tokens)
- skills(id, name, skill_type, description, config, parameters, status, created_at)
- data_sources(id, resource_id, name, status, frequency, endpoint, protocol)
- audit_logs(id, event_type, risk_level, description, operator, created_at)
- knowledge_bases(id, name, description, embedding_model_id, rerank_model_id, chunk_count, created_at)
- collected_data(id, source_name, keyword, title, url, content, summary, sentiment, saved, created_at)
- groups(id, name, owner_id, avatar, announcement, created_at)
- group_members(id, group_id, user_id, role, joined_at)
- friendships(id, user_id, friend_id, created_at)
- friend_requests(id, from_user_id, to_user_id, status, message, created_at)
- refresh_tokens(id, uid, token, expires, created_at)
- roles(id, name, code, description, is_active)
- ds_configs(id, name, url, method, headers, body, parse_type, parse_rule, status, created_at)
- clean_rules(id, name, rule_type, config, status, created_at)
- workflows(id, name, description, status, created_at)
"""

# 关键词降级模板（无 AI 时使用）
QUERY_TEMPLATES = [
    {"keywords": ["数据源", "多少", "数量", "data source", "count", "total"], "sql": "SELECT COUNT(*) AS total FROM data_sources", "label": "数据源总数"},
    {"keywords": ["数据源", "列表", "list", "data source", "show"], "sql": "SELECT name, status, protocol, endpoint FROM data_sources ORDER BY created_at DESC", "label": "数据源列表"},
    {"keywords": ["数据源", "活跃", "active", "running"], "sql": "SELECT COUNT(*) AS active_total FROM data_sources WHERE status='active'", "label": "活跃数据源"},
    {"keywords": ["审计", "高风险", "high risk", "danger"], "sql": "SELECT event_type, description, operator, created_at FROM audit_logs WHERE risk_level='high' ORDER BY created_at DESC LIMIT 20", "label": "高风险审计"},
    {"keywords": ["审计", "日志", "audit", "log", "event"], "sql": "SELECT event_type, risk_level, description, operator, created_at FROM audit_logs ORDER BY created_at DESC LIMIT 20", "label": "审计日志"},
    {"keywords": ["审计", "统计", "stats", "summary"], "sql": "SELECT risk_level, COUNT(*) AS cnt FROM audit_logs GROUP BY risk_level", "label": "审计统计"},
    {"keywords": ["用户", "多少", "user count", "users", "how many user", "registered"], "sql": "SELECT COUNT(*) AS total_users FROM users", "label": "用户总数"},
    {"keywords": ["用户", "列表", "user list", "show users"], "sql": "SELECT username, nickname, role, email, is_active, created_at FROM users ORDER BY created_at DESC", "label": "用户列表"},
    {"keywords": ["用户", "活跃", "active users"], "sql": "SELECT username, nickname, role FROM users WHERE is_active=1 ORDER BY created_at DESC", "label": "活跃用户"},
    {"keywords": ["agent", "数字员工", "bot", "employee"], "sql": "SELECT name, base_model, status, description FROM agents ORDER BY created_at DESC", "label": "数字员工列表"},
    {"keywords": ["员工", "发布", "published", "online"], "sql": "SELECT name, base_model FROM agents WHERE status='published'", "label": "已发布员工"},
    {"keywords": ["消息", "多少", "message count", "how many messages"], "sql": "SELECT COUNT(*) AS total_messages FROM messages", "label": "消息总数"},
    {"keywords": ["消息", "最近", "recent message", "latest"], "sql": "SELECT content, msg_type, sender_id, created_at FROM messages WHERE status!='recalled' ORDER BY created_at DESC LIMIT 10", "label": "最近10条消息"},
    {"keywords": ["消息", "分布", "distribution", "by type"], "sql": "SELECT msg_type, COUNT(*) AS cnt FROM messages GROUP BY msg_type ORDER BY cnt DESC", "label": "消息类型分布"},
    {"keywords": ["角色", "权限", "role", "permission"], "sql": "SELECT name, code, description FROM roles ORDER BY id", "label": "角色列表"},
    {"keywords": ["知识库", "kb", "knowledge"], "sql": "SELECT name, description, doc_count FROM knowledge_bases ORDER BY doc_count DESC", "label": "知识库列表"},
    {"keywords": ["采集", "数据", "collected", "warehouse"], "sql": "SELECT title, source_name, sentiment, created_at FROM collected_data WHERE saved=1 ORDER BY created_at DESC LIMIT 20", "label": "采集数据"},
    {"keywords": ["群", "group"], "sql": "SELECT name, owner_id, created_at FROM groups ORDER BY created_at DESC", "label": "群列表"},
    {"keywords": ["模型", "model", "ai"], "sql": "SELECT name, provider, model_name, model_type, is_active FROM ai_models ORDER BY created_at DESC", "label": "AI模型列表"},
    {"keywords": ["技能", "skill"], "sql": "SELECT name, skill_type, status, description FROM skills ORDER BY created_at DESC", "label": "技能列表"},
    {"keywords": ["情感", "sentiment", "情绪"], "sql": "SELECT sentiment, COUNT(*) AS cnt FROM collected_data WHERE saved=1 GROUP BY sentiment", "label": "情感分布"},
    {"keywords": ["今天", "今日", "today", "24小时"], "sql": "SELECT COUNT(*) AS today_count FROM messages WHERE created_at >= date('now','start of day')", "label": "今日消息数"},
]


@query_router.get("/models")
def available_models(db: SessionLocal = Depends(get_db)):
    """获取可用于 NL2SQL 的聊天模型列表"""
    models = db.query(AIModel).filter(AIModel.model_type == "chat", AIModel.is_active == True).all()
    default = get_default_model(db)
    return [{"id": m.id, "name": m.name, "model_name": m.model_name, "provider": m.provider,
             "is_default": default and m.id == default.id} for m in models]


@query_router.post("/nl2sql")
async def nl2sql(body: QueryIn, db: SessionLocal = Depends(get_db), current: User = Depends(get_current_user)):
    """自然语言→SQL：AI模式（有真实Key）+ 关键词降级（占位符Key）"""
    question = body.question.strip()
    if not question:
        return QueryOut(sql="", explanation="请输入问题", rows=[])

    # 获取模型
    ai_model = None
    if body.model_id:
        ai_model = get_model(body.model_id, db)
    if not ai_model:
        ai_model = get_default_model(db)
    if not ai_model:
        ai_model = db.query(AIModel).filter(AIModel.model_type == "chat", AIModel.is_active == True).first()

    use_ai = (ai_model and ai_model.is_active and ai_model.api_key
              and "placeholder" not in ai_model.api_key and len(ai_model.api_key) > 20)

    if use_ai:
        return await _ai_nl2sql(question, ai_model, db)
    else:
        return _keyword_nl2sql(question, db)


async def _ai_nl2sql(question: str, ai_model, db) -> QueryOut:
    """使用 LLM 生成 SQL"""
    prompt = f"""You are a SQL expert. Generate a SQLite SELECT query for the given question.

Database schema:
{DB_SCHEMA}

RULES:
1. ONLY generate SELECT queries. No INSERT/UPDATE/DELETE/DROP/ALTER.
2. Use SQLite-compatible syntax.
3. Return JSON format: {{"sql": "...", "explanation": "中文解释", "chart_type": "bar|line|pie|scatter|table", "chart_title": "图表标题"}}
4. chart_type: "pie" for ratios/distributions, "bar" for comparisons/counts, "line" for time trends, "table" for lists, "scatter" for correlations.
5. Limit results to 100 rows maximum.

Question: {question}"""

    client = OpenAIClient(api_key=ai_model.api_key, endpoint=ai_model.endpoint,
                          model_name=ai_model.model_name, temperature=0.1, max_tokens=1024, timeout=30)
    try:
        resp = await client.chat_completion([{"role": "user", "content": prompt}])
        ai_text = OpenAIClient.extract_content(resp)
        return _parse_and_execute(ai_text, question, db)
    except Exception:
        return _keyword_nl2sql(question, db)
    finally:
        await client.close()


def _parse_and_execute(ai_text: str, question: str, db) -> QueryOut:
    """解析 LLM 输出、校验安全、执行 SQL"""
    # 提取 JSON
    try:
        # 处理 markdown code block
        json_match = re.search(r'\{[\s\S]*\}', ai_text)
        if json_match:
            parsed = json.loads(json_match.group())
        else:
            parsed = json.loads(ai_text)
    except json.JSONDecodeError:
        return QueryOut(sql=ai_text[:500], explanation="AI 返回格式无法解析，请重试", rows=[])

    sql = (parsed.get("sql") or "").strip().rstrip(";")
    explanation = parsed.get("explanation", "")
    chart_type = parsed.get("chart_type", "table")
    chart_title = parsed.get("chart_title", "")

    if not sql:
        return QueryOut(explanation="AI 未生成有效 SQL", rows=[])

    # 安全校验：只允许 SELECT
    if not re.match(r'^\s*SELECT\b', sql, re.IGNORECASE):
        return QueryOut(sql=sql, explanation="安全拦截：只允许 SELECT 查询", rows=[])

    # 禁止危险关键字
    dangerous = ["DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE", "EXEC", "--", ";"]
    upper_sql = sql.upper()
    for d in dangerous:
        if d in upper_sql.split():
            return QueryOut(sql=sql, explanation=f"安全拦截：SQL 包含禁止的 {d} 操作", rows=[])

    # 添加 LIMIT
    if "LIMIT" not in upper_sql:
        sql += " LIMIT 100"

    # 执行
    import time
    t0 = time.time()
    try:
        result = db.execute(text(sql))
        columns = list(result.keys())
        rows = [dict(zip(columns, row)) for row in result]
        elapsed_ms = round((time.time() - t0) * 1000, 1)

        # 计算总行数（去掉LIMIT的COUNT）
        total_count = len(rows)
        count_sql = f"SELECT COUNT(*) AS cnt FROM ({sql.rstrip(';').replace(' LIMIT 100','').replace(' LIMIT 50','').replace(' LIMIT 10','').replace(' LIMIT 20','')}) AS subq"
        try:
            cr = db.execute(text(count_sql))
            total_count = cr.scalar() or len(rows)
        except Exception:
            total_count = len(rows)

        # 生成图表数据
        chart_data = _build_chart_data(rows, columns, chart_type)
        explanation_full = f"{explanation} | 共{len(rows)}条记录(总计{total_count}条) | 耗时{elapsed_ms}ms"
        return QueryOut(sql=sql, explanation=explanation_full, rows=rows,
                        chart_type=chart_type, chart_title=chart_title, chart_data=chart_data)
    except Exception as e:
        return QueryOut(sql=sql, explanation=f"查询执行失败: {e}", rows=[])


def _keyword_nl2sql(question: str, db) -> QueryOut:
    """关键词匹配降级模式"""
    q = question.lower()
    best, best_score = None, 0
    for item in QUERY_TEMPLATES:
        score = sum(len(kw) for kw in item["keywords"] if kw.lower() in q)
        if score > best_score:
            best_score = score
            best = item

    if best:
        import time
        t0 = time.time()
        try:
            result = db.execute(text(best["sql"]))
            cols = list(result.keys())
            rows = [dict(zip(cols, row)) for row in result]
            elapsed_ms = round((time.time() - t0) * 1000, 1)
            total_count = len(rows)
            chart_type = _infer_chart(rows, cols, question)
            chart_data = _build_chart_data(rows, cols, chart_type)
            label_full = f"{best['label']} | 共{len(rows)}条记录(总计{total_count}条) | 耗时{elapsed_ms}ms"
            return QueryOut(sql=best["sql"], explanation=label_full, rows=rows,
                            chart_type=chart_type, chart_title=best["label"], chart_data=chart_data)
        except Exception as e:
            return QueryOut(sql=best["sql"], explanation=f"执行失败: {e}", rows=[])

    # 表名兜底
    table_hints = {"data_source": "data_sources", "agent": "agents", "audit": "audit_logs",
                   "user": "users", "message": "messages", "数据源": "data_sources",
                   "数字员工": "agents", "审计": "audit_logs", "用户": "users", "消息": "messages"}
    for hint, tbl in table_hints.items():
        if hint in q:
            try:
                result = db.execute(text(f"SELECT * FROM {tbl} LIMIT 10"))
                cols = list(result.keys())
                rows = [dict(zip(cols, row)) for row in result]
                return QueryOut(sql=f"SELECT * FROM {tbl} LIMIT 10",
                                explanation=f"{tbl} 表前10条", rows=rows, chart_type="table")
            except Exception:
                pass

    return QueryOut(sql="", explanation="无法理解此问题。请尝试：'有多少数据源'、'审计高风险日志'、'用户列表' 等", rows=[])


def _infer_chart(rows: list, columns: list, question: str) -> str:
    """推断合适的图表类型"""
    if not rows or len(columns) < 2:
        return "table"
    # 列表型查询（很多文本列）→ table
    text_cols = [c for c in columns if not any(isinstance(r.get(c), (int, float)) for r in rows if r.get(c) is not None)]
    if len(text_cols) >= len(columns) * 0.6:
        return "table"
    numeric_cols = [c for c in columns if any(isinstance(r.get(c), (int, float)) or (isinstance(r.get(c), str) and r.get(c).replace('.','').isdigit()) for r in rows if r.get(c) is not None)]
    if not numeric_cols:
        return "table"
    if len(rows) == 1:
        return "bar"
    # 时间/日期列 → 折线图
    time_keywords = ["date", "time", "created_at", "updated_at", "时间", "日期"]
    if any(tk in " ".join(columns).lower() for tk in time_keywords):
        return "line"
    # COUNT/GROUP BY → 柱状图; 占比 → 饼图
    if "count" in " ".join(columns).lower() or "total" in " ".join(columns).lower():
        return "bar" if len(rows) > 5 else "pie"
    if "cnt" in " ".join(columns).lower() or "num" in " ".join(columns).lower():
        return "bar"
    if len(rows) <= 6:
        return "bar"
    return "bar"


def _build_chart_data(rows: list, columns: list, chart_type: str) -> dict | None:
    """构建 ECharts 格式的图表数据"""
    if not rows or len(columns) < 2:
        return None

    # 找到 label 列（第一个字符串列）和 value 列（第一个数字列）
    label_col = columns[0]
    value_col = None
    for c in columns:
        if any(isinstance(r.get(c), (int, float)) for r in rows):
            value_col = c
            break
    if not value_col:
        return None

    labels = [str(r.get(label_col, ""))[:30] for r in rows]
    values = [float(r.get(value_col, 0) or 0) for r in rows]
    series_name = value_col

    if chart_type == "pie":
        return {
            "labels": labels,
            "series": [{"name": series_name, "data": [{"name": l, "value": v} for l, v in zip(labels, values)]}],
        }
    else:
        return {
            "labels": labels,
            "series": [{"name": series_name, "data": values, "type": chart_type}],
        }
