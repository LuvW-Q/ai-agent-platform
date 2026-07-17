"""需要登录态的上传文件读取接口。"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from core.security import get_current_user
from core.upload_security import UPLOAD_ROOT, IMAGE_EXTENSIONS, media_type_for_path
from database.session import SessionLocal, get_db
from models.group_member import GroupMember
from models.message import Message
from models.user import User


upload_router = APIRouter(prefix="/api/uploads", tags=["上传文件"])


def _can_read_message_upload(relative: Path, user: User, db: SessionLocal) -> bool:
    parts = relative.parts
    if len(parts) < 3:
        return False
    try:
        uploader_id = int(parts[1])
    except (TypeError, ValueError):
        return False
    if user.id == uploader_id or (user.role or "").upper() in {"ROOT", "AUDIT", "ADMIN"}:
        return True

    file_url = f"/api/uploads/{relative.as_posix()}"
    messages = db.query(Message).filter(
        Message.file_url == file_url,
        Message.sender_id == uploader_id,
    ).all()
    for message in messages:
        if message.sender_id == user.id or message.receiver_id == user.id:
            return True
        if message.group_id is not None:
            membership = db.query(GroupMember).filter(
                GroupMember.group_id == message.group_id,
                GroupMember.user_id == user.id,
            ).first()
            if membership is not None:
                return True
    return False


@upload_router.get("/{file_path:path}")
def get_uploaded_file(file_path: str, db: SessionLocal = Depends(get_db),
                      user: User = Depends(get_current_user)):
    relative = Path(file_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise HTTPException(400, "文件路径无效")
    target = (UPLOAD_ROOT / relative).resolve()
    try:
        target.relative_to(UPLOAD_ROOT)
    except ValueError:
        raise HTTPException(400, "文件路径无效")
    if not target.is_file():
        raise HTTPException(404, "文件不存在")

    category = relative.parts[0] if relative.parts else ""
    if category == "messages" and not _can_read_message_upload(relative, user, db):
        raise HTTPException(403, "无权访问该消息附件")
    if category not in {"avatars", "messages", "kb"}:
        raise HTTPException(403, "无权访问该上传文件")

    disposition = "inline" if target.suffix.lower() in IMAGE_EXTENSIONS else "attachment"
    response = FileResponse(
        target,
        media_type=media_type_for_path(target),
        filename=None if disposition == "inline" else target.name,
    )
    response.headers["Content-Disposition"] = f'{disposition}; filename="{target.name}"'
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, max-age=300"
    return response
