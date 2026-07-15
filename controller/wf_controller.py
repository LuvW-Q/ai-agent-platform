"""
工作流编排控制器：节点编排 + 校验 + 执行
"""
from __future__ import annotations

import json, traceback
from fastapi import APIRouter, Depends, HTTPException
from database.session import SessionLocal, get_db
from core.security import get_current_user
from dao.model_dao import get_model, get_default_model
from dao.skill_dao import get_skill
from core.sandbox import sandbox
from core.openai_client import OpenAIClient
from core.milvus_client import search_chunks
from core.embedding_service import get_embedding
from models.user import User
from models.workflow import Workflow, WorkflowNode, WorkflowEdge
from models.ai_model import AIModel
from pydantic import BaseModel

wf_router = APIRouter(prefix="/api/workflows", tags=["工作流编排"])

# ============ 可用节点类型 ============
NODE_TYPES = {
    "start": {"label": "开始", "color": "#4edea3", "inputs": 0, "outputs": 1, "config": []},
    "end": {"label": "结束", "color": "#ffb4ab", "inputs": 1, "outputs": 0, "config": []},
    "llm": {"label": "LLM 调用", "color": "#adc6ff", "inputs": 1, "outputs": 1,
            "config": [{"key": "model_id", "label": "模型", "type": "model_select"},
                       {"key": "system_prompt", "label": "System Prompt", "type": "textarea"},
                       {"key": "user_prompt", "label": "User Prompt（{{input}}）", "type": "textarea"},
                       {"key": "temperature", "label": "温度", "type": "number", "default": 0.7}]},
    "skill": {"label": "技能调用", "color": "#ffb786", "inputs": 1, "outputs": 1,
              "config": [{"key": "skill_id", "label": "技能", "type": "skill_select"}]},
    "condition": {"label": "条件判断", "color": "#ffb786", "inputs": 1, "outputs": 2,
                  "config": [{"key": "expression", "label": "条件表达式（{{output}}）", "type": "text"}]},
    "kb_search": {"label": "知识库检索", "color": "#4edea3", "inputs": 1, "outputs": 1,
                  "config": [{"key": "kb_id", "label": "知识库", "type": "kb_select"},
                             {"key": "top_k", "label": "返回条数", "type": "number", "default": 5}]},
    "http": {"label": "HTTP 请求", "color": "#a6e6ff", "inputs": 1, "outputs": 1,
             "config": [{"key": "url", "label": "URL", "type": "text"},
                        {"key": "method", "label": "方法", "type": "select", "options": ["GET", "POST"]},
                        {"key": "headers", "label": "Headers (JSON)", "type": "textarea"},
                        {"key": "body", "label": "Body（{{input}}）", "type": "textarea"}]},
    "code": {"label": "代码执行", "color": "#a6e6ff", "inputs": 1, "outputs": 1,
             "config": [{"key": "code", "label": "Python 代码（input 变量可用）", "type": "code"}]},
}

# Validation rules for edge connections
VALID_CONNECTIONS = {
    "start": ["llm", "skill", "kb_search", "http", "code", "condition"],
    "llm": ["llm", "skill", "kb_search", "http", "code", "condition", "end"],
    "skill": ["llm", "skill", "kb_search", "http", "code", "condition", "end"],
    "kb_search": ["llm", "skill", "kb_search", "http", "code", "condition", "end"],
    "http": ["llm", "skill", "kb_search", "http", "code", "condition", "end"],
    "code": ["llm", "skill", "kb_search", "http", "code", "condition", "end"],
    "condition": ["llm", "skill", "kb_search", "http", "code", "end"],
}


# ============ Schemas ============
class WFCreateIn(BaseModel):
    name: str
    description: str = ""


class WFUpdateIn(BaseModel):
    name: str | None = None
    description: str | None = None
    nodes: list[dict] | None = None
    edges: list[dict] | None = None


# ============ 工作流 CRUD ============
@wf_router.get("")
def list_wf(db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    wfs = db.query(Workflow).order_by(Workflow.updated_at.desc()).all()
    return [{"id": w.id, "name": w.name, "description": w.description, "status": w.status,
             "node_count": db.query(WorkflowNode).filter(WorkflowNode.workflow_id == w.id).count(),
             "created_at": w.created_at.isoformat()} for w in wfs]


@wf_router.post("", status_code=201)
def create_wf(body: WFCreateIn, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    wf = Workflow(name=body.name, description=body.description, created_by=user.username)
    db.add(wf)
    db.commit()
    db.refresh(wf)
    # 自动添加 start / end 节点
    db.add(WorkflowNode(workflow_id=wf.id, node_type="start", label="开始", position_x=100, position_y=300))
    db.add(WorkflowNode(workflow_id=wf.id, node_type="end", label="结束", position_x=700, position_y=300))
    db.commit()
    return {"id": wf.id, "name": wf.name}


@wf_router.get("/node-types")
def get_node_types():
    """获取可用节点类型列表"""
    return NODE_TYPES


@wf_router.get("/{wf_id}")
def get_wf(wf_id: int, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    wf = db.query(Workflow).filter(Workflow.id == wf_id).first()
    if not wf:
        raise HTTPException(404, "工作流不存在")
    nodes = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == wf_id).all()
    edges = db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == wf_id).all()
    return {
        "id": wf.id, "name": wf.name, "description": wf.description, "status": wf.status,
        "nodes": [{"id": n.id, "type": n.node_type, "label": n.label, "config": json.loads(n.config) if n.config else {},
                   "x": n.position_x, "y": n.position_y} for n in nodes],
        "edges": [{"id": e.id, "source": e.source_node_id, "target": e.target_node_id,
                   "condition": e.condition, "label": e.label} for e in edges],
    }


@wf_router.put("/{wf_id}")
def update_wf(wf_id: int, body: WFUpdateIn, db: SessionLocal = Depends(get_db),
              user: User = Depends(get_current_user)):
    wf = db.query(Workflow).filter(Workflow.id == wf_id).first()
    if not wf:
        raise HTTPException(404, "工作流不存在")
    if body.name is not None:
        wf.name = body.name
    if body.description is not None:
        wf.description = body.description

    # 全量替换节点和边
    if body.nodes is not None:
        db.query(WorkflowNode).filter(WorkflowNode.workflow_id == wf_id).delete()
        db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == wf_id).delete()
        # 保存节点（临时ID→真实ID映射）
        id_map = {}
        for n in body.nodes:
            node = WorkflowNode(
                workflow_id=wf_id, node_type=n.get("type", "llm"),
                label=n.get("label", ""), config=json.dumps(n.get("config", {})),
                position_x=n.get("x", 0), position_y=n.get("y", 0),
            )
            db.add(node)
            db.flush()
            id_map[n.get("id")] = node.id
        # 保存边（引用真实ID）
        if body.edges is not None:
            for e in body.edges:
                src = id_map.get(e.get("source"), e.get("source"))
                tgt = id_map.get(e.get("target"), e.get("target"))
                edge = WorkflowEdge(workflow_id=wf_id, source_node_id=src, target_node_id=tgt,
                                    condition=e.get("condition", ""), label=e.get("label", ""))
                db.add(edge)
    db.commit()
    return {"id": wf.id, "name": wf.name, "updated": True}


@wf_router.delete("/{wf_id}")
def delete_wf(wf_id: int, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    wf = db.query(Workflow).filter(Workflow.id == wf_id).first()
    if not wf:
        raise HTTPException(404, "工作流不存在")
    db.query(WorkflowNode).filter(WorkflowNode.workflow_id == wf_id).delete()
    db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == wf_id).delete()
    db.delete(wf)
    db.commit()
    return {"deleted": True}


# ============ 校验 ============
@wf_router.post("/{wf_id}/validate")
def validate_wf(wf_id: int, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """校验工作流编排是否合理"""
    wf = db.query(Workflow).filter(Workflow.id == wf_id).first()
    if not wf:
        raise HTTPException(404, "工作流不存在")
    nodes = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == wf_id).all()
    edges = db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == wf_id).all()

    errors = []
    warnings = []
    node_map = {n.id: n for n in nodes}

    # 1. 必须有 start 和 end
    start_nodes = [n for n in nodes if n.node_type == "start"]
    end_nodes = [n for n in nodes if n.node_type == "end"]
    if not start_nodes:
        errors.append("缺少「开始」节点")
    if not end_nodes:
        errors.append("缺少「结束」节点")
    if len(start_nodes) > 1:
        errors.append("只能有一个「开始」节点")
    if len(end_nodes) > 1:
        errors.append("只能有一个「结束」节点")

    # 2. 检查每条边的连接合法性
    for e in edges:
        src = node_map.get(e.source_node_id)
        tgt = node_map.get(e.target_node_id)
        if not src:
            errors.append(f"边 #{e.id} 的源节点 #{e.source_node_id} 不存在")
            continue
        if not tgt:
            errors.append(f"边 #{e.id} 的目标节点 #{e.target_node_id} 不存在")
            continue
        allowed = VALID_CONNECTIONS.get(src.node_type, [])
        if tgt.node_type not in allowed:
            errors.append(f"「{NODE_TYPES.get(src.node_type, {}).get('label', src.node_type)}」不能连接到「{NODE_TYPES.get(tgt.node_type, {}).get('label', tgt.node_type)}」")

    # 3. 检查 start 不能作为目标，end 不能作为源
    for e in edges:
        tgt = node_map.get(e.target_node_id)
        if tgt and tgt.node_type == "start":
            errors.append("「开始」节点不能作为其他节点的目标")
        src = node_map.get(e.source_node_id)
        if src and src.node_type == "end":
            errors.append("「结束」节点不能连接其他节点")

    # 4. 条件节点必须有两条出边
    for n in nodes:
        if n.node_type == "condition":
            out_count = sum(1 for e in edges if e.source_node_id == n.id)
            if out_count != 2:
                errors.append(f"条件节点「{n.label or n.id}」必须有恰好2条出边（是/否），当前 {out_count} 条")

    # 5. 检查孤立节点
    connected_ids = set()
    for e in edges:
        connected_ids.add(e.source_node_id)
        connected_ids.add(e.target_node_id)
    for n in nodes:
        if n.id not in connected_ids and n.node_type not in ("start", "end"):
            warnings.append(f"节点「{n.label or n.id}」({NODE_TYPES.get(n.node_type, {}).get('label', '')}) 未连接到任何边")

    # 6. LLM 节点必须选择模型
    for n in nodes:
        if n.node_type == "llm":
            cfg = json.loads(n.config) if n.config else {}
            if not cfg.get("model_id"):
                warnings.append(f"LLM 节点「{n.label or n.id}」未选择模型")

    is_valid = len(errors) == 0
    wf.status = "published" if is_valid and len(warnings) == 0 else ("error" if errors else "draft")
    db.commit()

    return {"valid": is_valid, "errors": errors, "warnings": warnings}


# ============ 执行 ============
@wf_router.post("/{wf_id}/run")
async def run_wf(wf_id: int, input_data: dict = None, db: SessionLocal = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """执行工作流"""
    if input_data is None:
        input_data = {}
    wf = db.query(Workflow).filter(Workflow.id == wf_id).first()
    if not wf:
        raise HTTPException(404, "工作流不存在")
    nodes = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == wf_id).all()
    edges = db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == wf_id).all()

    if len(nodes) <= 2:
        return {"output": "工作流只有开始/结束节点，请添加至少一个处理节点（如LLM、技能等）", "steps": []}

    node_map = {n.id: n for n in nodes}

    # 构建邻接表
    adj = {}
    for e in edges:
        adj.setdefault(e.source_node_id, []).append(e)

    # 找到 start 节点
    start = next((n for n in nodes if n.node_type == "start"), None)
    if not start:
        raise HTTPException(400, "工作流缺少开始节点")

    # BFS 执行
    context = {"input": input_data or {}, "output": "", "steps": []}
    executed = set()
    queue = [start.id]

    while queue:
        node_id = queue.pop(0)
        if node_id in executed:
            continue
        node = node_map.get(node_id)
        if not node:
            continue

        try:
            result = await _execute_node(node, context, db)
            executed.add(node_id)
            context["steps"].append({"node_id": node.id, "type": node.node_type,
                                     "label": node.label, "result": str(result)[:200]})
            context["output"] = result

            # 条件分支
            out_edges = adj.get(node_id, [])
            if node.node_type == "condition":
                condition_true = bool(result)
                for e in out_edges:
                    if condition_true and "否" not in e.label and "false" not in e.label.lower():
                        queue.append(e.target_node_id)
                    elif not condition_true and ("否" in e.label or "false" in e.label.lower()):
                        queue.append(e.target_node_id)
            else:
                for e in out_edges:
                    queue.append(e.target_node_id)

        except Exception as e:
            context["steps"].append({"node_id": node.id, "type": node.node_type,
                                     "label": node.label, "error": str(e)})
            context["output"] = f"执行失败: {e}"
            break

    return context


async def _execute_node(node: WorkflowNode, context: dict, db) -> str:
    """执行单个节点"""
    cfg = json.loads(node.config) if node.config else {}
    inp = context.get("output", "") or json.dumps(context.get("input", {}))

    if node.node_type == "start":
        return json.dumps(context.get("input", {}))

    elif node.node_type == "end":
        return context.get("output", "")

    elif node.node_type == "llm":
        model_id = cfg.get("model_id")
        if not model_id:
            return "错误: 未选择模型"
        m = get_model(int(model_id), db)
        if not m:
            return "错误: 模型不存在"
        if "placeholder" in (m.api_key or "") or len(m.api_key or "") < 20:
            return f"(模拟LLM回复) 收到输入: {str(inp)[:200]}。请配置真实的API Key以启用LLM节点。"
        sys_prompt = cfg.get("system_prompt", "")
        user_prompt = cfg.get("user_prompt", "{{input}}").replace("{{input}}", str(inp))
        client = OpenAIClient(api_key=m.api_key, endpoint=m.endpoint, model_name=m.model_name,
                              temperature=float(cfg.get("temperature", 0.7)), max_tokens=2048)
        try:
            msgs = [{"role": "user", "content": user_prompt}]
            if sys_prompt:
                msgs.insert(0, {"role": "system", "content": sys_prompt})
            resp = await client.chat_completion(msgs)
            return OpenAIClient.extract_content(resp)
        except Exception as e:
            return f"LLM调用失败: {str(e)[:200]}"
        finally:
            await client.close()

    elif node.node_type == "skill":
        skill_id = cfg.get("skill_id")
        if not skill_id:
            return "错误: 未选择技能"
        skill = get_skill(int(skill_id), db)
        if not skill:
            return "错误: 技能不存在"
        result = sandbox.execute_function(skill.config, "execute", {"arg": inp})
        return json.dumps(result.get("result", result.get("error", "")), ensure_ascii=False)

    elif node.node_type == "kb_search":
        kb_id = cfg.get("kb_id")
        if not kb_id:
            return "错误: 未选择知识库"
        emb_model = db.query(AIModel).filter(AIModel.model_type == "embedding", AIModel.is_active == True).first()
        if not emb_model or "placeholder" in (emb_model.api_key or ""):
            return "错误: 无可用嵌入模型或API Key为占位符，请在模型管理中配置真实的embedding模型"
        vecs = await get_embedding([str(inp)], emb_model.api_key, emb_model.endpoint, emb_model.model_name)
        if not vecs:
            return "错误: 嵌入失败，请检查嵌入模型配置"
        chunks = search_chunks(int(kb_id), vecs[0], top_k=int(cfg.get("top_k", 5)))
        return "\n\n".join([c["chunk_text"] for c in chunks]) if chunks else "(知识库中无相关内容)"

    elif node.node_type == "http":
        import httpx
        url = cfg.get("url", "")
        method = cfg.get("method", "GET")
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                if method == "POST":
                    r = await c.post(url, json={"input": inp})
                else:
                    r = await c.get(url, params={"input": inp})
                return r.text[:2000]
        except Exception as e:
            return f"HTTP 错误: {e}"

    elif node.node_type == "code":
        code = cfg.get("code", "")
        result = sandbox.execute_raw(code, {"input": inp})
        return str(result.get("result", result.get("error", "")))

    elif node.node_type == "condition":
        return str(inp)

    return str(inp)
