"""受限 Python 技能执行器。

用户代码只在可终止的独立子进程中运行。执行环境不提供网络、文件系统、
数据库或项目模块，并在执行前拒绝危险导入和双下划线反射访问。
"""
from __future__ import annotations

import ast
import base64
import bisect
import collections
import copy
import csv
import dataclasses
import decimal
import enum
import fractions
import functools
import hashlib
import heapq
import io
import itertools
import json
import logging
import math
import multiprocessing
import operator
import pprint
import random
import re
import statistics
import string
import sys
import textwrap
import time
import traceback
import typing
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_MAX_TRANSPORT_BYTES = 1024 * 1024

_ALLOWED_MODULES: frozenset[str] = frozenset({
    "json", "math", "re", "time", "random", "datetime", "collections",
    "itertools", "functools", "hashlib", "base64", "csv", "statistics",
    "decimal", "fractions", "io", "string", "textwrap", "bisect",
    "heapq", "operator", "copy", "pprint", "uuid", "typing", "enum",
    "dataclasses",
})

_FORBIDDEN_NAMES = {
    "open", "exec", "eval", "compile", "globals", "locals", "input",
    "help", "breakpoint", "memoryview", "__import__",
}


def _safe_import(name: str, *args, **kwargs):
    top_level = name.split(".")[0]
    if top_level not in _ALLOWED_MODULES:
        raise ImportError(f"沙箱禁止导入模块: {name}")
    return __import__(name, *args, **kwargs)


_SAFE_BUILTINS: dict[str, Any] = {
    "bool": bool, "int": int, "float": float, "str": str, "bytes": bytes,
    "list": list, "tuple": tuple, "dict": dict, "set": set,
    "frozenset": frozenset, "complex": complex, "slice": slice,
    "True": True, "False": False, "None": None, "Ellipsis": Ellipsis,
    "abs": abs, "all": all, "any": any, "ascii": ascii, "bin": bin,
    "callable": callable, "chr": chr, "divmod": divmod, "enumerate": enumerate,
    "filter": filter, "format": format, "hex": hex, "isinstance": isinstance,
    "issubclass": issubclass, "iter": iter, "len": len, "map": map,
    "max": max, "min": min, "next": next, "oct": oct, "ord": ord,
    "pow": pow, "print": print, "range": range, "repr": repr,
    "reversed": reversed, "round": round, "sorted": sorted, "sum": sum,
    "zip": zip,
    "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
    "KeyError": KeyError, "IndexError": IndexError, "AttributeError": AttributeError,
    "RuntimeError": RuntimeError, "StopIteration": StopIteration,
    "ZeroDivisionError": ZeroDivisionError, "OverflowError": OverflowError,
    "ImportError": ImportError, "AssertionError": AssertionError,
    "ArithmeticError": ArithmeticError, "LookupError": LookupError,
    "NameError": NameError, "OSError": OSError, "TimeoutError": TimeoutError,
    "__import__": _safe_import,
}

_SAFE_GLOBALS = {
    "json": json, "math": math, "re": re, "time": time, "random": random,
    "datetime": datetime, "date": date, "timedelta": timedelta,
    "timezone": timezone, "collections": collections, "itertools": itertools,
    "functools": functools, "hashlib": hashlib, "base64": base64, "csv": csv,
    "statistics": statistics, "decimal": decimal, "fractions": fractions,
    "io": io, "string": string, "textwrap": textwrap, "bisect": bisect,
    "heapq": heapq, "operator": operator, "copy": copy, "pprint": pprint,
    "uuid": uuid, "typing": typing, "enum": enum, "dataclasses": dataclasses,
}


def _validate_code(code: str) -> None:
    """拒绝网络/文件/反射逃逸所需的语法和名称。"""
    tree = ast.parse(code, mode="exec")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names]
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            for name in names:
                if name.split(".")[0] not in _ALLOWED_MODULES:
                    raise ValueError(f"沙箱禁止导入模块: {name}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise ValueError("沙箱禁止访问双下划线属性")
        if isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            raise ValueError(f"沙箱禁止使用名称: {node.id}")


def _build_globals(context: dict | None = None) -> dict[str, Any]:
    values = {"__builtins__": _SAFE_BUILTINS, **_SAFE_GLOBALS}
    if context:
        values.update(context)
    return values


def _execute_function_local(code: str, function_name: str, args: Any) -> dict[str, Any]:
    result = {"success": False, "result": None, "error": "", "stdout": ""}
    captured = io.StringIO()
    old_stdout = sys.stdout
    try:
        _validate_code(code)
        globals_dict = _build_globals()
        sys.stdout = captured
        exec(code, globals_dict)
        func = globals_dict.get(function_name)
        if not callable(func):
            result["error"] = f"函数 '{function_name}' 未定义或不可调用"
            return result
        result["result"] = func(args)
        result["success"] = True
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    finally:
        sys.stdout = old_stdout
        result["stdout"] = captured.getvalue()
    return result


def _execute_raw_local(code: str, context: dict | None) -> dict[str, Any]:
    captured = io.StringIO()
    old_stdout = sys.stdout
    try:
        _validate_code(code)
        globals_dict = _build_globals(context)
        sys.stdout = captured
        exec(code, globals_dict)
        return {
            "success": True,
            "result": globals_dict.get("result", captured.getvalue()),
            "error": "",
            "stdout": captured.getvalue(),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "success": False,
            "result": None,
            "error": f"{type(exc).__name__}: {exc}",
            "stdout": captured.getvalue(),
        }
    finally:
        sys.stdout = old_stdout


def _sandbox_process_entry(mode: str, code: str, function_name: str,
                           args: Any, context: dict | None, conn) -> None:
    try:
        if mode == "function":
            result = _execute_function_local(code, function_name, args)
        else:
            result = _execute_raw_local(code, context)
        try:
            payload = json.dumps(result, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError):
            result["result"] = repr(result.get("result"))
            payload = json.dumps(result, ensure_ascii=False).encode("utf-8")
        if len(payload) > _MAX_TRANSPORT_BYTES:
            payload = json.dumps({
                "success": False,
                "result": None,
                "error": "沙箱输出超过 1MB 限制",
                "stdout": "",
            }, ensure_ascii=False).encode("utf-8")
        conn.send_bytes(payload)
    except Exception as exc:  # noqa: BLE001
        payload = json.dumps({
            "success": False,
            "result": None,
            "error": str(exc),
            "stdout": "",
        }, ensure_ascii=False).encode("utf-8")
        conn.send_bytes(payload)
    finally:
        conn.close()


class Sandbox:
    def __init__(self, default_timeout: int = 10):
        self.default_timeout = default_timeout

    def _run_isolated(self, mode: str, code: str, function_name: str = "",
                      args: Any = None, context: dict | None = None,
                      timeout: int | None = None) -> dict[str, Any]:
        timeout = timeout or self.default_timeout
        ctx = multiprocessing.get_context("spawn")
        parent_conn, child_conn = ctx.Pipe(duplex=False)
        process = ctx.Process(
            target=_sandbox_process_entry,
            args=(mode, code, function_name, args, context, child_conn),
            daemon=True,
        )
        process.start()
        child_conn.close()
        process.join(timeout)
        if process.is_alive():
            process.terminate()
            process.join(1)
            parent_conn.close()
            return {
                "success": False,
                "result": None,
                "error": f"执行超时（{timeout}s），子进程已终止",
                "stdout": "",
            }
        if parent_conn.poll(0.5):
            try:
                payload = parent_conn.recv_bytes(_MAX_TRANSPORT_BYTES)
                result = json.loads(payload.decode("utf-8"))
                if not isinstance(result, dict):
                    raise ValueError("沙箱返回格式错误")
                return result
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                return {
                    "success": False,
                    "result": None,
                    "error": f"沙箱返回解析失败: {exc}",
                    "stdout": "",
                }
            finally:
                parent_conn.close()
        parent_conn.close()
        return {
            "success": False,
            "result": None,
            "error": f"沙箱子进程异常退出（exitcode={process.exitcode}）",
            "stdout": "",
        }

    def execute_function(self, code: str, function_name: str,
                         args: dict[str, Any] | list | None = None,
                         timeout: int | None = None) -> dict[str, Any]:
        if not code or not code.strip():
            return {"success": False, "result": None, "error": "代码不能为空", "stdout": ""}
        if not function_name or not isinstance(function_name, str):
            return {"success": False, "result": None, "error": "函数名不能为空", "stdout": ""}
        return self._run_isolated(
            "function", code, function_name=function_name, args=args, timeout=timeout
        )

    def execute_raw(self, code: str, context: dict | None = None,
                    timeout: int | None = None) -> dict[str, Any]:
        if not code or not code.strip():
            return {"success": False, "result": None, "error": "代码不能为空", "stdout": ""}
        return self._run_isolated("raw", code, context=context, timeout=timeout)


sandbox = Sandbox()
