#!/usr/bin/env python3
"""三方组件本地操作服务（仅监听 127.0.0.1:8098）。

供扩展报告「Redis 核验」「MQ 核验」页面执行真实查询/写入/删除，避免只能看截图。
安全边界：
  - 只绑定回环地址，无鉴权，禁止暴露到公网；
  - Redis 只支持 string key 的 get/set/del/scan；
  - RabbitMQ 只支持查询队列/拉取消息/发布/清空队列，不删除 exchange/queue；
  - 所有写操作由页面显式提交，不自动执行。
"""
from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

import requests

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None
MQ_BASE = os.getenv("RABBITMQ_MANAGEMENT_URL", "http://127.0.0.1:15672")
MQ_AUTH = (os.getenv("RABBITMQ_USERNAME", "guest"), os.getenv("RABBITMQ_PASSWORD", "guest"))
ALLOWED_KEY = re.compile(r"^[A-Za-z0-9:_\-.*]{1,200}$")


def redis_client():
    import redis

    client = redis.Redis(
        host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, password=REDIS_PASSWORD,
        decode_responses=True, socket_connect_timeout=2, socket_timeout=2,
    )
    client.ping()
    return client


def mq(method: str, path: str, **kwargs):
    return requests.request(method, f"{MQ_BASE}/api/{path}", auth=MQ_AUTH, timeout=5, **kwargs)


def mask_key(key: str) -> str:
    if key.startswith(("sms:phone:", "sms:cooldown:")):
        return key.rsplit(":", 1)[0] + ":" + key.rsplit(":", 1)[-1][:3] + "****"
    return key


class Handler(BaseHTTPRequestHandler):
    server_version = "shang-thirdparty/1.0"

    def _send(self, status: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, {})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        try:
            if parsed.path == "/api/health":
                result = {"redis": False, "rabbitmq": False}
                try:
                    redis_client().ping()
                    result["redis"] = True
                except Exception:  # noqa: BLE001
                    pass
                try:
                    result["rabbitmq"] = mq("GET", "overview").ok
                except Exception:  # noqa: BLE001
                    pass
                return self._send(200, result)
            if parsed.path == "/api/redis/scan":
                pattern = query.get("pattern", "*")
                if not ALLOWED_KEY.match(pattern):
                    return self._send(400, {"error": "非法 pattern"})
                client = redis_client()
                keys = list(client.scan_iter(match=pattern, count=200))[:100]
                rows = []
                for key in keys:
                    kind = client.type(key)
                    rows.append({
                        "key": key, "type": kind, "ttl": client.ttl(key),
                        "value": client.get(key) if kind == "string" else None,
                    })
                return self._send(200, {"pattern": pattern, "count": len(keys), "items": rows})
            if parsed.path == "/api/redis/get":
                key = query.get("key", "")
                if not ALLOWED_KEY.match(key):
                    return self._send(400, {"error": "非法 key"})
                client = redis_client()
                kind = client.type(key)
                return self._send(200, {
                    "key": key, "type": kind, "ttl": client.ttl(key),
                    "value": client.get(key) if kind == "string" else None,
                })
            if parsed.path == "/api/mq/queues":
                response = mq("GET", "queues")
                response.raise_for_status()
                return self._send(200, {"items": response.json()})
            if parsed.path == "/api/mq/messages":
                vhost = query.get("vhost", "/")
                queue = query.get("queue", "")
                if not queue:
                    return self._send(400, {"error": "缺少 queue"})
                response = mq(
                    "POST", f"queues/{quote(vhost, safe='')}/{quote(queue, safe='')}/get",
                    json={"count": int(query.get("count", 10)), "ackmode": "ack_requeue_true",
                          "encoding": "auto", "truncate": 50000},
                )
                response.raise_for_status()
                return self._send(200, {"items": response.json()})
        except Exception as exc:  # noqa: BLE001
            return self._send(500, {"error": str(exc)})
        return self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            body = self._body()
            if parsed.path == "/api/redis/set":
                key = str(body.get("key", ""))
                if not ALLOWED_KEY.match(key):
                    return self._send(400, {"error": "非法 key"})
                ttl = int(body.get("ttl") or 0)
                client = redis_client()
                if ttl > 0:
                    client.set(key, str(body.get("value", "")), ex=ttl)
                else:
                    client.set(key, str(body.get("value", "")))
                return self._send(200, {"ok": True, "key": key, "ttl": client.ttl(key)})
            if parsed.path == "/api/redis/delete":
                key = str(body.get("key", ""))
                if not ALLOWED_KEY.match(key):
                    return self._send(400, {"error": "非法 key"})
                deleted = redis_client().delete(key)
                return self._send(200, {"ok": True, "deleted": deleted, "key": key})
            if parsed.path == "/api/mq/publish":
                vhost = str(body.get("vhost") or "/")
                exchange = str(body.get("exchange") or "commerce.order.event")
                routing_key = str(body.get("routingKey") or "order.paid")
                payload = body.get("payload")
                if not isinstance(payload, str):
                    payload = json.dumps(payload, ensure_ascii=False)
                response = mq(
                    "POST", f"exchanges/{quote(vhost, safe='')}/{quote(exchange, safe='')}/publish",
                    json={"properties": {}, "routing_key": routing_key,
                          "payload": payload, "payload_encoding": "string"},
                )
                response.raise_for_status()
                return self._send(200, {"ok": True, "result": response.json()})
            if parsed.path == "/api/mq/consume":
                vhost = str(body.get("vhost") or "/")
                queue = str(body.get("queue") or "")
                if not queue:
                    return self._send(400, {"error": "缺少 queue"})
                response = mq(
                    "POST", f"queues/{quote(vhost, safe='')}/{quote(queue, safe='')}/get",
                    json={"count": 1, "ackmode": "ack_requeue_false",
                          "encoding": "auto", "truncate": 50000},
                )
                response.raise_for_status()
                return self._send(200, {"ok": True, "items": response.json(),
                                        "note": "ack_requeue_false：消息已从队列删除"})
            if parsed.path == "/api/mq/purge":
                vhost = str(body.get("vhost") or "/")
                queue = str(body.get("queue") or "")
                if body.get("confirm") != "PURGE":
                    return self._send(400, {"error": "需要 confirm=PURGE"})
                response = mq(
                    "DELETE", f"queues/{quote(vhost, safe='')}/{quote(queue, safe='')}/contents"
                )
                response.raise_for_status()
                return self._send(200, {"ok": True})
        except Exception as exc:  # noqa: BLE001
            return self._send(500, {"error": str(exc)})
        return self._send(404, {"error": "not found"})

    def log_message(self, fmt: str, *args) -> None:
        print("[thirdparty]", fmt % args)


def main() -> None:
    port = int(os.getenv("THIRDPARTY_PORT", "8098"))
    print(f"[thirdparty] http://127.0.0.1:{port}  Redis {REDIS_HOST}:{REDIS_PORT}  MQ {MQ_BASE}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
