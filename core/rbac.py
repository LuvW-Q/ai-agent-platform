"""
RBAC依赖：基于角色的访问控制
"""
from fastapi import Depends, HTTPException
from core.security import get_current_user
from models.user import User


class _RequireRole:
    def __init__(self, *roles: str):
        self.allowed = {r.upper() for r in roles}

    def __call__(self, user: User = Depends(get_current_user)) -> User:
        if (user.role or "").upper() not in self.allowed:
            raise HTTPException(403, "权限不足，需要角色: " + ", ".join(sorted(self.allowed)))
        return user


def require_role(*roles: str) -> _RequireRole:
    return _RequireRole(*roles)
