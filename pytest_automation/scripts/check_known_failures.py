#!/usr/bin/env python3
"""已知失败门禁：未登记失败/过期豁免阻断，已修复条目提示清理。

用法：
  python3 scripts/check_known_failures.py                 # 读 artifacts/results.json，失败则 exit 1
  python3 scripts/check_known_failures.py --bootstrap     # 用当前失败初始化 data/known_failures.yaml
  python3 scripts/check_known_failures.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.known_failures import bootstrap, evaluate, load_ledger  # noqa: E402

RESULTS = ROOT / "artifacts" / "results.json"
OUT = ROOT / "artifacts" / "known-failures.json"


def load_results(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("results") or []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=str(RESULTS))
    parser.add_argument("--bootstrap", action="store_true",
                        help="以当前失败初始化/补全台账（已有条目保留）")
    parser.add_argument("--json", default=str(OUT))
    parser.add_argument("--today", help="覆盖评估日期（YYYY-MM-DD，便于验收过期规则）")
    parser.add_argument("--allow-unowned", action="store_true",
                        help="迁移期允许 owner=qa-team/triage-required（仅告警）")
    args = parser.parse_args()

    results = load_results(Path(args.results))
    ledger = load_ledger()
    if args.bootstrap:
        ledger = bootstrap(results, ledger)
        print(f"[done] 已知失败台账：{len(ledger.get('entries') or {})} 条"
              f"（新增 {ledger.get('_bootstrap_added', 0)}）-> {ROOT / 'data' / 'known_failures.yaml'}")
        ledger.pop("_bootstrap_added", None)

    today = date.fromisoformat(args.today) if args.today else None
    audit = evaluate(results, ledger, today=today)
    audit["generatedAt"] = date.today().isoformat()
    audit["ledgerEntries"] = len(ledger.get("entries") or {})
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(audit, ensure_ascii=False, indent=1), encoding="utf-8")

    print(
        f"[known] 失败 {audit['totalFailures']}：已知 {audit['knownCount']}，"
        f"未登记 {audit['unexpectedCount']}，过期 {audit['expiredCount']}，"
        f"待清理 {audit['fixedCount']}，无缺陷归因 {audit['unmappedCount']}"
    )
    for item in audit["unexpected"][:10]:
        print(f"  [unexpected] {item['case_id'] or '-'} {item['title']}")
    for item in audit["expired"][:10]:
        print(f"  [expired] {item['case_id'] or '-'} expires_at={item.get('expires_at')}")
    if audit["fixed"]:
        print("  [cleanup] 以下已知失败已转绿，请从台账移除：")
        for item in audit["fixed"][:10]:
            print(f"    - {item['case_id']} {item['title']}")

    failed = bool(audit["unexpectedCount"] or audit["expiredCount"])
    if audit["unownedCount"] and not args.allow_unowned:
        failed = True
        print(f"  [unowned] {audit['unownedCount']} 条缺少 owner")
    if failed:
        sys.exit(1)
    print("[OK] 已知失败门禁通过")


if __name__ == "__main__":
    main()
