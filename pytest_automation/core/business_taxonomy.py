"""业务分类：Allure 套件树按“业务域 → 业务模块”归档，验证维度独立成标签。

设计原则：
- 一个用例只归属一个业务模块，避免 MQ/Redis/大数据量等横切维度把套件树拆散；
- 优先按用例实际调用的接口判断业务主体，其次按函数/文件兜底；
- 分类器不依赖 pytest/Allure，报告脚本与审计脚本可复用。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAXONOMY_FILE = ROOT / "data" / "business_taxonomy.yaml"
ENDPOINT_MAP_FILE = ROOT / "artifacts" / "case_endpoint_map.json"
ATTRIBUTION_FILE = ROOT / "data" / "endpoint_attribution.yaml"


@dataclass(frozen=True)
class Classification:
    domain: str
    module: str
    dimension: str

    @property
    def path(self) -> str:
        return f"{self.domain}/{self.module}"

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@lru_cache(maxsize=1)
def taxonomy() -> dict:
    try:
        import yaml

        with TAXONOMY_FILE.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except Exception as exc:  # noqa: BLE001 - 分类失败不能阻断测试执行
        print(f"[taxonomy] 业务分类配置加载失败：{exc}")
        return {}


@lru_cache(maxsize=1)
def attribution() -> dict[str, list[str]]:
    try:
        import yaml

        data = yaml.safe_load(ATTRIBUTION_FILE.read_text(encoding="utf-8")) or {}
        return {str(key): [str(item) for item in (value or [])] for key, value in data.items()}
    except Exception:  # noqa: BLE001
        return {}


def _attribution_for(nodeid: str) -> list[str]:
    base = nodeid.split("[", 1)[0]
    return attribution().get(base) or attribution().get(nodeid) or []


@lru_cache(maxsize=1)
def endpoint_map() -> dict[str, list[str]]:
    try:
        data = json.loads(ENDPOINT_MAP_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return {
        str(nodeid): [str(item) for item in (endpoints or [])]
        for nodeid, endpoints in (data.get("tests") or {}).items()
    }


def _decode_unicode_escapes(value: str) -> str:
    if "\\u" not in value:
        return value

    return re.sub(
        r"\\u([0-9a-fA-F]{4})",
        lambda match: chr(int(match.group(1), 16)),
        value,
    )


def _endpoint_from_nodeid(nodeid: str) -> list[str]:
    """参数化用例的 id 里通常带“检查类型｜METHOD /path”，可直接提取。"""
    decoded = _decode_unicode_escapes(nodeid)
    matches = re.findall(r"\b(GET|POST|PUT|DELETE|PATCH)\s+(/[^\s\]]+)", decoded)
    return [f"{method} {path}" for method, path in matches]


def _path(endpoint: str) -> str:
    return endpoint.split(" ", 1)[-1].strip()


@lru_cache(maxsize=1)
def endpoint_rules() -> list[dict]:
    rules = list(taxonomy().get("endpoint_rules") or [])
    return sorted(rules, key=lambda rule: len(str(rule.get("path") or "")), reverse=True)


def _endpoint_rule(path: str) -> dict | None:
    for rule in endpoint_rules():
        prefix = str(rule.get("path") or "")
        if prefix and path.startswith(prefix):
            return rule
    return None


def _candidate_endpoints(nodeid: str, endpoints: list[str] | None = None) -> list[str]:
    candidates: list[str] = []
    for endpoint in list(endpoints or []) + _endpoint_from_nodeid(nodeid) + (endpoint_map().get(nodeid) or []):
        if endpoint not in candidates:
            candidates.append(endpoint)
    return candidates


def _best_endpoint(nodeid: str, endpoints: list[str] | None = None) -> dict | None:
    preferred = _attribution_for(nodeid)
    if preferred:
        rule = _endpoint_rule(_path(preferred[0]))
        if rule:
            return rule
    best: dict | None = None
    for endpoint in _candidate_endpoints(nodeid, endpoints):
        rule = _endpoint_rule(_path(endpoint))
        if not rule:
            continue
        if best is None or int(rule.get("priority") or 0) > int(best.get("priority") or 0):
            best = rule
    return best


def select_endpoint(nodeid: str, endpoints: list[str] | None = None) -> str | None:
    """选用例的业务主体接口，供 Allure 按接口聚合排序。

    优先使用运行期映射里的模板端点；多接口用例选 endpoint_rules.priority 最高的业务动作；
    没有规则命中时保留第一个端点。无接口映射的用例返回 None。
    """
    preferred = _attribution_for(nodeid)
    if preferred:
        return preferred[0]
    candidates = _candidate_endpoints(nodeid, endpoints)
    if not candidates:
        return None
    ranked = sorted(
        enumerate(candidates),
        key=lambda pair: (
            -int((_endpoint_rule(_path(pair[1])) or {}).get("priority") or 0),
            pair[0],
        ),
    )
    return ranked[0][1]


def _file_part(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


def _file_rule(nodeid: str) -> dict | None:
    file_part = _file_part(nodeid)
    rules = taxonomy().get("file_rules") or {}
    if file_part in rules:
        return rules[file_part]
    for key, value in rules.items():
        if file_part.startswith(str(key)):
            return value
    return None


def _keyword_rule(nodeid: str) -> dict | None:
    lowered = nodeid.lower()
    for rule in taxonomy().get("keyword_rules") or []:
        if str(rule.get("match") or "").lower() in lowered:
            return rule
    return None


def _function_override(nodeid: str) -> dict | None:
    base = nodeid.split("[", 1)[0]
    overrides = taxonomy().get("function_overrides") or {}
    return overrides.get(base) or overrides.get(nodeid)


def _dimension_from_check(nodeid: str) -> str | None:
    if "test_endpoint_sweep" not in nodeid:
        return None
    decoded = _decode_unicode_escapes(nodeid)
    match = re.search(r"\[([^\]｜|]+)[｜|]", decoded)
    if not match:
        return None
    check = match.group(1).lower()
    for rule in taxonomy().get("dimension_check_rules") or []:
        if str(rule.get("match") or "").lower() in check:
            return str(rule.get("dimension") or "")
    return "接口巡检"


def _dimension_from_function(nodeid: str) -> str | None:
    lowered = nodeid.lower()
    for rule in taxonomy().get("dimension_function_rules") or []:
        if str(rule.get("match") or "").lower() in lowered:
            return str(rule.get("dimension") or "")
    return None


def _dimension_from_file(nodeid: str) -> str | None:
    file_part = _file_part(nodeid)
    for key, value in (taxonomy().get("dimension_files") or {}).items():
        if file_part.startswith(str(key)):
            return str(value)
    return None


def classify(nodeid: str, endpoints: list[str] | None = None) -> Classification:
    """返回用例的业务域/业务模块/验证维度。"""
    overrides = taxonomy().get("dimension_overrides") or {}
    dimension = (
        overrides.get(nodeid.split("[", 1)[0])
        or _dimension_from_check(nodeid)
        or (_dimension_from_function(nodeid) if "test_endpoint_matrix_orders" in nodeid else None)
        or _dimension_from_file(nodeid)
        or _dimension_from_function(nodeid)
        or str((taxonomy().get("default") or {}).get("dimension") or "功能")
    )

    chosen = _function_override(nodeid)
    if chosen is None:
        chosen = _best_endpoint(nodeid, endpoints)
    if chosen is None:
        chosen = _keyword_rule(nodeid)
    if chosen is None:
        chosen = _file_rule(nodeid)
    default = taxonomy().get("default") or {}
    domain = str((chosen or {}).get("domain") or default.get("domain") or "平台治理")
    module = str((chosen or {}).get("module") or default.get("module") or "未分类")
    return Classification(domain=domain, module=module, dimension=dimension)


CATEGORY_ORDER = [
    "功能正向校验",
    "逆向校验",
    "边界值校验",
    "异常校验",
    "特殊场景校验",
    "其他校验",
]
_DIMENSION_CATEGORY = {
    "功能正向校验": {"功能", "功能正向", "数据库落库", "消息队列", "缓存一致性",
                    "数据一致性", "CRUD 往返", "数据驱动", "冒烟", "UI 功能", "端到端"},
    "逆向校验": {"参数校验"},
    "边界值校验": {"边界值", "边界与校验", "参数组合", "参数联动"},
    "异常校验": {"异常", "请求方式"},
    "特殊场景校验": {"安全", "越权", "幂等", "大数据量", "接口巡检"},
}


def category_for_dimension(dimension: str) -> str:
    """把细粒度验证维度归并为 Allure 的测试大分类。"""
    for category in CATEGORY_ORDER:
        if dimension in _DIMENSION_CATEGORY.get(category, set()):
            return category
    return "其他校验"


def describe(nodeid: str) -> dict[str, str]:
    return classify(nodeid).as_dict()
