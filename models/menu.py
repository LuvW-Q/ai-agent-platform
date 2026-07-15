"""
菜单模型：基于角色的动态菜单管理
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Boolean
from database.session import Base


class Menu(Base):
    __tablename__ = "menus"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False)             # 菜单显示名
    icon = Column(String(50), default="")                  # Material Symbol 图标名
    path = Column(String(100), nullable=False)             # 前端路由
    parent_id = Column(Integer, default=0)                 # 父菜单 ID, 0 为顶级
    sort_order = Column(Integer, default=0)                # 排序序号
    role_codes = Column(String(200), default="")           # 可见角色代码串，逗号分隔，空=全部
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
