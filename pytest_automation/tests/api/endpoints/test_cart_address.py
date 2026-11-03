"""接口级试点扩展：购物车项与收货地址。

同一个接口在一个类中组织：
- 类级上下文复用会员/SKU；
- 逆向参数化保留独立失败粒度；
- 正向请求同时校验 API 响应与 DB 行；
- 特殊场景（重复加购合并、默认地址）独立。
"""
from __future__ import annotations

from contextlib import nullcontext

import pytest

try:
    import allure  # type: ignore
except ImportError:  # pragma: no cover
    allure = None

from core.assertions import error, ok
from helpers import db
from helpers.auth_helper import add_to_cart, new_customer, pick_sku
from helpers.data_factory import address_payload
from helpers.db_contract import verify_write

pytestmark = [pytest.mark.api]


def _step(name: str):
    return allure.step(name) if allure else nullcontext()


@pytest.fixture(scope="class")
def cart_context():
    customer = new_customer()
    try:
        yield {"customer": customer, "sku": pick_sku(customer.client)}
    finally:
        customer.client.close()


@pytest.fixture
def cart_flow_context():
    """可变链路使用独立会员，验证点共享上下文不污染加购/合并场景。"""
    customer = new_customer()
    try:
        yield {"customer": customer, "sku": pick_sku(customer.client)}
    finally:
        customer.client.close()


@pytest.fixture(scope="class")
def address_context():
    customer = new_customer()
    try:
        yield {"customer": customer}
    finally:
        customer.client.close()


class TestCreateCartItem:
    @pytest.mark.P1
    @pytest.mark.parametrize(
        ("name", "payload", "http", "code"),
        [
            ("数量 0", {"skuId": "<sku>", "quantity": 0}, 200, 40000),
            ("数量负数", {"skuId": "<sku>", "quantity": -1}, 200, 40000),
        ],
    )
    def test_cart_validation_points(self, cart_context, name, payload, http, code):
        actual = dict(payload)
        if actual.get("skuId") == "<sku>":
            actual["skuId"] = cart_context["sku"]["sku_id"]
        with _step(f"加购校验：{name}"):
            response = cart_context["customer"].client.post("/api/cart/items", json=actual)
            body = error(response, http_status=http, code=code)
            assert body.get("msg")

    @pytest.mark.P0
    @pytest.mark.db
    def test_cart_positive_api_db(self, cart_flow_context):
        customer = cart_flow_context["customer"]
        sku = cart_flow_context["sku"]
        payload = {"skuId": sku["sku_id"], "quantity": 2}
        with _step("API：加入购物车"):
            item = ok(customer.client.post("/api/cart/items", json=payload))
            cart_item_id = str(item["cartItemId"])
            assert item["quantity"] == 2
        with _step("DB：购物车项落库"):
            row = verify_write("POST /api/cart/items", payload, response=item)
            assert str(row["sku_id"]) == str(sku["sku_id"])
            assert int(row["quantity"]) == 2

    @pytest.mark.P1
    @pytest.mark.db
    def test_cart_same_sku_merges(self, cart_flow_context):
        customer = cart_flow_context["customer"]
        sku_id = cart_flow_context["sku"]["sku_id"]
        first = add_to_cart(customer.client, sku_id, 1)
        second = add_to_cart(customer.client, sku_id, 2)
        assert str(first["cartItemId"]) == str(second["cartItemId"])
        assert second["quantity"] == 3
        row = db.query_one(
            "SELECT quantity FROM commerce.cart_item WHERE id = %s",
            (str(second["cartItemId"]),),
        )
        assert row and int(row["quantity"]) == 3


class TestCreateAddress:
    @pytest.mark.P1
    @pytest.mark.parametrize(
        ("name", "payload"),
        [
            ("缺姓名", {"phone": "13900000000", "detail": "地址"}),
            ("手机号非法", {"name": "张三", "phone": "abc", "detail": "地址"}),
            ("缺详细地址", {"name": "张三", "phone": "13900000000"}),
        ],
    )
    def test_address_validation_points(self, address_context, name, payload):
        with _step(f"地址校验：{name}"):
            response = address_context["customer"].client.post("/api/addresses", json=payload)
            body = error(response, code=40000)
            assert body.get("msg")

    @pytest.mark.P0
    @pytest.mark.db
    def test_address_positive_api_db_and_default(self, address_context):
        customer = address_context["customer"]
        payload = address_payload(customer.phone)
        with _step("API：创建地址"):
            address_id = str(ok(customer.client.post("/api/addresses", json=payload)))
        with _step("DB：地址落库"):
            row = verify_write("POST /api/addresses", payload, response=address_id)
            assert row["name"] == payload["name"]
            assert row["is_default"] is True
        with _step("API/DB：设置默认地址"):
            ok(customer.client.put(f"/api/addresses/{address_id}/default", json={"isDefault": True}))
            row = verify_write(
                "PUT /api/addresses/{id}/default",
                {"isDefault": True},
                path={"id": address_id},
            )
            assert row["is_default"] is True
