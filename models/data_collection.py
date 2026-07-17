"""
数据采集系统模型：数据源配置、清洗规则、采集结果、数据仓库
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey
from database.session import Base


class DataSourceConfig(Base):
    """数据源配置"""
    __tablename__ = "ds_configs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    url = Column(String(1000), nullable=False)
    method = Column(String(10), default="GET")
    headers = Column(Text, default="{}")           # JSON headers
    body = Column(Text, default="")                 # POST body
    parse_type = Column(String(20), default="selector")  # selector/xpath/rss/crawl4ai
    parse_rule = Column(Text, default="")           # CSS选择器 / XPath / 空=crawl4ai全文
    template = Column(String(50), default="")       # baidu/rss/custom
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class CleanRule(Base):
    """清洗规则"""
    __tablename__ = "clean_rules"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    rule_type = Column(String(30), nullable=False)  # remove_html/trim_whitespace/remove_empty/format_date/regex_replace/deduplicate
    config = Column(Text, default="{}")             # JSON: {"pattern":"...", "replacement":"..."}
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class CollectedData(Base):
    """采集结果 -> 数据仓库"""
    __tablename__ = "collected_data"
    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, ForeignKey("ds_configs.id"))
    source_name = Column(String(200), default="")
    keyword = Column(String(200), default="")
    title = Column(String(500), default="")
    url = Column(String(1000), default="")
    content = Column(Text, default="")
    summary = Column(Text, default="")              # AI 摘要
    keywords_extracted = Column(Text, default="")   # 提取的关键字 JSON
    entities = Column(Text, default="")             # 实体：时间/地点/人物/事件 JSON
    sentiment = Column(String(20), default="neutral")  # positive/neutral/negative
    saved = Column(Boolean, default=False)          # 是否保存到仓库
    deep_collected = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
