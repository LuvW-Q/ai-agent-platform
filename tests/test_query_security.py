"""Security regression tests for model-produced NL2SQL execution."""

import json
import sqlite3

import pytest

from controller.query_controller import _execute_readonly_select, _parse_and_execute
from dao.user_dao import find_user_by_name
from models.user import User


def test_readonly_query_executor_allows_declared_business_columns(db_session):
    columns, rows = _execute_readonly_select(
        db_session,
        "SELECT username, role FROM users ORDER BY id LIMIT 5",
    )
    assert columns == ["username", "role"]
    assert isinstance(rows, list)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT password_hash FROM users",
        "SELECT token FROM refresh_tokens",
        "SELECT auth_key FROM api_registries",
        "SELECT name FROM sqlite_master",
        "SELECT load_extension('missing')",
    ],
)
def test_readonly_query_executor_blocks_secrets_and_sqlite_internals(db_session, sql):
    with pytest.raises(sqlite3.DatabaseError):
        _execute_readonly_select(db_session, sql)


def test_model_generated_secret_query_is_rejected(db_session):
    model_output = json.dumps({
        "sql": "SELECT username, password_hash FROM users",
        "explanation": "read users",
        "chart_type": "table",
        "chart_title": "users",
    })
    result = _parse_and_execute(model_output, "read users", db_session)
    assert result.rows == []
    assert "查询执行失败" in result.explanation


def test_readonly_query_executor_does_not_poison_application_connection(db_session):
    username = db_session.query(User.username).first()[0]
    assert find_user_by_name(username, db_session) is not None

    _execute_readonly_select(db_session, "SELECT COUNT(*) AS total FROM users")

    raw_connection = db_session.connection().connection.driver_connection
    assert raw_connection.execute("PRAGMA query_only").fetchone()[0] == 0
    assert find_user_by_name(username, db_session) is not None
