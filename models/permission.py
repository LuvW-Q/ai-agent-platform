"""功能点与角色-功能-资源权限绑定模型。"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint

from database.session import Base


class FunctionPoint(Base):
    __tablename__ = "function_points"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    code = Column(String(80), unique=True, nullable=False, index=True)
    description = Column(Text, default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class RoleFunctionPermission(Base):
    __tablename__ = "role_function_permissions"
    __table_args__ = (
        UniqueConstraint("role_code", "function_code", "resource", name="uq_role_function_resource"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    role_code = Column(String(50), nullable=False, index=True)
    function_code = Column(String(80), nullable=False, index=True)
    resource = Column(String(255), nullable=False)
    actions = Column(String(255), default="查看")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
