"""无需动态代码执行的内置技能。"""
from __future__ import annotations

import ast
import operator
import random
from urllib.parse import quote

import httpx

from core.safe_http import request_public_url
from models.data_collection import CollectedData


_TRACKS = (
    {"song": "夜空中最亮的星", "artist": "逃跑计划"},
    {"song": "平凡之路", "artist": "朴树"},
    {"song": "稻香", "artist": "周杰伦"},
    {"song": "光年之外", "artist": "G.E.M.邓紫棋"},
    {"song": "成都", "artist": "赵雷"},
)

_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _calculate(expression: str) -> int | float:
    tree = ast.parse(expression, mode="eval")

    def evaluate(node):
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 12:
                raise ValueError("指数绝对值不能超过 12")
            result = _BINARY_OPERATORS[type(node.op)](left, right)
            if not isinstance(result, (int, float)) or abs(result) > 10 ** 15:
                raise ValueError("计算结果超出允许范围")
            return result
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
            return _UNARY_OPERATORS[type(node.op)](evaluate(node.operand))
        raise ValueError("表达式仅支持数字、括号和常用算术运算符")

    return evaluate(tree)


def execute_builtin_skill(handler: str, args: dict, db):
    if handler == "calculator":
        expression = str(args.get("expression") or "").strip()
        if not expression or len(expression) > 200:
            raise ValueError("请输入不超过 200 个字符的数学表达式")
        return {"expression": expression, "result": _calculate(expression)}
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


async def execute_builtin_skill_async(handler: str, args: dict, db):
    if handler != "weather":
        return execute_builtin_skill(handler, args, db)
    city = str(args.get("city") or "Beijing").strip()
    if not city or len(city) > 80:
        raise ValueError("城市名长度必须为 1 至 80 个字符")
    url = f"https://wttr.in/{quote(city, safe='')}?format=j1"
    async with httpx.AsyncClient(timeout=12) as client:
        response = await request_public_url(
            client, "GET", url, headers={"User-Agent": "DataOutlook/1.0"}
        )
    response.raise_for_status()
    payload = response.json()
    current = (payload.get("current_condition") or [{}])[0]
    today = (payload.get("weather") or [{}])[0]
    return {
        "city": city,
        "temperature": f"{current.get('temp_C', 'N/A')}°C",
        "description": ((current.get("weatherDesc") or [{}])[0]).get("value", "N/A"),
        "humidity": f"{current.get('humidity', 'N/A')}%",
        "wind": f"{current.get('winddir16Point', 'N/A')} {current.get('windspeedKmph', 'N/A')}km/h",
        "today_high": f"{today.get('maxtempC', 'N/A')}°C",
        "today_low": f"{today.get('mintempC', 'N/A')}°C",
    }
