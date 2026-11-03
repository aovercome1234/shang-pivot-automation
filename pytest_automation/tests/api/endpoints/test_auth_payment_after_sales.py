"""接口级迁移：认证、支付、售后、评价。

每个类对应一个业务接口；正向链路做 API/DB/中间件分层，逆向校验参数化，
特殊场景（幂等、审核/隐藏）独立；旧专项用例继续作为回归对照。
"""
from __future__ import annotations

import json
import os
import time
from contextlib import nullcontext

import pytest

try:
    import allure  # type: ignore
except ImportError:  # pragma: no cover
    allure = None

from config.settings import settings
from core.api_client import ApiClient
from core.assertions import error, ok
from helpers import db
from helpers.auth_helper import add_to_cart, create_address, submit_order
from helpers.data_factory import address_payload, order_payload, unique_key, unique_phone
from helpers.db_contract import verify_write

pytestmark = [pytest.mark.api]


def _step(name: str):
    return allure.step(name) if allure else nullcontext()


def _shipped_order(customer, admin, sku_id: str, confirm: bool = False) -> str:
    address_id = create_address(customer.client, address_payload(customer.phone))
    item = add_to_cart(customer.client, sku_id, 1)
    order = submit_order(
        customer.client,
        order_payload(address_id=address_id, cart_item_ids=[str(item["cartItemId"])]),
    )
    order_id = str(order["orderId"])
    ok(customer.client.post("/api/payment/sandbox", json={"orderId": order_id}))
    ok(admin.post(
        f"/admin/orders/{order_id}/ship",
        json={"carrier": "顺丰速运", "trackingNo": f"SF{order_id[-8:]}"},
    ))
    if confirm:
        ok(customer.client.post(f"/api/orders/{order_id}/confirm"))
    return order_id


def _wait_event(order_id: str, timeout: float = 15.0) -> list[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = db.query(
            "SELECT order_id, event_type, trace_id, payload::text AS payload "
            "FROM commerce.order_event_log WHERE order_id = %s AND event_type = 'ORDER_PAID'",
            (int(order_id),),
        )
        if rows:
            return rows
        time.sleep(0.3)
    return []


class TestCustomerAuth:
    @pytest.mark.P0
    def test_sms_login_api_redis_db(self):
        redis = pytest.importorskip("redis")
        client = redis.Redis(host=os.getenv("REDIS_HOST", "127.0.0.1"),
                             port=int(os.getenv("REDIS_PORT", "6379")),
                             db=int(os.getenv("REDIS_DB", "0")), decode_responses=True,
                             socket_connect_timeout=2)
        try:
            client.ping()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Redis 不可用：{exc}")
        phone = unique_phone()
        api = ApiClient(settings.api_mall_base)
        try:
            with _step("发送验证码"):
                sms = ok(api.post("/api/auth/sms/send", json={"phone": phone}))
                assert sms["cooldownSec"] == 60
                assert client.get(f"sms:phone:{phone}") == settings.sms_code
                assert 0 < client.ttl(f"sms:phone:{phone}") <= 300
            with _step("验证码登录"):
                login = ok(api.post("/api/auth/login", json={
                    "phone": phone, "code": settings.sms_code, "clientType": "web",
                }))
                assert login["accessToken"] and login["customer"]["status"] == "NORMAL"
                assert not client.exists(f"sms:phone:{phone}"), "登录成功应消费验证码"
            with _step("DB：会员已创建"):
                row = db.query_one("SELECT id, status FROM identity.customer WHERE phone=%s", (phone,))
                assert row and row["status"] == "NORMAL"
        finally:
            api.close()
            client.close()

    @pytest.mark.P1
    @pytest.mark.parametrize(
        ("name", "payload", "code"),
        [
            ("手机号格式错误", {"phone": "abc", "code": "123456", "clientType": "web"}, 40000),
            ("clientType 非法", {"phone": "13900000000", "code": "123456", "clientType": "x"}, 40000),
        ],
    )
    def test_auth_validation_points(self, anonymous, name, payload, code):
        with _step(f"认证校验：{name}"):
            body = error(anonymous.post("/api/auth/login", json=payload), code=code)
            assert body.get("msg")


class TestPaymentSandbox:
    @pytest.mark.P0
    @pytest.mark.db
    def test_payment_api_db_mq(self, customer, order):
        order_id = order["order_id"]
        with _step("API：沙箱支付"):
            data = ok(customer.client.post("/api/payment/sandbox", json={"orderId": order_id}))
            assert data["status"] == "PENDING_SHIP"
        with _step("DB：订单/支付落库"):
            row = verify_write("POST /api/payment/sandbox", {"orderId": order_id},
                               natural={"order_id": order_id})
            assert row["status"] == "PAID"
            assert db.order_row(order_id)["status"] == "PENDING_SHIP"
        with _step("MQ：ORDER_PAID 事件"):
            events = _wait_event(order_id)
            assert events and json.loads(events[0]["payload"])["orderId"] == order_id

    @pytest.mark.P1
    @pytest.mark.db
    def test_payment_twice_single_row(self, customer, order):
        order_id = order["order_id"]
        ok(customer.client.post("/api/payment/sandbox", json={"orderId": order_id}))
        error(customer.client.post("/api/payment/sandbox", json={"orderId": order_id}), code=40902)
        row = db.query_one("SELECT count(*) AS n FROM commerce.payment WHERE order_id=%s AND deleted=FALSE",
                           (order_id,))
        assert int(row["n"]) == 1


class TestAfterSale:
    @pytest.mark.P0
    @pytest.mark.db
    def test_apply_and_audit_api_db(self, customer, admin, sku):
        order_id = _shipped_order(customer, admin, sku["sku_id"])
        payload = {"orderId": order_id, "type": "REFUND",
                   "reason": f"接口级售后 {unique_key('as')}",
                   "evidenceKeys": ["PRODUCT/seed/product_1.jpg"]}
        after_sale_id = str(ok(customer.client.post("/api/after-sales", json=payload)))
        row = verify_write("POST /api/after-sales", payload, response=after_sale_id)
        assert row["status"] == "PENDING_AUDIT"
        audit = {"approved": True, "remark": "接口级审核通过"}
        ok(admin.post(f"/admin/after-sales/{after_sale_id}/audit", json=audit))
        row = verify_write("POST /admin/after-sales/{id}/audit", audit,
                           path={"id": after_sale_id})
        assert row["status"] == "COMPLETED"

    @pytest.mark.P1
    @pytest.mark.parametrize(
        ("payload", "keyword"),
        [
            ({"orderId": None}, "必填"),
            ({"orderId": "0", "type": "NOT_A_TYPE", "reason": "x"}, "type"),
        ],
    )
    def test_after_sale_validation_points(self, customer, payload, keyword):
        body = error(customer.client.post("/api/after-sales", json=payload), code=40000)
        assert keyword in body["msg"]


class TestReview:
    @pytest.mark.P0
    @pytest.mark.db
    def test_create_and_hide_api_db(self, customer, admin, sku):
        order_id = _shipped_order(customer, admin, sku["sku_id"], confirm=True)
        item = db.query_one(
            "SELECT id FROM commerce.order_item WHERE order_id=%s AND deleted=FALSE LIMIT 1",
            (order_id,),
        )
        payload = {"orderItemId": str(item["id"]), "rating": 5,
                   "content": "接口级评价", "picKeys": ["PRODUCT/seed/product_1.jpg"]}
        review_id = str(ok(customer.client.post("/api/reviews", json=payload)))
        row = verify_write("POST /api/reviews", payload, response=review_id)
        assert int(row["rating"]) == 5
        ok(admin.put(f"/admin/reviews/{review_id}/status", json={"status": "HIDDEN"}))
        row = verify_write("PUT /admin/reviews/{id}/status",
                           {"status": "HIDDEN"}, path={"id": review_id})
        assert row["status"] == "HIDDEN"
