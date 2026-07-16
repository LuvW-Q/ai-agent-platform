"""
Pytest conftest — set env before any project import, so the test uses a
separate SQLite database and never touches the production data.

Provides ``db_session`` fixture usable by any integration test that needs
a live SQLAlchemy session on the test database.
"""
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Point SQLite to a dedicated test file — never touch the dev database.
TEST_DB = PROJECT_ROOT / "data_outlook_v2.test.db"
if TEST_DB.exists():
    TEST_DB.unlink()
os.environ["SQLITE_URL"] = f"sqlite:///{TEST_DB}"


@pytest.fixture(scope="function")
def db_session():
    """Provide a clean SQLAlchemy session backed by the test database.

    Imports ``main`` to trigger ``Base.metadata.create_all``, then yields a
    session.  After the test the session is rolled back so each test sees a
    clean slate.
    """
    import main as _  # noqa: F401 — ensures tables exist
    from database.session import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()
