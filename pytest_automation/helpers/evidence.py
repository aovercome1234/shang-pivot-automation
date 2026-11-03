"""三方组件核验证据：记录实际执行的 SQL / 查询结果，供报告引用。

不生成“看起来像”的假数据：每条记录带时间、pytest 当前用例、参数与真实结果。
默认写入 artifacts/thirdparty/evidence.jsonl（追加）。
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "artifacts" / "thirdparty"
_LOCK = threading.Lock()


def _mask(value, key: str = ""):
    if isinstance(value, dict):
        return {k: _mask(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(item, key) for item in value]
    if key.lower() in ("password", "token", "accesstoken", "refreshtoken",
                       "authorization", "secret", "smscode"):
        return "***"
    if key.lower() == "phone" and isinstance(value, str) and len(value) >= 7:
        return value[:3] + "****" + value[-4:]
    return value


def record(kind: str, payload: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": kind,
        "at": datetime.now().isoformat(timespec="milliseconds"),
        "runId": os.getenv("RUN_ID", ""),
        "case": os.getenv("PYTEST_CURRENT_TEST", ""),
        **_mask(payload),
    }
    line = json.dumps(payload, ensure_ascii=False, default=str)
    with _LOCK:
        with (OUT_DIR / "evidence.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def record_db(*, endpoint: str, table: str, locate: str, sql: str,
              params: tuple | list | None, row: dict | None) -> None:
    record("db", {
        "endpoint": endpoint, "table": table, "locate": locate,
        "sql": sql, "params": list(params or []), "row": row or {},
    })


def record_redis(*, command: str, key: str, value=None, ttl=None, note: str = "") -> None:
    record("redis", {"command": command, "key": key, "value": value, "ttl": ttl, "note": note})


def record_mq(*, command: str, result, note: str = "") -> None:
    record("mq", {"command": command, "result": result, "note": note})
