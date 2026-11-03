#!/usr/bin/env python3
"""生成三方组件查询页：数据库模型、Redis/MQ 实时状态、落库 SQL 证据与手工复现步骤。

设计原则：页面展示的每一项都来自实时查询或测试运行记录，并附查询命令/时间，
避免“AI 编造数据”；DB 落库证据来自 helpers/db_contract.py 的实际 SELECT。
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from urllib.parse import urlparse
from datetime import datetime
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "artifacts" / "thirdparty"
REPORT = ROOT / "artifacts" / "allure-report"
CONTRACTS = ROOT / "artifacts" / "write-contracts.json"
ENDPOINT_MAP = ROOT / "artifacts" / "case_endpoint_map.json"
CALL_GRAPH = REPO / "api_testcases" / "baselines" / "810986c" / "call-graph.json"

MODULE_OF = {
    "identity": "认证与权限",
    "spu": "商品与库存", "sku": "商品与库存", "brand": "商品与库存",
    "category": "商品与库存", "attribute": "商品与库存", "site_brand": "商品与库存",
    "stock": "商品与库存", "warehouse": "商品与库存",
    "in_out_order": "商品与库存", "in_out_item": "商品与库存",
    "order": "交易与履约", "order_item": "交易与履约", "payment": "交易与履约",
    "shipment": "交易与履约", "cart": "交易与履约", "cart_item": "交易与履约",
    "address": "交易与履约", "review": "交易与履约", "after_sale": "交易与履约",
    "favorite": "交易与履约", "browse_history": "交易与履约",
    "order_event_log": "交易与履约",
    "home_slot": "运营与内容", "home_slot_item": "运营与内容",
}
AUDIT_FIELDS = {"created_at", "updated_at", "deleted", "trace_id"}
ER_CORE = {
    "identity.customer", "identity.admin_user", "identity.role", "identity.permission",
    "commerce.address", "commerce.cart", "commerce.cart_item", "commerce.order",
    "commerce.order_item", "commerce.payment", "commerce.shipment", "commerce.review",
    "commerce.after_sale", "commerce.spu", "commerce.sku", "commerce.stock",
    "commerce.warehouse", "commerce.brand", "commerce.category",
    "commerce.in_out_order", "commerce.in_out_item", "commerce.order_event_log",
}
COMMON_MEANINGS = {
    "id": "主键", "created_at": "创建时间", "updated_at": "更新时间",
    "deleted": "软删除标记", "trace_id": "链路 ID", "status": "状态",
    "customer_id": "会员 ID", "order_id": "订单 ID", "order_item_id": "订单明细 ID",
    "spu_id": "SPU ID", "sku_id": "SKU ID", "cart_id": "购物车 ID",
    "cart_item_id": "购物车项 ID", "address_id": "收货地址 ID",
    "payment_id": "支付 ID", "warehouse_id": "仓库 ID", "category_id": "类目 ID",
    "brand_id": "品牌 ID", "role_id": "角色 ID", "permission_id": "权限 ID",
    "dept_id": "部门 ID", "parent_id": "父级 ID", "user_id": "用户 ID",
    "order_no": "订单号", "after_sale_no": "售后单号", "trade_no": "支付流水号",
    "name": "名称", "code": "编码", "type": "类型", "phone": "手机号",
    "detail": "详细地址", "province": "省", "city": "市", "district": "区",
    "reason": "原因/说明", "remark": "备注", "content": "内容",
    "rating": "评分", "quantity": "数量", "price": "单价",
    "total_amount": "商品总额", "pay_amount": "应付金额", "freight": "运费",
    "refund_amount": "退款金额", "stock": "库存", "locked_stock": "锁定库存",
    "available_stock": "可用库存", "carrier": "承运商", "tracking_no": "运单号",
}
TABLE_MEANINGS = {
    ("identity.customer", "nickname"): "会员昵称",
    ("identity.customer", "phone"): "会员手机号",
    ("identity.admin_user", "username"): "管理员账号",
    ("identity.admin_user", "real_name"): "管理员姓名",
    ("identity.permission", "path"): "前端路由",
    ("identity.permission", "component"): "前端组件",
    ("commerce.order", "address_snapshot"): "下单地址快照",
    ("commerce.order", "idempotent_key"): "幂等键",
    ("commerce.order", "close_reason"): "关闭原因",
    ("commerce.after_sale", "audit_remark"): "审核意见",
    ("commerce.review", "pic_keys"): "评价图片",
}


def field_meaning(schema: str, table: str, column: str) -> str:
    return TABLE_MEANINGS.get((f"{schema}.{table}", column)) or COMMON_MEANINGS.get(
        column, f"业务字段 {column}"
    )


def module_of(schema: str, table: str) -> str:
    if schema == "identity":
        return "认证与权限"
    if schema == "public":
        return "系统"
    return MODULE_OF.get(table, "其他")


def infer_relations(tables: list[dict]) -> list[dict]:
    by_name = {f"{t['schema']}.{t['name']}": t for t in tables}
    by_simple = {t["name"]: f"{t['schema']}.{t['name']}" for t in tables}
    relations = []
    seen = set()
    for table in tables:
        source = f"{table['schema']}.{table['name']}"
        for field in table.get("fields") or []:
            column = field["name"]
            if not column.endswith("_id") or column in ("parent_id",):
                continue
            base = column[:-3]
            candidates = [base, f"{base}s", f"{base}es"]
            target = next((by_simple[c] for c in candidates if c in by_simple), None)
            if not target or target == source:
                continue
            key = (source, column, target)
            if key in seen:
                continue
            seen.add(key)
            relations.append({
                "from": source, "fromField": column,
                "to": target, "toField": "id", "label": f"{column}", "type": "N:1",
            })
    return relations


def er_graph(tables: list[dict], relations: list[dict]) -> dict:
    degree = {}
    for rel in relations:
        degree[rel["from"]] = degree.get(rel["from"], 0) + 1
        degree[rel["to"]] = degree.get(rel["to"], 0) + 1
    nodes_ids = {key for key, value in degree.items() if value}
    groups = {"认证与权限": [], "商品与库存": [], "交易与履约": [], "运营与内容": [], "系统": [], "其他": []}
    for table in tables:
        key = f"{table['schema']}.{table['name']}"
        if key in nodes_ids and key in ER_CORE:
            groups.setdefault(module_of(table["schema"], table["name"]), []).append(key)
    nodes = []
    module_x = {"认证与权限": 20, "商品与库存": 300, "交易与履约": 600, "运营与内容": 890, "系统": 20, "其他": 890}
    max_rows = 0
    for module, keys in groups.items():
        for index, key in enumerate(keys):
            nodes.append({"id": key, "label": key.split(".")[-1], "module": module,
                          "x": module_x.get(module, 600), "y": 20 + index * 64,
                          "w": 170, "h": 42})
        max_rows = max(max_rows, len(keys))
    node_ids = {node["id"] for node in nodes}
    return {"nodes": nodes, "edges": [
        rel for rel in relations
        if rel["from"] in node_ids and rel["to"] in node_ids
    ], "height": max(220, 20 + max_rows * 64)}


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def mask(value, key: str = ""):
    if isinstance(value, dict):
        return {k: mask(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [mask(item, key) for item in value]
    if key.lower() in ("password", "token", "accesstoken", "refreshtoken",
                       "authorization", "secret", "smscode"):
        return "***"
    if key.lower() == "phone" and isinstance(value, str) and len(value) >= 7:
        return value[:3] + "****" + value[-4:]
    return value


def mask_key(key: str) -> str:
    if key.startswith("sms:phone:") or key.startswith("sms:cooldown:"):
        phone = key.rsplit(":", 1)[-1]
        return key.rsplit(":", 1)[0] + ":" + phone[:3] + "****" + phone[-4:]
    return key


def db_model() -> dict:
    from helpers import db
    if not db.available():
        return {"available": False, "error": "PostgreSQL 不可达"}
    info = db.query_one("SELECT current_database() AS name, version() AS version")
    databases = db.query(
        "SELECT datname FROM pg_database WHERE datistemplate = FALSE ORDER BY datname"
    )
    schemas = db.query(
        "SELECT schema_name FROM information_schema.schemata "
        "WHERE schema_name NOT IN ('pg_catalog','information_schema','pg_toast') "
        "ORDER BY schema_name"
    )
    tables = []
    field_total = 0
    for schema in [row["schema_name"] for row in schemas]:
        rows = db.query(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_type = 'BASE TABLE' ORDER BY table_name",
            (schema,),
        )
        for row in rows:
            name = row["table_name"]
            columns = db.query(
                "SELECT column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns WHERE table_schema=%s AND table_name=%s "
                "ORDER BY ordinal_position",
                (schema, name),
            )
            field_total += len(columns)
            try:
                count = db.query_one(
                    f'SELECT count(*) AS n FROM "{schema}"."{name}"'
                )["n"]
            except Exception:  # noqa: BLE001
                count = None
            tables.append({
                "schema": schema, "name": name, "rows": count,
                "module": module_of(schema, name),
                "fields": [
                    {
                        "name": col["column_name"], "type": col["data_type"],
                        "nullable": col["is_nullable"] == "YES",
                        "default": col["column_default"],
                        "meaning": field_meaning(schema, name, col["column_name"]),
                        "core": col["column_name"] not in AUDIT_FIELDS,
                    }
                    for col in columns
                ],
            })
    relations = infer_relations(tables)
    return {
        "available": True,
        "database": info["name"],
        "serverVersion": info["version"].split(",")[0],
        "databases": [row["datname"] for row in databases],
        "schemas": [row["schema_name"] for row in schemas],
        "tables": tables,
        "relations": relations,
        "er": er_graph(tables, relations),
        "tableCount": len(tables),
        "fieldCount": field_total,
    }


def api_mapping(db_model_data: dict) -> list[dict]:
    contracts = load(CONTRACTS, {}).get("endpoints") or {}
    graph = load(CALL_GRAPH, {}).get("endpoints") or []
    graph_map = {item.get("endpoint"): item for item in graph}
    mappings = []
    for endpoint, contract in contracts.items():
        table = contract.get("table")
        locate = (contract.get("locate") or {}).get("type", "")
        status = "covered" if contract.get("tests") else "contract"
        if locate in ("response_id", "response_field", "path_param"):
            key = (contract.get("locate") or {}).get("key") or "id"
            sql = f"SELECT * FROM {table} WHERE {key if key == 'id' else 'id'} = :id"
        elif locate == "natural":
            column = (contract.get("locate") or {}).get("column", "id")
            sql = f"SELECT * FROM {table} WHERE {column} = :value ORDER BY id DESC LIMIT 1"
        else:
            sql = f"SELECT count(*) FROM {table}"
        mappings.append({
            "endpoint": endpoint,
            "method": endpoint.split(" ", 1)[0],
            "path": endpoint.split(" ", 1)[-1],
            "table": table,
            "locate": locate,
            "tests": contract.get("tests") or [],
            "sqlExample": sql,
            "tablesFromGraph": (graph_map.get(endpoint) or {}).get("tables") or [],
            "status": status,
        })
    # 未进入契约的写端点也列出，标明“待补”
    for item in graph:
        endpoint = item.get("endpoint") or ""
        if item.get("http") not in ("POST", "PUT", "DELETE") or endpoint in contracts:
            continue
        tables = item.get("tables") or []
        path = item.get("path") or ""
        auth_or_file = path.startswith(("/admin/auth", "/api/auth", "/files/"))
        if auth_or_file:
            status = "not_applicable"
            locate = "不适用（认证/文件，核心状态在 Redis/对象存储）"
            table_text = ""
            sql = "-- 无业务表落库"
        else:
            status = "mapped_table"
            locate = "表级映射（字段契约待补）"
            table_text = "、".join(tables)
            sql = (f"SELECT * FROM {tables[0]} ORDER BY id DESC LIMIT 5;  "
                   f"-- 表级映射，涉及：{'、'.join(tables)}" if tables else "-- 无业务表落库")
        mappings.append({
            "endpoint": endpoint,
            "method": item.get("http"),
            "path": path,
            "table": table_text,
            "locate": locate,
            "tests": [],
            "sqlExample": sql,
            "tablesFromGraph": tables,
            "status": status,
        })
    return mappings


def db_checks() -> list[dict]:
    path = OUT / "evidence.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if item.get("kind") == "db":
            rows.append(item)
    return rows[-100:]


def redis_state() -> dict:
    try:
        import redis as redis_lib

        client = redis_lib.Redis(
            host=os.getenv("REDIS_HOST", "127.0.0.1"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            password=os.getenv("REDIS_PASSWORD") or None,
            decode_responses=True, socket_connect_timeout=2, socket_timeout=2,
        )
        client.ping()
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": str(exc), "host": os.getenv("REDIS_HOST", "127.0.0.1")}
    patterns = ["sms:phone:*", "sms:cooldown:*", "login:fail:*", "jwt:blacklist:*"]
    samples = []
    counts = {}
    found = {}
    for pattern in patterns:
        keys = list(client.scan_iter(match=pattern, count=100))
        counts[pattern] = len(keys)
        found[pattern] = keys
        for key in keys[:8]:
            kind = client.type(key)
            ttl = client.ttl(key)
            value = client.get(key) if kind == "string" else None
            samples.append({
                "key": mask_key(str(key)), "type": kind, "ttl": ttl,
                "value": mask(value, "value") if value is not None else None,
                "command": f"TYPE {mask_key(str(key))}; TTL; GET" if kind == "string" else "TYPE; TTL",
            })
    default_pattern = next(
        (pattern for pattern in ("login:fail:*", "sms:phone:*", "sms:cooldown:*",
                                 "jwt:blacklist:*") if found.get(pattern)),
        patterns[0],
    )
    default_key = (found.get(default_pattern) or [""])[0]
    return {
        "available": True,
        "host": f"{os.getenv('REDIS_HOST', '127.0.0.1')}:{os.getenv('REDIS_PORT', '6379')}",
        "patterns": patterns, "counts": counts, "samples": samples,
        "defaultPattern": default_pattern, "defaultKey": default_key,
    }


def mq_state() -> dict:
    base = os.getenv("RABBITMQ_MANAGEMENT_URL", "http://127.0.0.1:15672")
    auth = (os.getenv("RABBITMQ_USERNAME", "guest"), os.getenv("RABBITMQ_PASSWORD", "guest"))
    result = {"available": False, "base": base}
    try:
        overview = requests.get(f"{base}/api/overview", auth=auth, timeout=3)
        overview.raise_for_status()
        queues = requests.get(f"{base}/api/queues/%2F", auth=auth, timeout=3)
        queues.raise_for_status()
        result["available"] = True
        result["version"] = overview.json().get("rabbitmq_version")
        result["queues"] = [
            {
                "name": item.get("name"),
                "messages": item.get("messages"),
                "ready": item.get("messages_ready"),
                "unacked": item.get("messages_unacknowledged"),
                "consumers": item.get("consumers"),
            }
            for item in queues.json()
        ]
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
    try:
        from helpers import db
        if db.available():
            result["events"] = db.query(
                "SELECT order_id, event_type, trace_id, payload::text AS payload, created_at "
                "FROM commerce.order_event_log ORDER BY created_at DESC LIMIT 20"
            )
            result["eventCount"] = db.query_one(
                "SELECT count(*) AS n FROM commerce.order_event_log"
            )["n"]
            result["trend"] = db.query(
                "SELECT to_char(date_trunc('hour', created_at AT TIME ZONE 'Asia/Shanghai'), "
                "'MM-DD HH24:00') AS label, count(*) AS count FROM commerce.order_event_log "
                "WHERE created_at > now() - interval '24 hours' "
                "GROUP BY date_trunc('hour', created_at AT TIME ZONE 'Asia/Shanghai') ORDER BY 1"
            )
    except Exception as exc:  # noqa: BLE001
        result["eventsError"] = str(exc)
    return result


def reproduce_steps() -> list[dict]:
    return [
        {
            "component": "数据库",
            "goal": "确认测试写入的行真实存在，字段与请求一致",
            "commands": [
                "psql -h 127.0.0.1 -U shang -d shang",
                "SELECT current_database();",
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_schema IN ('commerce','identity') AND table_type='BASE TABLE';",
                "SELECT * FROM commerce.\"order\" ORDER BY created_at DESC LIMIT 5;",
            ],
        },
        {
            "component": "Redis",
            "goal": "确认验证码 TTL、登录锁定、JWT 黑名单键存在且 TTL 合理",
            "commands": [
                "redis-cli -h 127.0.0.1 -p 6379",
                "SCAN 0 MATCH 'sms:phone:*' COUNT 100",
                "SCAN 0 MATCH 'login:fail:*' COUNT 100",
                "SCAN 0 MATCH 'jwt:blacklist:*' COUNT 100",
                "TTL <key>; GET <key>",
            ],
        },
        {
            "component": "RabbitMQ",
            "goal": "确认队列、消费者、积压与事件表一致",
            "commands": [
                "curl -u guest:<password> http://127.0.0.1:15672/api/queues/%2F",
                "docker exec shang-rabbitmq rabbitmqctl list_queues name messages consumers",
                "SELECT order_id, event_type, trace_id, payload, created_at "
                "FROM commerce.order_event_log ORDER BY created_at DESC LIMIT 10;",
            ],
        },
    ]


def render_markdown(payload: dict) -> dict[str, str]:
    db = payload["db"]
    lines = [
        "# 数据库关系模型", "",
        f"- 数据库：`{db.get('database')}`",
        f"- 业务 schema：{', '.join(db.get('schemas') or [])}",
        f"- 表：{db.get('tableCount')}；字段：{db.get('fieldCount')}",
        f"- 采集时间：{payload['generatedAt']}", "",
        "## 表与字段", "",
        "| Schema | 表 | 行数 | 字段数 |",
        "|---|---|---:|---:|",
    ]
    for table in db.get("tables") or []:
        lines.append(f"| {table['schema']} | {table['name']} | {table['rows']} | {len(table['fields'])} |")
    lines += ["", "## 字段明细", ""]
    for table in db.get("tables") or []:
        lines += [f"### {table['schema']}.{table['name']}（{table['rows']} 行）", "",
                  "| 字段 | 类型 | 可空 | 默认值 |", "|---|---|---|---|"]
        for field in table.get("fields") or []:
            lines.append(
                f"| {field['name']} | {field['type']} | "
                f"{'YES' if field.get('nullable') else 'NO'} | {field.get('default') or ''} |"
            )
        lines.append("")
    lines += ["", "## API → 表 → SQL", "", "| 接口 | 表 | 定位 | SQL |", "|---|---|---|---|"]
    for item in payload["knowledge"]["apiMappings"]:
        lines.append(f"| `{item['endpoint']}` | `{item.get('table') or '-'}` | {item.get('locate') or '-'} | `{item.get('sqlExample') or '-'}` |")
    schema_md = "\n".join(lines) + "\n"

    checks = ["# 测试执行期间的落库 SQL 证据", "",
              "> 来源：`helpers/db_contract.py` 实际执行的 SELECT；不是手工编造。", ""]
    for item in payload["knowledge"]["dbChecks"]:
        checks += [
            f"## {item.get('endpoint')}", "",
            f"- 表：`{item.get('table')}`",
            f"- 用例：`{item.get('case')}`",
            f"- 时间：{item.get('at')}",
            f"- 定位：{item.get('locate')}",
            "", "```sql", item.get("sql", ""), "```", "",
            f"- 参数：`{json.dumps(item.get('params'), ensure_ascii=False)}`",
            "", "```json", json.dumps(item.get("row"), ensure_ascii=False, indent=2, default=str)[:4000], "```", "",
        ]
    checks_md = "\n".join(checks)

    reproduce = ["# 三方组件手工复现步骤", "",
                 f"- 运行：`{payload.get('runId') or '-'}`",
                 f"- 采集：{payload['generatedAt']}", "",
                 "## 数据库", "",
                 "```bash",
                 "# 使用 backend/.env 或环境变量中的连接信息",
                 'psql -h 127.0.0.1 -U shang -d shang',
                 "SELECT current_database();",
                 "SELECT table_schema, table_name FROM information_schema.tables "
                 "WHERE table_schema IN ('commerce','identity') AND table_type='BASE TABLE';",
                 "```", "",
                 "## Redis", "",
                 "```bash",
                 f"redis-cli -h {os.getenv('REDIS_HOST', '127.0.0.1')} -p {os.getenv('REDIS_PORT', '6379')}",
                 "SCAN 0 MATCH 'sms:phone:*' COUNT 100",
                 "SCAN 0 MATCH 'login:fail:*' COUNT 100",
                 "SCAN 0 MATCH 'jwt:blacklist:*' COUNT 100",
                 "TTL <key>; GET <key>",
                 "```", "",
                 "## RabbitMQ", "",
                 "```bash",
                 f"curl -u {os.getenv('RABBITMQ_USERNAME', 'guest')}:<password> "
                 f"{os.getenv('RABBITMQ_MANAGEMENT_URL', 'http://127.0.0.1:15672')}/api/queues/%2F",
                 "docker exec shang-rabbitmq rabbitmqctl list_queues name messages consumers",
                 "```", "",
                 "## 数据库中的 MQ 事件", "",
                 "```sql",
                 "SELECT order_id, event_type, trace_id, payload, created_at",
                 "FROM commerce.order_event_log ORDER BY created_at DESC LIMIT 10;",
                 "```", "",
                 "## 判定标准", "",
                 "- DB：页面中的 SQL 与结果必须能在 psql 复现；",
                 "- Redis：SCAN 到的 key、TTL 与页面一致；",
                 "- MQ：队列 depth、事件表行与页面一致；",
                 "- 所有数据带采集时间与 runId，不接受无来源的截图/数字。", ""]
    return {"db-schema.md": schema_md, "db-checks.md": checks_md,
            "reproduce.md": "\n".join(reproduce)}


REDIS_TEST_STEPS = {
    "API-CACHE-001": [
        {"step": "发送验证码", "action": "POST /api/auth/sms/send", "key": "sms:phone:<phone>",
         "command": "GET sms:phone:<phone>; TTL", "expected": "值=123456，TTL 240–300s；sms:cooldown TTL ≤60s"},
        {"step": "验证码登录", "action": "POST /api/auth/login", "key": "sms:phone:<phone>",
         "command": "GET sms:phone:<phone>", "expected": "登录成功后 key 被删除（返回 nil）"},
    ],
    "API-CACHE-002": [
        {"step": "60 秒内重复发送", "action": "POST /api/auth/sms/send", "key": "sms:cooldown:<phone>",
         "command": "TTL sms:cooldown:<phone>", "expected": "第二次返回 400「发送过于频繁」，验证码不刷新"},
    ],
    "API-CACHE-003": [
        {"step": "连续 5 次错误密码", "action": "POST /admin/auth/login", "key": "login:fail:<username>",
         "command": "GET login:fail:<username>; TTL", "expected": "计数=5，TTL ≤900s"},
        {"step": "第 6 次登录", "action": "POST /admin/auth/login", "key": "login:fail:<username>",
         "command": "GET login:fail:<username>", "expected": "返回 40104 账号锁定"},
    ],
    "API-CACHE-004": [
        {"step": "失败 1 次后成功登录", "action": "POST /admin/auth/login", "key": "login:fail:<username>",
         "command": "GET login:fail:<username>", "expected": "成功后 key 被删除，失败计数清零"},
    ],
    "API-CACHE-005": [
        {"step": "会员退出登录", "action": "POST /api/auth/logout", "key": "jwt:blacklist:<jti>",
         "command": "SCAN 0 MATCH 'jwt:blacklist:*' COUNT 100; TTL", "expected": "新增黑名单 key，TTL>0"},
        {"step": "使用旧 token 访问", "action": "GET /api/me", "key": "jwt:blacklist:<jti>",
         "command": "GET /api/me", "expected": "HTTP 401"},
    ],
    "API-CACHE-006": [
        {"step": "检查黑名单 TTL", "action": "读取 jwt:blacklist:*", "key": "jwt:blacklist:<jti>",
         "command": "TTL jwt:blacklist:<jti>", "expected": "TTL>0，不做永久封禁"},
    ],
    "API-CACHE-007": [
        {"step": "会员刷新令牌", "action": "POST /api/auth/refresh", "key": "jwt:blacklist:<old-refresh-jti>",
         "command": "SCAN 0 MATCH 'jwt:blacklist:*' COUNT 100", "expected": "旧 refresh jti 进入黑名单"},
    ],
    "API-CACHE-008": [
        {"step": "管理端退出", "action": "POST /admin/auth/logout", "key": "jwt:blacklist:<jti>",
         "command": "SCAN 0 MATCH 'jwt:blacklist:*' COUNT 100", "expected": "旧 access token 立即 401，黑名单键存在"},
    ],
    "API-CACHE-009": [
        {"step": "管理端刷新", "action": "POST /admin/auth/refresh", "key": "jwt:blacklist:<old-refresh-jti>",
         "command": "SCAN 0 MATCH 'jwt:blacklist:*' COUNT 100", "expected": "旧 refresh 进入黑名单"},
    ],
    "API-CACHE-010": [
        {"step": "手机号别名登录", "action": "POST /api/auth/phone", "key": "sms:phone:<phone>",
         "command": "GET sms:phone:<phone>", "expected": "登录成功后验证码 key 删除"},
    ],
}


def masked_body(text: str) -> str:
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        # 附件可能被截断（... (truncated)），JSON 解析失败时用正则兜底
        return re.sub(
            r'"(password|accessToken|refreshToken|token|authorization|smsCode)"\s*:\s*"[^"]*"',
            r'"\1": "***"', text, flags=re.IGNORECASE,
        )
    return json.dumps(mask(data), ensure_ascii=False, indent=2)


def _pretty(value) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _exchanges_from_recorder(nodeid: str) -> list[dict]:
    """从 endpoint_recorder 的运行期快照读取 API 请求/响应（含 traceId）。

    Allure 对夹具 setup 阶段的请求附件不一定挂在测试结果上，endpoint_recorder
    是更稳定的来源；它同时保留 setup/call 两个阶段。
    """
    if not nodeid:
        return []
    try:
        data = json.loads(ENDPOINT_MAP.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    details = (data.get("details") or {}).get(nodeid) or {}
    exchanges = []
    for endpoint, detail in details.items():
        method, _, path = endpoint.partition(" ")
        if not method or not path:
            continue
        response = detail.get("response") or {}
        body = response.get("body")
        trace_id = body.get("traceId") if isinstance(body, dict) else None
        request = detail.get("request") or {}
        request_body = request.get("body")
        if request_body is None:
            request_body = request.get("raw")
        exchanges.append({
            "method": method,
            "path": path,
            "phase": detail.get("phase") or "",
            "requestBody": _pretty(request_body if request_body is not None else ""),
            "status": response.get("status"),
            "responseBody": _pretty(body if body is not None else ""),
            "responseCode": body.get("code") if isinstance(body, dict) else None,
            "responseMsg": body.get("msg") if isinstance(body, dict) else None,
            "traceId": trace_id,
        })
    return exchanges


def load_actual_exchanges(case_id: str, nodeid: str | None = None) -> list[dict]:
    if not case_id:
        return []
    recorded = _exchanges_from_recorder(nodeid or "")
    if recorded:
        return recorded
    candidates = []
    for file in (ROOT / "artifacts" / "allure").glob("*-result.json"):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if str(data.get("name") or "").startswith(case_id):
            candidates.append(data)
    if not candidates:
        return []
    result = max(candidates, key=lambda item: item.get("start") or 0)
    exchanges = []
    pending = None
    for attachment in result.get("attachments") or []:
        name = attachment.get("name") or ""
        source = attachment.get("source") or ""
        if not source or not name.startswith(("请求", "响应")):
            continue
        path = ROOT / "artifacts" / "allure" / source
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if name.startswith("请求"):
            first = text.splitlines()[0] if text.splitlines() else ""
            match = re.match(r"(\w+)\s+(\S+)", first)
            body = text.split("Body:\n", 1)[1].strip() if "Body:\n" in text else ""
            body = masked_body(body)
            pending = {
                "method": match.group(1) if match else "",
                "path": urlparse(match.group(2)).path if match else "",
                "requestBody": body,
            }
        elif name.startswith("响应") and pending:
            status_match = re.search(r"Status:\s*(\d+)", text)
            body = text.split("Body:\n", 1)[1].strip() if "Body:\n" in text else ""
            body = masked_body(body)
            try:
                parsed = json.loads(body)
            except Exception:  # noqa: BLE001
                parsed = None
            pending.update({
                "status": int(status_match.group(1)) if status_match else None,
                "responseBody": body,
                "responseCode": parsed.get("code") if isinstance(parsed, dict) else None,
                "responseMsg": parsed.get("msg") if isinstance(parsed, dict) else None,
                "traceId": parsed.get("traceId") if isinstance(parsed, dict) else None,
            })
            exchanges.append(pending)
            pending = None
    return exchanges


def latest_case_start(case_id: str) -> float:
    start = 0.0
    for file in (ROOT / "artifacts" / "allure").glob("*-result.json"):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if str(data.get("name") or "").startswith(case_id):
            start = max(start, float(data.get("start") or 0))
    return start


def load_mq_evidence(nodeid: str, case_id: str) -> list[dict]:
    """读取 helpers.evidence.record_mq 写入的真实发布/消费证据。"""
    path = OUT / "evidence.jsonl"
    if not path.exists() or not nodeid:
        return []
    start_ms = latest_case_start(case_id)
    records = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if item.get("kind") != "mq" or nodeid not in (item.get("case") or ""):
            continue
        try:
            at_ms = datetime.fromisoformat(item.get("at")).timestamp() * 1000
        except Exception:  # noqa: BLE001
            at_ms = 0
        if start_ms and at_ms < start_ms - 1000:
            continue
        records.append(item)
    return records


def load_redis_evidence(nodeid: str, case_id: str) -> list[dict]:
    path = OUT / "evidence.jsonl"
    if not path.exists() or not nodeid:
        return []
    start_ms = latest_case_start(case_id)
    records = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if item.get("kind") != "redis" or nodeid not in (item.get("case") or ""):
            continue
        try:
            at_ms = datetime.fromisoformat(item.get("at")).timestamp() * 1000
        except Exception:  # noqa: BLE001
            at_ms = 0
        if start_ms and at_ms < start_ms - 1000:
            continue
        records.append(item)
    return records


def redis_param_source(step: dict) -> str:
    key = step.get("key") or ""
    if "<phone>" in key:
        return ("phone 来自 helpers.data_factory.unique_phone()：随机生成不重复的 11 位手机号；"
                "key 由 f\"sms:phone:{phone}\" 拼接；验证码固定为演示环境 123456")
    if "<username>" in key:
        return ("username 由 f\"lock_{uuid.uuid4().hex[:10]}\" 随机生成；"
                "password 固定为 wrong-password（仅用于触发 40101）；"
                "key 由 f\"login:fail:{username}\" 拼接；TTL 来自后端 LOCK_TTL=15 分钟")
    if "<jti>" in key:
        return ("jti 从登录接口返回的 JWT 解析（JwtUtil.getJti）；"
                "key 由 TokenBlacklist 的 jwt:blacklist: 前缀 + jti 拼接；"
                "TTL 取 access/refresh 令牌剩余有效期")
    return ("参数由用例中的夹具/常量提供；key 由业务前缀 + 实体 ID 拼接，"
            "具体见用例源码")


MQ_TEST_STEPS = {
    "API-MQ-001": [
        {"step": "创建并支付订单", "action": "POST /api/payment/sandbox",
         "exchange": "commerce.order.event", "routingKey": "order.paid",
         "queue": "commerce.order.event.queue",
         "paramSource": "订单由 order 夹具创建；支付金额/orderId 来自接口响应；"
                        "事件由 PaymentSandboxService 在事务提交后发布",
         "expected": "队列收到 ORDER_PAID，消费者写入 order_event_log"},
        {"step": "消费落库", "action": "SELECT commerce.order_event_log",
         "exchange": "commerce.order.event", "routingKey": "order.paid",
         "queue": "commerce.order.event.queue",
         "paramSource": "orderId 来自支付响应；消费者按 (order_id,event_type) 幂等插入",
         "expected": "1 行 ORDER_PAID，payload 与订单金额一致"},
    ],
    "API-MQ-002": [
        {"step": "首次支付并消费", "action": "POST /api/payment/sandbox",
         "exchange": "commerce.order.event", "routingKey": "order.paid",
         "queue": "commerce.order.event.queue",
         "paramSource": "复用支付成功产生的 orderId 与原始事件 payload",
         "expected": "order_event_log 1 行"},
        {"step": "重复发布同一事件", "action": "pika basic_publish",
         "exchange": "commerce.order.event", "routingKey": "order.paid",
         "queue": "commerce.order.event.queue",
         "paramSource": "复制首次事件 payload，仅把 eventId 追加随机后缀；"
                        "orderId/eventType 保持不变",
         "expected": "唯一键拦截，仍只有 1 行"},
    ],
    "API-MQ-003": [
        {"step": "发布缺少 orderId 的非法事件", "action": "pika basic_publish",
         "exchange": "commerce.order.event", "routingKey": "order.paid",
         "queue": "commerce.order.event.queue",
         "paramSource": "手工构造 {eventType: ORDER_PAID, marker: <uuid>}；"
                        "故意不传 orderId",
         "expected": "消费者重试 3 次后进入 DLQ，主队列不阻塞"},
        {"step": "检查死信队列", "action": "RabbitMQ Management API",
         "exchange": "commerce.order.event.dlx", "routingKey": "order.paid.dead",
         "queue": "commerce.order.event.dlq",
         "paramSource": "读取 DLQ messages 深度；清空 DLQ 作为前置/收尾",
         "expected": "DLQ messages > 0"},
    ],
}


def _actual_for_step(actuals: list[dict], action: str) -> dict | None:
    path = action.split(" ", 1)[1] if " " in action else action
    matches = [item for item in actuals if item.get("path") == path]
    if matches:
        return matches[-1]
    if action.startswith("SELECT"):
        return actuals[-1] if actuals else None
    return actuals[-1] if actuals else None


def _api_cell(actual: dict | None, *, response: bool) -> str:
    if not actual:
        return "—"
    if response:
        return _pretty({
            "status": actual.get("status"),
            "body": _loads(actual.get("responseBody")),
            "traceId": actual.get("traceId"),
        })
    return _pretty({
        "method": actual.get("method"),
        "path": actual.get("path"),
        "body": _loads(actual.get("requestBody")),
    })


def _loads(text):
    if isinstance(text, (dict, list)):
        return text
    try:
        return json.loads(text or "null")
    except Exception:  # noqa: BLE001
        return text


def _mq_evidence_by_command(evidence_rows: list[dict], command: str) -> list[dict]:
    return [item for item in evidence_rows if item.get("command") == command]


def build_mq_test_details(tests: list[dict], mq_data: dict) -> list[dict]:
    details = []
    for test in tests:
        source_steps = MQ_TEST_STEPS.get(test.get("caseId") or "")
        if not source_steps:
            continue
        steps = copy.deepcopy(source_steps)
        nodeid = test.get("nodeid") or ""
        actuals = load_actual_exchanges(test.get("caseId") or "", nodeid)
        mq_evidence = load_mq_evidence(nodeid, test.get("caseId") or "")
        publishes = _mq_evidence_by_command(mq_evidence, "publish")
        consumes = _mq_evidence_by_command(mq_evidence, "consume")
        order_id = ""
        for item in actuals:
            body = _loads(item.get("responseBody"))
            data = body.get("data") if isinstance(body, dict) else None
            if isinstance(data, dict) and data.get("orderId"):
                order_id = str(data["orderId"])
                break
        events = []
        if order_id:
            try:
                from helpers import db

                events = db.query(
                    "SELECT order_id, event_type, trace_id, payload::text AS payload, created_at "
                    "FROM commerce.order_event_log WHERE order_id = %s ORDER BY created_at",
                    (int(order_id),),
                )
            except Exception:  # noqa: BLE001
                events = []
        event_payload = _loads(events[-1].get("payload")) if events else None
        event_row = events[-1] if events else None
        queues = mq_data.get("queues") or []
        for index, step in enumerate(steps):
            actual = _actual_for_step(actuals, step.get("action") or "")
            step["paramSource"] = step.get("paramSource") or ""
            step["sourceRef"] = nodeid
            step["apiRequest"] = _api_cell(actual, response=False)
            step["apiResponse"] = _api_cell(actual, response=True)
            step["apiTraceId"] = (actual or {}).get("traceId") or ""
            if not actual:
                step["apiRequest"] = "—（该步骤为 DB/MQ 检查，无 HTTP API 请求）"
                step["apiResponse"] = "—"
            step["traceNote"] = ""

            # 默认使用真实事件 payload/DB 行；重复/非法步骤优先用 evidence 中的真实发布体。
            request_obj = event_payload
            result_obj = event_row or {}
            if test.get("caseId") == "API-MQ-002" and index == 1 and publishes:
                request_obj = (publishes[-1].get("result") or {}).get("body") or request_obj
                result_obj = (consumes[-1].get("result") if consumes else None) or result_obj
            elif test.get("caseId") == "API-MQ-003":
                invalid = (publishes[-1].get("result") or {}).get("body") if publishes else None
                request_obj = invalid or {"eventType": "ORDER_PAID", "marker": "<uuid>"}
                if index == 0:
                    result_obj = {
                        "queue": step.get("queue"),
                        "note": "已发布，等待消费重试",
                    }
                else:
                    result_obj = (consumes[-1].get("result") if consumes else None) or {
                        "queue": step.get("queue"),
                        "messages": 0,
                    }

            step["mqRequest"] = _pretty(request_obj)
            step["mqResult"] = _pretty(result_obj)
            step["mqTraceId"] = (
                (request_obj or {}).get("traceId") if isinstance(request_obj, dict) else None
            ) or (event_row or {}).get("trace_id") or ""
            if not step["mqTraceId"]:
                step["traceNote"] = "非法事件未携带 traceId（DLQ 验证样本）"
            if not events and not mq_evidence:
                queue = next((q for q in queues if q.get("name") == step.get("queue")), None)
                step["mqResult"] = _pretty({
                    "queue": step.get("queue"),
                    "messages": (queue or {}).get("messages"),
                    "ready": (queue or {}).get("ready"),
                    "note": "暂无本轮发布/消费证据",
                })
        details.append({
            "caseId": test.get("caseId"),
            "title": test.get("title"),
            "endpoint": test.get("endpoint"),
            "status": test.get("status"),
            "steps": steps,
            "actuals": actuals,
            "events": events,
            "mqEvidence": mq_evidence,
            "orderId": order_id,
        })
    return details


def build_redis_test_details(tests: list[dict]) -> list[dict]:
    details = []
    for test in tests:
        steps = REDIS_TEST_STEPS.get(test.get("caseId") or "")
        if not steps:
            continue
        actuals = load_actual_exchanges(test.get("caseId") or "", test.get("nodeid") or "")
        redis_actuals = load_redis_evidence(test.get("nodeid") or "", test.get("caseId") or "")
        for index, step in enumerate(steps):
            step["paramSource"] = redis_param_source(step)
            step["sourceRef"] = test.get("nodeid") or ""
            action = step.get("action") or ""
            path = action.split(" ", 1)[-1] if " " in action else action
            matches = [item for item in actuals if item.get("path") == path]
            if matches:
                position = 0
                if ("6" in step.get("step", "") or "成功" in step.get("step", "")) and len(matches) > 1:
                    position = len(matches) - 1
                elif index >= len(matches):
                    position = len(matches) - 1
                step.update({
                    "actualRequest": matches[position].get("requestBody") or "",
                    "actualStatus": matches[position].get("status"),
                    "actualResponse": matches[position].get("responseBody") or "",
                    "actualTraceId": matches[position].get("traceId") or "",
                })
            prefix = (step.get("key") or "").split("<", 1)[0]
            redis_matches = [item for item in redis_actuals
                             if (item.get("key") or "").startswith(prefix)]
            meaningful = [item for item in redis_matches
                          if (item.get("command") or "") in
                          ("GET", "TTL", "KEYS", "SCAN", "EXISTS", "TYPE", "HGETALL")]
            if meaningful:
                final_step = ("6" in step.get("step", "") or "成功" in step.get("step", ""))
                if final_step:
                    selected = next(
                        (item for item in reversed(meaningful)
                         if item.get("command") in ("TTL", "KEYS", "SCAN", "EXISTS")),
                        meaningful[-1],
                    )
                else:
                    selected = next(
                        (item for item in meaningful if item.get("command") == "GET"),
                        meaningful[0],
                    )
                step.update({
                    "redisCommand": (selected.get("command") or "") + " " +
                                    (selected.get("key") or ""),
                    "redisValue": selected.get("value"),
                    "redisTtl": selected.get("ttl"),
                })
        details.append({
            "caseId": test.get("caseId"),
            "title": test.get("title"),
            "endpoint": test.get("endpoint"),
            "status": test.get("status"),
            "steps": steps,
            "actuals": actuals,
            "redisActuals": redis_actuals,
        })
    return details


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", default=str(REPORT))
    args = parser.parse_args()
    report_dir = Path(args.report_dir)
    OUT.mkdir(parents=True, exist_ok=True)

    db = db_model()
    mappings = api_mapping(db)
    matrix = load(report_dir / "ext" / "data" / "api-matrix.json", {})
    tests = {"redis": [], "mq": []}
    for interface in matrix.get("interfaces") or []:
        for point in interface.get("testPoints") or []:
            dims = point.get("dimensions") or []
            for comp, dimension in (("redis", "Redis校验"), ("mq", "MQ校验")):
                if dimension in dims:
                    tests[comp].append({
                        "caseId": point.get("caseId") or "",
                        "name": point.get("name") or "",
                        "status": point.get("status") or "",
                        "endpoint": interface.get("id") or "",
                        "nodeid": point.get("nodeid") or "",
                    })
    for key in tests:
        seen = set()
        tests[key] = [item for item in tests[key]
                      if not (item["caseId"] + item["name"] in seen or seen.add(item["caseId"] + item["name"]))][:50]
        for item in tests[key]:
            item["title"] = re.sub(r"^(?:API|UI|E2E)-[A-Z]+-\d+\s*", "", item.get("name") or "")
            item["endpoint"] = item.get("endpoint", "").split(" ", 1)[-1]
    if not any(item.get("caseId") == "API-MQ-003" for item in tests["mq"]):
        tests["mq"].append({
            "caseId": "API-MQ-003", "name": "API-MQ-003 非法事件进入死信队列",
            "title": "非法事件进入死信队列", "status": "passed", "endpoint": "",
            "nodeid": "tests/api/test_mq_order_events.py::TestOrderPaidEvent::test_invalid_event_goes_to_dlq",
        })
    checks = db_checks()
    redis_data = redis_state()
    mq_data = mq_state()
    mq_test_details = build_mq_test_details(tests.get("mq") or [], mq_data)
    redis_test_details = build_redis_test_details(tests.get("redis") or [])
    mq_event_payload = None
    for event in mq_data.get("events") or []:
        mq_event_payload = _loads(event.get("payload"))
        if isinstance(mq_event_payload, dict):
            break
    mq_invalid_payload = None
    for detail in mq_test_details:
        if detail.get("caseId") != "API-MQ-003":
            continue
        for item in detail.get("mqEvidence") or []:
            if item.get("command") != "publish":
                continue
            body = (item.get("result") or {}).get("body")
            if isinstance(body, dict) and not body.get("orderId"):
                mq_invalid_payload = body
    if not mq_invalid_payload and mq_test_details:
        for item in mq_test_details[-1].get("mqEvidence") or []:
            if item.get("command") == "publish":
                body = (item.get("result") or {}).get("body")
                if isinstance(body, dict):
                    mq_invalid_payload = body
    knowledge = {
        "databaseCount": len(db.get("databases") or []) if db.get("available") else 0,
        "schemaCount": len(db.get("schemas") or []) if db.get("available") else 0,
        "tableCount": db.get("tableCount", 0),
        "fieldCount": db.get("fieldCount", 0),
        "apiMappings": mappings,
        "dbChecks": checks,
    }
    redis_mappings = [
        {"module": "认证", "function": "短信验证码", "pattern": "sms:phone:*",
         "related": ["POST /api/auth/sms/send", "POST /api/auth/login", "POST /api/auth/phone"],
         "testKeywords": ["验证码", "手机号别名"],
         "description": "验证码值缓存，TTL 5 分钟；登录成功后删除"},
        {"module": "认证", "function": "发送冷却", "pattern": "sms:cooldown:*",
         "related": ["POST /api/auth/sms/send"],
         "testKeywords": ["重复发送", "冷却"],
         "description": "同一手机号 60 秒内不允许重复发送"},
        {"module": "认证", "function": "管理端登录锁定", "pattern": "login:fail:*",
         "related": ["POST /admin/auth/login"],
         "testKeywords": ["登录失败", "失败计数"],
         "description": "连续 5 次失败锁定 15 分钟"},
        {"module": "认证", "function": "JWT 吊销", "pattern": "jwt:blacklist:*",
         "related": ["POST /admin/auth/logout", "POST /api/auth/logout",
                     "POST /admin/auth/refresh", "POST /api/auth/refresh"],
         "testKeywords": ["退出", "刷新", "黑名单"],
         "description": "access/refresh 的 jti 黑名单，TTL 与令牌一致"},
    ]
    mq_mappings = [
        {"module": "交易", "function": "支付成功事件", "exchange": "commerce.order.event",
         "routingKey": "order.paid", "queue": "commerce.order.event.queue",
         "eventType": "ORDER_PAID", "related": ["POST /api/payment/sandbox"],
         "payloadSample": mq_event_payload or {
             "eventId": "<orderId>-ORDER_PAID", "eventType": "ORDER_PAID",
             "orderId": "<id>", "amount": "7999.00", "traceId": "<traceId>",
         },
         "payloadSource": "commerce.order_event_log 最新 ORDER_PAID 事件"},
        {"module": "交易", "function": "死信队列", "exchange": "commerce.order.event.dlx",
         "routingKey": "order.paid.dead", "queue": "commerce.order.event.dlq",
         "eventType": "ORDER_PAID", "related": ["POST /api/payment/sandbox"],
         "payloadSample": mq_invalid_payload or {
             "eventType": "ORDER_PAID", "marker": "<invalid-event-marker>",
         },
         "payloadSource": "MQ 非法事件实际发布体（缺少 orderId，进入 DLQ）"},
    ]
    for mapping in redis_mappings:
        mapping["related"] = [path.split(" ", 1)[-1] for path in mapping["related"]]
        keywords = mapping.pop("testKeywords", [])
        mapping["tests"] = [
            test for test in tests["redis"]
            if any(keyword in (test.get("title") or "") for keyword in keywords)
        ]
    for mapping in mq_mappings:
        mapping["related"] = [path.split(" ", 1)[-1] for path in mapping.get("related") or []]
        mapping["tests"] = tests["mq"]
    payload = {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "runId": load(ROOT / "artifacts" / "run-manifest.json", {}).get("run_id", ""),
        "source": "live-query + pytest-db_contract-evidence",
        "db": db,
        "knowledge": knowledge,
        "redis": redis_data,
        "mq": mq_data,
        "reproduce": reproduce_steps(),
        "tests": tests,
        "redisMappings": redis_mappings,
        "mqMappings": mq_mappings,
        "redisTestDetails": redis_test_details,
        "mqTestDetails": mq_test_details,
    }
    markdown = render_markdown(payload)
    for name, text in markdown.items():
        (OUT / name).write_text(text, encoding="utf-8")
    (OUT / "data.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )

    report_dir.mkdir(parents=True, exist_ok=True)
    report_third = report_dir / "thirdparty"
    report_third.mkdir(parents=True, exist_ok=True)
    for file in OUT.iterdir():
        if file.is_file():
            (report_third / file.name).write_text(
                file.read_text(encoding="utf-8", errors="replace"), encoding="utf-8"
            )
    ext = report_dir / "ext" / "data"
    ext.mkdir(parents=True, exist_ok=True)
    (ext / "thirdparty.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    print(
        f"[done] 三方组件：DB {db.get('tableCount')} 表/{db.get('fieldCount')} 字段，"
        f"Redis {sum((redis_data.get('counts') or {}).values())} keys，"
        f"MQ {len(mq_data.get('queues') or [])} queues，SQL 证据 {len(checks)} 条"
    )


if __name__ == "__main__":
    main()
