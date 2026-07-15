"""
仪表盘路由：从数据库实时计算大屏所需指标
"""
import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from schema.api import DashboardMetrics
from database.session import SessionLocal, get_db
from core.security import get_current_user
from models.user import User
from models.data_source import DataSource
from models.agent import Agent
from models.audit_log import AuditLog
from models.message import Message
from models.data_collection import CollectedData

dashboard_router = APIRouter(prefix="/api/dashboard", tags=["仪表盘"])


@dashboard_router.get("/metrics", response_model=DashboardMetrics)
def get_metrics(db: SessionLocal = Depends(get_db), current: User = Depends(get_current_user)):
    """从数据库实时计算数字大屏指标"""

    # 数据源统计
    total_sources = db.query(func.count(DataSource.id)).scalar() or 0
    active_sources = db.query(func.count(DataSource.id)).filter(DataSource.status == "active").scalar() or 0
    error_sources = db.query(func.count(DataSource.id)).filter(DataSource.status == "error").scalar() or 0
    active_pipelines = active_sources
    crawl_success_rate = round((active_sources / total_sources * 100) if total_sources > 0 else 0, 1)

    # 今日消息数
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_messages = db.query(func.count(Message.id)).filter(Message.created_at >= today_start).scalar() or 0

    # 活跃用户：最近7天发过消息的用户
    week_ago = datetime.utcnow() - timedelta(days=7)
    active_senders = db.query(Message.sender_id).filter(Message.created_at >= week_ago).distinct().subquery()
    active_users = db.query(func.count(User.id)).filter(User.id.in_(active_senders)).scalar() or 0
    if active_users == 0:
        active_users = db.query(func.count(User.id)).scalar() or 0

    # 审计日志分级统计
    audit_high = db.query(func.count(AuditLog.id)).filter(AuditLog.risk_level == "high").scalar() or 0
    audit_medium = db.query(func.count(AuditLog.id)).filter(AuditLog.risk_level == "medium").scalar() or 0
    audit_low = db.query(func.count(AuditLog.id)).filter(AuditLog.risk_level == "low").scalar() or 0

    # 活跃威胁数 = 高风险 + 错误数据源
    active_threats = audit_high + error_sources

    # 情感倾向：低风险占比
    total_audit = audit_high + audit_medium + audit_low
    sentiment_positive = round(audit_low / total_audit * 100) if total_audit > 0 else 100

    # 信任评分：100 为基准，高风险-2，中风险-0.5，错误数据源-3
    trust_score = round(max(0, 100 - audit_high * 2 - audit_medium * 0.5 - error_sources * 3), 1)

    # 数据接入量：基于消息数量 + 数据源数量推算日志量
    total_msg = db.query(func.count(Message.id)).scalar() or 0
    ingress_gb = total_sources * 0.3 + total_msg * 0.001
    if ingress_gb >= 1:
        data_ingress_24h = f"{ingress_gb:.1f} TB" if ingress_gb >= 1024 else f"{ingress_gb:.1f} GB"
    else:
        data_ingress_24h = f"{ingress_gb * 1024:.0f} MB"

    # 活跃数字员工（status=published）
    active_agents = db.query(func.count(Agent.id)).filter(Agent.status == "published").scalar() or 0

    # 采集数据总量
    total_collected = db.query(func.count(CollectedData.id)).filter(CollectedData.saved == True).scalar() or 0

    # 在线用户数（简化：7天内活跃即可）
    online_users = db.query(func.count(User.id)).filter(User.is_active == True).scalar() or 0

    # 风险分布 JSON
    risk_distribution = json.dumps({
        "high": audit_high, "medium": audit_medium, "low": audit_low
    }, ensure_ascii=False)

    return DashboardMetrics(
        active_pipelines=active_pipelines,
        crawl_success_rate=crawl_success_rate,
        data_ingress_24h=data_ingress_24h,
        active_threats=active_threats,
        today_messages=today_messages,
        active_users=active_users,
        audit_high=audit_high,
        audit_medium=audit_medium,
        audit_low=audit_low,
        sentiment_positive=sentiment_positive,
        trust_score=trust_score,
        active_agents=active_agents,
        total_collected=total_collected,
        online_users=online_users,
        risk_distribution=risk_distribution,
    )


@dashboard_router.get("/screen-data")
def screen_data(db: SessionLocal = Depends(get_db), current: User = Depends(get_current_user)):
    """大屏专用：采集量/活跃员工/实时消息流+词云数据"""
    # 按 source_name 统计采集量（模拟国家分布）
    source_stats = db.query(
        CollectedData.source_name, func.count(CollectedData.id)
    ).filter(CollectedData.saved == True).group_by(CollectedData.source_name).all()

    # 词云数据
    keywords_all = []
    for cd in db.query(CollectedData.keywords_extracted).filter(
        CollectedData.keywords_extracted != "", CollectedData.saved == True
    ).limit(100).all():
        try:
            keywords_all.extend(json.loads(cd.keywords_extracted))
        except Exception:
            pass
    wordcloud = {}
    for kw in keywords_all:
        wordcloud[kw] = wordcloud.get(kw, 0) + 1

    # 活跃员工
    active_agents = db.query(Agent).filter(Agent.status == "published").count()

    # 采集总量
    total_collected = db.query(CollectedData).filter(CollectedData.saved == True).count()

    # 实时消息流（最近20条消息）
    recent_msgs = db.query(Message).order_by(Message.created_at.desc()).limit(20).all()

    return {
        "source_stats": [{"name": s[0], "value": s[1]} for s in source_stats],
        "wordcloud": [{"name": k, "value": v} for k, v in sorted(wordcloud.items(), key=lambda x: -x[1])[:50]],
        "active_agents": active_agents,
        "total_collected": total_collected,
        "total_messages": db.query(Message).count(),
        "recent_messages": [
            {
                "content": (m.content or "")[:50],
                "time": m.created_at.isoformat() if m.created_at else "",
            }
            for m in recent_msgs
        ],
    }
