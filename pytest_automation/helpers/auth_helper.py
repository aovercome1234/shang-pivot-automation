"""认证与购物业务辅助：登录、取商品 SKU、加购、下单。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from config.settings import settings
from core.api_client import ApiClient
from core.assertions import ok
from helpers.data_factory import unique_phone


def login_customer(client: ApiClient, phone: str, code: str = None) -> dict:
    data = ok(
        client.post(
            "/api/auth/login",
            json={
                "phone": phone,
                "code": code or settings.sms_code,
                "clientType": "web",
            },
        )
    )
    client.set_token(data["accessToken"])
    return data


def login_admin(client: ApiClient, username: str = None, password: str = None) -> dict:
    data = ok(
        client.post(
            "/admin/auth/login",
            json={
                "username": username or settings.admin_username,
                "password": password if password is not None else settings.admin_password,
            },
        )
    )
    client.set_token(data["accessToken"])
    return data


def new_customer(phone: str = None) -> SimpleNamespace:
    """新建一个隔离会员：每次调用都是全新账号，写用例互不干扰。"""
    phone = phone or unique_phone()
    client = ApiClient(settings.api_mall_base)
    data = login_customer(client, phone)
    return SimpleNamespace(
        phone=phone,
        client=client,
        token=data["accessToken"],
        refresh_token=data.get("refreshToken", ""),
        expires_in=data.get("expiresIn"),
        info=data.get("customer") or {},
    )


def pick_sku(client: ApiClient, spu_id: str = "101") -> dict:
    """选一个在售、有库存的 SKU；固定商品不存在时回退到商品列表。"""
    detail = ok(client.get(f"/api/products/{spu_id}"))
    candidates = [s for s in detail.get("skus", []) if int(s.get("availableStock") or 0) > 0]
    if candidates:
        sku = candidates[0]
        return {
            "spu_id": str(detail["spu"]["id"]),
            "sku_id": str(sku["skuId"]),
            "price": float(sku["price"]),
            "stock": int(sku["availableStock"]),
            "title": sku.get("title") or detail["spu"].get("name"),
        }

    page = ok(client.get("/api/products", params={"page": 1, "size": 50}))
    for row in page.get("records", []):
        detail = ok(client.get(f"/api/products/{row['spuId']}"))
        for sku in detail.get("skus", []):
            if int(sku.get("availableStock") or 0) > 0:
                return {
                    "spu_id": str(detail["spu"]["id"]),
                    "sku_id": str(sku["skuId"]),
                    "price": float(sku["price"]),
                    "stock": int(sku["availableStock"]),
                    "title": sku.get("title") or detail["spu"].get("name"),
                }
    pytest.fail(
        "演示环境没有可售库存的 SKU：这是商品/库存数据前置条件缺失，"
        "请检查商品是否上架、库存是否大于 0（不再静默 skip）"
    )


def add_to_cart(client: ApiClient, sku_id: str, quantity: int = 1) -> dict:
    return ok(client.post("/api/cart/items", json={"skuId": sku_id, "quantity": quantity}))


def create_address(client: ApiClient, payload: dict) -> str:
    return str(ok(client.post("/api/addresses", json=payload)))


def submit_order(client: ApiClient, payload: dict) -> dict:
    return ok(client.post("/api/orders", json=payload))
