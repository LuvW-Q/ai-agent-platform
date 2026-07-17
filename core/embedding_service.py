"""
嵌入与重排序服务
支持通过配置的 OpenAI 协议模型进行文本嵌入和重排序
"""
from __future__ import annotations

import json, logging
from typing import Any
import httpx
from fastapi import HTTPException
from core.safe_http import request_public_url
from core.url_guard import assert_public_url

logger = logging.getLogger(__name__)


async def get_embedding(texts: list[str], api_key: str, endpoint: str, model_name: str) -> list[list[float]] | None:
    """调用 OpenAI 协议 embedding 接口"""
    url = f"{endpoint.rstrip('/')}/embeddings"
    assert_public_url(url)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model_name, "input": texts}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await request_public_url(client, "POST", url, json=payload, headers=headers)
            if resp.status_code != 200:
                logger.warning("Embedding failed: %s %s", resp.status_code, resp.text[:300])
                return None
            data = resp.json()
            return [d["embedding"] for d in sorted(data.get("data", []), key=lambda x: x["index"])]
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Embedding error: %s", e)
        return None


async def rerank_documents(
    query: str,
    documents: list[str],
    api_key: str,
    endpoint: str,
    model_name: str,
    top_n: int = 5,
) -> list[dict]:
    """
    重排序文档（Cohere / Jina / 通义 等 rerank 协议）
    尝试标准 rerank 格式: POST /rerank {"model":"...", "query":"...", "documents":[...]}
    """
    url = f"{endpoint.rstrip('/')}/rerank"
    assert_public_url(url)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model_name, "query": query, "documents": documents, "top_n": top_n}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await request_public_url(client, "POST", url, json=payload, headers=headers)
            if resp.status_code != 200:
                logger.warning("Rerank failed: %s %s", resp.status_code, resp.text[:200])
                # 降级：返回原始顺序
                return [{"index": i, "text": d, "score": 0.0} for i, d in enumerate(documents[:top_n])]
            data = resp.json()
            results = data.get("results", [])
            return [{"index": r.get("index", 0), "text": documents[r.get("index", 0)] if r.get("index", 0) < len(documents) else "", "score": r.get("relevance_score", 0)} for r in results]
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Rerank error: %s", e)
        return [{"index": i, "text": d, "score": 0.0} for i, d in enumerate(documents[:top_n])]


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[dict]:
    """简单文本切块（按句子边界）"""
    import re
    sentences = re.split(r'([。！？.!?\n])', text)
    # 合并短句
    merged = []
    buf = ""
    for i in range(0, len(sentences) - 1, 2):
        s = sentences[i] + (sentences[i + 1] if i + 1 < len(sentences) else "")
        if len(buf) + len(s) > chunk_size and buf:
            merged.append(buf.strip())
            buf = s
        else:
            buf += s
    if buf.strip():
        merged.append(buf.strip())

    chunks = []
    for idx, m in enumerate(merged):
        if len(m) < 10:
            continue
        chunks.append({"index": idx, "text": m[:4096], "metadata": "{}"})
    return chunks
