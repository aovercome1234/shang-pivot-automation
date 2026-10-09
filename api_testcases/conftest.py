"""全局 pytest 配置：加载所有 fixtures 和 Allure 报告钩子"""
import sys
import json
import os
import re
import datetime
import uuid
from pathlib import Path
import pytest

# 确保项目根目录在 path 中
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 自动加载 fixtures
pytest_plugins = [
    "fixtures.api_fixtures",
]

# ============= Allure 报告增强钩子 =============

try:
    import allure  # type: ignore
    _ALLURE = True
except ImportError:
    _ALLURE = False


def pytest_configure(config):
    """pytest 启动时配置"""
    if _ALLURE:
        allure_dir = config.getoption("--alluredir", None)
        if allure_dir:
            # 生成环境信息附件
            env_info = {
                "Framework": "api_testcases",
                "Python": sys.version.split()[0],
                "Platform": sys.platform,
            }
            env_path = Path(allure_dir) / "environment.properties"
            env_path.parent.mkdir(parents=True, exist_ok=True)
            with open(env_path, "w") as f:
                for k, v in env_info.items():
                    f.write(f"{k}={v}\n")

            # 生成 executor 信息（CI 场景可扩展）
            executor_path = Path(allure_dir) / "executor.json"
            try:
                executor_info = {
                    "name": "pytest",
                    "type": "pytest",
                    "reportUrl": "",
                }
                with open(executor_path, "w") as f:
                    json.dump(executor_info, f, indent=2)
            except Exception:
                pass
    config._automation_results = []


def pytest_make_parametrize_id(config, val):
    """让 Allure 正确显示参数化用例名称"""
    if isinstance(val, dict) and "desc" in val:
        return val["desc"]
    return str(val)


def pytest_collection_modifyitems(config, items):
    """为测试用例自动添加 allure.dynamic 方法增强报告"""
    pass  # 由具体测试类中的标签实现


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Persist redacted request/response + step/PNG evidence for every failure."""
    outcome = yield
    report = outcome.get_result()
    if report.outcome != "failed":
        if report.when == "call":
            _record_automation_result(item, report, None)
        return
    try:
        from evidence import write_failure_evidence
        response = None
        for value in item.funcargs.values():
            candidate = getattr(value, "last_response", None)
            if candidate is not None:
                response = candidate
        path = write_failure_evidence(item.nodeid, report, response)
        os.environ["LAST_FAILURE_EVIDENCE"] = str(path)
        _record_automation_result(item, report, path)
    except Exception as exc:
        # Evidence generation must never mask the original test failure.
        print(f"[evidence] unable to write failure evidence: {exc}")


def _record_automation_result(item, report, evidence_path):
    """Collect a stable sidecar result file for ZenTao synchronization."""
    config = item.config
    case_ids = []
    for marker in item.iter_markers(name="zt_case"):
        case_ids.extend(str(value) for value in marker.args)
        case_ids.extend(str(value) for value in marker.kwargs.get("case_ids", []))
    if not case_ids:
        return
    config._automation_results.append({
        "nodeid": item.nodeid,
        "outcome": report.outcome,
        "case_ids": case_ids,
        "duration_seconds": getattr(report, "duration", 0),
        "evidence_json": str(evidence_path) if evidence_path else "",
    })


def pytest_sessionfinish(session, exitstatus):
    output = Path(os.getenv("RESULTS_JSON", "artifacts/automation_results.json"))
    output.parent.mkdir(parents=True, exist_ok=True)
    # 结果新鲜度绑定：run_id + 起止时间 + junit 摘要，防止"改/触碰结果文件"绕过 C8。
    junit = Path(os.getenv("JUNIT_XML", str(output.parent / "junit.xml")))
    digest = ""
    if junit.exists():
        import hashlib
        digest = hashlib.sha256(junit.read_bytes()).hexdigest()
    payload = {
        "exit_status": exitstatus,
        "base_url": os.getenv("BASE_URL", ""),
        "run_id": os.getenv("RUN_ID", "") or uuid.uuid4().hex,
        "started_at": os.getenv("RUN_STARTED_AT", ""),
        "finished_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "junit_xml": str(junit),
        "junit_sha256": digest,
        "results": getattr(session.config, "_automation_results", []),
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if not payload["results"]:
        print("[results] 警告：结果为空——没有任何测试挂 zt_case 标记，回写禅道会拿不到数据"
              "（检查 parametrize 是否带 marks=pytest.mark.zt_case(...)）")
