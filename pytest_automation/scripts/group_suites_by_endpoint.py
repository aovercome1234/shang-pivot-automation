#!/usr/bin/env python3
"""在 Allure Suites 的业务模块下按接口再聚合一层。

Allure 生成器只提供 parentSuite/suite/subSuite 三层标签，无法同时表达
“业务域 → 业务模块 → 接口 → 用例”。这里在 `data/suites.json` 的模块节点下插入
接口分组节点（Allure 的树组件支持任意深度），并让组内用例按编号稳定排序。

只处理“接口自动化”层；UI/端到端保持原树。脚本可重复执行：检测到模块下已经是
接口分组节点时直接跳过。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.business_taxonomy import category_for_dimension, select_endpoint  # noqa: E402

REPORT = ROOT / "artifacts" / "allure-report"
API_LAYER = "接口自动化"
CROSS_ENDPOINT = "跨接口 / 业务校验"


def _group_uid(module_uid: str, endpoint: str) -> str:
    return hashlib.md5(f"{module_uid}|{endpoint}".encode("utf-8")).hexdigest()


def _endpoint_templates(report: Path) -> dict[str, list[str]]:
    """从接口矩阵读取端点模板，用于把 /admin/warehouses/1 归一到 {id}。"""
    candidates = [
        report / "ext" / "data" / "api-matrix.json",
        ROOT.parent / "api_testcases" / "artifacts" / "endpoint-model.json",
    ]
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        interfaces = data.get("interfaces") or data.get("endpoints") or []
        templates: dict[str, list[str]] = {}
        for item in interfaces:
            method = str(item.get("method") or "").upper()
            endpoint = str(item.get("path") or item.get("url") or "")
            if method and endpoint:
                templates.setdefault(method, []).append(endpoint)
        if templates:
            return templates
    return {}


def _normalize_endpoint(endpoint: str, templates: dict[str, list[str]]) -> str:
    parts = endpoint.split(" ", 1)
    if len(parts) != 2:
        return endpoint
    method, path = parts[0].upper(), parts[1]
    for template in templates.get(method, []):
        pattern = "^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(template)) + "$"
        if re.match(pattern, path):
            return f"{method} {template}"
    return f"{method} {path}"


def _endpoint_sort_key(endpoint: str):
    if endpoint == CROSS_ENDPOINT:
        return (1, "", "", endpoint)
    parts = endpoint.split(" ", 1)
    method = parts[0]
    path = parts[1] if len(parts) > 1 else endpoint
    method_order = {"GET": 0, "POST": 1, "PUT": 2, "DELETE": 3, "PATCH": 4}.get(method, 9)
    return (0, path, method_order, method)


def _case_sort_key(node: dict) -> str:
    return str(node.get("name") or "").lower()


def _load_metadata(report: Path) -> dict[str, dict]:
    result = {}
    for path in (report / "data" / "test-cases").glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        uid = data.get("uid")
        labels = {item.get("name"): item.get("value") for item in data.get("labels") or []}
        result[uid] = {
            "nodeid": labels.get("pytest_nodeid") or "",
            "dimension": labels.get("test_dimension") or "",
            "category": labels.get("test_category") or "",
        }
    return result


def _is_test_leaf(node: dict) -> bool:
    return "status" in node and node.get("name")


def group_module(module: dict, metadata: dict[str, dict],
                 templates: dict[str, list[str]]) -> tuple[list[dict], int, int]:
    children = module.get("children") or []
    if not children or not all(_is_test_leaf(child) for child in children):
        return children, 0, 0

    buckets: dict[str, list[tuple[dict, str]]] = {}
    for child in children:
        meta = metadata.get(child.get("uid") or "", {})
        nodeid = meta.get("nodeid") or ""
        endpoint = select_endpoint(nodeid) if nodeid else None
        if endpoint:
            endpoint = _normalize_endpoint(endpoint, templates)
        category = meta.get("category") or category_for_dimension(meta.get("dimension") or "")
        buckets.setdefault(endpoint or CROSS_ENDPOINT, []).append((child, category))

    groups = []
    category_count = 0
    order = {
        "功能正向校验": 0, "逆向校验": 1, "边界值校验": 2,
        "异常校验": 3, "特殊场景校验": 4, "其他校验": 5,
    }
    for endpoint in sorted(buckets, key=_endpoint_sort_key):
        endpoint_uid = _group_uid(module.get("uid") or "", endpoint)
        by_category: dict[str, list[dict]] = {}
        for leaf, category in buckets[endpoint]:
            by_category.setdefault(category, []).append(leaf)
        category_nodes = []
        for category in sorted(by_category, key=lambda name: (order.get(name, 99), name)):
            category_uid = _group_uid(endpoint_uid, category)
            leaves = sorted(by_category[category], key=_case_sort_key)
            for leaf in leaves:
                leaf["parentUid"] = category_uid
            category_nodes.append({
                "name": category,
                "uid": category_uid,
                "children": leaves,
            })
            category_count += 1
        groups.append({
            "name": endpoint,
            "uid": endpoint_uid,
            "children": category_nodes,
        })
    return groups, len(groups), category_count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", default=str(REPORT))
    args = parser.parse_args()
    report = Path(args.report_dir)
    suites_file = report / "data" / "suites.json"
    if not suites_file.exists():
        print(f"[skip] 未找到 {suites_file}")
        return

    suites = json.loads(suites_file.read_text(encoding="utf-8"))
    metadata = _load_metadata(report)
    templates = _endpoint_templates(report)
    changed_modules = 0
    inserted_groups = 0
    inserted_categories = 0
    for layer in suites.get("children") or []:
        if layer.get("name") != API_LAYER:
            continue
        for domain in layer.get("children") or []:
            for module in domain.get("children") or []:
                grouped, count, categories = group_module(module, metadata, templates)
                if count:
                    module["children"] = grouped
                    changed_modules += 1
                    inserted_groups += count
                    inserted_categories += categories

    suites_file.write_text(
        json.dumps(suites, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(
        f"[done] 接口聚合：{changed_modules} 个业务模块，插入 {inserted_groups} 个接口分组、"
        f"{inserted_categories} 个测试大分类"
    )


if __name__ == "__main__":
    main()
