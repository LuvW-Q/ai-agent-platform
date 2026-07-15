"""
种子数据 —— 收敛 main.py 中所有 migrate_* / seed_data 逻辑
首次启动时写入，确保各页面有内容可展示
"""
from __future__ import annotations

from database.session import SessionLocal
from models.role import Role
from models.agent import Agent
from models.user import User
from models.ai_model import AIModel
from models.skill import Skill
from models.audit_log import AuditLog
from models.sensitive_word import SensitiveWord
from models.data_collection import DataSourceConfig, CleanRule, CollectedData
from models.menu import Menu
from models.setting import Setting
from models.api_registry import ApiRegistry
from core.security import hash_password


def run_seed():
    db = SessionLocal()
    try:
        _seed_roles(db)
        _seed_users(db)
        _seed_ai_models(db)
        _seed_skills(db)
        _seed_agents(db)
        _seed_audit_logs(db)
        _seed_sensitive_words(db)
        _seed_sources_and_rules(db)
        _seed_collected_data(db)
        _seed_menus(db)
        _seed_api_registries(db)
        _seed_settings(db)
        db.commit()
        print("[seed] 种子数据写入完成")
    except Exception as e:
        db.rollback()
        print(f"[seed] 种子数据写入失败: {e}")
    finally:
        db.close()


def _seed_roles(db: SessionLocal):
    if db.query(Role).first():
        return
    for r in [
        Role(name="超级管理员", code="ROOT", description="全系统最高权限，可管理所有模块"),
        Role(name="安全审计员", code="AUDIT", description="负责审计日志查看与风险分析"),
        Role(name="运维工程师", code="OPS", description="数据源管理与管道运维"),
        Role(name="普通用户", code="USER", description="可使用对话、问数、数字员工等功能"),
        Role(name="访客", code="GUEST", description="仅可查看公开大屏"),
    ]:
        db.add(r)
    print("[seed] 角色写入完成")


def _seed_users(db: SessionLocal):
    if db.query(User).filter(User.username == "admin").first():
        return
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
    print("[seed] 用户写入完成")


def _seed_ai_models(db: SessionLocal):
    existing = {m.model_name for m in db.query(AIModel).all()}
    added = 0
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
        AIModel(name="DALL-E 3", provider="OpenAI", api_key="sk-placeholder",
                model_name="dall-e-3", endpoint="https://api.openai.com/v1",
                context_length=4096, model_type="image", is_default=False, is_active=True),
        AIModel(name="Stable Diffusion", provider="StabilityAI", api_key="sk-placeholder",
                model_name="stable-diffusion-xl", endpoint="https://api.stability.ai/v1",
                context_length=4096, model_type="image", is_default=False, is_active=True),
    ]:
        if m.model_name not in existing:
            db.add(m)
            added += 1
    if added:
        print(f"[seed] AI 模型写入完成（新增 {added} 条）")
    else:
        print("[seed] AI 模型无变更")


def _seed_skills(db: SessionLocal):
    if db.query(Skill).first():
        return
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
    print("[seed] 技能写入完成")


def _seed_agents(db: SessionLocal):
    if db.query(Agent).first():
        return
    # 约定 model_id: 1 = gpt-4o, 2 = deepseek-chat, 4 = claude-3.5-sonnet
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
        Agent(name="天气助手", base_model="gpt-4o", model_id=1,
              persona_prompt="你是天气助手，可以查询全球任意城市的实时天气情况。",
              skill_bindings="Weather_Query", skill_ids="3",
              status="published", description="查询实时天气信息"),
        Agent(name="代码助手", base_model="gpt-4o", model_id=1,
              persona_prompt="你是一位资深程序员，擅长用 Python/JavaScript/Java 等语言编写高质量的代码。回答简洁，附有代码示例。",
              skill_bindings="Code_Helper", skill_ids="1,2",
              status="published", description="编写和调试代码"),
    ]:
        db.add(ag)
    print("[seed] 数字员工写入完成")


def _seed_audit_logs(db: SessionLocal):
    if db.query(AuditLog).first():
        return
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
    print("[seed] 审计日志写入完成")


def _seed_sensitive_words(db: SessionLocal):
    if db.query(SensitiveWord).first():
        return
    for w in [
        SensitiveWord(word="密码", replacement="***", action="block"),
        SensitiveWord(word="身份证", replacement="***", action="block"),
        SensitiveWord(word="银行卡", replacement="***", action="block"),
        SensitiveWord(word="fuck", replacement="****", action="replace"),
        SensitiveWord(word="shit", replacement="****", action="replace"),
    ]:
        db.add(w)
    print("[seed] 敏感词写入完成")


def _seed_sources_and_rules(db: SessionLocal):
    if not db.query(DataSourceConfig).first():
        for src in [
            DataSourceConfig(name="百度新闻搜索", url="https://news.baidu.com/ns?word={keyword}&tn=news",
                             method="GET", parse_type="selector", parse_rule=".result",
                             headers='{"User-Agent":"Mozilla/5.0"}', template="baidu"),
            DataSourceConfig(name="36氪RSS", url="https://36kr.com/feed",
                             method="GET", parse_type="crawl4ai", parse_rule="",
                             headers='{"User-Agent":"Mozilla/5.0"}', template="rss"),
            DataSourceConfig(name="知乎热门", url="https://www.zhihu.com/api/v3/feed/topstory?limit=20",
                             method="GET", parse_type="selector", parse_rule=".TopstoryItem",
                             headers='{"User-Agent":"Mozilla/5.0"}', template="custom"),
        ]:
            db.add(src)
        print("[seed] 数据采集源写入完成")
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
        print("[seed] 清洗规则写入完成")


def _seed_menus(db: SessionLocal):
    """初始化菜单表，按角色分权限（增量写入：已有菜单不覆盖）"""
    existing_paths = {m.path for m in db.query(Menu).all()}

    # 用户侧可见（普通用户 /USER）
    user_menus = [
        Menu(name="智能对话", icon="forum", path="/de", sort_order=1, role_codes="USER,AUDIT,OPS,ROOT"),
        Menu(name="智能问数", icon="terminal", path="/query", sort_order=2, role_codes="USER,AUDIT,OPS,ROOT"),
        Menu(name="数字员工", icon="precision_manufacturing", path="/agent-management", sort_order=3, role_codes="USER,AUDIT,OPS,ROOT"),
        Menu(name="创意工坊", icon="palette", path="/creative", sort_order=14, role_codes="ROOT,OPS,USER"),
    ]
    # 管理侧可见（AUDIT / OPS / ROOT）
    admin_menus = [
        Menu(name="控制台", icon="database", path="/dashboard", sort_order=10, role_codes="ROOT,AUDIT,OPS"),
        Menu(name="数字大屏", icon="monitoring", path="/screen", sort_order=11, role_codes="ROOT,AUDIT,OPS,USER,GUEST"),
        Menu(name="模型管理", icon="model_training", path="/models", sort_order=12, role_codes="ROOT,OPS"),
        Menu(name="技能管理", icon="extension", path="/skills", sort_order=13, role_codes="ROOT,OPS"),
        Menu(name="员工编排", icon="smart_toy", path="/agents", sort_order=14, role_codes="ROOT,OPS"),
        Menu(name="工作流", icon="account_tree", path="/workflows", sort_order=15, role_codes="ROOT,OPS"),
        Menu(name="RAG 管理", icon="book_4", path="/rag", sort_order=16, role_codes="ROOT,OPS"),
        Menu(name="权限管理", icon="admin_panel_settings", path="/permissions", sort_order=17, role_codes="ROOT"),
        Menu(name="审计管理", icon="security", path="/audit", sort_order=18, role_codes="ROOT,AUDIT"),
        Menu(name="智能审计", icon="gavel", path="/smart-audit", sort_order=19, role_codes="ROOT,AUDIT"),
        Menu(name="聊天管理", icon="chat_bubble", path="/chat-management", sort_order=20, role_codes="ROOT,AUDIT"),
        Menu(name="数据采集", icon="cloud_download", path="/data-collection", sort_order=21, role_codes="ROOT,OPS"),
        Menu(name="消息中心", icon="chat", path="/messages", sort_order=22, role_codes="ROOT,AUDIT,OPS,USER"),
        Menu(name="IM 控制台", icon="forum", path="/im", sort_order=23, role_codes="ROOT,AUDIT,OPS,USER"),
    ]
    common_menus = [
        Menu(name="系统设置", icon="settings", path="/settings", sort_order=99, role_codes="ROOT,AUDIT,OPS,USER"),
    ]
    # 接口管理（B线）— 接口注册表 + 接口型数字员工
    api_menus = [
        Menu(name="接口管理", icon="api", path="/api-registry", sort_order=24, role_codes="ROOT,OPS"),
    ]
    added = 0
    for m in user_menus + admin_menus + common_menus + api_menus:
        if m.path not in existing_paths:
            db.add(m)
            added += 1
    if added:
        print(f"[seed] 菜单写入完成（新增 {added} 条）")
    else:
        print("[seed] 菜单无变更")


def _seed_api_registries(db: SessionLocal):
    """初始化接口注册表样本：让接口管理页一启动就有数据可展示"""
    if db.query(ApiRegistry).first():
        return
    for api in [
        ApiRegistry(name="高德地图地理编码", code="gaode_geocode",
                    base_url="https://restapi.amap.com/v3/geocode/geo?{params}",
                    method="GET", headers='{"Content-Type":"application/json"}',
                    response_path="geocodes",
                    auth_type="query", auth_key="",
                    description="将地址转为经纬度坐标"),
        ApiRegistry(name="天气查询（wttr.in）", code="wttr",
                    base_url="https://wttr.in/{params}?format=j1",
                    method="GET", headers='{"User-Agent":"Mozilla/5.0"}',
                    response_path="current_condition",
                    auth_type="none", auth_key="",
                    description="全球城市天气快速查询"),
        ApiRegistry(name="GitHub 用户信息", code="github_user",
                    base_url="https://api.github.com/users/{params}",
                    method="GET", headers='{"Accept":"application/vnd.github+json"}',
                    response_path="name",
                    auth_type="none", auth_key="",
                    description="根据 GitHub 用户名拉取公开资料"),
    ]:
        db.add(api)
    print("[seed] 接口注册表样本写入完成")


def _seed_settings(db: SessionLocal):
    """初始化系统设置默认值"""
    if db.query(Setting).first():
        return
    defaults = [
        Setting(key="system_name", value="智能数据瞭望系统", description="系统名称"),
        Setting(key="log_retention_days", value="30", description="日志保留天数"),
        Setting(key="default_model_id", value="1", description="默认模型ID"),
        Setting(key="sensitive_threshold", value="0.6", description="敏感词匹配阈值"),
        Setting(key="voice_enabled", value="true", description="语音播报开关"),
        Setting(key="face_recognition_enabled", value="false", description="人脸识别开关"),
        Setting(key="collection_rate_limit", value="10", description="采集频率限制(次/分钟)"),
    ]
    for s in defaults:
        db.add(s)
    print("[seed] 系统设置写入完成")


def _seed_collected_data(db: SessionLocal):
    """补充采集数据样本，让仪表盘 total_collected 有数据可展示"""
    if db.query(CollectedData).filter(CollectedData.saved == True).first():
        return
    for i, d in enumerate([
        CollectedData(source_name="百度新闻搜索", keyword="人工智能", title="人工智能技术发展现状与未来趋势",
                      url="https://example.com/ai-trends", summary="人工智能在各行业加速渗透，预计2026年规模突破万亿",
                      sentiment="positive", saved=True, source_id=1),
        CollectedData(source_name="新浪新闻搜索", keyword="数据治理", title="数据治理成为企业数字化转型核心环节",
                      url="https://example.com/data-governance", summary="数据治理体系逐步完善，提升企业数据资产价值",
                      sentiment="positive", saved=True, source_id=2),
        CollectedData(source_name="必应新闻搜索", keyword="信息安全", title="全球信息安全事件回顾：风险与应对",
                      url="https://example.com/security", summary="数据泄露事件频发，企业强化安全防御体系",
                      sentiment="negative", saved=True, source_id=3),
        CollectedData(source_name="百度新闻搜索", keyword="联邦学习", title="联邦学习在隐私计算中的应用",
                      url="https://example.com/federated-learning", summary="联邦学习推动数据要素流通与隐私保护平衡",
                      sentiment="neutral", saved=True, source_id=1),
        CollectedData(source_name="新浪新闻搜索", keyword="智慧城市", title="智慧城市建设进入新阶段",
                      url="https://example.com/smart-city", summary="数据驱动城市治理，迈向精细化运营",
                      sentiment="positive", saved=True, source_id=2),
    ], start=1):
        if not db.query(CollectedData).filter(CollectedData.url == d.url).first():
            db.add(d)
    print("[seed] 采集数据样本写入完成")
