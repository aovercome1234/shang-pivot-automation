"""失败诊断：按 traceId 抓取后端日志片段，挂到 Allure。

对应测试方案 §6「失败诊断」：响应里有 traceId 却不去用，等于浪费源码埋点。
后端日志路径默认 ../backend/logs/shang-pivot.log，可用 BACKEND_LOG 覆盖。
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    import allure  # type: ignore
except ImportError:  # pragma: no cover
    allure = None

_MAX_LINES = 80


def _log_path() -> Path | None:
    configured = os.getenv("BACKEND_LOG", "")
    if configured:
        path = Path(configured)
        return path if path.exists() else None
    default = Path(__file__).resolve().parents[2] / "backend" / "logs" / "shang-pivot.log"
    return default if default.exists() else None


def trace_excerpt(trace_id: str) -> str:
    """返回包含该 traceId 的日志行（含紧随其后的堆栈行）。"""
    path = _log_path()
    if not path or not trace_id:
        return ""
    lines: list[str] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if trace_id in line:
                    lines.append(line.rstrip())
                    # 堆栈通常紧跟其后（以空白开头 / at 开头）
                    position = 0
                elif lines and position < _MAX_LINES:
                    lines.append(line.rstrip())
                    position += 1
                elif lines:
                    break
    except OSError:
        return ""
    return "\n".join(lines)


def attach(trace_id: str, name: str = "后端日志（按 traceId）") -> str:
    """把日志片段挂到 Allure 并返回片段文本（便于本地调试时直接看）。"""
    text = trace_excerpt(trace_id)
    if not text:
        text = f"未找到 traceId={trace_id} 的日志（BACKEND_LOG 未配置或日志已轮转）"
    if allure is not None:
        allure.attach(text, name=name, attachment_type=allure.attachment_type.TEXT)
    return text
