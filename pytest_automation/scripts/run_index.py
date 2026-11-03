#!/usr/bin/env python3
"""建立跨轮运行索引（SQLite）：run 指标 + 用例级结果，供版本对比/趋势查询。"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parent
HISTORY = ROOT / "artifacts" / "history"
RUNS = ROOT / "artifacts" / "runs"
DB = HISTORY / "index.sqlite"


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def registry_map() -> dict[str, str]:
    data = load(ROOT / "data" / "case_registry.json", {})
    return {nodeid: item.get("case_id") for nodeid, item in (data.get("cases") or {}).items()}


def seconds(start: str, stop: str) -> float:
    try:
        return (datetime.fromisoformat(stop) - datetime.fromisoformat(start)).total_seconds()
    except Exception:  # noqa: BLE001
        return 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", default=str(HISTORY / "metrics.json"))
    args = parser.parse_args()
    HISTORY.mkdir(parents=True, exist_ok=True)
    case_ids = registry_map()
    runs = []
    for root in (HISTORY, RUNS):
        if not root.exists():
            continue
        for directory in sorted(root.iterdir()):
            if not directory.is_dir() or directory.name == "index.sqlite":
                continue
            manifest = load(directory / "run-manifest.json", {})
            results = load(directory / "results.json", {}).get("results") or []
            if not manifest or not results:
                continue
            coverage = load(directory / "coverage.json", {})
            summary = coverage.get("summary") or {}
            runtime = coverage.get("runtime") or {}
            counts = manifest.get("counts") or {}
            total = int(manifest.get("total") or len(results))
            runs.append({
                "run_id": manifest.get("run_id") or directory.name,
                "path": str(directory.relative_to(ROOT)),
                "started_at": manifest.get("started_at") or "",
                "finished_at": manifest.get("finished_at") or "",
                "commit": (manifest.get("git") or {}).get("commit") or "",
                "branch": (manifest.get("git") or {}).get("branch") or "",
                "env": manifest.get("env") or "",
                "total": total,
                "passed": int(counts.get("passed") or 0),
                "failed": int(counts.get("failed") or 0),
                "skipped": int(counts.get("skipped") or 0),
                "interface_rate": summary.get("interfaceRate"),
                "db_rate": summary.get("writeDbRate"),
                "method_rate": summary.get("methodRate"),
                "line_rate": runtime.get("lineRate"),
                "wall_seconds": round(
                    float(manifest.get("wall_seconds") or 0)
                    or seconds(manifest.get("started_at") or "", manifest.get("finished_at") or ""),
                    1,
                ),
                "complete": total >= 100,
                "results": [
                    {
                        "nodeid": item.get("nodeid") or "",
                        "case_id": case_ids.get(item.get("nodeid") or "") or "",
                        "status": item.get("outcome") or "unknown",
                        "duration_ms": round(float(item.get("duration_seconds") or 0) * 1000, 1),
                    }
                    for item in results
                ],
            })
    conn = sqlite3.connect(DB)
    conn.executescript(
        """
        DROP TABLE IF EXISTS runs;
        DROP TABLE IF EXISTS case_results;
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY, path TEXT, started_at TEXT, finished_at TEXT,
            git_commit TEXT, branch TEXT, env TEXT, total INTEGER, passed INTEGER,
            failed INTEGER, skipped INTEGER, interface_rate REAL, db_rate REAL,
            method_rate REAL, line_rate REAL, wall_seconds REAL, complete INTEGER
        );
        CREATE TABLE case_results (
            run_id TEXT, nodeid TEXT, case_id TEXT, status TEXT, duration_ms REAL
        );
        CREATE INDEX idx_case_run ON case_results(run_id);
        CREATE INDEX idx_case_id ON case_results(case_id);
        """
    )
    for run in runs:
        conn.execute(
            "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run["run_id"], run["path"], run["started_at"], run["finished_at"],
             run["commit"], run["branch"], run["env"], run["total"], run["passed"],
             run["failed"], run["skipped"], run["interface_rate"], run["db_rate"],
             run["method_rate"], run["line_rate"], run["wall_seconds"],
             1 if run["complete"] else 0),
        )
        conn.executemany(
            "INSERT INTO case_results VALUES (?,?,?,?,?)",
            [(run["run_id"], item["nodeid"], item["case_id"], item["status"],
              item["duration_ms"]) for item in run["results"]],
        )
    conn.commit()
    conn.close()
    metrics = [
        {key: value for key, value in run.items() if key != "results"}
        for run in runs
    ]
    Path(args.json_out).write_text(
        json.dumps(metrics, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    complete = [run for run in metrics if run["complete"]]
    print(f"[done] 索引 {len(runs)} 轮（完整 {len(complete)}）-> {DB}")


if __name__ == "__main__":
    main()
