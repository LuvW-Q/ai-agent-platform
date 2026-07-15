"""
沙箱执行环境
安全执行用户自定义 Python 函数（技能 function_call 类型）
使用 exec() + 受限全局命名空间，支持超时控制与 stdout 捕获

设计要点:
  1. 受限 builtins —— 移除 __import__ / open / eval / exec / compile 等危险函数
  2. 白名单 __import__ —— 仅允许导入常用标准库、httpx、sqlalchemy 及项目模块
  3. 超时机制 —— 优先使用 signal.SIGALRM (Linux/macOS)，Windows 回退 threading
  4. stdout 捕获 —— 将 print 输出收集到返回结果中
  5. 全局异常捕获 —— 任何异常都不会传播到调用方
"""
from __future__ import annotations

import io
import json
import math
import re
import time
import sys
import random
import signal
import threading
import traceback
import logging
from datetime import datetime, date, time as dtime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 模块白名单 —— 沙箱内允许导入的模块
# ---------------------------------------------------------------------------

_ALLOWED_MODULES: frozenset[str] = frozenset({
    # 标准库
    "json", "math", "re", "time", "random", "datetime", "collections",
    "itertools", "functools", "urllib", "hashlib", "base64", "csv",
    "statistics", "decimal", "fractions", "io", "string", "textwrap",
    "bisect", "heapq", "operator", "copy", "pprint", "uuid",
    "typing", "enum", "dataclasses", "pathlib", "tempfile",
    # 第三方
    "httpx", "sqlalchemy",
    # 项目模块
    "models", "database", "dao", "core",
})


def _safe_import(name: str, *args, **kwargs):
    """受限的 __import__，仅允许白名单中的模块"""
    top_level = name.split(".")[0]
    if top_level not in _ALLOWED_MODULES:
        raise ImportError(f"沙箱禁止导入模块: {name}")
    return __import__(name, *args, **kwargs)


# ---------------------------------------------------------------------------
# 受限 builtins
# ---------------------------------------------------------------------------

_SAFE_BUILTINS: dict[str, Any] = {
    # 类型与常量
    "bool": bool, "int": int, "float": float, "str": str, "bytes": bytes,
    "list": list, "tuple": tuple, "dict": dict, "set": set,
    "frozenset": frozenset, "complex": complex, "slice": slice,
    "True": True, "False": False, "None": None, "Ellipsis": Ellipsis,
    # 常用内置函数
    "abs": abs, "all": all, "any": any, "ascii": ascii, "bin": bin,
    "callable": callable, "chr": chr, "divmod": divmod, "enumerate": enumerate,
    "filter": filter, "format": format, "getattr": getattr, "hasattr": hasattr,
    "hash": hash, "hex": hex, "id": id, "isinstance": isinstance,
    "issubclass": issubclass, "iter": iter, "len": len, "map": map,
    "max": max, "min": min, "next": next, "oct": oct, "ord": ord,
    "pow": pow, "print": print, "range": range, "repr": repr,
    "reversed": reversed, "round": round, "sorted": sorted, "sum": sum,
    "type": type, "zip": zip, "setattr": setattr, "delattr": delattr,
    "dir": dir, "vars": vars,
    # 常用异常
    "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
    "KeyError": KeyError, "IndexError": IndexError, "AttributeError": AttributeError,
    "RuntimeError": RuntimeError, "StopIteration": StopIteration,
    "ZeroDivisionError": ZeroDivisionError, "OverflowError": OverflowError,
    "ImportError": ImportError, "FileNotFoundError": FileNotFoundError,
    "NotImplementedError": NotImplementedError, "AssertionError": AssertionError,
    "ArithmeticError": ArithmeticError, "LookupError": LookupError,
    "NameError": NameError, "OSError": OSError, "TimeoutError": TimeoutError,
    # 受限导入
    "__import__": _safe_import,
}


# ---------------------------------------------------------------------------
# 沙箱执行器
# ---------------------------------------------------------------------------

# Windows 不支持 signal.SIGALRM，需要回退到 threading
_HAS_SIGALRM: bool = hasattr(signal, "SIGALRM")

# 序列化 stdout 重定向，避免多线程竞争
_stdout_lock = threading.Lock()


class Sandbox:
    """
    沙箱执行环境

    用法::

        sb = Sandbox()
        result = sb.execute_function(
            code="def add(a, b):\\n    return a + b",
            function_name="add",
            args={"a": 1, "b": 2},
            timeout=5,
        )
        # result = {"success": True, "result": 3, "error": "", "stdout": ""}
    """

    def __init__(self, default_timeout: int = 10):
        self.default_timeout = default_timeout

    # ------------------------------------------------------------------
    # 构建沙箱全局命名空间
    # ------------------------------------------------------------------

    def _build_globals(self) -> dict[str, Any]:
        """构建受限的全局命名空间，预导入常用库与项目依赖"""
        g: dict[str, Any] = {"__builtins__": _SAFE_BUILTINS}

        # 标准库
        g.update({
            "json": json,
            "math": math,
            "re": re,
            "time": time,
            "random": random,
            "datetime": datetime,
            "date": date,
            "timedelta": timedelta,
            "timezone": timezone,
        })

        # 尝试导入更多标准库（失败不影响核心功能）
        for mod_name in (
            "collections", "itertools", "functools", "hashlib", "base64",
            "csv", "statistics", "decimal", "fractions", "io",
            "string", "textwrap", "bisect", "heapq", "operator",
            "copy", "pprint", "uuid", "typing", "enum",
            "dataclasses", "pathlib",
        ):
            try:
                g[mod_name] = __import__(mod_name)
            except ImportError:
                pass

        # urllib 子模块
        try:
            import urllib
            g["urllib"] = urllib
        except ImportError:
            pass

        # 第三方库
        try:
            import httpx
            g["httpx"] = httpx
        except ImportError:
            logger.debug("[Sandbox] httpx 不可用")

        try:
            import sqlalchemy
            g["sqlalchemy"] = sqlalchemy
        except ImportError:
            logger.debug("[Sandbox] sqlalchemy 不可用")

        # 项目依赖
        try:
            from database.session import SessionLocal
            g["SessionLocal"] = SessionLocal
        except ImportError:
            logger.debug("[Sandbox] SessionLocal 不可用")

        try:
            from database.session import Base
            g["Base"] = Base
        except ImportError:
            pass

        try:
            import models as _models_pkg
            g["models"] = _models_pkg
        except ImportError:
            logger.debug("[Sandbox] models 包不可用")

        return g

    # ------------------------------------------------------------------
    # 超时执行（signal 方式）
    # ------------------------------------------------------------------

    @staticmethod
    def _run_with_signal_timeout(func, args, timeout):
        """使用 signal.SIGALRM 实现超时（Linux/macOS）"""

        def _handler(signum, frame):
            raise TimeoutError(f"执行超时（{timeout}s）")

        old_handler = signal.signal(signal.SIGALRM, _handler)
        signal.alarm(timeout)
        try:
            # 统一将 args 作为单个位置参数传递（execute(args) 约定）
            return func(args)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

    # ------------------------------------------------------------------
    # 超时执行（threading 方式）
    # ------------------------------------------------------------------

    @staticmethod
    def _run_with_thread_timeout(func, args, timeout):
        """使用 threading 实现超时（Windows / 通用回退）"""
        box: dict[str, Any] = {"value": None, "error": None}

        def _worker():
            try:
                # 统一将 args 作为单个位置参数传递（execute(args) 约定）
                box["value"] = func(args)
            except Exception as exc:  # noqa: BLE001
                box["error"] = exc

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            # 守护线程无法强制终止，但调用方会收到超时错误
            raise TimeoutError(f"执行超时（{timeout}s）")
        if box["error"] is not None:
            raise box["error"]
        return box["value"]

    # ------------------------------------------------------------------
    # 核心方法
    # ------------------------------------------------------------------

    def execute_function(
        self,
        code: str,
        function_name: str,
        args: dict[str, Any] | list | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """
        在沙箱中执行用户自定义函数

        Args:
            code:          Python 源代码字符串（需定义目标函数）
            function_name: 要调用的函数名
            args:          参数。dict 视为关键字参数，list/tuple 视为位置参数
            timeout:       超时秒数，默认 10s

        Returns:
            {
                "success": bool,        # 是否成功
                "result":  Any | None,  # 函数返回值
                "error":   str,         # 错误信息（含 traceback）
                "stdout":  str,         # print 输出内容
            }
        """
        if timeout is None:
            timeout = self.default_timeout

        result: dict[str, Any] = {
            "success": False,
            "result": None,
            "error": "",
            "stdout": "",
        }

        if not code or not code.strip():
            result["error"] = "代码不能为空"
            return result

        if not function_name or not isinstance(function_name, str):
            result["error"] = "函数名不能为空"
            return result

        # 构建沙箱全局命名空间
        sandbox_globals = self._build_globals()

        # 捕获 stdout
        old_stdout = sys.stdout
        captured = io.StringIO()

        try:
            # 1. 执行代码定义函数
            with _stdout_lock:
                sys.stdout = captured
                try:
                    exec(code, sandbox_globals)
                finally:
                    sys.stdout = old_stdout

            # 2. 查找目标函数
            func = sandbox_globals.get(function_name)
            if func is None or not callable(func):
                result["error"] = f"函数 '{function_name}' 未定义或不可调用"
                return result

            # 3. 带超时执行函数
            with _stdout_lock:
                sys.stdout = captured
                try:
                    if _HAS_SIGALRM:
                        ret = self._run_with_signal_timeout(func, args, timeout)
                    else:
                        ret = self._run_with_thread_timeout(func, args, timeout)
                    result["success"] = True
                    result["result"] = ret
                finally:
                    sys.stdout = old_stdout

        except TimeoutError as exc:
            result["error"] = str(exc)
            logger.warning("[Sandbox] 超时: %s", exc)
        except Exception as exc:  # noqa: BLE001
            tb = traceback.format_exc()
            result["error"] = f"{type(exc).__name__}: {exc}\n{tb}"
            logger.warning("[Sandbox] 执行异常: %s", exc)
        finally:
            sys.stdout = old_stdout
            result["stdout"] = captured.getvalue()

        return result


    def execute_raw(self, code: str, context: dict = None) -> dict:
        """执行任意 Python 代码片段（用于工作流 code 节点）"""
        if not code or not code.strip():
            return {"success": False, "error": "代码不能为空", "result": None}
        g = self._build_globals()
        if context:
            for k, v in context.items():
                g[k] = v
        old = sys.stdout
        cap = io.StringIO()
        try:
            with _stdout_lock:
                sys.stdout = cap
                exec(code, g)
                sys.stdout = old
            result_val = g.get("result", cap.getvalue())
            return {"success": True, "result": result_val, "stdout": cap.getvalue()}
        except Exception as e:
            return {"success": False, "error": str(e), "result": None, "stdout": cap.getvalue()}
        finally:
            sys.stdout = old


# 全局单例
sandbox = Sandbox()
