"""
Pytest conftest — set env before any project import, so the test uses a
separate SQLite database and never touches the production data.
"""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Point SQLite to a dedicated test file — never touch the dev database.
TEST_DB = PROJECT_ROOT / "data_outlook_v2.test.db"
if TEST_DB.exists():
    TEST_DB.unlink()
os.environ["SQLITE_URL"] = f"sqlite:///{TEST_DB}"
