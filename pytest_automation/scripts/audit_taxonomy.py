#!/usr/bin/env python3
"""审计业务分类：输出业务域/业务模块/验证维度分布，发现未归类或明显偏斜。"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.business_taxonomy import classify  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=str(ROOT / "artifacts" / "results.json"))
    parser.add_argument("--json-out", default=str(ROOT / "artifacts" / "taxonomy-audit.json"))
    args = parser.parse_args()

    payload = json.loads(Path(args.results).read_text(encoding="utf-8"))
    results = payload.get("results") or []
    domains: Counter[str] = Counter()
    modules: Counter[str] = Counter()
    dimensions: Counter[str] = Counter()
    failed_by_module: Counter[str] = Counter()
    samples: dict[str, list[str]] = defaultdict(list)

    for item in results:
        nodeid = item.get("nodeid") or ""
        if not nodeid:
            continue
        item_classification = classify(nodeid)
        domains[item_classification.domain] += 1
        modules[item_classification.path] += 1
        dimensions[item_classification.dimension] += 1
        if item.get("outcome") in ("failed", "broken"):
            failed_by_module[item_classification.path] += 1
        if len(samples[item_classification.path]) < 2:
            samples[item_classification.path].append(nodeid)

    unclassified = [
        nodeid for nodeid in (item.get("nodeid") or "" for item in results)
        if nodeid and classify(nodeid).module == "未分类"
    ]
    audit = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "total": len(results),
        "unclassified": unclassified,
        "domains": dict(domains.most_common()),
        "modules": dict(modules.most_common()),
        "dimensions": dict(dimensions.most_common()),
        "failedByModule": dict(failed_by_module.most_common()),
        "samples": samples,
    }
    Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json_out).write_text(
        json.dumps(audit, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    print(f"用例 {len(results)} 条；未归类 {len(unclassified)} 条")
    print("\n业务域:")
    for name, count in domains.most_common():
        print(f"  {count:4}  {name}")
    print("\n验证维度:")
    for name, count in dimensions.most_common():
        print(f"  {count:4}  {name}")
    print("\n业务模块（失败数）:")
    for name, count in modules.most_common():
        print(f"  {count:4}  {name:24} 失败 {failed_by_module.get(name, 0)}")
    print(f"\n审计结果 -> {args.json_out}")


if __name__ == "__main__":
    main()
