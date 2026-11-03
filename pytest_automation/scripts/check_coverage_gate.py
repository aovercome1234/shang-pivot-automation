#!/usr/bin/env python3
"""覆盖率门禁：静态接口/DB/方法/链路 + 可选 JaCoCo 行覆盖。

读取：
- data/coverage_gate.yaml
- ext/data/coverage.json
- ext/data/compare.json（取上一轮基线，禁止当前文件自比）
- artifacts/jacoco/report.xml（存在时）

用法：
  python3 scripts/check_coverage_gate.py
  python3 scripts/check_coverage_gate.py --require-runtime   # nightly
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "data" / "coverage_gate.yaml"
REPORT = ROOT / "artifacts" / "allure-report"
COVERAGE = REPORT / "ext" / "data" / "coverage.json"
COMPARE = REPORT / "ext" / "data" / "compare.json"
OUT = ROOT / "artifacts" / "quality-gate" / "coverage-gate.json"


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-runtime", action="store_true",
                        help="缺少/过期 JaCoCo 行覆盖时失败（nightly 使用）")
    parser.add_argument("--json", default=str(OUT))
    args = parser.parse_args()

    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    coverage = load(COVERAGE, {})
    compare = load(COMPARE, {})
    summary = coverage.get("summary") or {}
    runtime = coverage.get("runtime") or {}
    totals = compare.get("totals") or {}
    static_cfg = config.get("static") or {}
    runtime_cfg = config.get("runtime") or {}

    checks: list[dict] = []

    def add_check(name: str, actual, minimum=None, baseline=None,
                  delta_min=None, unit="%", severity="error") -> None:
        failures = []
        if actual is None:
            if severity == "error":
                failures.append("实际值缺失")
        else:
            if minimum is not None and actual < minimum:
                failures.append(f"低于下限 {minimum:g}{unit}")
            if baseline is not None and delta_min is not None:
                delta = actual - baseline
                if delta < delta_min:
                    failures.append(
                        f"较基线 {baseline:.1f}{unit} 下降 {abs(delta):.1f}pp"
                        f"（允许下限 {delta_min:g}pp）"
                    )
        checks.append({
            "name": name,
            "actual": actual,
            "baseline": baseline,
            "minimum": minimum,
            "deltaMin": delta_min,
            "unit": unit,
            "status": "failed" if failures else "passed",
            "message": "；".join(failures) if failures else "通过",
        })

    add_check("接口覆盖率", summary.get("interfaceRate"),
              minimum=static_cfg.get("interface_rate_min"), unit="%")
    add_check("链路节点覆盖率", summary.get("chainRate"),
              minimum=static_cfg.get("chain_rate_min"), unit="%")
    add_check("链路方法覆盖率", summary.get("methodRate"),
              minimum=static_cfg.get("chain_method_rate_min"),
              baseline=(totals.get("methodRate") or [None])[0],
              delta_min=static_cfg.get("method_rate_delta_min_pp"), unit="%")
    add_check("写接口 DB 断言率", summary.get("writeDbRate"),
              minimum=static_cfg.get("write_db_rate_min"),
              baseline=(totals.get("dbRate") or [None])[0],
              delta_min=static_cfg.get("write_db_delta_min_pp"), unit="%")

    runtime_ok = bool(runtime.get("lineRate") is not None)
    age_days = None
    if runtime_ok:
        try:
            generated = datetime.fromisoformat(str(runtime.get("generatedAt")))
            age_days = (datetime.now() - generated).days
            max_age = int(runtime_cfg.get("max_age_days") or 14)
            if age_days > max_age:
                runtime_ok = False
                checks.append({
                    "name": "JaCoCo 行覆盖率数据新鲜度",
                    "actual": f"{age_days} 天",
                    "minimum": f"≤{max_age} 天",
                    "status": "failed" if args.require_runtime else "warning",
                    "message": f"运行时数据已过期（{runtime.get('generatedAt')}）",
                })
        except ValueError:
            age_days = None
    if runtime_ok:
        line_rate = float(runtime["lineRate"]) * 100
        baseline_line = (totals.get("lineRate") or [None])[0]
        baseline_line = float(baseline_line) * 100 if baseline_line is not None else None
        add_check("JaCoCo 行覆盖率", line_rate,
                  baseline=baseline_line,
                  delta_min=runtime_cfg.get("line_rate_delta_min_pp"), unit="%")
    else:
        checks.append({
            "name": "JaCoCo 行覆盖率",
            "actual": None,
            "status": "failed" if args.require_runtime else "warning",
            "message": "缺少或过期的 JaCoCo 数据；PR 允许告警，nightly 使用 --require-runtime",
        })

    if runtime_cfg.get("new_java_line_rate_enabled"):
        checks.append({
            "name": "新增 Java 代码行覆盖率",
            "actual": None,
            "minimum": runtime_cfg.get("new_java_line_rate_min"),
            "status": "failed",
            "message": "已启用但尚未生成 JaCoCo + git diff 的新增行覆盖数据",
        })
    else:
        checks.append({
            "name": "新增 Java 代码行覆盖率",
            "actual": None,
            "minimum": runtime_cfg.get("new_java_line_rate_min"),
            "status": "warning",
            "message": "第二阶段能力：当前仅记录配置，未阻断",
        })

    failed = [item for item in checks if item["status"] == "failed"]
    payload = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "requireRuntime": args.require_runtime,
        "runtimeAgeDays": age_days,
        "checks": checks,
        "failed": len(failed),
        "status": "failed" if failed else "passed",
    }
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    for item in checks:
        print(f"[{item['status']:7}] {item['name']}: {item.get('actual')} ({item['message']})")
    if failed:
        print(f"[FAIL] 覆盖率门禁 {len(failed)} 项未通过")
        sys.exit(1)
    print("[OK] 覆盖率门禁通过")


if __name__ == "__main__":
    main()
