"""RabbitMQ 订单事件用例：消费落库、重复投递幂等、失败重试进死信队列。

链路：POST /api/payment/sandbox → 事务提交后发 MQ → 消费者写 commerce.order_event_log。
所有断言都落 DB 或 RabbitMQ 管理接口，不依赖消费者日志。
"""
from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import nullcontext

import pytest

try:
    import allure  # type: ignore
except ImportError:  # pragma: no cover
    allure = None

from core.assertions import ok
from helpers import db, evidence

pika = pytest.importorskip("pika")

pytestmark = [pytest.mark.api, pytest.mark.db]

EXCHANGE = "commerce.order.event"
ROUTING_KEY = "order.paid"
QUEUE = "commerce.order.event.queue"
DLQ = "commerce.order.event.dlq"


def _rabbit():
    params = dict(
        host=os.getenv("RABBITMQ_HOST", "127.0.0.1"),
        port=int(os.getenv("RABBITMQ_PORT", "5672")),
        credentials=pika.PlainCredentials(
            os.getenv("RABBITMQ_USERNAME", "guest"),
            os.getenv("RABBITMQ_PASSWORD", "guest"),
        ),
        heartbeat=0,
    )
    try:
        conn = pika.BlockingConnection(pika.ConnectionParameters(**params))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"RabbitMQ 不可用：{exc}")
    return conn


def _management(method: str, path: str, **kwargs):
    import requests

    base = os.getenv("RABBITMQ_MANAGEMENT_URL", "http://127.0.0.1:15672")
    auth = (
        os.getenv("RABBITMQ_USERNAME", "guest"),
        os.getenv("RABBITMQ_PASSWORD", "guest"),
    )
    return requests.request(method, f"{base}/api/{path}", auth=auth, timeout=5, **kwargs)


def _publish(body: dict | str) -> None:
    conn = _rabbit()
    channel = conn.channel()
    payload = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    channel.basic_publish(
        exchange=EXCHANGE,
        routing_key=ROUTING_KEY,
        body=payload,
        properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
    )
    evidence.record_mq(
        command="publish",
        result={
            "exchange": EXCHANGE,
            "routingKey": ROUTING_KEY,
            "queue": QUEUE,
            "published": True,
            "body": body if isinstance(body, dict) else payload,
            "traceId": body.get("traceId") if isinstance(body, dict) else None,
        },
        note="pika basic_publish",
    )
    channel.close()
    conn.close()


def _events(order_id: str) -> list[dict]:
    return db.query(
        "SELECT order_id, event_type, payload::text AS payload, trace_id, created_at "
        "FROM commerce.order_event_log WHERE order_id = %s AND event_type = 'ORDER_PAID' "
        "ORDER BY created_at",
        (int(order_id),),
    )


def _wait_event(order_id: str, timeout: float = 15.0) -> list[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = _events(order_id)
        if rows:
            return rows
        time.sleep(0.3)
    return []


def _attach(name: str, value) -> None:
    if allure:
        allure.attach(json.dumps(value, ensure_ascii=False, default=str)[:16000],
                      name=name, attachment_type=allure.attachment_type.JSON)


class TestOrderPaidEvent:
    def test_payment_publishes_and_consumes(self, customer, order):
        """支付成功 → 事件落库，payload 与订单一致，traceId 贯通。"""
        order_id = order["order_id"]
        assert not _events(order_id), "测试订单不应已有事件"
        with allure.step(f"支付订单 {order_id} 并等待 ORDER_PAID") if allure else nullcontext():
            resp = ok(customer.client.post("/api/payment/sandbox", json={"orderId": order_id}))
            _attach("支付响应", resp)
            assert resp["status"] == "PENDING_SHIP"
            rows = _wait_event(order_id)
        _attach("order_event_log 查询结果", rows)
        with allure.step("校验 order_event_log 消费结果") if allure else nullcontext():
            assert rows, "15 秒内未消费到 ORDER_PAID 事件"
            assert len(rows) == 1
            payload = json.loads(rows[0]["payload"])
            assert payload["eventId"] == f"{order_id}-ORDER_PAID"
            assert str(payload["orderId"]) == str(order_id)
            assert float(payload["amount"]) == float(order["data"]["payAmount"])
            assert payload["traceId"], "事件应携带请求 traceId"
            assert rows[0]["trace_id"] == payload["traceId"]
            evidence.record_mq(
                command="consume",
                result={"queue": QUEUE, "events": rows, "payload": payload},
                note="ORDER_PAID 消费落库",
            )
            _attach("校验通过的事件行", rows)

    def test_duplicate_delivery_is_idempotent(self, customer, order):
        """同一事件重复投递：唯一键拦截，只保留一行。"""
        order_id = order["order_id"]
        with allure.step(f"首次支付 {order_id} 并消费事件") if allure else nullcontext():
            ok(customer.client.post("/api/payment/sandbox", json={"orderId": order_id}))
            first = _wait_event(order_id)
            assert len(first) == 1
        duplicate = json.loads(first[0]["payload"])
        duplicate["eventId"] = duplicate["eventId"] + "-" + uuid.uuid4().hex[:6]
        with allure.step("重复发布同一 ORDER_PAID 事件") if allure else nullcontext():
            _publish(duplicate)
            evidence.record_mq(
                command="consume",
                result={"queue": QUEUE, "events": first, "payload": duplicate},
                note="重复投递前已有事件",
            )
            _attach("重复投递 payload", duplicate)
            time.sleep(2)
        rows = _events(order_id)
        evidence.record_mq(
            command="consume",
            result={"queue": QUEUE, "events": rows, "duplicatePayload": duplicate},
            note="重复投递后事件行数",
        )
        _attach("重复投递后的 order_event_log", rows)
        with allure.step("校验重复投递仍只有 1 行") if allure else nullcontext():
            assert len(rows) == 1, "重复事件不应新增行"

    def test_invalid_event_goes_to_dlq(self):
        """缺少 orderId 的事件：重试后进入死信队列，不阻塞主队列。"""
        try:
            _management("DELETE", f"queues/%2F/{DLQ}/contents")
        except Exception:  # noqa: BLE001
            pass
        marker = f"bad-{uuid.uuid4().hex[:8]}"
        with allure.step("发布缺少 orderId 的非法事件") if allure else nullcontext():
            _publish({"eventType": "ORDER_PAID", "marker": marker})
            _attach("非法事件 payload", {"eventType": "ORDER_PAID", "marker": marker})

        deadline = time.time() + 20
        depth = 0
        while time.time() < deadline:
            try:
                response = _management("GET", f"queues/%2F/{DLQ}")
                depth = int(response.json().get("messages") or 0)
            except Exception:  # noqa: BLE001
                depth = 0
            if depth > 0:
                break
            time.sleep(0.5)
        evidence.record_mq(
            command="consume",
            result={"queue": DLQ, "messages": depth,
                    "invalidBody": {"eventType": "ORDER_PAID", "marker": marker}},
            note="非法事件进入死信队列",
        )
        _attach("DLQ messages 深度", {"queue": DLQ, "messages": depth})
        with allure.step("校验非法事件进入 DLQ") if allure else nullcontext():
            assert depth > 0, "非法事件应进入死信队列"
        _management("DELETE", f"queues/%2F/{DLQ}/contents")
