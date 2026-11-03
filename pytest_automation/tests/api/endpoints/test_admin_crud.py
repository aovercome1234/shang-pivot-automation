"""接口级迁移：管理端品牌/类目/字典/部门/仓库 CRUD。

每个资源仍按接口拆分测试点并显式归属到 POST/PUT/DELETE，避免巡检或列表查询
抢占接口归属；逆向校验参数化，正向链路按 API → DB 分层，删除校验软删事实。
原有 ``test_admin_crud_roundtrip.py`` 保留为回归对照。
"""
from __future__ import annotations

import uuid
from contextlib import nullcontext

import pytest

try:
    import allure  # type: ignore
except ImportError:  # pragma: no cover
    allure = None

from core.assertions import error, ok
from helpers import db
from helpers.db_contract import verify_deleted, verify_write

pytestmark = [pytest.mark.api]


def _step(name: str):
    return allure.step(name) if allure else nullcontext()


def _uid() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture(scope="module")
def category_ref() -> str:
    if not db.available():
        pytest.skip("数据库不可达：品牌需要引用一个已有类目")
    row = db.query_one(
        "SELECT id FROM commerce.category WHERE deleted = FALSE ORDER BY id LIMIT 1"
    )
    if not row:
        pytest.skip("演示数据缺少类目")
    return str(row["id"])


def _create_brand(admin, category_ref: str, name: str | None = None) -> str:
    payload = {"name": name or f"接口品牌-{_uid()}", "categoryId": category_ref}
    return str(ok(admin.post("/admin/brands", json=payload)))


class TestAdminBrandCrud:
    @pytest.mark.P1
    @pytest.mark.parametrize(
        ("name", "payload", "keyword"),
        [
            ("缺品牌名称", {"categoryId": "<category>"}, "品牌名称"),
            ("缺类目", {"name": "接口校验品牌"}, "类目"),
        ],
    )
    def test_brand_create_validation(self, admin, category_ref, name, payload, keyword):
        actual = dict(payload)
        if actual.get("categoryId") == "<category>":
            actual["categoryId"] = category_ref
        with _step(f"品牌校验：{name}"):
            body = error(admin.post("/admin/brands", json=actual), code=40000)
            assert keyword in body["msg"]
        if actual.get("name"):
            row = db.query_one("SELECT count(*) AS n FROM commerce.brand WHERE name=%s", (actual["name"],))
            assert int(row["n"]) == 0, "校验失败不应落库"

    @pytest.mark.P0
    @pytest.mark.db
    def test_brand_create_api_db(self, admin, category_ref):
        payload = {"name": f"接口品牌-{_uid()}", "categoryId": category_ref}
        with _step("API：创建品牌"):
            brand_id = str(ok(admin.post("/admin/brands", json=payload)))
        with _step("DB：品牌字段与请求一致"):
            row = verify_write("POST /admin/brands", payload, response=brand_id)
            assert str(row["category_id"]) == str(category_ref)
            assert row["status"] == "ENABLED"

    @pytest.mark.P1
    @pytest.mark.db
    def test_brand_update_api_db(self, admin, category_ref):
        brand_id = _create_brand(admin, category_ref)
        payload = {"name": f"接口品牌改-{_uid()}", "categoryId": category_ref, "status": "DISABLED"}
        with _step("API：更新品牌"):
            ok(admin.put(f"/admin/brands/{brand_id}", json=payload))
        with _step("DB：品牌名称/状态已更新"):
            row = verify_write("PUT /admin/brands/{id}", payload, path={"id": brand_id})
            assert row["status"] == "DISABLED"

    @pytest.mark.P1
    @pytest.mark.db
    def test_brand_delete_api_db(self, admin, category_ref):
        brand_id = _create_brand(admin, category_ref)
        with _step("API/DB：删除品牌并校验软删"):
            ok(admin.delete(f"/admin/brands/{brand_id}"))
            verify_deleted("DELETE /admin/brands/{id}", path={"id": brand_id})


class TestAdminCategoryCrud:
    @pytest.mark.P1
    @pytest.mark.parametrize(
        ("payload",),
        [
            ({},),
            ({"name": "   "},),
        ],
    )
    def test_category_create_validation(self, admin, payload):
        with _step("类目名称必填校验"):
            body = error(admin.post("/admin/categories", json=payload), code=40000)
            assert "类目名称" in body["msg"]

    @pytest.mark.P0
    @pytest.mark.db
    def test_category_create_api_db(self, admin):
        payload = {"name": f"接口类目-{_uid()}", "parentId": "0", "sort": 9999}
        with _step("API：创建一级类目"):
            category_id = str(ok(admin.post("/admin/categories", json=payload)))
        with _step("DB：类目落库且默认启用"):
            row = verify_write("POST /admin/categories", payload, response=category_id)
            assert int(row["parent_id"]) == 0
            assert row["status"] == "ENABLED" and int(row["level"]) == 1

    @pytest.mark.P1
    @pytest.mark.db
    def test_category_update_api_db(self, admin):
        category_id = str(ok(admin.post("/admin/categories", json={"name": f"接口类目-{_uid()}", "parentId": "0", "sort": 9999})))
        payload = {"name": f"接口类目改-{_uid()}", "parentId": "0", "level": 1, "sort": 9999, "status": "DISABLED"}
        with _step("API：更新类目"):
            ok(admin.put(f"/admin/categories/{category_id}", json=payload))
        with _step("DB：类目名称/状态已更新"):
            row = verify_write("PUT /admin/categories/{id}", payload, path={"id": category_id})
            assert row["status"] == "DISABLED"

    @pytest.mark.P1
    @pytest.mark.db
    def test_category_delete_api_db(self, admin):
        category_id = str(ok(admin.post("/admin/categories", json={"name": f"接口类目-{_uid()}", "parentId": "0", "sort": 9999})))
        with _step("API/DB：删除类目并校验软删"):
            ok(admin.delete(f"/admin/categories/{category_id}"))
            verify_deleted("DELETE /admin/categories/{id}", path={"id": category_id})


class TestAdminDictCrud:
    @pytest.mark.P1
    @pytest.mark.parametrize(
        ("payload", "keyword"),
        [
            ({"name": "缺编码字典"}, "字典编码"),
            ({"code": f"auto_{_uid()}"}, "字典名称"),
        ],
    )
    def test_dict_create_validation(self, admin, payload, keyword):
        with _step("字典必填校验"):
            body = error(admin.post("/admin/dicts", json=payload), code=40000)
            assert keyword in body["msg"]

    @pytest.mark.P1
    def test_dict_duplicate_code_conflict(self, admin):
        payload = {"code": f"auto_dup_{_uid()}", "name": "接口重复字典"}
        ok(admin.post("/admin/dicts", json=payload))
        with _step("重复编码被拒"):
            body = error(admin.post("/admin/dicts", json=payload), code=40900)
            assert "已存在" in body["msg"]

    @pytest.mark.P0
    @pytest.mark.db
    def test_dict_create_api_db(self, admin):
        code = f"auto_ep_{_uid()}"
        payload = {"code": code, "name": f"接口字典-{_uid()}"}
        with _step("API：创建字典"):
            dict_id = str(ok(admin.post("/admin/dicts", json=payload)))
        with _step("DB：字典编码/名称落库"):
            row = verify_write("POST /admin/dicts", payload, response=dict_id)
            assert row["code"] == code

    @pytest.mark.P1
    @pytest.mark.db
    def test_dict_update_api_db(self, admin):
        code = f"auto_ep_{_uid()}"
        dict_id = str(ok(admin.post("/admin/dicts", json={"code": code, "name": "接口字典"})))
        payload = {"code": code, "name": f"接口字典改-{_uid()}", "remark": "接口级更新"}
        with _step("API：更新字典"):
            ok(admin.put(f"/admin/dicts/{dict_id}", json=payload))
        with _step("DB：字典名称已更新"):
            row = verify_write("PUT /admin/dicts/{id}", payload, path={"id": dict_id})
            assert row["name"] == payload["name"]

    @pytest.mark.P1
    @pytest.mark.db
    def test_dict_delete_api_db(self, admin):
        dict_id = str(ok(admin.post("/admin/dicts", json={"code": f"auto_ep_{_uid()}", "name": "接口字典"})))
        with _step("API/DB：删除字典并校验软删"):
            ok(admin.delete(f"/admin/dicts/{dict_id}"))
            verify_deleted("DELETE /admin/dicts/{id}", path={"id": dict_id})


class TestAdminDeptCrud:
    @pytest.mark.P1
    @pytest.mark.parametrize(
        ("payload",),
        [
            ({},),
            ({"name": "  "},),
        ],
    )
    def test_dept_create_validation(self, admin, payload):
        with _step("部门名称必填校验"):
            body = error(admin.post("/admin/depts", json=payload), code=40000)
            assert "部门名称" in body["msg"]

    @pytest.mark.P0
    @pytest.mark.db
    def test_dept_create_api_db(self, admin):
        payload = {"name": f"接口部门-{_uid()}", "parentId": "0"}
        with _step("API：创建部门"):
            dept_id = str(ok(admin.post("/admin/depts", json=payload)))
        with _step("DB：部门落库且默认启用"):
            row = verify_write("POST /admin/depts", payload, response=dept_id)
            assert int(row["parent_id"]) == 0 and row["status"] == "ENABLED"

    @pytest.mark.P1
    @pytest.mark.db
    def test_dept_update_api_db(self, admin):
        dept_id = str(ok(admin.post("/admin/depts", json={"name": f"接口部门-{_uid()}", "parentId": "0"})))
        payload = {"name": f"接口部门改-{_uid()}", "parentId": "0", "sort": 5, "status": "DISABLED"}
        with _step("API：更新部门"):
            ok(admin.put(f"/admin/depts/{dept_id}", json=payload))
        with _step("DB：部门名称/排序/状态已更新"):
            row = verify_write("PUT /admin/depts/{id}", payload, path={"id": dept_id})
            assert int(row["sort"]) == 5 and row["status"] == "DISABLED"

    @pytest.mark.P1
    @pytest.mark.db
    def test_dept_delete_api_db(self, admin):
        dept_id = str(ok(admin.post("/admin/depts", json={"name": f"接口部门-{_uid()}", "parentId": "0"})))
        with _step("API/DB：删除部门并校验软删"):
            ok(admin.delete(f"/admin/depts/{dept_id}"))
            verify_deleted("DELETE /admin/depts/{id}", path={"id": dept_id})


class TestAdminWarehouseCrud:
    @pytest.mark.P1
    @pytest.mark.parametrize(
        ("payload",),
        [
            ({},),
            ({"name": "   "},),
        ],
    )
    def test_warehouse_create_validation(self, admin, payload):
        with _step("仓库名称必填校验"):
            body = error(admin.post("/admin/warehouses", json=payload), code=40000)
            assert "仓库名称" in body["msg"]

    @pytest.mark.P0
    @pytest.mark.db
    def test_warehouse_create_api_db(self, admin):
        payload = {"name": f"接口仓库-{_uid()}"}
        with _step("API：创建仓库"):
            warehouse_id = str(ok(admin.post("/admin/warehouses", json=payload)))
        with _step("DB：仓库落库且默认启用"):
            row = verify_write("POST /admin/warehouses", payload, response=warehouse_id)
            assert row["status"] == "ENABLED"

    @pytest.mark.P1
    @pytest.mark.db
    def test_warehouse_update_api_db(self, admin):
        warehouse_id = str(ok(admin.post("/admin/warehouses", json={"name": f"接口仓库-{_uid()}"})))
        payload = {"name": f"接口仓库改-{_uid()}", "status": "DISABLED"}
        with _step("API：更新仓库"):
            ok(admin.put(f"/admin/warehouses/{warehouse_id}", json=payload))
        with _step("DB：仓库名称/状态已更新"):
            row = verify_write("PUT /admin/warehouses/{id}", payload, path={"id": warehouse_id})
            assert row["status"] == "DISABLED"
