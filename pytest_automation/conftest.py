"""pytest 全局入口：插件加载、Allure 标签、失败截图、结果文件。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

pytest_plugins = [
    "fixtures.api_fixtures",
    "fixtures.ui_fixtures",
]

try:
    import allure  # type: ignore
except ImportError:  # pragma: no cover
    allure = None

try:
    from playwright.sync_api import Page  # type: ignore
except ImportError:  # pragma: no cover
    Page = None


_ENV_LABELS = {
    "epic": "尚品汇 · 自动化测试",
    "api": "接口自动化",
    "ui": "UI 自动化",
    "e2e": "端到端链路",
    "security": "安全测试",
}
_SEVERITY = {"P0": "blocker", "P1": "critical", "P2": "normal"}


def pytest_configure(config):
    config._automation_results = []
    if allure is None:
        return
    allure_dir = config.getoption("--alluredir", None)
    if not allure_dir:
        return

    # environment.properties 按 Latin-1 读取，只能写 ASCII
    from config.settings import settings

    info = {
        "Framework": "pytest_automation (API + Playwright)",
        "Test env": settings.env,
        "Mall API": settings.api_mall_base,
        "Admin API": settings.api_admin_base,
        "Mall UI": settings.ui_mall_url,
        "Admin UI": settings.ui_admin_url,
        "UI": "on" if settings.run_ui else "off",
        "Python": sys.version.split()[0],
    }
    out = Path(allure_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "environment.properties", "w", encoding="utf-8") as f:
        for key, value in info.items():
            f.write(f"{key}={value}\n")

    categories = [
        {"name": "① 接口契约/结构", "matchedStatuses": ["failed", "broken"],
         "messageRegex": ".*(响应不是 JSON|响应体应为对象|缺少字段|业务码期望).*"},
        {"name": "② 业务规则", "matchedStatuses": ["failed", "broken"],
         "messageRegex": ".*(业务码期望|提示信息应包含|HTTP 期望).*"},
        {"name": "③ UI 元素/导航", "matchedStatuses": ["failed", "broken"],
         "messageRegex": ".*(Timeout|locator|waiting for).*"},
        {"name": "④ 服务端 5xx", "matchedStatuses": ["failed", "broken"],
         "messageRegex": ".*实际 5\\d\\d.*"},
        {"name": "⑤ 其余失败", "matchedStatuses": ["failed", "broken"]},
    ]
    (out / "categories.json").write_text(
        json.dumps(categories, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def pytest_report_header(config):
    """报告头暴露关键开关，避免“为什么被 skip”靠猜。"""
    from config.settings import settings

    return [
        f"test env: {settings.env}",
        f"admin credentials: {'loaded' if settings.admin_password else 'MISSING (.env.local / ADMIN_PASSWORD)'}",
        f"ui: {'on' if settings.run_ui else 'off'}",
    ]


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """所有 UI 用例统一 1280x720；商城 <768px 会切 H5 形态，不能混测。"""
    return {**browser_context_args, "viewport": {"width": 1280, "height": 720}}


@pytest.fixture(autouse=True)
def _allure_labels(request):
    """按 marker 自动设置 epic / feature / severity，报告可按层钻取。"""
    if allure is None:
        yield
        return
    markers = {m.name for m in request.node.iter_markers()}
    if "api" in markers:
        allure.dynamic.epic(_ENV_LABELS["api"])
        allure.dynamic.feature("接口")
    if "ui" in markers:
        allure.dynamic.epic(_ENV_LABELS["ui"])
        allure.dynamic.feature("浏览器")
    if "e2e" in markers:
        allure.dynamic.epic(_ENV_LABELS["e2e"])
        allure.dynamic.feature("业务链路")
    if "security" in markers:
        allure.dynamic.feature("安全")
    for level, severity in _SEVERITY.items():
        if level in markers:
            allure.dynamic.severity(severity)
            break
    story = request.node.name.replace("test_", "").replace("_", " ")
    allure.dynamic.story(story)
    yield


def _safe_name(nodeid: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", nodeid).strip("_")[:180]


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    markers = {m.name for m in item.iter_markers()}
    if report.when == "call":
        item.config._automation_results.append(
            {
                "nodeid": item.nodeid,
                "outcome": report.outcome,
                "duration_seconds": round(getattr(report, "duration", 0), 3),
            }
        )

    # 用例结束后附加 Playwright trace（每个 UI 用例一份）
    if report.when == "teardown" and "ui" in markers and allure is not None:
        try:
            from fixtures.ui_fixtures import trace_path

            trace = trace_path(item.nodeid)
            if trace.exists():
                allure.attach.file(str(trace), name="Playwright Trace", extension="zip")
        except Exception as exc:  # noqa: BLE001 - 附件失败不能掩盖用例结果
            print(f"[ui] Playwright trace 附件失败：{exc}")

    if report.outcome != "failed" or Page is None:
        return

    # 失败留证：UI 用例截图并挂到 Allure
    for value in item.funcargs.values():
        page = value if isinstance(value, Page) else getattr(value, "page", None)
        if not isinstance(page, Page):
            continue
        try:
            from config.settings import settings

            target = settings.artifacts_dir / "ui" / "failures" / f"{_safe_name(item.nodeid)}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(target), full_page=True)
            if allure is not None:
                allure.attach.file(
                    str(target),
                    name="失败截图",
                    attachment_type=allure.attachment_type.PNG,
                )
        except Exception as exc:  # noqa: BLE001 - 留证失败不能掩盖原始失败
            print(f"[ui] 失败截图写入失败：{exc}")


def pytest_sessionfinish(session, exitstatus):
    from config.settings import settings

    # --collect-only 也会触发 sessionfinish；不要把上一轮结果覆盖成空
    if session.config.option.collectonly:
        return

    payload = {
        "exit_status": int(exitstatus),
        "env": settings.env,
        "mall_api": settings.api_mall_base,
        "admin_api": settings.api_admin_base,
        "results": getattr(session.config, "_automation_results", []),
    }
    output = settings.artifacts_dir / "results.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
