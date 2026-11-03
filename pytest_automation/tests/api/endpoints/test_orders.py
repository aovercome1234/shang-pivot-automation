"""接口级试点：POST /api/orders 的测试点分组。

组织方式：
- 一个接口一个类；类级上下文复用会员/地址/SKU，减少每个测试点重复登录与造数；
- 逆向/边界用参数化测试点保留独立失败粒度；
- 正向事务一次执行，按 API → DB → MQ 分层断言；
- 幂等、大数据量、越权仍作为特殊场景独立执行，避免共享可变状态。

不是把所有断言塞进一个巨大用例：API 失败时仍能定位到具体测试点；
MQ 采用轮询，不依赖固定 sleep。
"""
from __future__ import annotations

import json
import time
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

try:
    import allure  # type: ignore
except ImportError:  # pragma: no cover
    allure = None

from core.assertions import error, ok
from helpers import db
from helpers.auth_helper import (
    add_to_cart, create_address, new_customer, pick_sku, submit_order,
)
from helpers.data_factory import address_payload, order_payload, unique_key
from helpers.db_contract import verify_write

pytestmark = [pytest.mark.api]


def _step(name: str):
    return allure.step(name) if allure else nullcontext()


@pytest.fixture(scope="class")
def endpoint_context():
    """同一接口测试点共享只读上下文；每个测试仍用唯一幂等键/订单。"""
    customer = new_customer()
    try:
        sku = pick_sku(customer.client)
        address = create_address(customer.client, address_payload(customer.phone))
        yield SimpleNamespace(customer=customer, sku=sku, address=address)
    finally:
        customer.client.close()


def _payload(context, **overrides):
    payload = order_payload(
        address_id=context.address, sku_id=context.sku["sku_id"], quantity=1
    )
    payload.update(overrides)
    return payload


def _wait_order_event(order_id: str, timeout: float = 15.0) -> list[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = db.query(
            "SELECT order_id, event_type, trace_id, payload::text AS payload, created_at "
            "FROM commerce.order_event_log WHERE order_id = %s AND event_type = 'ORDER_PAID' "
            "ORDER BY created_at",
            (int(order_id),),
        )
        if rows:
            return rows
        time.sleep(0.3)
    return []


class TestCreateOrderEndpoint:
    @pytest.mark.P0
    @pytest.mark.parametrize(
        ("name", "overrides", "keyword"),
        [
            ("缺失幂等键", {"idempotentKey": None}, "idempotentKey"),
            ("幂等键为空白", {"idempotentKey": "   "}, "idempotentKey"),
            ("数量为 0", {"quantity": 0}, "数量"),
            ("数量为负数", {"quantity": -1}, "数量"),
            ("无购物车明细且无 SKU", {"skuId": None, "quantity": None}, "购物车项"),
        ],
    )
    def test_validation_points(self, endpoint_context, name, overrides, keyword):
        """逆向/边界测试点：同一接口、同一上下文，独立参数化失败粒度。"""
        payload = _payload(endpoint_context)
        if overrides.get("idempotentKey", "keep") is None:
            payload.pop("idempotentKey", None)
        else:
            payload.update(overrides)
        with _step(f"验证 {name}"):
            response = endpoint_context.customer.client.post("/api/orders", json=payload)
            body = error(response, code=40000)
            assert keyword in body["msg"], f"{name}: {body}"

    @pytest.mark.P1
    def test_boundary_quantity_one(self, endpoint_context):
        """边界值下界：quantity=1 创建待支付订单，DB 行同步落库。"""
        with _step("数量下界 1 创建订单"):
            payload = _payload(endpoint_context, quantity=1)
            data = submit_order(endpoint_context.customer.client, payload)
            order_id = str(data["orderId"])
            assert data["status"] == "PENDING_PAY"
            row = verify_write("POST /api/orders", payload, response=order_id)
            assert row["status"] == "PENDING_PAY"
            ok(endpoint_context.customer.client.post(f"/api/orders/{order_id}/cancel"))

    @pytest.mark.P0
    @pytest.mark.db
    def test_positive_api_db_mq(self, endpoint_context):
        """正向事务：一次下单 + 支付，分层校验 API、DB、MQ。"""
        if not db.available():
            pytest.skip("数据库不可达：正向场景需要 DB/MQ 事件校验")
        context = endpoint_context
        item = add_to_cart(context.customer.client, context.sku["sku_id"], 2)
        payload = order_payload(
            address_id=context.address,
            cart_item_ids=[str(item["cartItemId"])],
        )
        with _step("API：提交订单"):
            data = submit_order(context.customer.client, payload)
            order_id = str(data["orderId"])
            assert data["status"] == "PENDING_PAY"
            assert float(data["payAmount"]) >= float(data["goodsAmount"])

        with _step("API：支付订单"):
            payment = ok(
                context.customer.client.post("/api/payment/sandbox", json={"orderId": order_id})
            )
            assert payment["status"] == "PENDING_SHIP"
            payment_trace = (
                context.customer.client.last_response.json().get("traceId")
                if context.customer.client.last_response is not None else ""
            )

        with _step("DB：订单与库存锁定"):
            verify_write("POST /api/orders", payload, response=order_id)
            order_row = db.order_row(order_id)
            assert order_row["status"] == "PENDING_SHIP"
            items = db.order_items(order_id)
            assert len(items) == 1 and int(items[0]["quantity"]) == 2

        with _step("MQ：ORDER_PAID 消费落库"):
            events = _wait_order_event(order_id)
            assert events, "15 秒内未消费到 ORDER_PAID"
            event = events[0]
            event_payload = json.loads(event["payload"])
            assert event_payload["orderId"] == order_id
            assert float(event_payload["amount"]) == float(data["payAmount"])
            if payment_trace:
                assert event["trace_id"] == payment_trace, "MQ traceId 未贯通"

    @pytest.mark.P0
    def test_idempotency_replay(self, endpoint_context):
        """特殊场景：幂等重放不重复锁库存、不生成第二张订单。"""
        context = endpoint_context
        if not db.available():
            pytest.skip("数据库不可达：幂等场景需要库存锁定断言")
        before = db.stock_of(context.sku["sku_id"])
        item = add_to_cart(context.customer.client, context.sku["sku_id"], 1)
        payload = order_payload(
            address_id=context.address, cart_item_ids=[str(item["cartItemId"])]
        )
        first = submit_order(context.customer.client, payload)
        second = submit_order(context.customer.client, payload)
        order_id = str(first["orderId"])
        assert str(second["orderId"]) == order_id
        after = db.stock_of(context.sku["sku_id"])
        assert after["locked_stock"] == before["locked_stock"] + 1
        ok(context.customer.client.post(f"/api/orders/{order_id}/cancel"))

    @pytest.mark.P1
    def test_foreign_address_rejected(self, endpoint_context):
        """特殊场景：使用他人地址下单被拒绝。"""
        other = new_customer()
        try:
            foreign = create_address(other.client, address_payload(other.phone))
            payload = _payload(endpoint_context, addressId=foreign)
            body = error(
                endpoint_context.customer.client.post("/api/orders", json=payload),
                code=40000,
            )
            assert "地址" in body["msg"]
        finally:
            other.client.close()

    @pytest.mark.P1
    @pytest.mark.serial
    def test_bulk_twenty_items(self, endpoint_context):
        """特殊场景：20 个购物车项合并下单，API 明细与 DB 一致。"""
        context = endpoint_context
        if not db.available():
            pytest.skip("数据库不可达：大数据量场景需要库存数据")
        skus = db.query(
            """
            SELECT s.sku_id, k.price
              FROM commerce.stock s
              JOIN commerce.sku k ON k.id = s.sku_id AND k.deleted = FALSE
              JOIN commerce.spu p ON p.id = k.spu_id AND p.deleted = FALSE
             WHERE s.deleted = FALSE AND p.status = 'ON' AND k.status = 'ENABLED'
               AND s.physical_stock - s.locked_stock >= 1
             ORDER BY s.sku_id LIMIT 20
            """
        )
        assert len(skus) == 20, f"可售 SKU 不足 20 个（实际 {len(skus)}）"
        ids = [
            str(add_to_cart(context.customer.client, str(item["sku_id"]), 1)["cartItemId"])
            for item in skus
        ]
        data = submit_order(
            context.customer.client,
            order_payload(address_id=context.address, cart_item_ids=ids),
        )
        detail = ok(context.customer.client.get(f"/api/orders/{data['orderId']}"))
        assert len(detail["items"]) == 20
        assert float(detail["order"]["totalAmount"]) == pytest.approx(
            sum(float(item["price"]) for item in skus), abs=0.01
        )
        ok(context.customer.client.post(f"/api/orders/{data['orderId']}/cancel"))

    @pytest.mark.P1
    def test_unauthenticated_rejected(self, endpoint_context, anonymous):
        """异常场景：未认证下单返回 401，而不是 400/500。"""
        payload = _payload(endpoint_context)
        response = anonymous.post("/api/orders", json=payload)
        body = error(response, http_status=401)
        assert body["code"] in (40100, 40103)
