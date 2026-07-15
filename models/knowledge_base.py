"""
知识库 & 文档 模型
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Boolean
from database.session import Base


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    description = Column(String(500), default="")
    embedding_model_id = Column(Integer, ForeignKey("ai_models.id"), nullable=True)
    rerank_model_id = Column(Integer, ForeignKey("ai_models.id"), nullable=True)
    chunk_size = Column(Integer, default=500)
    chunk_overlap = Column(Integer, default=50)
    doc_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class KBDocument(Base):
    __tablename__ = "kb_documents"
    id = Column(Integer, primary_key=True, autoincrement=True)
    kb_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=False, index=True)
    filename = Column(String(500), nullable=False)
    file_type = Column(String(20), default="txt")  # txt/md/pdf/docx
    file_size = Column(Integer, default=0)
    content = Column(Text, default="")            # 原始文本内容
    chunk_count = Column(Integer, default=0)
    status = Column(String(20), default="pending")  # pending/processing/done/error
    error_msg = Column(String(500), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
