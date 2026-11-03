"""补齐 P0 缺口的写接口落库断言。

覆盖：商品、订单、角色/用户、属性/字典项、文件、运营位/站点品牌、库存/出入库、
收藏/足迹/会员资料，以及 clear-invalid 的“保留有效项”DB 事实。
所有定位都使用响应 ID、路径 ID 或自然键，避免只断言 HTTP 200。
"""
from __future__ import annotations

import uuid

import pytest

from core.assertions import ok
from helpers import db
from helpers.data_factory import unique_phone
from helpers.db_contract import verify_deleted, verify_write

pytestmark = [pytest.mark.api, pytest.mark.db, pytest.mark.regression]


def _uid() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture(scope="module")
def category_id() -> str:
    if not db.available():
        pytest.skip("数据库不可达：需要类目构造商品/属性")
    row = db.query_one(
        "SELECT id FROM commerce.category WHERE deleted = FALSE ORDER BY id LIMIT 1"
    )
    assert row, "演示数据缺少类目"
    return str(row["id"])


@pytest.fixture(scope="module")
def dict_id() -> str:
    row = db.query_one(
        "SELECT id FROM identity.dict WHERE deleted = FALSE ORDER BY id LIMIT 1"
    )
    if not row:
        pytest.skip("演示数据缺少字典")
    return str(row["id"])


@pytest.fixture(scope="module")
def config_row() -> dict:
    row = db.query_one(
        "SELECT id, config_value, remark FROM identity.system_config "
        "WHERE deleted = FALSE AND is_secret = FALSE ORDER BY id LIMIT 1"
    )
    if not row:
        pytest.skip("演示数据缺少非敏感系统配置")
    return row


def _product_payload(category_id: str, name: str, status: str = "DRAFT") -> dict:
    return {
        "categoryId": category_id,
        "name": name,
        "subtitle": "落库断言商品",
        "pics": ["https://cdn.example.com/auto/product.png"],
        "detailHtml": "<p>落库断言</p>",
        "status": status,
        "skus": [
            {
                "title": "落库规格",
                "price": 12.34,
                "costPrice": 8.0,
                "status": "ENABLED",
                "initStock": 0,
            }
        ],
    }


def _create_product(admin, category_id: str, name: str, status: str = "DRAFT") -> tuple[str, dict]:
    payload = _product_payload(category_id, name, status)
    product_id = str(ok(admin.post("/admin/products", json=payload)))
    return product_id, payload


def _product_status(product_id: str) -> str:
    row = db.query_one(
        "SELECT status FROM commerce.spu WHERE id = %s AND deleted = FALSE",
        (product_id,),
    )
    assert row, f"商品 {product_id} 不存在"
    return row["status"]


@pytest.mark.P0
def test_product_create_and_update_persisted(admin, category_id):
    product_id, payload = _create_product(admin, category_id, f"落库商品-{_uid()}")
    verify_write("POST /admin/products", payload, response=product_id)
    assert _product_status(product_id) == "DRAFT"

    update = {
        **payload,
        "name": payload["name"] + "-更新",
        "subtitle": "更新后的副标题",
        "status": "DRAFT",
    }
    update.pop("skus", None)
    ok(admin.put(f"/admin/products/{product_id}", json=update))
    verify_write("PUT /admin/products/{id}", update, path={"id": product_id})
    assert _product_status(product_id) == "DRAFT"


@pytest.mark.P1
def test_product_on_off_and_batch_off_persisted(admin, category_id):
    product_id, _ = _create_product(admin, category_id, f"上下架商品-{_uid()}")
    ok(admin.put(f"/admin/products/{product_id}/on"))
    verify_write("PUT /admin/products/{id}/on", {}, path={"id": product_id})
    assert _product_status(product_id) == "ON"

    ok(admin.put(f"/admin/products/{product_id}/off"))
    verify_write("PUT /admin/products/{id}/off", {}, path={"id": product_id})
    assert _product_status(product_id) == "OFF"

    ok(admin.put(f"/admin/products/{product_id}/on"))
    count = ok(admin.put("/admin/products/batch-off", json=[int(product_id)]))
    assert int(count) >= 1
    verify_write("PUT /admin/products/batch-off", {}, natural={"id": product_id})
    assert _product_status(product_id) == "OFF"


@pytest.mark.P1
def test_product_delete_persisted(admin, category_id):
    product_id, _ = _create_product(admin, category_id, f"删除商品-{_uid()}")
    ok(admin.delete(f"/admin/products/{product_id}"))
    verify_deleted("DELETE /admin/products/{id}", path={"id": product_id})


@pytest.mark.P0
def test_role_crud_persisted(admin):
    code = f"auto_role_{_uid()}"
    payload = {
        "code": code,
        "name": "落库角色",
        "dataScope": "ALL",
        "status": "ENABLED",
        "remark": "落库断言",
        "permissionIds": [],
    }
    role_id = str(ok(admin.post("/admin/roles", json=payload)))
    verify_write("POST /admin/roles", payload, response=role_id)

    update = {
        "name": "落库角色-更新",
        "dataScope": "SELF",
        "status": "DISABLED",
        "remark": "更新后",
        "permissionIds": [],
    }
    ok(admin.put(f"/admin/roles/{role_id}", json=update))
    verify_write("PUT /admin/roles/{id}", update, path={"id": role_id})

    ok(admin.delete(f"/admin/roles/{role_id}"))
    verify_deleted("DELETE /admin/roles/{id}", path={"id": role_id})


@pytest.mark.P0
def test_admin_user_crud_password_status_persisted(admin):
    username = f"auto_user_{_uid()}"
    payload = {
        "username": username,
        "password": "Admin@123",
        "realName": "落库用户",
        "phone": unique_phone(),
        "email": f"{username}@example.com",
        "status": "ENABLED",
        "roleIds": [],
    }
    user_id = str(ok(admin.post("/admin/users", json=payload)))
    verify_write("POST /admin/users", payload, response=user_id)

    update = {
        **payload,
        "realName": "落库用户-更新",
        "status": "ENABLED",
    }
    update.pop("password", None)
    ok(admin.put(f"/admin/users/{user_id}", json=update))
    verify_write("PUT /admin/users/{id}", update, path={"id": user_id})

    ok(admin.put(f"/admin/users/{user_id}/status", json={"status": "DISABLED"}))
    verify_write("PUT /admin/users/{id}/status", {"status": "DISABLED"}, path={"id": user_id})

    old_hash = db.query_one(
        "SELECT password FROM identity.admin_user WHERE id = %s", (user_id,)
    )["password"]
    ok(admin.put(f"/admin/users/{user_id}/password", json={"password": "NewPass@123"}))
    verify_write("PUT /admin/users/{id}/password", {}, path={"id": user_id})
    new_hash = db.query_one(
        "SELECT password FROM identity.admin_user WHERE id = %s", (user_id,)
    )["password"]
    assert new_hash and new_hash != old_hash, "重置密码后 password 哈希未变化"

    ok(admin.delete(f"/admin/users/{user_id}"))
    verify_deleted("DELETE /admin/users/{id}", path={"id": user_id})


@pytest.mark.P1
def test_attribute_crud_persisted(admin, category_id):
    payload = {
        "categoryId": category_id,
        "name": f"落库属性-{_uid()}",
        "type": "SPEC",
        "options": ["A", "B"],
        "sort": 1,
    }
    attribute_id = str(ok(admin.post("/admin/attributes", json=payload)))
    verify_write("POST /admin/attributes", payload, response=attribute_id)

    update = {**payload, "name": payload["name"] + "-更新", "sort": 2}
    ok(admin.put(f"/admin/attributes/{attribute_id}", json=update))
    verify_write("PUT /admin/attributes/{id}", update, path={"id": attribute_id})

    ok(admin.delete(f"/admin/attributes/{attribute_id}"))
    verify_deleted("DELETE /admin/attributes/{id}", path={"id": attribute_id})


@pytest.mark.P1
def test_dict_item_crud_persisted(admin, dict_id):
    payload = {
        "dictId": dict_id,
        "label": f"落库字典项-{_uid()}",
        "value": f"auto_{_uid()}",
        "sort": 1,
        "status": "ENABLED",
    }
    item_id = str(ok(admin.post("/admin/dict-items", json=payload)))
    verify_write("POST /admin/dict-items", payload, response=item_id)

    update = {**payload, "label": payload["label"] + "-更新", "sort": 2}
    ok(admin.put(f"/admin/dict-items/{item_id}", json=update))
    verify_write("PUT /admin/dict-items/{id}", update, path={"id": item_id})

    ok(admin.delete(f"/admin/dict-items/{item_id}"))
    verify_deleted("DELETE /admin/dict-items/{id}", path={"id": item_id})


@pytest.mark.P1
def test_system_config_update_persisted(admin, config_row):
    config_id = str(config_row["id"])
    payload = {
        "configValue": f"persist-{_uid()}",
        "remark": "落库断言更新",
    }
    try:
        ok(admin.put(f"/admin/system-configs/{config_id}", json=payload))
        verify_write("PUT /admin/system-configs/{id}", payload, path={"id": config_id})
    finally:
        ok(admin.put(f"/admin/system-configs/{config_id}", json={
            "configValue": config_row["config_value"],
            "remark": config_row["remark"],
        }))


@pytest.mark.P1
def test_file_confirm_persisted(admin, customer):
    admin_payload = {
        "objectKey": f"PRODUCT/auto/{_uid()}.jpg",
        "contentType": "image/jpeg",
        "sizeBytes": 12,
        "bizType": "PRODUCT",
        "visibility": "PUBLIC",
    }
    admin_resp = ok(admin.post("/admin/files/confirm", json=admin_payload))
    verify_write("POST /admin/files/confirm", admin_payload, response=admin_resp)

    client_payload = {
        "objectKey": f"AVATAR/auto/{_uid()}.png",
        "contentType": "image/png",
        "sizeBytes": 12,
        "bizType": "AVATAR",
    }
    client_resp = ok(customer.client.post("/api/files/confirm", json=client_payload))
    verify_write("POST /api/files/confirm", client_payload, response=client_resp)


@pytest.mark.P1
def test_file_upload_persisted(admin, customer):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 20
    admin_resp = ok(admin.post(
        "/admin/files/upload",
        files={"file": ("auto.png", png, "image/png")},
        data={"bizType": "PRODUCT"},
        headers={"Content-Type": None},
    ))
    verify_write("POST /admin/files/upload", {}, response=admin_resp)

    client_resp = ok(customer.client.post(
        "/api/files/upload",
        files={"file": ("auto.png", png, "image/png")},
        data={"bizType": "AVATAR"},
        headers={"Content-Type": None},
    ))
    verify_write("POST /api/files/upload", {}, response=client_resp)


@pytest.mark.P1
def test_home_slot_and_site_brand_persisted(admin):
    slot = db.query_one(
        "SELECT code, title, status, sort FROM commerce.home_slot ORDER BY id LIMIT 1"
    )
    if slot:
        slot_payload = {
            "title": f"自动化运营位-{_uid()}",
            "status": slot["status"] or "OFF",
            "sort": int(slot["sort"] or 0),
        }
        try:
            ok(admin.put(f"/admin/home/slots/{slot['code']}", json=slot_payload))
            verify_write(
                "PUT /admin/home/slots/{code}", slot_payload,
                natural={"code": slot["code"]},
            )
        finally:
            ok(admin.put(f"/admin/home/slots/{slot['code']}", json={
                "title": slot["title"],
                "status": slot["status"],
                "sort": slot["sort"],
            }))

    brand = db.query_one("SELECT * FROM commerce.site_brand WHERE id = 1")
    if brand:
        brand_payload = {
            "name": f"落库站点-{_uid()}",
            "slogan": "落库断言",
        }
        try:
            ok(admin.put("/admin/site/brand", json=brand_payload))
            verify_write("PUT /admin/site/brand", brand_payload, natural={"id": 1})
        finally:
            ok(admin.put("/admin/site/brand", json={
                "name": brand["name"],
                "slogan": brand["slogan"],
            }))


@pytest.mark.P1
def test_stock_adjust_and_in_out_persisted(admin):
    stock = db.query_one(
        "SELECT sku_id, warehouse_id, physical_stock FROM commerce.stock "
        "WHERE deleted = FALSE ORDER BY sku_id LIMIT 1"
    )
    if not stock:
        pytest.skip("缺少库存行")
    sku_id, warehouse_id = str(stock["sku_id"]), str(stock["warehouse_id"])
    before = int(stock["physical_stock"])
    try:
        ok(admin.put("/admin/stocks/adjust", json={
            "skuId": sku_id,
            "warehouseId": warehouse_id,
            "changeQty": 1,
            "reason": "落库断言盘点",
        }))
        verify_write(
            "PUT /admin/stocks/adjust", {},
            natural={"sku_id": sku_id, "warehouse_id": warehouse_id},
        )
        after = db.query_one(
            "SELECT physical_stock FROM commerce.stock "
            "WHERE sku_id = %s AND warehouse_id = %s AND deleted = FALSE",
            (sku_id, warehouse_id),
        )
        assert int(after["physical_stock"]) == before + 1
    finally:
        ok(admin.put("/admin/stocks/adjust", json={
            "skuId": sku_id,
            "warehouseId": warehouse_id,
            "changeQty": -1,
            "reason": "落库断言恢复",
        }))

    payload = {
        "type": "PURCHASE_IN",
        "warehouseId": warehouse_id,
        "remark": f"落库断言入库-{_uid()}",
        "items": [{"skuId": sku_id, "qty": 1, "remark": "入库"}],
    }
    bill_id = str(ok(admin.post("/admin/in-out", json=payload)))
    verify_write("POST /admin/in-out", payload, response=bill_id)
    item = db.query_one(
        "SELECT qty FROM commerce.in_out_item WHERE bill_id = %s AND sku_id = %s",
        (bill_id, sku_id),
    )
    assert item and int(item["qty"]) == 1, "出入库明细未落库"


@pytest.mark.P1
def test_cart_clear_invalid_keeps_valid_row_persisted(customer, sku):
    from helpers.auth_helper import add_to_cart

    item = add_to_cart(customer.client, sku["sku_id"], 1)
    item_id = str(item["cartItemId"])
    ok(customer.client.post("/api/cart/clear-invalid"))
    verify_write("POST /api/cart/clear-invalid", {}, natural={"id": item_id})
    row = db.query_one(
        "SELECT id FROM commerce.cart_item WHERE id = %s",
        (item_id,),
    )
    assert row, "有效购物车项不应被 clear-invalid 删除"


@pytest.mark.P1
def test_favorites_history_profile_persisted(customer, sku):
    customer_id = str(customer.info["id"])
    spu_id = str(sku["spu_id"])

    ok(customer.client.post(f"/api/favorites/{spu_id}"))
    verify_write(
        "POST /api/favorites/{spuId}", {},
        natural={"customer_id": customer_id, "spu_id": spu_id},
    )
    ok(customer.client.delete(f"/api/favorites/{spu_id}"))
    verify_deleted(
        "DELETE /api/favorites/{spuId}",
        natural={"customer_id": customer_id, "spu_id": spu_id},
    )

    ok(customer.client.get(f"/api/products/{spu_id}"))
    assert db.query_one(
        "SELECT id FROM commerce.browse_history WHERE customer_id = %s AND spu_id = %s",
        (customer_id, spu_id),
    ), "浏览商品后未写入足迹"
    ok(customer.client.delete("/api/history"))
    verify_deleted("DELETE /api/history", natural={"customer_id": customer_id})

    nickname = f"落库昵称-{_uid()}"
    ok(customer.client.put("/api/me", json={"nickname": nickname}))
    verify_write("PUT /api/me", {"nickname": nickname}, natural={"id": customer_id})
