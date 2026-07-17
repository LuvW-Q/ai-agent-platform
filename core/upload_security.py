"""上传文件的分块保存、大小限制和真实文件类型校验。"""
from __future__ import annotations

import os
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile


UPLOAD_ROOT = (Path(__file__).resolve().parents[1] / "uploads").resolve()
CHUNK_SIZE = 64 * 1024

IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"})
MESSAGE_EXTENSIONS = frozenset({
    *IMAGE_EXTENSIONS, ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt",
    ".pptx", ".txt", ".csv", ".md", ".zip", ".rar", ".mp3", ".mp4",
    ".wav", ".avi", ".mov",
})
KB_EXTENSIONS = frozenset({".txt", ".md", ".csv", ".json", ".pdf", ".docx"})

_MEDIA_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp",
    ".pdf": "application/pdf", ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain; charset=utf-8", ".csv": "text/csv; charset=utf-8",
    ".md": "text/markdown; charset=utf-8", ".json": "application/json",
    ".zip": "application/zip", ".rar": "application/vnd.rar",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".mp4": "video/mp4",
    ".avi": "video/x-msvideo", ".mov": "video/quicktime",
}


@dataclass(frozen=True)
class SavedUpload:
    absolute_path: Path
    relative_path: str
    original_name: str
    extension: str
    size: int
    media_type: str

    @property
    def is_image(self) -> bool:
        return self.extension in IMAGE_EXTENSIONS


def media_type_for_path(path: Path) -> str:
    return _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


def validate_message_file_url(file_url: str, user_id: int) -> None:
    """发送消息时校验附件 URL 确属当前用户上传目录。"""
    if not file_url:
        return
    prefix = "/api/uploads/"
    if not file_url.startswith(prefix):
        raise HTTPException(400, "附件地址无效")
    relative = Path(file_url.removeprefix(prefix))
    if relative.is_absolute() or ".." in relative.parts:
        raise HTTPException(400, "附件地址无效")
    parts = relative.parts
    if len(parts) < 3 or parts[0] != "messages":
        raise HTTPException(400, "附件地址无效")
    try:
        uploader_id = int(parts[1])
    except (TypeError, ValueError):
        raise HTTPException(400, "附件地址无效")
    if uploader_id != user_id:
        raise HTTPException(403, "只能发送自己上传的附件")
    target = (UPLOAD_ROOT / relative).resolve()
    try:
        target.relative_to(UPLOAD_ROOT)
    except ValueError:
        raise HTTPException(400, "附件地址无效")
    if not target.is_file():
        raise HTTPException(400, "附件不存在或已失效")


def _validate_zip_container(path: Path, extension: str, max_size: int) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > 2000:
                raise HTTPException(400, "压缩容器文件条目过多")
            if sum(item.file_size for item in members) > max_size * 10:
                raise HTTPException(400, "压缩容器解压后大小超过限制")
            names = {item.filename for item in members}
    except (zipfile.BadZipFile, OSError):
        raise HTTPException(400, "文件内容与扩展名不匹配")

    required = {
        ".docx": "word/document.xml",
        ".xlsx": "xl/workbook.xml",
        ".pptx": "ppt/presentation.xml",
    }.get(extension)
    if required and ("[Content_Types].xml" not in names or required not in names):
        raise HTTPException(400, "Office 文件结构无效")


def _validate_content(path: Path, extension: str, header: bytes, max_size: int) -> None:
    valid = True
    if extension in {".jpg", ".jpeg"}:
        valid = header.startswith(b"\xff\xd8\xff")
    elif extension == ".png":
        valid = header.startswith(b"\x89PNG\r\n\x1a\n")
    elif extension == ".gif":
        valid = header.startswith((b"GIF87a", b"GIF89a"))
    elif extension == ".bmp":
        valid = header.startswith(b"BM")
    elif extension == ".webp":
        valid = len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    elif extension == ".pdf":
        valid = header.startswith(b"%PDF-")
    elif extension in {".doc", ".xls", ".ppt"}:
        valid = header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    elif extension in {".docx", ".xlsx", ".pptx", ".zip"}:
        valid = header.startswith(b"PK")
    elif extension == ".rar":
        valid = header.startswith((b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00"))
    elif extension == ".mp3":
        valid = header.startswith(b"ID3") or (len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0)
    elif extension == ".wav":
        valid = len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WAVE"
    elif extension == ".avi":
        valid = len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"AVI "
    elif extension in {".mp4", ".mov"}:
        valid = len(header) >= 12 and header[4:8] == b"ftyp"
    elif extension in {".txt", ".csv", ".md", ".json"}:
        valid = b"\x00" not in header
        if valid:
            try:
                header.decode("utf-8")
            except UnicodeDecodeError:
                valid = False

    if not valid:
        raise HTTPException(400, "文件内容与扩展名不匹配")
    if extension in {".docx", ".xlsx", ".pptx", ".zip"}:
        _validate_zip_container(path, extension, max_size)


async def save_validated_upload(
    file: UploadFile,
    *,
    category: str,
    allowed_extensions: frozenset[str],
    max_size: int,
) -> SavedUpload:
    original_name = Path(file.filename or "").name
    extension = Path(original_name).suffix.lower()
    if not original_name or extension not in allowed_extensions:
        raise HTTPException(400, f"不支持的文件类型: {extension or '无扩展名'}")

    category_path = (UPLOAD_ROOT / category).resolve()
    try:
        category_path.relative_to(UPLOAD_ROOT)
    except ValueError:
        raise HTTPException(400, "上传目录无效")
    category_path.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid.uuid4().hex}{extension}"
    destination = category_path / filename
    temporary = category_path / f".{filename}.part"
    total = 0
    header = bytearray()
    try:
        with temporary.open("wb") as output:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_size:
                    raise HTTPException(400, f"文件超过 {max_size // (1024 * 1024)}MB 限制")
                if len(header) < 8192:
                    header.extend(chunk[:8192 - len(header)])
                output.write(chunk)
        if total == 0:
            raise HTTPException(400, "文件内容为空")
        _validate_content(temporary, extension, bytes(header), max_size)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    relative = destination.relative_to(UPLOAD_ROOT).as_posix()
    return SavedUpload(
        absolute_path=destination,
        relative_path=relative,
        original_name=original_name,
        extension=extension,
        size=total,
        media_type=_MEDIA_TYPES[extension],
    )
