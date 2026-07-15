"""
技能数据访问层
"""
from database.session import SessionLocal
from models.skill import Skill


# ===== 技能 =====
def list_skills(db: SessionLocal):
    return db.query(Skill).order_by(Skill.created_at.desc()).all()


def get_skill(skill_id: int, db: SessionLocal):
    return db.query(Skill).filter(Skill.id == skill_id).first()


def create_skill(skill: Skill, db: SessionLocal):
    try:
        db.add(skill)
        db.commit()
        db.refresh(skill)
        return skill
    except Exception:
        db.rollback()
        return None


def update_skill(skill_id: int, updates_dict: dict, db: SessionLocal):
    skill = get_skill(skill_id, db)
    if not skill:
        return None
    try:
        for key, value in updates_dict.items():
            setattr(skill, key, value)
        db.commit()
        db.refresh(skill)
        return skill
    except Exception:
        db.rollback()
        return None


def delete_skill(skill_id: int, db: SessionLocal):
    skill = get_skill(skill_id, db)
    if skill:
        db.delete(skill)
        db.commit()
        return True
    return False


def get_skills_by_ids(ids_list: list, db: SessionLocal):
    if not ids_list:
        return []
    return db.query(Skill).filter(Skill.id.in_(ids_list)).all()


def get_skills_by_type(skill_type: str, db: SessionLocal):
    """按类型筛选：function_call/mcp/prompt"""
    return db.query(Skill).filter(Skill.skill_type == skill_type).all()
