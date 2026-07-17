"""
创意工坊：调用 image/video 模型生成内容
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Literal
from database.session import SessionLocal, get_db
from core.security import get_current_user
from models.user import User
from dao.model_dao import get_model, get_default_model
from models.ai_model import AIModel
import httpx
from core.generation_api import generation_endpoint

creative_router = APIRouter(prefix="/api/creative", tags=["创意工坊"])


class CreativeIn(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=4000)
    model_id: int | None = None
    type: Literal["image", "video"] = "image"
    n: int = Field(1, ge=1, le=4)
    size: Literal["1024x1024", "1024x1792", "1792x1024"] = "1024x1024"
    duration: int = Field(5, ge=1, le=60)
    resolution: Literal["720p", "1080p"] = "720p"


class CreativeOut(BaseModel):
    success: bool
    urls: list[str] = Field(default_factory=list)
    error: str = ""


@creative_router.post("/generate", response_model=CreativeOut)
async def generate(body: CreativeIn, db: SessionLocal = Depends(get_db),
                   user: User = Depends(get_current_user)):
    model_id = body.model_id
    if not model_id:
        default = get_default_model(db)
        if not default or default.model_type != body.type:
            # fallback: 找第一个匹配 type 的模型
            m = db.query(AIModel).filter(
                AIModel.model_type == body.type, AIModel.is_active == True
            ).first()
            if not m:
                raise HTTPException(400, f"无可用 {body.type} 模型")
            model_id = m.id
        else:
            model_id = default.id

    m = get_model(model_id, db)
    if not m:
        raise HTTPException(404, "模型不存在")
    if m.model_type != body.type:
        raise HTTPException(400, f"模型类型不匹配：需要 {body.type}，实际 {m.model_type}")
    if not m.is_active:
        raise HTTPException(400, "模型已停用")
    if not m.api_key or "placeholder" in m.api_key.lower():
        raise HTTPException(400, "模型 API Key 尚未配置")

    try:
        if body.type == "image":
            # 调 /v1/images/generations
            payload = {
                "model": m.model_name,
                "prompt": body.prompt,
                "n": body.n,
                "size": body.size,
            }
            async with httpx.AsyncClient(timeout=60) as http:
                resp = await http.post(
                    generation_endpoint(m.endpoint, "image"),
                    json=payload,
                    headers={"Authorization": f"Bearer {m.api_key}"}
                )
                resp.raise_for_status()
                data = resp.json()
            urls = _extract_generation_urls(data, "image")
            if not urls:
                return CreativeOut(success=False, error=_upstream_error(data, "图片服务未返回可用结果"))
            return CreativeOut(success=True, urls=urls)
        elif body.type == "video":
            # 视频生成端点（通用格式）
            payload = {
                "model": m.model_name,
                "prompt": body.prompt,
                "duration": body.duration,
                "resolution": body.resolution,
            }
            async with httpx.AsyncClient(timeout=120) as http:
                resp = await http.post(
                    generation_endpoint(m.endpoint, "video"),
                    json=payload,
                    headers={"Authorization": f"Bearer {m.api_key}"}
                )
                resp.raise_for_status()
                data = resp.json()
            urls = _extract_generation_urls(data, "video")
            if not urls:
                return CreativeOut(success=False, error=_upstream_error(data, "视频服务未返回可播放地址"))
            return CreativeOut(success=True, urls=urls)
        else:
            raise HTTPException(400, f"不支持的类型: {body.type}")
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:300].strip()
        return CreativeOut(
            success=False,
            error=f"上游服务返回 HTTP {exc.response.status_code}" + (f"：{detail}" if detail else ""),
        )
    except (httpx.HTTPError, ValueError) as exc:
        return CreativeOut(success=False, error=str(exc))


def _extract_generation_urls(payload: dict, media_type: str) -> list[str]:
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    if isinstance(rows, dict):
        rows = [rows]
    urls = []
    for item in rows if isinstance(rows, list) else []:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or item.get("video_url") or item.get("output_url")
        if not url and media_type == "image" and item.get("b64_json"):
            url = "data:image/png;base64," + item["b64_json"]
        if isinstance(url, str) and (
            url.startswith("https://") or url.startswith("http://")
            or (media_type == "image" and url.startswith("data:image/"))
        ):
            urls.append(url)
    if isinstance(payload, dict):
        top_level_url = payload.get("url") or payload.get("video_url") or payload.get("output_url")
        if isinstance(top_level_url, str) and top_level_url.startswith(("https://", "http://")):
            urls.append(top_level_url)
    return list(dict.fromkeys(urls))


def _upstream_error(payload: dict, fallback: str) -> str:
    if not isinstance(payload, dict):
        return fallback
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("detail") or fallback)[:500]
    if error:
        return str(error)[:500]
    if payload.get("id"):
        return f"生成任务 {payload['id']} 已提交，但服务尚未返回结果地址"
    return fallback
