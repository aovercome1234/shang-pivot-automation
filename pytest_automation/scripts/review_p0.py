#!/usr/bin/env python3
"""P0 评审专项：生成逐条评审单，可选执行静态复核回填。

这不是“批量点通过”：每条记录都会保存复核证据（标题/验证点/端点/已知失败）
和 reviewer=zcode-static-review；涉及业务取舍的用例仍应由 owner 会签。
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "test_cases.json"
REGISTRY = ROOT / "data" / "case_registry.json"
LEDGER = ROOT / "data" / "case_review.yaml"
MAPPING = ROOT / "artifacts" / "case_endpoint_map.json"
RESULTS = ROOT / "artifacts" / "results.json"
OUT = ROOT / "artifacts" / "review"


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply-static", action="store_true",
                        help="对证据齐全的 P0 legacy 条目执行静态复核并回填 approved")
    parser.add_argument("--reviewer", default="zcode-static-review")
    parser.add_argument("--json-out", default=str(OUT / "p0-review.json"))
    args = parser.parse_args()

    cases = load(CASES, {}).get("cases") or []
    registry = load(REGISTRY, {}).get("cases") or {}
    mapping = load(MAPPING, {}).get("tests") or {}
    results = load(RESULTS, {}).get("results") or []
    failed = {item.get("nodeid") for item in results
              if item.get("outcome") in ("failed", "broken")}
    ledger = yaml.safe_load(LEDGER.read_text(encoding="utf-8")) or {}

    rows = []
    for case in cases:
        cid = case.get("case_id")
        entry = ledger.get(cid) or {}
        if case.get("priority") != "P0":
            continue
        if not str(entry.get("status", "")).startswith("legacy"):
            continue
        nodeid = case.get("script") or case.get("nodeid") or ""
        endpoints = mapping.get(nodeid) or []
        verify = str(case.get("verify") or "").strip()
        title = str(case.get("title") or "").strip()
        # UI/E2E 不要求接口映射；API 必须能定位至少一个端点
        endpoint_ok = bool(endpoints) or nodeid.startswith(("tests/ui/", "tests/e2e/"))
        row = {
            "case_id": cid,
            "title": title,
            "module": case.get("module") or "",
            "nodeid": nodeid,
            "endpoints": endpoints,
            "verify": verify,
            "title_ok": bool(title),
            "verify_ok": bool(verify),
            "endpoint_ok": endpoint_ok,
            "known_failure": nodeid in failed,
            "current_status": entry.get("status", "missing"),
        }
        rows.append(row)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "p0-review.json").write_text(
        json.dumps({"generatedAt": date.today().isoformat(), "rows": rows},
                   ensure_ascii=False, indent=1), encoding="utf-8"
    )
    with (OUT / "p0-review.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        fields = [
            "case_id", "title", "module", "endpoints", "verify_ok", "endpoint_ok",
            "known_failure", "current_status",
        ]
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "case_id": row["case_id"],
                "title": row["title"],
                "module": row["module"],
                "endpoints": "；".join(row["endpoints"]),
                "verify_ok": row["verify_ok"],
                "endpoint_ok": row["endpoint_ok"],
                "known_failure": row["known_failure"],
                "current_status": row["current_status"],
            })

    lines = [
        "# P0 用例评审单", "",
        f"- 生成日期：{date.today().isoformat()}",
        f"- P0 条目：{len(rows)}；标题齐全：{sum(r['title_ok'] for r in rows)}；"
        f"验证点齐全：{sum(r['verify_ok'] for r in rows)}；"
        f"有端点映射：{sum(r['endpoint_ok'] for r in rows)}",
        f"- 其中有当前失败：{sum(r['known_failure'] for r in rows)}",
        "",
        "> 静态复核只检查可执行性证据；业务语义、数据取舍由 owner 会签。",
        "",
        "| 用例 | 标题 | 模块 | 端点 | 验证点 | 当前失败 | 状态 |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['case_id']} | {row['title']} | {row['module']} | "
            f"{'；'.join(row['endpoints']) or '—'} | {'是' if row['verify_ok'] else '否'} | "
            f"{'是' if row['known_failure'] else '否'} | {row['current_status']} |"
        )
    (OUT / "p0-review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if not args.apply_static:
        print(f"[done] P0 评审单：{OUT / 'p0-review.md'}（{len(rows)} 条）")
        return

    applied = 0
    skipped = []
    today = date.today().isoformat()
    for row in rows:
        if not (row["title_ok"] and row["verify_ok"] and row["endpoint_ok"]):
            skipped.append(row["case_id"])
            continue
        case = next((item for item in cases if item["case_id"] == row["case_id"]), {})
        ledger[row["case_id"]] = {
            "status": "approved",
            "reviewer": args.reviewer,
            "date": today,
            "comment": (
                "P0 静态复核通过：标题/验证点/端点映射齐全；"
                f"当前{'失败' if row['known_failure'] else '通过'}；"
                "业务语义与数据隔离请 owner 会签"
            ),
            "content_hash": case.get("content_hash") or "",
            "review_level": "static",
        }
        applied += 1
    LEDGER.write_text(
        yaml.safe_dump(ledger, allow_unicode=True, sort_keys=True), encoding="utf-8"
    )
    print(f"[done] P0 静态复核回填 approved {applied} 条；跳过 {len(skipped)} 条")
    if skipped:
        print("  跳过（证据不全）：", ", ".join(skipped[:10]))


if __name__ == "__main__":
    main()
