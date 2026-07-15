"""
创意工坊：调用 image/video 模型生成内容
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from database.session import SessionLocal, get_db
from core.security import get_current_user
from models.user import User
from dao.model_dao import get_model, get_default_model
from models.ai_model import AIModel
import httpx

creative_router = APIRouter(prefix="/api/creative", tags=["创意工坊"])


class CreativeIn(BaseModel):
    prompt: str
    model_id: int | None = None
    type: str = "image"  # image / video
    n: int = 1
    size: str = "1024x1024"


class CreativeOut(BaseModel):
    success: bool
    urls: list[str] = []
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
                    f"{m.endpoint.rstrip('/')}/v1/images/generations",
                    json=payload,
                    headers={"Authorization": f"Bearer {m.api_key}"}
                )
                data = resp.json()
            urls = [item["url"] for item in data.get("data", [])]
            return CreativeOut(success=True, urls=urls)
        elif body.type == "video":
            # 视频生成端点（通用格式）
            payload = {
                "model": m.model_name,
                "prompt": body.prompt,
            }
            async with httpx.AsyncClient(timeout=120) as http:
                resp = await http.post(
                    f"{m.endpoint.rstrip('/')}/v1/video/generations",
                    json=payload,
                    headers={"Authorization": f"Bearer {m.api_key}"}
                )
                data = resp.json()
            urls = [item.get("url", item.get("video_url", "")) for item in data.get("data", [])]
            return CreativeOut(success=True, urls=urls)
        else:
            raise HTTPException(400, f"不支持的类型: {body.type}")
    except Exception as e:
        return CreativeOut(success=False, error=str(e))
