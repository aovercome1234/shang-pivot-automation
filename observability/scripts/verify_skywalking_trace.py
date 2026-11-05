#!/usr/bin/env python3
"""发送单个业务接口，并在 SkyWalking 中验证“接口 → 代码 → SQL”链路完整性。

用途：性能测试/链路追踪体系接入后的最小验收探针。只发送一次请求，不产生负载。
默认凭据从环境变量读取，避免把账号密码写进仓库：

  SW_USER=... SW_PASSWORD=... python3 observability/scripts/verify_skywalking_trace.py \
    --base-url http://49.233.135.247:60084 --path '/api/search?q=iPhone'

可加要求：
  --require-redis   要求 trace 中出现 Redis/virtual cache span
  --require-mq      要求 trace 中出现 MQ/virtual MQ span
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

DEFAULT_TIMEOUT = 10


def http_json(url: str, *, method: str = "GET", payload: dict | None = None,
              headers: dict | None = None, timeout: int = DEFAULT_TIMEOUT) -> dict:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{url} 未返回 JSON：{raw[:300]}") from exc


def build_probe_url(base_url: str, path: str, probe: str) -> str:
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    parsed = urllib.parse.urlsplit(url)
    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    pairs.append(("perf_trace_probe", probe))
    return urllib.parse.urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        urllib.parse.urlencode(pairs),
        parsed.fragment,
    ))


def endpoint_name(method: str, path: str) -> str:
    pathname = urllib.parse.urlsplit(path).path
    return f"{method.upper()}:{pathname}"


class SkyWalkingClient:
    def __init__(self, graphql_url: str, username: str, password: str):
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        self.graphql_url = graphql_url
        self.headers = {"Authorization": f"Basic {token}"}

    def gql(self, query: str, variables: dict | None = None) -> dict:
        result = http_json(
            self.graphql_url,
            method="POST",
            payload={"query": query, "variables": variables or {}},
            headers=self.headers,
            timeout=20,
        )
        if result.get("errors"):
            raise RuntimeError(json.dumps(result["errors"], ensure_ascii=False))
        return result.get("data") or {}

    def find_service(self, service_name: str) -> dict:
        data = self.gql(
            """
            query($serviceName: String!) {
              findService(serviceName: $serviceName) { id name shortName layers normal }
            }
            """,
            {"serviceName": service_name},
        )
        service = data.get("findService")
        if not service:
            raise AssertionError(f"SkyWalking 中找不到服务：{service_name}")
        return service

    def find_endpoint(self, service_id: str, name: str) -> dict:
        data = self.gql(
            """
            query($keyword: String!, $serviceId: ID!, $limit: Int!) {
              findEndpoint(keyword: $keyword, serviceId: $serviceId, limit: $limit) { id name }
            }
            """,
            {"keyword": name, "serviceId": service_id, "limit": 20},
        )
        for endpoint in data.get("findEndpoint") or []:
            if endpoint.get("name") == name:
                return endpoint
        raise AssertionError(f"SkyWalking 中找不到端点：{name}")

    def recent_traces(self, service_id: str, minutes: int) -> list[dict]:
        end = dt.datetime.now()
        start = end - dt.timedelta(minutes=minutes)
        traces: list[dict] = []
        seen: set[str] = set()
        # OAP 查询按开始时间倒序返回；压测窗口可能较密集，分页扫描前几页降低漏查概率。
        for page_num in range(1, 6):
            data = self.gql(
                """
                query($condition: TraceQueryCondition) {
                  queryBasicTraces(condition: $condition) {
                    traces { segmentId endpointNames duration start isError traceIds }
                  }
                }
                """,
                {
                    "condition": {
                        "serviceId": service_id,
                        "queryDuration": {
                            "start": start.strftime("%Y-%m-%d %H%M"),
                            "end": end.strftime("%Y-%m-%d %H%M"),
                            "step": "MINUTE",
                        },
                        "traceState": "ALL",
                        "queryOrder": "BY_START_TIME",
                        "paging": {"pageNum": page_num, "pageSize": 500},
                    }
                },
            )
            page = ((data.get("queryBasicTraces") or {}).get("traces")) or []
            if not page:
                break
            for brief in page:
                trace_id = (brief.get("traceIds") or [None])[0]
                if trace_id and trace_id not in seen:
                    seen.add(trace_id)
                    traces.append(brief)
        return traces

    def trace(self, trace_id: str) -> list[dict]:
        data = self.gql(
            """
            query($traceId: ID!) {
              queryTrace(traceId: $traceId) {
                spans {
                  traceId segmentId spanId parentSpanId serviceCode serviceInstanceName
                  startTime endTime endpointName type peer component isError layer
                  tags { key value }
                  logs { time data { key value } }
                }
              }
            }
            """,
            {"traceId": trace_id},
        )
        return ((data.get("queryTrace") or {}).get("spans")) or []


def tag_map(span: dict) -> dict[str, str]:
    return {str(tag.get("key")): str(tag.get("value") or "") for tag in span.get("tags") or []}


def summarize_span(span: dict) -> dict:
    tags = tag_map(span)
    return {
        "spanId": span.get("spanId"),
        "name": span.get("endpointName"),
        "type": span.get("type"),
        "component": span.get("component"),
        "peer": span.get("peer"),
        "durationMs": int(span.get("endTime") or 0) - int(span.get("startTime") or 0),
        "isError": span.get("isError"),
        "dbStatement": tags.get("db.statement"),
        "url": tags.get("url"),
    }


def find_probe_trace(client: SkyWalkingClient, service: dict, endpoint: dict,
                     request_started_ms: int, request_finished_ms: int,
                     timeout_seconds: int) -> tuple[str, list[dict]]:
    """按请求时间窗定位单次探针 trace。

    SkyWalking Tomcat 插件的 `url` tag 会剥掉 query string，因此不能依赖
    `perf_trace_probe` 出现在 url 中；单次探针用“端点名 + 请求时间窗”定位。
    """
    deadline = time.time() + timeout_seconds
    min_start = request_started_ms - 2_000
    max_start = request_finished_ms + 10_000
    while time.time() < deadline:
        traces = client.recent_traces(service["id"], minutes=1440)
        for brief in reversed(traces):
            if endpoint["name"] not in (brief.get("endpointNames") or []):
                continue
            start_ms = int(brief.get("start") or 0)
            if not (min_start <= start_ms <= max_start):
                continue
            trace_id = (brief.get("traceIds") or [None])[0]
            if not trace_id:
                continue
            spans = client.trace(trace_id)
            entry = next((s for s in spans if s.get("type") == "Entry" and s.get("endpointName") == endpoint["name"]), None)
            if entry:
                return trace_id, spans
        time.sleep(2)
    raise AssertionError(
        f"{timeout_seconds}s 内未找到 {endpoint['name']} 在请求时间窗内的 SkyWalking trace"
    )


def extract_sql_tables(sql_spans: list[dict]) -> list[str]:
    tables: set[str] = set()
    for span in sql_spans:
        statement = span.get("dbStatement") or ""
        for match in re.finditer(r"\b(?:FROM|JOIN|UPDATE|INTO)\s+([\w.]+)", statement, re.I):
            tables.add(match.group(1))
    return sorted(tables)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("PERF_BASE_URL", "http://49.233.135.247:60084"))
    parser.add_argument("--path", default=os.getenv("PERF_PROBE_PATH", "/api/search?q=iPhone"))
    parser.add_argument("--method", default=os.getenv("PERF_PROBE_METHOD", "GET"))
    parser.add_argument("--payload-json", default=os.getenv("PERF_PROBE_PAYLOAD_JSON", ""),
                        help="POST/PUT 请求体 JSON 字符串")
    parser.add_argument("--header", action="append", default=[],
                        help="附加请求头，格式 'Name: value'，可重复")
    parser.add_argument("--endpoint-name", default="",
                        help="SkyWalking 端点名，默认按 method + path 推导，如 POST:/api/auth/login")
    parser.add_argument("--service", default=os.getenv("SW_SERVICE_NAME", "shang-pivot"))
    parser.add_argument("--graphql", default=os.getenv("SW_GRAPHQL_URL", ""))
    parser.add_argument("--username", default=os.getenv("SW_USER", ""))
    parser.add_argument("--password", default=os.getenv("SW_PASSWORD", ""))
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--code-regex", default=r"(Controller|Service|Mapper|Repository)")
    parser.add_argument("--require-redis", action="store_true")
    parser.add_argument("--require-mq", action="store_true")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    if not args.username or not args.password:
        raise SystemExit("请通过 SW_USER / SW_PASSWORD 提供 SkyWalking 账号，不要把凭据写入仓库")
    graphql = args.graphql or args.base_url.rstrip("/") + "/skywalking/graphql"
    probe = f"trace-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    probe_url = build_probe_url(args.base_url, args.path, probe)
    payload = json.loads(args.payload_json) if args.payload_json else None
    headers = {"X-Perf-Probe": probe}
    for raw_header in args.header:
        name, sep, value = raw_header.partition(":")
        if not sep:
            raise SystemExit(f"--header 需要 'Name: value' 格式：{raw_header}")
        headers[name.strip()] = value.strip()

    request_started_ms = int(time.time() * 1000)
    started = time.time()
    response = http_json(
        probe_url,
        method=args.method.upper(),
        payload=payload,
        headers=headers,
        timeout=20,
    )
    elapsed_ms = round((time.time() - started) * 1000, 1)
    request_finished_ms = int(time.time() * 1000)
    if response.get("code") != 0:
        raise AssertionError(f"业务接口未成功：code={response.get('code')} msg={response.get('msg')}")

    client = SkyWalkingClient(graphql, args.username, args.password)
    service = client.find_service(args.service)
    expected_endpoint = args.endpoint_name or endpoint_name(args.method, args.path)
    endpoint = client.find_endpoint(service["id"], expected_endpoint)
    trace_id, spans = find_probe_trace(
        client, service, endpoint, request_started_ms, request_finished_ms, args.timeout
    )

    summaries = [summarize_span(span) for span in spans]
    entry = next((s for s in summaries if s["type"] == "Entry" and s["name"] == endpoint["name"]), None)
    code_spans = [
        s for s in summaries
        if s["type"] == "Local" and re.search(args.code_regex, str(s["name"] or ""))
    ]
    sql_spans = [
        s for s in summaries
        if (s["type"] == "Exit" and s["dbStatement"])
        or ("jdbc" in str(s["component"] or "").lower() and s["dbStatement"])
    ]
    redis_spans = [
        s for s in summaries
        if "redis" in str(s["component"] or "").lower() or "6379" in str(s["peer"] or "")
    ]
    mq_spans = [
        s for s in summaries
        if any(token in str(s["component"] or "").lower() for token in ("rabbit", "rocket", "kafka", "mq"))
        or "5672" in str(s["peer"] or "")
    ]

    checks = {
        "api_success": response.get("code") == 0,
        "skywalking_service": service.get("normal") is True,
        "entry_span": bool(entry),
        "code_span": bool(code_spans),
        "sql_span": bool(sql_spans),
    }
    if args.require_redis:
        checks["redis_span"] = bool(redis_spans)
    if args.require_mq:
        checks["mq_span"] = bool(mq_spans)

    evidence = {
        "checkedAt": dt.datetime.now().isoformat(timespec="seconds"),
        "baseUrl": args.base_url,
        "probeUrl": probe_url,
        "probe": probe,
        "api": {
            "method": args.method.upper(),
            "elapsedMs": elapsed_ms,
            "requestWindowMs": [request_started_ms, request_finished_ms],
            "code": response.get("code"),
            "msg": response.get("msg"),
            "traceId": response.get("traceId"),
        },
        "skywalking": {
            "graphql": graphql,
            "service": service,
            "endpoint": endpoint,
            "traceId": trace_id,
            "spanCount": len(spans),
            "entry": entry,
            "codeSpans": code_spans,
            "sqlSpans": sql_spans,
            "redisSpans": redis_spans,
            "mqSpans": mq_spans,
        },
        "checks": checks,
    }

    out = Path(args.out) if args.out else (
        Path(__file__).resolve().parents[2] / "artifacts" / "observability" /
        f"skywalking-trace-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "status": "PASS" if all(checks.values()) else "FAIL",
        "probe": probe,
        "businessTraceId": response.get("traceId"),
        "skywalkingTraceId": trace_id,
        "spans": len(spans),
        "codeSpans": [s["name"] for s in code_spans],
        "sqlTables": extract_sql_tables(sql_spans),
        "checks": checks,
        "evidence": str(out),
    }, ensure_ascii=False, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - CLI 需要直接给出可读失败原因
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
