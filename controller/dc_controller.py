"""
数据采集控制器：数据源/清洗规则管理 + 采集执行 + 数据仓库
"""
from __future__ import annotations

import json, re, uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from database.session import SessionLocal, get_db
from core.security import get_current_user
from dao.model_dao import get_default_model
from core.openai_client import OpenAIClient
from models.user import User
from models.data_collection import DataSourceConfig, CleanRule, CollectedData
from models.collection_task import CollectionTask
from pydantic import BaseModel
import httpx
from bs4 import BeautifulSoup

dc_router = APIRouter(prefix="/api/dc", tags=["数据采集"])


# ============ Schemas ============
class DSCreateIn(BaseModel):
    name: str
    url: str
    method: str = "GET"
    headers: str = "{}"
    body: str = ""
    parse_type: str = "selector"
    parse_rule: str = ""
    template: str = ""


class DSUpdateIn(BaseModel):
    name: str | None = None
    url: str | None = None
    method: str | None = None
    headers: str | None = None
    body: str | None = None
    parse_type: str | None = None
    parse_rule: str | None = None
    template: str | None = None
    status: str | None = None


class CleanRuleIn(BaseModel):
    name: str
    rule_type: str
    config: str = "{}"


class CrawlIn(BaseModel):
    keyword: str
    source_ids: list[int] = []
    clean_rule_ids: list[int] = []


# ============ 数据源 CRUD ============
@dc_router.get("/sources")
def list_sources(db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(DataSourceConfig).order_by(DataSourceConfig.created_at.desc()).all()


@dc_router.post("/sources", status_code=201)
def create_source(body: DSCreateIn, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    ds = DataSourceConfig(**body.model_dump())
    db.add(ds)
    db.commit()
    db.refresh(ds)
    return {"id": ds.id, "name": ds.name}


@dc_router.put("/sources/{ds_id}")
def update_source(ds_id: int, body: DSUpdateIn, db: SessionLocal = Depends(get_db),
                  user: User = Depends(get_current_user)):
    ds = db.query(DataSourceConfig).filter(DataSourceConfig.id == ds_id).first()
    if not ds: raise HTTPException(404, "数据源不存在")
    for k, v in body.model_dump().items():
        if v is not None: setattr(ds, k, v)
    db.commit()
    return {"updated": True}


@dc_router.delete("/sources/{ds_id}")
def delete_source(ds_id: int, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    db.query(DataSourceConfig).filter(DataSourceConfig.id == ds_id).delete()
    db.commit()
    return {"deleted": True}


@dc_router.post("/sources/{ds_id}/test")
async def test_source(ds_id: int, db: SessionLocal = Depends(get_db),
                      user: User = Depends(get_current_user)):
    """测试数据源连接：访问URL 并返回状态码与摘要"""
    ds = db.query(DataSourceConfig).filter(DataSourceConfig.id == ds_id).first()
    if not ds:
        raise HTTPException(404, "数据源不存在")
    test_url = ds.url.replace("{keyword}", "test") if "{keyword}" in ds.url else ds.url
    try:
        headers = json.loads(ds.headers) if ds.headers else {}
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            if ds.method.upper() == "POST":
                req_body = ds.body.replace("{keyword}", "test") if ds.body else ""
                resp = await client.post(test_url, content=req_body, headers=headers)
            else:
                resp = await client.get(test_url, headers=headers)
        return {
            "success": resp.status_code < 500,
            "status_code": resp.status_code,
            "elapsed_ms": int(resp.elapsed.total_seconds() * 1000),
            "length": len(resp.content),
            "content_type": resp.headers.get("content-type", ""),
        }
    except httpx.TimeoutException:
        return {"success": False, "error": "请求超时（15s）", "status_code": None}
    except Exception as e:
        return {"success": False, "error": str(e), "status_code": None}


# ============ 清洗规则 CRUD ============
@dc_router.get("/rules")
def list_rules(db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(CleanRule).order_by(CleanRule.created_at.desc()).all()


@dc_router.post("/rules", status_code=201)
def create_rule(body: CleanRuleIn, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    r = CleanRule(**body.model_dump())
    db.add(r)
    db.commit()
    db.refresh(r)
    return {"id": r.id, "name": r.name}


@dc_router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    db.query(CleanRule).filter(CleanRule.id == rule_id).delete()
    db.commit()
    return {"deleted": True}


# ============ 数据采集 ============
@dc_router.post("/crawl")
async def do_crawl(body: CrawlIn, db: SessionLocal = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """执行采集：按关键词搜索数据源，抓取并清洗"""
    sources = db.query(DataSourceConfig).filter(
        DataSourceConfig.id.in_(body.source_ids), DataSourceConfig.status == "active"
    ).all() if body.source_ids else db.query(DataSourceConfig).filter(DataSourceConfig.status == "active").all()

    rules = db.query(CleanRule).filter(CleanRule.id.in_(body.clean_rule_ids)).all() if body.clean_rule_ids else []

    results = []
    for src in sources:
        try:
            url = src.url.replace("{keyword}", body.keyword)
            headers = json.loads(src.headers) if src.headers else {}
            async with httpx.AsyncClient(timeout=30) as client:
                if src.method == "POST":
                    req_body = src.body.replace("{keyword}", body.keyword) if src.body else ""
                    resp = await client.post(url, content=req_body, headers=headers)
                else:
                    resp = await client.get(url, headers=headers, follow_redirects=True)
                html = resp.text
        except Exception as e:
            results.append({"source": src.name, "error": str(e), "items": []})
            continue

        # 解析
        items = _parse_content(html, src.parse_type, src.parse_rule)

        # 清洗
        cleaned = [_apply_clean_rules(item, rules) for item in items]

        # 创建临时结果（不自动保存）
        result_items = []
        for item in cleaned:
            cd = CollectedData(
                source_id=src.id, source_name=src.name, keyword=body.keyword,
                title=item.get("title", ""), url=item.get("url", ""), content=item.get("content", "")[:5000],
            )
            db.add(cd)
            db.flush()
            result_items.append({
                "id": cd.id, "title": item.get("title", ""),
                "url": item.get("url", ""), "content": item.get("content", ""),
                "saved": cd.saved,
            })
        db.commit()

        results.append({"source": src.name, "source_id": src.id,
                        "count": len(cleaned), "items": result_items[:10]})

    return {"keyword": body.keyword, "results": results}


# ============ 数据仓库 ============
@dc_router.get("/warehouse")
def list_warehouse(keyword: str = Query(None), db: SessionLocal = Depends(get_db),
                   user: User = Depends(get_current_user)):
    q = db.query(CollectedData).filter(CollectedData.saved == True).order_by(CollectedData.created_at.desc())
    if keyword:
        q = q.filter((CollectedData.title.contains(keyword)) | (CollectedData.content.contains(keyword)))
    return q.limit(100).all()


@dc_router.post("/warehouse/{data_id}/save")
def save_to_warehouse(data_id: int, db: SessionLocal = Depends(get_db),
                      user: User = Depends(get_current_user)):
    d = db.query(CollectedData).filter(CollectedData.id == data_id).first()
    if not d: raise HTTPException(404, "数据不存在")
    d.saved = True
    db.commit()
    return {"saved": True}


@dc_router.post("/warehouse/{data_id}/deep-collect")
async def deep_collect(data_id: int, db: SessionLocal = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """深度采集：访问数据URL，AI 解析摘要+实体"""
    d = db.query(CollectedData).filter(CollectedData.id == data_id).first()
    if not d: raise HTTPException(404, "数据不存在")
    if not d.url: raise HTTPException(400, "该数据无来源URL")

    # 抓取目标页面
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(d.url, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True)
            full_text = resp.text
    except Exception as e:
        raise HTTPException(500, f"抓取失败: {e}")

    # 用 BeautifulSoup 提取正文
    soup = BeautifulSoup(full_text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    body_text = soup.get_text(separator="\n", strip=True)[:8000]

    d.content = body_text
    d.deep_collected = True

    # AI 摘要 + 实体提取
    chat_model = get_default_model(db)
    if chat_model and "placeholder" not in chat_model.api_key:
        client = OpenAIClient(api_key=chat_model.api_key, endpoint=chat_model.endpoint,
                              model_name=chat_model.model_name, temperature=0.3, max_tokens=1024)
        try:
            prompt = f"""请分析以下网页内容，提取关键信息并以JSON格式返回（不要markdown代码块）：
{{
  "summary": "100字以内的摘要",
  "keywords": ["关键词1", "关键词2"],
  "entities": {{"time": "时间", "location": "地点", "person": "人物", "event": "事件"}},
  "sentiment": "positive/neutral/negative"
}}

内容：{body_text[:4000]}"""
            resp = await client.chat_completion([{"role": "user", "content": prompt}])
            ai_text = OpenAIClient.extract_content(resp)
            # 尝试解析 JSON
            try:
                ai_json = json.loads(ai_text.strip().strip("`").strip("json").strip())
                d.summary = ai_json.get("summary", "")
                d.keywords_extracted = json.dumps(ai_json.get("keywords", []), ensure_ascii=False)
                d.entities = json.dumps(ai_json.get("entities", {}), ensure_ascii=False)
                d.sentiment = ai_json.get("sentiment", "neutral")
            except json.JSONDecodeError:
                d.summary = ai_text[:500]
        except Exception:
            d.summary = "AI 解析失败"
        finally:
            await client.close()

    d.saved = True
    db.commit()
    return {"id": d.id, "title": d.title, "summary": d.summary, "sentiment": d.sentiment,
            "keywords": d.keywords_extracted, "entities": d.entities}


@dc_router.delete("/warehouse/{data_id}")
def delete_warehouse(data_id: int, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    db.query(CollectedData).filter(CollectedData.id == data_id).delete()
    db.commit()
    return {"deleted": True}


# ============ 批量深度采集 + 任务进度日志 ============
@dc_router.post("/batch-deep-collect")
async def batch_deep_collect(body: CrawlIn, db: SessionLocal = Depends(get_db),
                              user: User = Depends(get_current_user)):
    """批量深度采集：创建任务，对仓库中已保存且未深度采集的数据执行深度采集"""
    source_ids_str = ",".join(str(s) for s in body.source_ids) if body.source_ids else ""
    task = CollectionTask(
        keyword=body.keyword,
        source_ids=source_ids_str,
        status="running",
        total_count=0,
        completed_count=0,
        log=f"开始批量深度采集: keyword={body.keyword}, source_ids={source_ids_str or 'all'}\n",
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # 选取需要深度采集的目标：仓库中已保存且未深度采集
    q = db.query(CollectedData).filter(
        CollectedData.saved == True,
        CollectedData.deep_collected == False,
    )
    if body.keyword:
        q = q.filter(CollectedData.keyword == body.keyword)
    if body.source_ids:
        q = q.filter(CollectedData.source_id.in_(body.source_ids))

    items_to_collect = q.all()
    task.total_count = len(items_to_collect)
    task.log += f"待采集条数: {task.total_count}\n"
    db.commit()

    completed = 0
    failed = 0
    async with httpx.AsyncClient(timeout=30) as client:
        for item in items_to_collect:
            try:
                if not item.url:
                    raise ValueError("该数据无来源URL")
                resp = await client.get(item.url, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True)
                full_text = resp.text
                soup = BeautifulSoup(full_text, "html.parser")
                for tag in soup(["script", "style", "nav", "footer", "header"]):
                    tag.decompose()
                body_text = soup.get_text(separator="\n", strip=True)[:8000]
                item.content = body_text
                item.deep_collected = True
                completed += 1
                task.completed_count = completed
                task.log += f"[OK] {item.title or (item.url[:50] if item.url else '未知条目')}... 深度采集完成\n"
            except Exception as e:
                failed += 1
                task.log += f"[FAIL] {item.title or (item.url[:50] if item.url else '未知条目')}... 错误: {str(e)}\n"
            db.commit()

    if task.total_count == 0:
        task.status = "completed"
        task.log += "无可深度采集的数据，任务直接结束\n"
    elif failed == 0:
        task.status = "completed"
        task.log += f"批量深度采集结束: 成功 {completed}/{task.total_count}, 失败 {failed}\n"
    else:
        task.status = "failed"
        task.log += f"批量深度采集结束: 成功 {completed}/{task.total_count}, 失败 {failed}\n"
    db.commit()
    return {
        "task_id": task.id,
        "status": task.status,
        "completed": completed,
        "total": task.total_count,
    }


@dc_router.get("/tasks")
def list_tasks(db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """列出最近的采集任务（最多20条，按创建时间倒序）"""
    tasks = db.query(CollectionTask).order_by(CollectionTask.created_at.desc()).limit(20).all()
    return [
        {
            "id": t.id,
            "keyword": t.keyword,
            "source_ids": t.source_ids,
            "total_count": t.total_count,
            "completed_count": t.completed_count,
            "status": t.status,
            "log": t.log,
            "created_at": t.created_at.isoformat() if t.created_at else "",
            "updated_at": t.updated_at.isoformat() if t.updated_at else "",
        }
        for t in tasks
    ]


@dc_router.get("/tasks/{task_id}")
def get_task(task_id: int, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """查询单个采集任务详情"""
    task = db.query(CollectionTask).filter(CollectionTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    return {
        "id": task.id,
        "keyword": task.keyword,
        "source_ids": task.source_ids,
        "total_count": task.total_count,
        "completed_count": task.completed_count,
        "status": task.status,
        "log": task.log,
        "created_at": task.created_at.isoformat() if task.created_at else "",
        "updated_at": task.updated_at.isoformat() if task.updated_at else "",
    }


# ============ 辅助函数 ============
def _parse_content(html: str, parse_type: str, parse_rule: str) -> list[dict]:
    items = []
    soup = BeautifulSoup(html, "html.parser")

    if parse_type == "crawl4ai" or not parse_rule:
        # crawl4ai 方式：返回整个页面正文
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)[:5000]
        items.append({"title": soup.title.string if soup.title else "", "content": text, "url": ""})
    elif parse_type == "xpath":
        try:
            from lxml import etree
            tree = etree.HTML(html)
            elements = tree.xpath(parse_rule)
            for el in elements:
                items.append({"title": el.text_content()[:200] if hasattr(el, "text_content") else str(el),
                              "content": str(el), "url": ""})
        except ImportError:
            items.append({"title": "XPath需要lxml库", "content": html[:2000], "url": ""})
    else:
        # CSS 选择器
        elements = soup.select(parse_rule) if parse_rule else [soup]
        for el in elements:
            link = el.find("a")
            items.append({
                "title": el.get_text(strip=True)[:200],
                "content": el.get_text(strip=True)[:2000],
                "url": link.get("href", "") if link else "",
            })
    return items


def _apply_clean_rules(item: dict, rules: list) -> dict:
    text = item.get("content", "")
    for r in rules:
        cfg = json.loads(r.config) if r.config else {}
        if r.rule_type == "remove_html":
            text = BeautifulSoup(text, "html.parser").get_text()
        elif r.rule_type == "trim_whitespace":
            text = re.sub(r'\s+', ' ', text).strip()
        elif r.rule_type == "remove_empty":
            if not text.strip():
                text = ""
        elif r.rule_type == "regex_replace":
            pattern = cfg.get("pattern", "")
            replacement = cfg.get("replacement", "")
            if pattern:
                text = re.sub(pattern, replacement, text)
        elif r.rule_type == "deduplicate":
            lines = list(dict.fromkeys(text.split("\n")))
            text = "\n".join(lines)
    item["content"] = text
    return item
