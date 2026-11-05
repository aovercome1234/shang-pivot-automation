#!/usr/bin/env python3
"""把首轮性能基线结果注入 Allure 扩展报告页。

产物：
- ext/data/perf-baseline.json
- ext/manifest.json 追加「性能测试 → 首轮基线」
- ext/assets/app.js 同步带 perf renderer 的脚本

用法：
  python3 observability/scripts/build_perf_report.py \
    --run-dir artifacts/performance/perf-xxx \
    --ext-dir pytest_automation/artifacts/allure-report/ext
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, __import__("math").ceil(len(ordered) * ratio) - 1))
    return round(ordered[index], 2)


def build_payload(run_dir: Path, ext_dir: Path) -> dict:
    result_file = run_dir / "baseline-result.json"
    result = json.loads(result_file.read_text(encoding="utf-8"))
    records = result.get("records") or []

    endpoint_latency: dict[str, list[float]] = {}
    endpoint_counts: dict[str, dict] = {}
    for record in records:
        endpoint = re.sub(r"^/products/\d+$", "/products/{spuId}", record.get("endpoint") or "")
        ok = bool(record.get("ok"))
        elapsed = float(record.get("elapsedMs") or 0)
        bucket = endpoint_counts.setdefault(endpoint, {"total": 0, "failed": 0})
        bucket["total"] += 1
        bucket["failed"] += 0 if ok else 1
        endpoint_latency.setdefault(endpoint, []).append(elapsed)

    endpoints = {}
    for endpoint, counts in endpoint_counts.items():
        lat = endpoint_latency.get(endpoint, [])
        total = counts["total"]
        failed = counts["failed"]
        endpoints[endpoint] = {
            "total": total,
            "failed": failed,
            "errorRate": round(failed / total, 6) if total else 0,
            "avgMs": round(sum(lat) / len(lat), 2) if lat else 0,
            "p50Ms": percentile(lat, 0.50),
            "p90Ms": percentile(lat, 0.90),
            "p95Ms": percentile(lat, 0.95),
            "p99Ms": percentile(lat, 0.99),
            "maxMs": round(max(lat), 2) if lat else 0,
        }

    if endpoints:
        result["summary"]["endpoints"] = endpoints

    deploy_file = run_dir / "deploy-sync.json"
    deployment = {}
    if deploy_file.exists():
        deployment = json.loads(deploy_file.read_text(encoding="utf-8"))

    rel_base = Path("../..") / "performance" / run_dir.name
    return {
        "runId": result.get("runId"),
        "generatedAt": dt.datetime.now().isoformat(timespec="seconds"),
        "source": result.get("mode") or "performance-baseline",
        "baseUrl": result.get("baseUrl"),
        "startedAt": result.get("startedAt"),
        "finishedAt": result.get("finishedAt"),
        "summary": result.get("summary"),
        "deploymentSync": deployment,
        "limitations": result.get("limitations") or [],
        "links": {
            "result": str(rel_base / "baseline-result.json"),
            "report": str(rel_base / "baseline-report.md"),
            "screenshot": str(rel_base / "extension-page.png"),
        },
    }


def upsert_manifest(ext_dir: Path) -> None:
    manifest_file = ext_dir / "manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    groups = [group for group in manifest.get("groups", []) if group.get("id") != "perf"]
    groups.append({
        "id": "perf",
        "title": "性能测试",
        "views": [
            {"id": "baseline", "title": "首轮基线", "type": "perf", "data": "data/perf-baseline.json"},
        ],
    })
    manifest["groups"] = groups
    manifest["version"] = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--ext-dir", default="pytest_automation/artifacts/allure-report/ext")
    parser.add_argument("--skip-copy-js", action="store_true")
    args = parser.parse_args()

    run_dir = (ROOT / args.run_dir).resolve() if not Path(args.run_dir).is_absolute() else Path(args.run_dir)
    ext_dir = (ROOT / args.ext_dir).resolve() if not Path(args.ext_dir).is_absolute() else Path(args.ext_dir)
    if not (run_dir / "baseline-result.json").exists():
        raise SystemExit(f"找不到 {run_dir / 'baseline-result.json'}")
    if not (ext_dir / "manifest.json").exists():
        raise SystemExit(f"找不到 {ext_dir / 'manifest.json'}，先生成 Allure 扩展报告")

    payload = build_payload(run_dir, ext_dir)
    data_file = ext_dir / "data" / "perf-baseline.json"
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.skip_copy_js:
        source_js = ROOT / "pytest_automation" / "scripts" / "report_shell" / "app.js"
        target_js = ext_dir / "assets" / "app.js"
        target_js.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_js, target_js)

    upsert_manifest(ext_dir)
    print(json.dumps({
        "status": "PASS",
        "runId": payload.get("runId"),
        "data": str(data_file),
        "manifest": str(ext_dir / "manifest.json"),
        "route": "#/perf/baseline",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}")
        raise SystemExit(1)
