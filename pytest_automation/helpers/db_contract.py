"""写接口落库断言：请求字段 ↔ DB 行逐字段比对。

契约来源：artifacts/write-contracts.json（由 data/write_contracts.yaml 生成）。
用法：
    row = verify_write("POST /api/addresses", payload, response=address_id)
    row = verify_write("PUT /api/addresses/{id}", payload, path={"id": address_id})
    row = verify_write("POST /api/payment/sandbox", {"orderId": oid}, natural={"order_id": oid})
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from helpers import db

try:
    import allure  # type: ignore
except ImportError:  # pragma: no cover
    allure = None

CONTRACTS = Path(__file__).resolve().parents[1] / "artifacts" / "write-contracts.json"
_cache: dict | None = None


def contracts() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CONTRACTS.read_text(encoding="utf-8")).get("endpoints") or {}
        except Exception:  # noqa: BLE001
            _cache = {}
    return _cache


def _table_columns(table: str) -> set[str]:
    schema, _, name = table.partition(".")
    rows = db.query(
        "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s",
        (schema, name),
    )
    return {r["column_name"] for r in rows}


def _locate(contract: dict, response, path, natural, endpoint: str = "") -> dict:
    table = contract["table"]
    locate = contract.get("locate") or {}
    kind = locate.get("type")
    columns = _table_columns(table)
    include_deleted = bool(contract.get("expect_deleted"))
    where_deleted = " AND deleted = FALSE" if ("deleted" in columns and not include_deleted) else ""
    sql = ""
    params = ()
    if kind == "response_id":
        params = (str(response),)
        sql = f"SELECT * FROM {table} WHERE id = %s{where_deleted}"
    elif kind == "response_field":
        value = (response or {}).get(locate["key"])
        assert value, f"响应缺少 {locate['key']}，无法定位落库行"
        params = (str(value),)
        sql = f"SELECT * FROM {table} WHERE id = %s{where_deleted}"
    elif kind == "path_param":
        value = (path or {}).get(locate["key"])
        assert value, f"路径参数缺少 {locate['key']}"
        params = (str(value),)
        sql = f"SELECT * FROM {table} WHERE id = %s{where_deleted}"
    elif kind == "natural":
        locate_columns = locate.get("columns") or [locate["column"]]
        values = []
        conditions = []
        for column in locate_columns:
            value = (natural or {}).get(column) or (natural or {}).get("value")
            assert value not in (None, ""), f"缺少定位值 {column}"
            conditions.append(f"{column} = %s")
            values.append(str(value))
        params = tuple(values)
        sql = (
            f"SELECT * FROM {table} WHERE " + " AND ".join(conditions) +
            f"{where_deleted} ORDER BY id DESC LIMIT 1"
        )
    else:
        raise AssertionError(f"未知定位方式：{kind}")
    context = allure.step(f"DB 查询 {endpoint} → {table}") if allure else None
    if context:
        with context:
            if allure:
                allure.attach(json.dumps({"sql": sql, "params": list(params or [])},
                                          ensure_ascii=False, default=str),
                              name="执行的 SQL / 参数", attachment_type=allure.attachment_type.JSON)
            row = db.query_one(sql, params)
            assert row, f"{table} 中找不到刚落库的行（locate={kind}）"
            if allure:
                allure.attach(json.dumps(row, ensure_ascii=False, default=str)[:12000],
                              name="查询结果行", attachment_type=allure.attachment_type.JSON)
    else:
        row = db.query_one(sql, params)
        assert row, f"{table} 中找不到刚落库的行（locate={kind}）"
    from helpers import evidence
    evidence.record_db(endpoint=endpoint, table=table, locate=kind,
                       sql=sql, params=params, row=row)
    return row


def _convert(value, kind: str):
    if kind == "int":
        return int(value)
    if kind == "bool":
        return bool(value)
    if kind == "decimal":
        return Decimal(str(value))
    if kind == "json":
        return value
    return str(value)


def verify_deleted(endpoint: str, *, path=None, natural=None) -> None:
    """删除类接口：行不存在或 deleted=TRUE 视为删除成功。"""
    contract = contracts().get(endpoint)
    assert contract, f"缺少写接口契约：{endpoint}"
    try:
        row = _locate(contract, None, path, natural, endpoint)
    except AssertionError:
        return  # 物理删除或已查不到
    columns = _table_columns(contract["table"])
    if "deleted" in columns:
        assert row.get("deleted") is True, f"{endpoint} 删除未生效：deleted={row.get('deleted')}"
    else:
        raise AssertionError(f"{endpoint} 声称删除但行仍存在（表无 deleted 列）")


def verify_write(endpoint: str, payload: dict, *, response=None, path=None, natural=None) -> dict:
    contract = contracts().get(endpoint)
    assert contract, f"缺少写接口契约：{endpoint}（请补 data/write_contracts.yaml）"
    row = _locate(contract, response, path, natural, endpoint)

    comparison = {"endpoint": endpoint, "table": contract["table"], "fields": [], "mismatches": []}
    for req_key, spec in (contract.get("fields") or {}).items():
        if req_key not in payload:
            assert spec.get("optional"), f"{endpoint} 请求缺少字段 {req_key}（契约要求必填）"
            continue
        column = spec["column"]
        expected = _convert(payload[req_key], spec.get("type", "string"))
        actual = row.get(column)
        if isinstance(actual, Decimal) or isinstance(expected, Decimal):
            ok = Decimal(str(actual)) == Decimal(str(expected))
        elif isinstance(expected, bool):
            ok = bool(actual) == expected
        else:
            ok = str(actual) == str(expected)
        comparison["fields"].append({
            "request": req_key, "column": column,
            "expected": expected, "actual": actual, "match": ok,
        })
        if not ok:
            comparison["mismatches"].append({
                "request": req_key, "column": column,
                "expected": expected, "actual": actual,
            })
        assert ok, f"{endpoint} 字段 {req_key} 未正确落库：DB {column}={actual!r}，请求={payload[req_key]!r}"

    for special in contract.get("special") or []:
        source = special.get("json_from")
        if source and source in payload:
            actual = row.get(special["column"])
            expected = payload[source] or []
            assert (actual or []) == expected, (
                f"{endpoint} JSONB 字段 {special['column']} 不一致：DB={actual!r}，请求={expected!r}"
            )

    for column in contract.get("generated") or []:
        if column in row:
            assert row[column] not in (None, ""), f"{endpoint} 生成列 {column} 为空"
    if allure:
        with allure.step(f"字段比对 {endpoint}"):
            allure.attach(json.dumps(comparison, ensure_ascii=False, default=str)[:16000],
                          name="请求字段 ↔ DB 列比对",
                          attachment_type=allure.attachment_type.JSON)
    return row
