"""动态技能执行边界回归测试。"""

from core.sandbox import sandbox


def test_sandbox_allows_safe_computation():
    result = sandbox.execute_function(
        "def execute(args):\n    return {'total': sum(args['values'])}",
        "execute",
        {"values": [1, 2, 3]},
    )
    assert result["success"] is True, result["error"]
    assert result["result"] == {"total": 6}


def test_sandbox_blocks_network_database_and_filesystem_imports():
    for module in ("httpx", "sqlalchemy", "database.session", "models.user", "pathlib"):
        result = sandbox.execute_function(
            f"import {module}\ndef execute(args):\n    return True",
            "execute",
            {},
        )
        assert result["success"] is False, module
        assert "沙箱禁止导入模块" in result["error"], result["error"]


def test_sandbox_blocks_dunder_reflection():
    result = sandbox.execute_function(
        "def execute(args):\n    return ().__class__.__mro__",
        "execute",
        {},
    )
    assert result["success"] is False
    assert "双下划线属性" in result["error"]


def test_sandbox_terminates_timed_out_process():
    result = sandbox.execute_function(
        "def execute(args):\n    while True:\n        pass",
        "execute",
        {},
        timeout=1,
    )
    assert result["success"] is False
    assert "子进程已终止" in result["error"]


def test_sandbox_converts_non_json_result_inside_child_process():
    result = sandbox.execute_function(
        "def execute(args):\n    return {1, 2, 3}",
        "execute",
        {},
    )
    assert result["success"] is True, result["error"]
    assert isinstance(result["result"], str)


def test_sandbox_rejects_oversized_result():
    result = sandbox.execute_function(
        "def execute(args):\n    return 'x' * (2 * 1024 * 1024)",
        "execute",
        {},
    )
    assert result["success"] is False
    assert "1MB" in result["error"]
