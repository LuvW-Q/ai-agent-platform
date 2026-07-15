"""
向量数据库客户端 — 双模式：Milvus (优先) / SQLite 全文搜索 (降级)
"""
from __future__ import annotations

import logging, json
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

MILVUS_URI = "http://localhost:19530"
MILVUS_TOKEN = "root:Milvus"
COLLECTION_PREFIX = "kb_"
DIM = 1536

_milvus_available: bool | None = None  # None=未检测, True/False
_milvus_client = None


def _try_milvus() -> bool:
    """检测 Milvus 是否可用"""
    global _milvus_available, _milvus_client
    if _milvus_available is not None:
        return _milvus_available
    try:
        from pymilvus import MilvusClient
        client = MilvusClient(uri=MILVUS_URI, token=MILVUS_TOKEN)
        # 尝试列出 collections 来验证连通性
        client.list_collections()
        _milvus_client = client
        _milvus_available = True
        logger.info("Milvus connected: %s", MILVUS_URI)
    except Exception as e:
        _milvus_available = False
        logger.warning("Milvus 不可用 (%s)，使用 SQLite 降级模式。请确保 Docker Desktop 中的 Milvus 已启动。", e)
    return _milvus_available


def _get_sqlite_path() -> str:
    """获取向量存储用的 SQLite 文件路径"""
    import os
    base = os.path.dirname(os.path.dirname(__file__))
    return os.path.join(base, "data_outlook_v2.db")


def _ensure_sqlite_vector_table():
    """确保 SQLite 中有向量/块存储表"""
    db_path = _get_sqlite_path()
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS kb_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kb_id INTEGER NOT NULL,
                doc_id INTEGER NOT NULL,
                chunk_index INTEGER DEFAULT 0,
                chunk_text TEXT DEFAULT '',
                vector_json TEXT DEFAULT '[]',
                metadata TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_kb_chunks_kb ON kb_chunks(kb_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_kb_chunks_doc ON kb_chunks(doc_id)"))
        conn.commit()
    return True


# ---------- 对外接口（自动 fallback） ----------

def milvus_available() -> bool:
    return _try_milvus()


def ensure_collection(kb_id: int, dim: int = DIM):
    if _try_milvus():
        try:
            from pymilvus import DataType
            coll_name = f"{COLLECTION_PREFIX}{kb_id}"
            if _milvus_client.has_collection(coll_name):
                return coll_name
            schema = _milvus_client.create_schema(enable_dynamic_field=True)
            schema.add_field("id", DataType.INT64, is_primary=True, auto_id=True)
            schema.add_field("doc_id", DataType.INT64)
            schema.add_field("chunk_index", DataType.INT64)
            schema.add_field("chunk_text", DataType.VARCHAR, max_length=4096)
            schema.add_field("vector", DataType.FLOAT_VECTOR, dim=dim)
            schema.add_field("metadata", DataType.VARCHAR, max_length=2048)
            idx_params = _milvus_client.prepare_index_params()
            idx_params.add_index(field_name="vector", index_type="IVF_FLAT", metric_type="COSINE", params={"nlist": 128})
            _milvus_client.create_collection(coll_name, schema=schema, index_params=idx_params)
            _milvus_client.load_collection(coll_name)
            logger.info("Milvus collection created: %s", coll_name)
            return coll_name
        except Exception as e:
            logger.warning("Milvus create collection failed: %s, falling back", e)
    # SQLite fallback
    _ensure_sqlite_vector_table()
    return f"sqlite_kb_{kb_id}"


def insert_chunks(kb_id: int, doc_id: int, chunks: list[dict], vectors: list[list[float]]):
    if _try_milvus():
        try:
            coll_name = ensure_collection(kb_id, dim=len(vectors[0]) if vectors else DIM)
            data = []
            for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
                data.append({"doc_id": doc_id, "chunk_index": chunk.get("index", i),
                             "chunk_text": chunk.get("text", ""), "vector": vec,
                             "metadata": chunk.get("metadata", "{}")})
            return _milvus_client.insert(coll_name, data)
        except Exception as e:
            logger.warning("Milvus insert failed: %s, using SQLite", e)

    # SQLite fallback
    _ensure_sqlite_vector_table()
    db_path = _get_sqlite_path()
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
            conn.execute(text(
                "INSERT INTO kb_chunks (kb_id, doc_id, chunk_index, chunk_text, vector_json, metadata) VALUES (:kb, :doc, :idx, :text, :vec, :meta)"
            ), {"kb": kb_id, "doc": doc_id, "idx": chunk.get("index", i),
                "text": chunk.get("text", ""), "vec": json.dumps(vec),
                "meta": chunk.get("metadata", "{}")})
        conn.commit()
    return {"insert_count": len(chunks)}


def search_chunks(kb_id: int, query_vector: list[float], top_k: int = 5) -> list[dict]:
    if _try_milvus():
        try:
            coll_name = f"{COLLECTION_PREFIX}{kb_id}"
            if not _milvus_client.has_collection(coll_name):
                return _sqlite_search(kb_id, query_vector, top_k)
            results = _milvus_client.search(coll_name, data=[query_vector], limit=top_k,
                                            output_fields=["doc_id", "chunk_index", "chunk_text", "metadata"])
            out = []
            for hit in results[0] if results else []:
                out.append({"id": hit.get("id"), "doc_id": hit.get("entity", {}).get("doc_id"),
                            "chunk_text": hit.get("entity", {}).get("chunk_text", ""),
                            "metadata": hit.get("entity", {}).get("metadata", "{}"),
                            "score": hit.get("distance", 0)})
            return out
        except Exception as e:
            logger.warning("Milvus search failed: %s", e)
    return _sqlite_search(kb_id, query_vector, top_k)


def _sqlite_search(kb_id: int, query_vector: list[float], top_k: int = 5) -> list[dict]:
    """SQLite 降级：余弦相似度暴力计算（小规模可用）"""
    import math
    _ensure_sqlite_vector_table()
    db_path = _get_sqlite_path()
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, doc_id, chunk_text, vector_json, metadata FROM kb_chunks WHERE kb_id=:kb ORDER BY id DESC LIMIT 500"
        ), {"kb": kb_id}).fetchall()

    scored = []
    for r in rows:
        try:
            vec = json.loads(r[3])
        except (json.JSONDecodeError, TypeError):
            continue
        # 余弦相似度
        dot = sum(a * b for a, b in zip(query_vector, vec))
        norm_q = math.sqrt(sum(a * a for a in query_vector))
        norm_v = math.sqrt(sum(b * b for b in vec))
        score = dot / (norm_q * norm_v) if norm_q and norm_v else 0
        scored.append({"id": r[0], "doc_id": r[1], "chunk_text": r[2],
                       "metadata": r[4] or "{}", "score": score})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def delete_doc_chunks(kb_id: int, doc_id: int):
    if _try_milvus():
        try:
            coll_name = f"{COLLECTION_PREFIX}{kb_id}"
            if _milvus_client.has_collection(coll_name):
                _milvus_client.delete(coll_name, filter=f"doc_id == {doc_id}")
                return
        except Exception as e:
            logger.warning("Milvus delete failed: %s", e)
    # SQLite fallback
    _ensure_sqlite_vector_table()
    db_path = _get_sqlite_path()
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM kb_chunks WHERE kb_id=:kb AND doc_id=:doc"),
                     {"kb": kb_id, "doc": doc_id})
        conn.commit()


def delete_collection(kb_id: int):
    if _try_milvus():
        try:
            coll_name = f"{COLLECTION_PREFIX}{kb_id}"
            if _milvus_client.has_collection(coll_name):
                _milvus_client.drop_collection(coll_name)
                return
        except Exception as e:
            logger.warning("Milvus drop collection failed: %s", e)
    # SQLite fallback
    _ensure_sqlite_vector_table()
    db_path = _get_sqlite_path()
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM kb_chunks WHERE kb_id=:kb"), {"kb": kb_id})
        conn.commit()


def collection_stats(kb_id: int) -> dict:
    if _try_milvus():
        try:
            coll_name = f"{COLLECTION_PREFIX}{kb_id}"
            if _milvus_client.has_collection(coll_name):
                s = _milvus_client.get_collection_stats(coll_name)
                return {"exists": True, "num_entities": s.get("row_count", 0),
                        "backend": "Milvus"}
        except Exception:
            pass
    # SQLite fallback
    _ensure_sqlite_vector_table()
    db_path = _get_sqlite_path()
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM kb_chunks WHERE kb_id=:kb"),
                             {"kb": kb_id}).scalar()
    return {"exists": True, "num_entities": count or 0, "backend": "SQLite (Milvus 不可用)"}
