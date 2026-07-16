"""无需动态代码执行的内置技能。"""
from __future__ import annotations

import random

from models.data_collection import CollectedData


_TRACKS = (
    {"song": "夜空中最亮的星", "artist": "逃跑计划"},
    {"song": "平凡之路", "artist": "朴树"},
    {"song": "稻香", "artist": "周杰伦"},
    {"song": "光年之外", "artist": "G.E.M.邓紫棋"},
    {"song": "成都", "artist": "赵雷"},
)


def execute_builtin_skill(handler: str, args: dict, db):
    if handler == "random_music":
        return random.choice(_TRACKS)
    if handler == "news_search":
        keyword = (args.get("keyword") or "").strip()
        query = db.query(CollectedData).filter(CollectedData.saved.is_(True))
        if keyword:
            query = query.filter(
                CollectedData.title.contains(keyword)
                | CollectedData.content.contains(keyword)
                | CollectedData.summary.contains(keyword)
            )
        rows = query.order_by(CollectedData.created_at.desc()).limit(5).all()
        return {
            "count": len(rows),
            "items": [
                {
                    "title": row.title or "无标题",
                    "source": row.source_name or "",
                    "summary": (row.summary or row.content or "")[:120],
                }
                for row in rows
            ],
        }
    raise ValueError(f"未知内置技能处理器: {handler}")
