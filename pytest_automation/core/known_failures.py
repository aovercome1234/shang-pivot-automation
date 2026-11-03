"""已知失败台账的读取、评估与初始化。

台账只管理“失败是否已知”这个决策，不改变用例结果：
- unexpected：本轮失败但台账没有有效条目；
- known：本轮失败且台账 status=active、未过期；
- fixed：台账 active 但本轮已通过，等待清理；
- expired：台账 expires_at 已过期，需续期或修复。
"""
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Iterable

import yaml

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "data" / "known_failures.yaml"
REGISTRY = ROOT / "data" / "case_registry.json"
DEFECTS = ROOT / "artifacts" / "allure-report" / "ext" / "data" / "defects.json"


def load_ledger(path: Path = LEDGER) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {"version": 1, "entries": {}}
    entries = data.get("entries") or {}
    if isinstance(entries, list):
        entries = {item.get("case_id"): item for item in entries if item.get("case_id")}
    return {**data, "entries": entries}


def save_ledger(ledger: dict, path: Path = LEDGER) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(ledger, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def registry_map() -> dict[str, dict]:
    import json

    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return {
        nodeid: item for nodeid, item in (data.get("cases") or {}).items()
    }


def _defect_map() -> dict[str, dict]:
    import json

    try:
        data = json.loads(DEFECTS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return {
        item.get("caseId"): item for item in (data.get("defects") or []) if item.get("caseId")
    }


def _unmapped_bug(nodeid: str) -> str:
    return "DEF-UNMAPPED-" + hashlib.sha1(nodeid.encode("utf-8")).hexdigest()[:8]


def bootstrap(results: Iterable[dict], ledger: dict | None = None) -> dict:
    """以当前失败结果为初始台账；已有 case_id 不覆盖人工修改。"""
    from core.business_taxonomy import classify

    ledger = ledger or load_ledger()
    entries = dict(ledger.get("entries") or {})
    registry = registry_map()
    defects = _defect_map()
    added = 0
    for item in results:
        if item.get("outcome") not in ("failed", "broken"):
            continue
        nodeid = item.get("nodeid") or ""
        if not nodeid:
            continue
        case = registry.get(nodeid) or {}
        case_id = case.get("case_id") or item.get("case_id") or _unmapped_bug(nodeid)
        if case_id in entries:
            continue
        defect = defects.get(nodeid) or {}
        classification = classify(nodeid)
        code = defect.get("code") or {}
        entries[case_id] = {
            "nodeid": nodeid,
            "title": defect.get("name") or case.get("title") or nodeid,
            "module": classification.path,
            "bug_id": defect.get("id") or _unmapped_bug(nodeid),
            "owner": code.get("author") or "qa-team",
            "reason": (defect.get("summary") or "当前失败，待缺陷归因")[:300],
            "expires_at": "2026-12-31",
            "status": "active",
            "source": "defect-library" if defect else "unmapped",
        }
        added += 1
    ledger = {
        "version": 1,
        "description": "已知失败台账；active 条目必须由缺陷单/owner/到期日约束，修复后清理",
        "entries": dict(sorted(entries.items())),
    }
    save_ledger(ledger)
    ledger["_bootstrap_added"] = added
    return ledger


def _expired(entry: dict, today: date) -> bool:
    raw = str(entry.get("expires_at") or "")
    try:
        return date.fromisoformat(raw[:10]) < today
    except ValueError:
        return True


def evaluate(results: Iterable[dict], ledger: dict, today: date | None = None) -> dict:
    """评估当前结果与台账，返回可写入报告/门禁的结构。"""
    today = today or date.today()
    entries = ledger.get("entries") or {}
    registry = registry_map()
    failures: list[dict] = []
    passed: list[dict] = []
    for item in results:
        status = item.get("outcome") or item.get("status") or "unknown"
        nodeid = item.get("nodeid") or ""
        if not nodeid:
            continue
        case = registry.get(nodeid) or {}
        record = {
            "nodeid": nodeid,
            "case_id": item.get("case_id") or case.get("case_id") or "",
            "title": item.get("title") or case.get("title") or nodeid,
            "status": status,
        }
        if status in ("failed", "broken"):
            failures.append(record)
        elif status == "passed":
            passed.append(record)

    known, unexpected, expired, unowned, unmapped = [], [], [], [], []
    for item in failures:
        entry = entries.get(item["case_id"])
        if not entry:
            unexpected.append(item)
            continue
        if entry.get("status") != "active":
            unexpected.append(item)
            continue
        if _expired(entry, today):
            expired.append({**item, "expires_at": entry.get("expires_at")})
            continue
        known.append({**item, "bug_id": entry.get("bug_id"), "owner": entry.get("owner")})
        if not entry.get("owner") or entry.get("owner") == "triage-required":
            unowned.append(item)
        if str(entry.get("bug_id") or "").startswith("DEF-UNMAPPED-"):
            unmapped.append(item)

    fixed = []
    for item in passed:
        entry = entries.get(item["case_id"])
        if entry and entry.get("status") == "active":
            fixed.append({**item, "bug_id": entry.get("bug_id"), "owner": entry.get("owner")})

    return {
        "totalFailures": len(failures),
        "knownCount": len(known),
        "unexpectedCount": len(unexpected),
        "expiredCount": len(expired),
        "fixedCount": len(fixed),
        "unownedCount": len(unowned),
        "unmappedCount": len(unmapped),
        "known": known,
        "unexpected": unexpected,
        "expired": expired,
        "fixed": fixed,
        "unowned": unowned,
        "unmapped": unmapped,
    }
