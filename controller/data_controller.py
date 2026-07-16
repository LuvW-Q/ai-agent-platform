"""
数据源管理路由
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from database.session import SessionLocal, get_db
from schema.api import DataSourceOut, DataSourceCreate
from dao.base_dao import list_data_sources, create_data_source, delete_data_source, get_data_source, log_action
from models.data_source import DataSource
from core.security import get_current_user
from core.rbac import require_role
from models.user import User

data_router = APIRouter(prefix="/api/data-sources", tags=["数据源管理"])


class DataSourceUpdateIn(BaseModel):
    name: str | None = None
    resource_id: str | None = None
    frequency: str | None = None
    endpoint: str | None = None
    protocol: str | None = None
    status: str | None = None


@data_router.get("", response_model=list[DataSourceOut])
def list_all(db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    return list_data_sources(db)


@data_router.post("", response_model=DataSourceOut, status_code=201)
def create(body: DataSourceCreate, db: SessionLocal = Depends(get_db),
           user: User = Depends(require_role("ROOT", "OPS", "ADMIN"))):
    ds = DataSource(
        resource_id=body.resource_id,
        name=body.name,
        frequency=body.frequency,
        endpoint=body.endpoint,
        protocol=body.protocol,
        status="idle",
    )
    saved = create_data_source(ds, db)
    if not saved:
        raise HTTPException(status_code=500, detail="创建失败")
    log_action("data_source_create", f"创建数据源: {body.name}", user.username, db)
    return saved


@data_router.put("/{ds_id}", response_model=DataSourceOut)
def update(ds_id: int, body: DataSourceUpdateIn, db: SessionLocal = Depends(get_db),
           user: User = Depends(require_role("ROOT", "OPS", "ADMIN"))):
    ds = get_data_source(ds_id, db)
    if not ds:
        raise HTTPException(404, "数据源不存在")
    for k, v in body.model_dump().items():
        if v is not None:
            setattr(ds, k, v)
    db.commit()
    db.refresh(ds)
    log_action("data_source_update", f"更新数据源: {ds.name}", user.username, db)
    return ds


@data_router.delete("/{ds_id}")
def delete(ds_id: int, db: SessionLocal = Depends(get_db),
           user: User = Depends(require_role("ROOT", "OPS", "ADMIN"))):
    ok = delete_data_source(ds_id, db)
    if ok:
        log_action("data_source_delete", f"删除数据源 ID: {ds_id}", user.username, db)
    return {"deleted": ok}
