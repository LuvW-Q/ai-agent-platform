"""
AI大模型数据访问层
"""
from database.session import SessionLocal
from models.ai_model import AIModel


# ===== 大模型 =====
def list_models(db: SessionLocal):
    return db.query(AIModel).order_by(AIModel.created_at.desc()).all()


def get_model(model_id: int, db: SessionLocal):
    return db.query(AIModel).filter(AIModel.id == model_id).first()


def create_model(model: AIModel, db: SessionLocal):
    try:
        db.add(model)
        db.commit()
        db.refresh(model)
        return model
    except Exception:
        db.rollback()
        return None


def update_model(model_id: int, updates_dict: dict, db: SessionLocal):
    model = get_model(model_id, db)
    if not model:
        return None
    try:
        for key, value in updates_dict.items():
            setattr(model, key, value)
        db.commit()
        db.refresh(model)
        return model
    except Exception:
        db.rollback()
        return None


def delete_model(model_id: int, db: SessionLocal):
    model = get_model(model_id, db)
    if model:
        db.delete(model)
        db.commit()
        return True
    return False


def set_default(model_id: int, db: SessionLocal):
    """取消所有默认，将指定模型设为默认"""
    model = get_model(model_id, db)
    if not model:
        return None
    try:
        db.query(AIModel).update({AIModel.is_default: False})
        model.is_default = True
        db.commit()
        db.refresh(model)
        return model
    except Exception:
        db.rollback()
        return None


def get_default_model(db: SessionLocal):
    return db.query(AIModel).filter(AIModel.is_default == True).first()


def get_models_by_type(model_type: str, db: SessionLocal):
    """按类型筛选：chat/embedding/rerank"""
    return db.query(AIModel).filter(AIModel.model_type == model_type).all()
