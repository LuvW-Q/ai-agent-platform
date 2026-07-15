"""
应用入口
启动 FastAPI，注册所有路由，初始化数据库，种子数据
"""
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from database.session import Base, engine, SessionLocal
from controller.auth_controller import auth_router
from controller.dashboard_controller import dashboard_router
from controller.data_controller import data_router
from controller.agent_controller import agent_router
from controller.im_controller import im_router
from controller.audit_controller import audit_router
from controller.permission_controller import permission_router
from controller.query_controller import query_router
from controller.friend_controller import friend_router
from controller.group_controller import group_router
from controller.ws_controller import ws_router
from controller.model_controller import model_router
from controller.skill_controller import skill_router
from controller.de_controller import de_router
from controller.page_controller import page_router
from controller.kb_controller import kb_router
from controller.wf_controller import wf_router
from controller.dc_controller import dc_router
from controller.smart_audit_controller import smart_audit as smart_audit_router

# 导入新模型，确保建表时创建
from models.ai_model import AIModel
from models.skill import Skill
from models.skill_call_log import SkillCallLog
from models.sensitive_word import SensitiveWord
from models.de_message import DEMessage
from models.knowledge_base import KnowledgeBase, KBDocument
from models.workflow import Workflow, WorkflowNode, WorkflowEdge
from models.data_collection import DataSourceConfig, CleanRule, CollectedData

# 建表
Base.metadata.create_all(bind=engine)

# 数据库迁移：为messages表添加新列（SQLite不支持IF NOT EXISTS语法，用try/except）
def migrate_messages_table():
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    columns = [c["name"] for c in inspector.get_columns("messages")]
    new_cols = {
        "msg_id": "VARCHAR(64) DEFAULT ''",
        "status": "VARCHAR(20) DEFAULT 'sent'",
        "file_url": "VARCHAR(500) DEFAULT ''",
        "file_name": "VARCHAR(255) DEFAULT ''",
        "file_size": "INTEGER DEFAULT 0",
        "recall_at": "DATETIME",
    }
    with engine.connect() as conn:
        for col, col_type in new_cols.items():
            if col not in columns:
                try:
                    conn.execute(text(f"ALTER TABLE messages ADD COLUMN {col} {col_type}"))
                    conn.commit()
                    print(f"[migrate] Added column {col} to messages table")
                except Exception as e:
                    print(f"[migrate] Column {col} already exists or error: {e}")

migrate_messages_table()


def migrate_agents_table():
    """为agents表添加新列"""
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    columns = [c["name"] for c in inspector.get_columns("agents")]
    new_cols = {
        "avatar": "VARCHAR(500) DEFAULT ''",
        "model_id": "INTEGER",
        "skill_ids": "VARCHAR(500) DEFAULT ''",
        "fallback_message": "VARCHAR(500) DEFAULT '系统繁忙，请稍后再试'",
    }
    with engine.connect() as conn:
        for col, col_type in new_cols.items():
            if col not in columns:
                try:
                    conn.execute(text(f"ALTER TABLE agents ADD COLUMN {col} {col_type}"))
                    conn.commit()
                    print(f"[migrate] Added column {col} to agents table")
                except Exception as e:
                    print(f"[migrate] Column {col} already exists or error: {e}")

migrate_agents_table()


def migrate_de_messages_table():
    """创建de_messages表（如果不存在）"""
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    if "de_messages" not in inspector.get_table_names():
        try:
            DEMessage.__table__.create(bind=engine)
            print("[migrate] Created de_messages table")
        except Exception as e:
            print(f"[migrate] de_messages table creation error: {e}")


def migrate_agent_model_binding():
    """按base_model名称匹配，自动修正Agent的model_id绑定"""
    db = SessionLocal()
    try:
        from models.agent import Agent
        from models.ai_model import AIModel
        models = {m.model_name: m.id for m in db.query(AIModel).all()}
        # base_model名称 → model_name 映射
        name_map = {
            "gpt-4o": "gpt-4o",
            "deepseek-v3": "deepseek-chat",
            "claude-3.5-sonnet": "claude-3-5-sonnet-20241022",
        }
        updated = 0
        # 修复所有Agent（不仅是model_id为None的）
        for agent in db.query(Agent).all():
            target_model_name = name_map.get(agent.base_model, agent.base_model)
            expected_model_id = models.get(target_model_name)
            if expected_model_id and agent.model_id != expected_model_id:
                agent.model_id = expected_model_id
                updated += 1
        if updated:
            db.commit()
            print(f"[migrate] Corrected model binding for {updated} agents")
    except Exception as e:
        db.rollback()
        print(f"[migrate] Agent model binding failed: {e}")
    finally:
        db.close()


migrate_de_messages_table()
migrate_agent_model_binding()


def seed_data():
    """首次启动时写入种子数据，让页面有内容可展示"""
    db = SessionLocal()
    try:
        from models.role import Role
        from models.data_source import DataSource
        from models.agent import Agent
        from models.audit_log import AuditLog
        from models.user import User
        from models.ai_model import AIModel
        from models.skill import Skill
        from models.sensitive_word import SensitiveWord
        from core.security import hash_password

        # 角色
        if not db.query(Role).first():
            for r in [
                Role(name="超级管理员", code="ROOT", description="全系统最高权限，可管理所有模块"),
                Role(name="安全审计员", code="AUDIT", description="负责审计日志查看与风险分析"),
                Role(name="运维工程师", code="OPS", description="数据源管理与管道运维"),
                Role(name="普通用户", code="USER", description="只读访问大屏和消息"),
                Role(name="访客", code="GUEST", description="仅可查看公开大屏"),
            ]:
                db.add(r)

        # 数据源
        if not db.query(DataSource).first():
            for ds in [
                DataSource(resource_id="FinNews_Crawler_01", name="金融新闻爬虫-01", status="active", frequency="5s / request", endpoint="api.market-intel.v3", protocol="http"),
                DataSource(resource_id="Global_Stock_DB", name="全球股票数据库", status="syncing", frequency="Real-time", endpoint="psql://primary-01", protocol="psql"),
                DataSource(resource_id="Logistics_Feed_v2", name="物流数据源-v2", status="idle", frequency="Event-driven", endpoint="webhook://external-7", protocol="webhook"),
                DataSource(resource_id="Alpha_Sentiment_Proxy", name="情感分析代理", status="error", frequency="10m / poll", endpoint="tls://10.0.42.11", protocol="tls"),
                DataSource(resource_id="Gov_Open_Data_03", name="政务开放数据-03", status="active", frequency="1h / batch", endpoint="api.gov-open.cn/v2", protocol="http"),
                DataSource(resource_id="Social_Media_Stream", name="社交媒体流", status="active", frequency="Real-time", endpoint="wss://stream.social-api.com", protocol="ws"),
            ]:
                db.add(ds)

        # 数字员工
        if not db.query(Agent).first():
            for ag in [
                Agent(name="金融数据分析师", base_model="gpt-4o", model_id=1,
                      persona_prompt="你是专业的金融数据分析师，擅长解读市场趋势和财务报表。",
                      skill_bindings="SQL_Executor,Financial_Analyzer", skill_ids="1,2,3",
                      status="published", description="自动分析金融数据并生成日报"),
                Agent(name="舆情监控员", base_model="deepseek-v3", model_id=2,
                      persona_prompt="你是舆情监控专员，负责实时监测社交媒体情感倾向。",
                      skill_bindings="Social_Monitor,Sentiment_Analyzer", skill_ids="1,2,3",
                      status="published", description="7x24小时监控全网舆情动态"),
                Agent(name="审计报告生成器", base_model="claude-3.5-sonnet", model_id=4,
                      persona_prompt="你是审计报告专家，根据审计日志自动生成合规报告。",
                      skill_bindings="Audit_Reader,Report_Generator", skill_ids="3,4",
                      status="draft", description="自动汇总审计日志生成周报"),
                Agent(name="运维巡检机器人", base_model="gpt-4o", model_id=1,
                      persona_prompt="你是运维巡检专家，负责检查系统健康状态和数据管道。",
                      skill_bindings="System_Checker,Alert_Sender", skill_ids="1,2,3",
                      status="published", description="定时巡检并推送告警"),
            ]:
                db.add(ag)

        # 审计日志
        if not db.query(AuditLog).first():
            for log in [
                AuditLog(event_type="Security Alert", risk_level="high", description="检测到异常大流量数据导出行为：员工 ID_9921", operator="system"),
                AuditLog(event_type="Audit Warning", risk_level="medium", description="审计流程中断：节点 [数据脱敏] 响应超时", operator="audit_service"),
                AuditLog(event_type="System Notification", risk_level="low", description="全域采集节点更新完成，接入率 99.8%", operator="system"),
                AuditLog(event_type="Access Violation", risk_level="high", description="越权访问尝试：外部 IP 182.16.0.45 探测管理后台", operator="firewall"),
                AuditLog(event_type="Data Sync", risk_level="low", description="数据源 Global_Stock_DB 完成全量同步，共 2.1M 条记录", operator="ops_agent"),
                AuditLog(event_type="Config Change", risk_level="medium", description="清洗规则 [Regex_Filter_v3] 已更新并发布到生产环境", operator="admin"),
                AuditLog(event_type="Login Alert", risk_level="medium", description="非工作时间管理员登录：IP 10.0.1.32 凌晨 02:14", operator="auth_service"),
                AuditLog(event_type="Agent Deploy", risk_level="low", description="数字员工 [金融数据分析师] 已发布上线", operator="admin"),
            ]:
                db.add(log)

        # 默认管理员
        if not db.query(User).filter(User.username == "admin").first():
            admin = User(
                username="admin",
                password_hash=hash_password("admin123"),
                nickname="Admin_Core",
                email="admin@dataoutlook.cn",
                role="ROOT",
                avatar="",
                signature="系统默认管理员",
                is_active=True,
            )
            db.add(admin)

        # IM演示用户
        for u in [
            ("demo", "demo123456", "Demo用户", "demo@dataoutlook.cn", "USER"),
            ("zhang_san", "zhang123456", "张三", "zhang_san@dataoutlook.cn", "USER"),
            ("li_si", "li123456", "李四", "li_si@dataoutlook.cn", "AUDIT"),
        ]:
            if not db.query(User).filter(User.username == u[0]).first():
                db.add(User(
                    username=u[0], password_hash=hash_password(u[1]),
                    nickname=u[2], email=u[3], role=u[4], avatar="", signature="", is_active=True,
                ))

        # AI模型种子数据
        if not db.query(AIModel).first():
            for m in [
                AIModel(name="GPT-4o", provider="OpenAI", api_key="sk-placeholder", model_name="gpt-4o",
                        endpoint="https://api.openai.com/v1", context_length=128000, model_type="chat",
                        is_default=True, is_active=True, temperature=0.7, max_tokens=4096),
                AIModel(name="DeepSeek-V3", provider="DeepSeek", api_key="sk-placeholder", model_name="deepseek-chat",
                        endpoint="https://api.deepseek.com/v1", context_length=64000, model_type="chat",
                        is_default=False, is_active=True, temperature=0.7, max_tokens=4096),
                AIModel(name="text-embedding-3-small", provider="OpenAI", api_key="sk-placeholder",
                        model_name="text-embedding-3-small", endpoint="https://api.openai.com/v1",
                        context_length=8191, model_type="embedding", is_default=False, is_active=True),
                AIModel(name="Claude-3.5-Sonnet", provider="Anthropic", api_key="sk-placeholder",
                        model_name="claude-3-5-sonnet-20241022", endpoint="https://api.anthropic.com/v1",
                        context_length=200000, model_type="chat", is_default=False, is_active=True,
                        temperature=0.7, max_tokens=4096),
            ]:
                db.add(m)

        # 技能种子数据
        if not db.query(Skill).first():
            for s in [
                Skill(name="获取当前时间", skill_type="function_call",
                      description="返回当前服务器时间和日期",
                      config="def execute(args):\n    from datetime import datetime\n    return {'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
                      parameters='{"type": "object", "properties": {}}',
                      status="active"),
                Skill(name="数据计算器", skill_type="function_call",
                      description="执行数学表达式计算",
                      config="def execute(args):\n    expr = args.get('expression', '')\n    import math\n    try:\n        result = eval(expr, {'__builtins__': {}}, {'math': math})\n        return {'result': str(result)}\n    except Exception as e:\n        return {'error': f'计算错误: {e}'}\n",
                      parameters='{"type": "object", "properties": {"expression": {"type": "string", "description": "数学表达式"}}, "required": ["expression"]}',
                      status="active"),
                Skill(name="天气查询", skill_type="function_call",
                      description="查询指定城市的实时天气信息（温度、湿度、风向等）",
                      config="""def execute(args):
    city = args.get('city', 'Beijing')
    import urllib.request, json
    try:
        url = f'https://wttr.in/{city}?format=j1'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        current = data.get('current_condition', [{}])[0]
        weather = data.get('weather', [{}])[0]
        temp_c = current.get('temp_C', 'N/A')
        humidity = current.get('humidity', 'N/A')
        desc = current.get('weatherDesc', [{}])[0].get('value', 'N/A')
        wind = current.get('winddir16Point', 'N/A') + ' ' + current.get('windspeedKmph', 'N/A') + 'km/h'
        max_temp = weather.get('maxtempC', 'N/A')
        min_temp = weather.get('mintempC', 'N/A')
        return {
            'city': city,
            'temperature': f'{temp_c}°C',
            'description': desc,
            'humidity': f'{humidity}%',
            'wind': wind,
            'today_high': f'{max_temp}°C',
            'today_low': f'{min_temp}°C',
        }
    except Exception as e:
        return {'error': f'天气查询失败: {str(e)}'}
""",
                      parameters='{"type": "object", "properties": {"city": {"type": "string", "description": "城市名(英文)"}}, "required": ["city"]}',
                      status="active"),
                Skill(name="审计报告模板", skill_type="prompt",
                      description="生成标准审计报告的提示词模板",
                      config="你是一位专业的审计报告专家。请根据以下审计日志信息，生成一份结构化的审计报告，包括：\n1. 审计概况\n2. 风险事件汇总\n3. 高风险事项\n4. 建议措施\n\n审计日志：{logs}\n请用中文输出报告。",
                      parameters='{"type": "object", "properties": {"logs": {"type": "string", "description": "审计日志内容"}}, "required": ["logs"]}',
                      status="active"),
            ]:
                db.add(s)

        # 敏感词种子数据
        if not db.query(SensitiveWord).first():
            for w in [
                SensitiveWord(word="密码", replacement="***", action="block"),
                SensitiveWord(word="身份证", replacement="***", action="block"),
                SensitiveWord(word="银行卡", replacement="***", action="block"),
                SensitiveWord(word="fuck", replacement="****", action="replace"),
                SensitiveWord(word="shit", replacement="****", action="replace"),
            ]:
                db.add(w)

        # 数据采集种子数据：默认新闻源和清洗规则
        from models.data_collection import DataSourceConfig, CleanRule
        if not db.query(DataSourceConfig).first():
            for src in [
                DataSourceConfig(name="百度新闻搜索", url="https://news.baidu.com/ns?word={keyword}&tn=news",
                                 method="GET", parse_type="selector", parse_rule=".result",
                                 headers='{"User-Agent":"Mozilla/5.0"}'),
                DataSourceConfig(name="新浪新闻搜索", url="https://search.sina.com.cn/news?q={keyword}",
                                 method="GET", parse_type="selector", parse_rule=".box-result",
                                 headers='{"User-Agent":"Mozilla/5.0"}'),
                DataSourceConfig(name="必应新闻搜索", url="https://www.bing.com/news/search?q={keyword}",
                                 method="GET", parse_type="crawl4ai", parse_rule="",
                                 headers='{"User-Agent":"Mozilla/5.0"}'),
                DataSourceConfig(name="搜狗新闻", url="https://news.sogou.com/news?query={keyword}",
                                 method="GET", parse_type="selector", parse_rule=".news-item",
                                 headers='{"User-Agent":"Mozilla/5.0"}'),
            ]:
                db.add(src)
        if not db.query(CleanRule).first():
            for rule in [
                CleanRule(name="去除HTML标签", rule_type="remove_html", config="{}"),
                CleanRule(name="去除多余空白", rule_type="trim_whitespace", config="{}"),
                CleanRule(name="去除空数据", rule_type="remove_empty", config="{}"),
                CleanRule(name="去重", rule_type="deduplicate", config="{}"),
                CleanRule(name="正则过滤", rule_type="regex_replace",
                          config='{"pattern":"[\\\\u4e00-\\\\u9fa5]+","replacement":""}'),
            ]:
                db.add(rule)

        db.commit()
        print("[seed] 种子数据写入完成")
    except Exception as e:
        db.rollback()
        print(f"[seed] 种子数据写入失败: {e}")
    finally:
        db.close()


# 写入种子数据
seed_data()

app = FastAPI(title="智能数据瞭望系统", version="1.0.0")

# CORS中间件：允许跨域请求
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def disable_static_cache(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# 静态资源
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# API路由
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(data_router)
app.include_router(agent_router)
app.include_router(im_router)
app.include_router(audit_router)
app.include_router(permission_router)
app.include_router(query_router)
app.include_router(friend_router)
app.include_router(group_router)
app.include_router(model_router)
app.include_router(skill_router)
app.include_router(de_router)
app.include_router(kb_router)
app.include_router(wf_router)
app.include_router(dc_router)
app.include_router(smart_audit_router)

# WebSocket路由
app.include_router(ws_router)

# 页面路由
app.include_router(page_router)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
