"""
用户数据访问层
"""
from database.session import SessionLocal
from models.user import User
from models.refresh_token import RefreshToken


def find_user_by_name(username: str, db: SessionLocal):
    return db.query(User).filter(User.username == username).first()

def insert_user(user: User, db: SessionLocal):
    try:
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    except Exception:
        db.rollback()
        return None

def update_user(user: User, db: SessionLocal):
    try:
        db.commit()
        db.refresh(user)
        return user
    except Exception:
        db.rollback()
        return None

def store_refresh_token(record: RefreshToken, db: SessionLocal):
    try:
        db.add(record)
        db.commit()
        return record
    except Exception:
        db.rollback()
        return None

def find_refresh_token(token: str, db: SessionLocal):
    return db.query(RefreshToken).filter(RefreshToken.token == token).first()
