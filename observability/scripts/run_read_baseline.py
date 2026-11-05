#!/usr/bin/env python3
"""只读链路首轮基线 runner。

k6 未安装或 SSH 不可用时，用本脚本从本机对公网入口执行小规模只读基线。
注意：该结果包含公网网络波动，只能作为首轮体验/观察基线，不能作为服务端容量结论。

推荐使用项目 pytest_automation/.venv 运行（含 requests）。
"""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import datetime as dt
import json
import math
import random
import re
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urljoin

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

DEFAULT_KEYWORDS = ["iPhone", "MacBook", "咖啡", "帐篷", "口红", "zzz不存在"]
WRITE = threading.Lock()


def parse_duration(value: str) -> int:
    match = re.fullmatch(r"(\d+)([smh])", value.strip())
    if not match:
        raise ValueError(f"时长格式应为 30s / 3m / 1h：{value}")
    amount = int(match.group(1))
    unit = match.group(2)
    return amount * {"s": 1, "m": 60, "h": 3600}[unit]


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * ratio) - 1))
    return round(ordered[index], 2)


def load_spu_ids(base_url: str, timeout: float) -> list[str]:
    response = requests.get(
        f"{base_url}/products",
        params={"page": 1, "size": 40},
        timeout=timeout,
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    body = response.json()
    records = ((body.get("data") or {}).get("records")) or []
    return [str(item["spuId"]) for item in records if item.get("spuId") is not None]


def pick_endpoint(mix: list[tuple[str, float]], spu_ids: list[str], keywords: list[str]) -> tuple[str, str]:
    roll = random.random()
    cursor = 0.0
    for name, weight in mix:
        cursor += weight
        if roll <= cursor:
            break
    else:
        name = mix[-1][0]

    if name == "products":
        return name, f"/products?page={random.randint(1, 4)}&size={random.randint(8, 20)}"
    if name == "search":
        return name, f"/search?q={random.choice(keywords)}&page=1&size=10"
    if name == "detail":
        spu_id = random.choice(spu_ids) if spu_ids else "101"
        return name, f"/products/{spu_id}"
    return "home", "/home"


def one_request(base_url: str, path: str, timeout: float, run_id: str) -> dict:
    url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    started = time.time()
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={
                "Accept": "application/json",
                "X-Perf-Run-Id": run_id,
                "X-Perf-Scenario": "public-read-baseline",
            },
        )
        elapsed_ms = (time.time() - started) * 1000
        try:
            body = response.json()
        except ValueError:
            body = {}
        return {
            "ts": round(started, 3),
            "endpoint": path.split("?", 1)[0],
            "path": path,
            "url": url,
            "httpStatus": response.status_code,
            "bizCode": body.get("code"),
            "elapsedMs": round(elapsed_ms, 2),
            "ok": response.status_code == 200 and body.get("code") == 0,
            "error": "",
        }
    except Exception as exc:  # noqa: BLE001 - 记录压测请求异常
        elapsed_ms = (time.time() - started) * 1000
        return {
            "ts": round(started, 3),
            "endpoint": path.split("?", 1)[0],
            "path": path,
            "url": url,
            "httpStatus": 0,
            "bizCode": None,
            "elapsedMs": round(elapsed_ms, 2),
            "ok": False,
            "error": str(exc)[:300],
        }


def summarize(records: list[dict], target_rps: int, started_at: float, finished_at: float) -> dict:
    elapsed_values = [float(item["elapsedMs"]) for item in records]
    failures = [item for item in records if not item["ok"]]
    endpoints: dict[str, dict] = {}
    for item in records:
        bucket = endpoints.setdefault(item["endpoint"], {"total": 0, "failed": 0, "latencies": []})
        bucket["total"] += 1
        bucket["failed"] += 0 if item["ok"] else 1
        bucket["latencies"].append(float(item["elapsedMs"]))

    endpoint_summary = {}
    for endpoint, bucket in sorted(endpoints.items()):
        lat = bucket["latencies"]
        endpoint_summary[endpoint] = {
            "total": bucket["total"],
            "failed": bucket["failed"],
            "errorRate": round(bucket["failed"] / bucket["total"], 6) if bucket["total"] else 0,
            "avgMs": round(sum(lat) / len(lat), 2) if lat else 0,
            "p50Ms": percentile(lat, 0.50),
            "p90Ms": percentile(lat, 0.90),
            "p95Ms": percentile(lat, 0.95),
            "p99Ms": percentile(lat, 0.99),
            "maxMs": round(max(lat), 2) if lat else 0,
        }

    duration_seconds = max(0.001, finished_at - started_at)
    total = len(records)
    actual_rps = total / duration_seconds
    overall = {
        "total": total,
        "failed": len(failures),
        "errorRate": round(len(failures) / total, 6) if total else 0,
        "actualRps": round(actual_rps, 2),
        "targetRps": target_rps,
        "avgMs": round(sum(elapsed_values) / total, 2) if total else 0,
        "p50Ms": percentile(elapsed_values, 0.50),
        "p90Ms": percentile(elapsed_values, 0.90),
        "p95Ms": percentile(elapsed_values, 0.95),
        "p99Ms": percentile(elapsed_values, 0.99),
        "maxMs": round(max(elapsed_values), 2) if elapsed_values else 0,
    }
    checks = {
        "error_rate_lt_1pct": overall["errorRate"] < 0.01,
        "p95_lt_800ms": overall["p95Ms"] < 800,
        "p99_lt_1500ms": overall["p99Ms"] < 1500,
    }
    return {"overall": overall, "endpoints": endpoint_summary, "checks": checks}


def write_markdown(path: Path, payload: dict) -> None:
    summary = payload["summary"]["overall"]
    checks = payload["summary"]["checks"]
    lines = [
        "# 首轮只读性能基线",
        "",
        f"- run_id：`{payload['runId']}`",
        f"- 目标 RPS：{summary['targetRps']}",
        f"- 实际 RPS：{summary['actualRps']}",
        f"- 请求数：{summary['total']}",
        f"- 失败数：{summary['failed']}（{summary['errorRate'] * 100:.3f}%）",
        f"- p50 / p90 / p95 / p99：{summary['p50Ms']} / {summary['p90Ms']} / {summary['p95Ms']} / {summary['p99Ms']} ms",
        f"- 最大耗时：{summary['maxMs']} ms",
        "",
        "## 检查项",
        "",
        f"- 错误率 <1%：{'PASS' if checks['error_rate_lt_1pct'] else 'FAIL'}",
        f"- p95 <800ms：{'PASS' if checks['p95_lt_800ms'] else 'FAIL'}",
        f"- p99 <1500ms：{'PASS' if checks['p99_lt_1500ms'] else 'FAIL'}",
        "",
        "## 分接口结果",
        "",
        "| 接口 | 请求数 | 失败 | 错误率 | avg | p95 | p99 | max |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for endpoint, item in payload["summary"]["endpoints"].items():
        lines.append(
            f"| `{endpoint}` | {item['total']} | {item['failed']} | {item['errorRate'] * 100:.3f}% "
            f"| {item['avgMs']} | {item['p95Ms']} | {item['p99Ms']} | {item['maxMs']} |"
        )
    lines += [
        "",
        "> 口径说明：本结果由本机经公网入口采集，包含公网网络波动；未同步服务器端监控，不代表容量结论。",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://49.233.135.247:60084/api")
    parser.add_argument("--rps", type=int, default=50)
    parser.add_argument("--duration", default="3m")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--run-id", default=f"perf-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}")
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--keywords", default=",".join(DEFAULT_KEYWORDS))
    parser.add_argument("--max-workers", type=int, default=0)
    args = parser.parse_args()

    if requests is None:
        raise SystemExit("缺少 requests，请使用 pytest_automation/.venv 运行")

    duration_seconds = parse_duration(args.duration)
    keywords = [item.strip() for item in args.keywords.split(",") if item.strip()]
    spu_ids = load_spu_ids(args.base_url, args.timeout)
    mix = [("products", 0.35), ("search", 0.25), ("detail", 0.20), ("home", 0.20)]
    out_dir = Path(args.out_dir or f"artifacts/performance/{args.run_id}")
    out_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    future_to_meta = {}
    started_at = time.time()
    deadline = started_at + duration_seconds
    workers = args.max_workers or max(50, min(300, args.rps * 3))

    with futures.ThreadPoolExecutor(max_workers=workers) as executor:
        while time.time() < deadline:
            second_start = time.time()
            for _ in range(args.rps):
                endpoint, path = pick_endpoint(mix, spu_ids, keywords)
                future = executor.submit(one_request, args.base_url, path, args.timeout, args.run_id)
                future_to_meta[future] = endpoint
            # 每秒补发一次，保证目标 RPS；请求本身在线程池并发执行。
            sleep_for = max(0.0, 1.0 - (time.time() - second_start))
            time.sleep(sleep_for)

        for future in futures.as_completed(future_to_meta):
            records.append(future.result())

    finished_at = time.time()
    summary = summarize(records, args.rps, started_at, finished_at)
    payload = {
        "runId": args.run_id,
        "mode": "public-read-baseline",
        "baseUrl": args.base_url,
        "startedAt": dt.datetime.fromtimestamp(started_at).isoformat(timespec="seconds"),
        "finishedAt": dt.datetime.fromtimestamp(finished_at).isoformat(timespec="seconds"),
        "durationSeconds": round(finished_at - started_at, 3),
        "workload": {"mix": mix, "keywords": keywords, "spuPoolSize": len(spu_ids)},
        "summary": summary,
        "records": records,
        "limitations": [
            "本机经公网入口执行，包含公网网络波动",
            "未部署服务器端 k6 脚本与后端 perf MDC 变更，未采集 JVM/DB/Redis/MQ 资源指标",
            "结果为只读链路基线，不包含登录与写链路",
        ],
    }
    result_file = out_dir / "baseline-result.json"
    result_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(out_dir / "baseline-report.md", payload)

    print(json.dumps({
        "status": "PASS" if all(summary["checks"].values()) else "FAIL",
        "runId": args.run_id,
        "summary": summary["overall"],
        "checks": summary["checks"],
        "result": str(result_file),
        "report": str(out_dir / "baseline-report.md"),
    }, ensure_ascii=False, indent=2))
    return 0 if all(summary["checks"].values()) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
