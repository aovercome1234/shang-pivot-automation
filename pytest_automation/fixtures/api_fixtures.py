"""API 夹具：匿名客户端、隔离会员、管理员、商品 SKU、地址、购物车、订单。"""
from __future__ import annotations

import pytest

from config.settings import settings
from core.api_client import ApiClient
from core.logger import get_logger
from helpers.auth_helper import (
    add_to_cart,
    create_address,
    login_admin,
    new_customer,
    pick_sku,
    submit_order,
)
from helpers.data_factory import address_payload, order_payload

log = get_logger("fixtures")


@pytest.fixture(scope="session")
def anonymous():
    """无 Token 客户端，用于公开接口（商品、搜索、分类、首页）。"""
    client = ApiClient(settings.api_mall_base)
    yield client
    client.close()


@pytest.fixture(scope="session")
def admin():
    """管理端客户端（session 级登录一次）。未提供密码则整组用例 skip。"""
    if not settings.admin_password:
        pytest.skip(
            "未设置 ADMIN_PASSWORD：请在 pytest_automation/.env.local 填写，"
            "或通过环境变量注入（.env.local 已 gitignore）"
        )
    client = ApiClient(settings.api_admin_base)
    login_admin(client)
    yield client
    client.close()


@pytest.fixture
def customer():
    """每次用例一个全新会员；teardown 不清理测试数据，保留给三方组件核验。

    报告中的 DB/Redis/MQ 证据需要能看到真实写入行，因此这里只关闭连接，
    不取消订单、不删除地址/购物车。数据隔离由随机会员保证。
    """
    cust = new_customer()
    yield cust
    cust.client.close()


@pytest.fixture
def second_customer():
    """第二个隔离会员，用于越权（IDOR）用例。"""
    cust = new_customer()
    yield cust
    cust.client.close()


@pytest.fixture(scope="session")
def sku(anonymous):
    """一个有库存的 SKU 信息：spu_id / sku_id / price / stock。"""
    return pick_sku(anonymous)


@pytest.fixture
def address(customer):
    """为当前会员创建一条默认地址；teardown 保留，供落库/SQL 证据核验。"""
    address_id = create_address(customer.client, address_payload(customer.phone))
    yield address_id


@pytest.fixture
def cart_item(customer, sku):
    """为当前会员加购一件商品，返回购物车项 ID。"""
    item = add_to_cart(customer.client, sku["sku_id"], 1)
    return str(item["cartItemId"])


@pytest.fixture
def order(customer, sku):
    """创建一笔待支付订单：地址 + 加购 + 下单。"""
    address_id = create_address(customer.client, address_payload(customer.phone))
    item = add_to_cart(customer.client, sku["sku_id"], 1)
    data = submit_order(
        customer.client,
        order_payload(address_id=address_id, cart_item_ids=[str(item["cartItemId"])]),
    )
    yield {
        "data": data,
        "order_id": str(data["orderId"]),
        "address_id": address_id,
        "cart_item_id": str(item["cartItemId"]),
        "sku": sku,
    }
