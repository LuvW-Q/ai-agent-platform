"""
Test SensitiveFilter-driven _classify_risk in smart_audit_controller.

Seeds sensitive_word rows directly via SQLAlchemy, then calls the private
_classify_risk helper to verify risk classification:
  - action="block" matched         → "high"
  - action="replace" matched       → "medium"
  - no match                       → "low"
"""
import pytest
from database.session import SessionLocal
from models.sensitive_word import SensitiveWord
from core.sensitive_filter import sensitive_filter

# Import app to trigger Base.metadata.create_all and seed data
from main import app  # noqa: F401


@pytest.fixture(scope="module")
def seeded_db():
    """Seed sensitive words once per module and invalidate the filter cache."""
    db = SessionLocal()
    db.add(SensitiveWord(word="赌博", replacement="***", action="block"))
    db.add(SensitiveWord(word="私聊", replacement="***", action="replace"))
    db.commit()
    sensitive_filter.invalidate_cache()
    yield db
    db.close()


def test_classify_high_on_block_word(seeded_db):
    """action='block' word in content → ('high', [])"""
    from controller.smart_audit_controller import _classify_risk

    risk, matched = _classify_risk("他在赌博", seeded_db)
    assert risk == "high"
    assert matched == []


def test_classify_medium_on_replace_word(seeded_db):
    """action='replace' word in content → ('medium', _)"""
    from controller.smart_audit_controller import _classify_risk

    risk, matched = _classify_risk("请加我微信私聊", seeded_db)
    assert risk == "medium"
    assert matched == ["***"]


def test_classify_low_on_clean_content(seeded_db):
    """No sensitive words → ('low', [])"""
    from controller.smart_audit_controller import _classify_risk

    risk, matched = _classify_risk("天气真好", seeded_db)
    assert risk == "low"
    assert matched == []
