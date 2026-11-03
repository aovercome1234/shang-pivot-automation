#!/usr/bin/env python3
"""把报告中的缺陷单同步到 Gitee Issues（幂等、UTF-8、可选 dry-run）。

凭据只从环境变量读取：
  GITEE_TOKEN   Gitee 私人令牌（必填才会真正提交）
  GITEE_OWNER   默认 aovercome1234
  GITEE_REPO    默认 shang-pivot-automation
  GITEE_LABELS  默认 bug（逗号分隔；标签必须已存在）
  GITEE_AUTHOR_MAP  可选 JSON，如 {"段文瑞":"d-wr"}；否则按作者名查询 Gitee 用户

幂等键：Issue body 中的 `<!-- zcode-defect-id: ... -->`；已有 issue 不重复创建。
没有 token 时只生成 payload 和 `gitee_issues.json`，状态标记 not_submitted，绝不伪造 issue URL。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    from config.settings import settings  # noqa: F401  # 触发 .env.local 加载
except Exception:  # noqa: BLE001
    pass
REPORT = ROOT / "artifacts" / "allure-report"
DEFECTS = REPORT / "ext" / "data" / "defects.json"
OUT_DIR = ROOT / "artifacts" / "gitee"
API = "https://gitee.com/api/v5"
DEFAULT_REPO_URL = "https://gitee.com/aovercome1234/shang-pivot-automation"
MARKER = "zcode-defect-id"
# Gitee 原生优先级：1 低、2 中、3 高、4 紧急；缺陷 P0/P1/P2 映射到紧急/高/中。
PRIORITY_VALUE = {"P0": 4, "P1": 3, "P2": 2}


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def repo_parts() -> tuple[str, str]:
    owner = os.getenv("GITEE_OWNER") or ""
    repo = os.getenv("GITEE_REPO") or ""
    if not owner or not repo:
        candidate = os.getenv("GITEE_REPO_URL", DEFAULT_REPO_URL).rstrip("/")
        path = urlparse(candidate).path.strip("/").removesuffix(".git")
        parts = path.split("/")
        if len(parts) >= 2:
            owner = owner or parts[-2]
            repo = repo or parts[-1]
    return owner or "aovercome1234", repo or "shang-pivot-automation"


_AUTHOR_CACHE: dict[str, str] = {}


def _author_login(author: str, token: str) -> str:
    """把代码作者显示名解析到 Gitee login；用于 assignee/正文 @提及。"""
    author = (author or "").strip()
    if not author:
        return ""
    if author in _AUTHOR_CACHE:
        return _AUTHOR_CACHE[author]
    mapping = {}
    try:
        mapping = json.loads(os.getenv("GITEE_AUTHOR_MAP", "{}") or "{}")
    except Exception:  # noqa: BLE001
        mapping = {}
    login = str(mapping.get(author) or "")
    if not login and token:
        try:
            response = requests.get(
                f"{API}/search/users",
                params={"access_token": token, "q": author},
                timeout=15,
            )
            if response.ok:
                rows = response.json() or []
                exact = [row for row in rows if row.get("name") == author]
                login = str((exact or rows or [{}])[0].get("login") or "")
        except Exception:  # noqa: BLE001
            login = ""
    _AUTHOR_CACHE[author] = login
    return login


def _readable(value) -> str:
    """还原 pytest 参数 id 中的 \\uXXXX，避免 Gitee 正文出现转义噪音。"""
    text = str(value if value is not None else "")
    return re.sub(
        r"\\u([0-9a-fA-F]{4})",
        lambda match: chr(int(match.group(1), 16)),
        text,
    )


def _text(value) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _truncate(value, limit: int) -> str:
    text = _text(value)
    return text if len(text) <= limit else text[:limit] + "\n... (truncated)"


def _cell(value) -> str:
    return _readable(value).replace("|", "\\|").replace("\n", " ")


def _marker(defect_id: str) -> str:
    return f"<!-- {MARKER}: {defect_id} -->"


def issue_title(defect: dict) -> str:
    priority = defect.get("priority") or "P2"
    source = "UI" if defect.get("ui") else "API"
    title = f"[自动化缺陷][{source}][{priority}] {_readable(defect.get('name') or defect.get('caseId'))}"
    summary = defect.get("summary") or ""
    if summary and summary not in title:
        title += f" - {summary}"
    return title[:180]


def issue_body(defect: dict, run_id: str, commit: str, owner: str, repo: str,
                author_login: str = "") -> str:
    code = defect.get("code") or {}
    link = defect.get("reportLink") or ""
    location = code.get("location") or "未定位"
    file_url = code.get("fileUrl") or ""
    chain = " → ".join(code.get("chain") or []) or "入口方法"
    request = _truncate(defect.get("request"), 9000)
    response = _truncate(defect.get("response"), 9000)
    log = _truncate(defect.get("backendLog") or "", 10000)
    snippet = _truncate(code.get("snippet") or "", 7000)
    screenshot = defect.get("screenshotUrl") or defect.get("screenshot") or ""
    screenshot_block = ""
    if screenshot:
        if str(screenshot).startswith(("http://", "https://")):
            screenshot_block = f"\n## UI 截图\n\n![UI 截图]({screenshot})\n"
        else:
            screenshot_block = f"\n## UI 截图\n\n本地截图：`{_cell(screenshot)}`（随本地缺陷单归档）\n"

    rows = [
        ("缺陷 ID", f"`{_readable(defect.get('id'))}`"),
        ("用例编号", _readable(defect.get("caseId") or "—")),
        ("来源", "UI 自动化" if defect.get("ui") else "接口自动化"),
        ("接口 / 页面", f"`{defect.get('endpoint') or '—'}`"),
        ("分类", _readable(defect.get("dimension") or "—")),
        ("优先级", defect.get("priority") or "P2"),
        ("运行轮次", run_id),
        ("运行 Commit", commit),
        ("本地缺陷单", link or "—"),
    ]
    if defect.get("verify"):
        rows.insert(4, ("断言意图", defect.get("verify")))
    if defect.get("browser"):
        rows.insert(3, ("浏览器", defect.get("browser")))
    response_obj = defect.get("response") or {}
    response_body = response_obj.get("body") if isinstance(response_obj, dict) else {}
    trace_id = ""
    if isinstance(response_body, dict):
        trace_id = response_body.get("traceId") or ""
    if not trace_id:
        trace_id = response_obj.get("traceId") if isinstance(response_obj, dict) else ""
    if trace_id:
        rows.append(("traceId", f"`{_cell(trace_id)}`"))
    if code.get("location"):
        rows.append(("代码位置", f"[{_cell(location)}]({file_url})" if file_url else f"`{_cell(location)}`"))
    if code.get("author"):
        login_text = f" @{author_login}" if author_login else ""
        rows.append(("代码作者", f"{code.get('author')}{login_text} <{code.get('authorEmail') or '-'}>"))
    if code.get("runCommit"):
        branch = code.get("branch") or "-"
        branch_url = f"https://gitee.com/{owner}/{repo}/tree/{branch}" if branch != "-" else ""
        branch_text = f"[{branch}]({branch_url})" if branch_url else f"`{branch}`"
        rows.append(("运行分支", branch_text + f" / `{code.get('remoteBranch') or '-'}`"))

    table = "\n".join(f"| {_cell(k)} | {_cell(v)} |" for k, v in rows)
    body = f"""{_marker(defect.get('id', ''))}
# 缺陷：{_cell(defect.get('name') or defect.get('caseId') or '未命名')}

## 缺陷摘要

> {_cell(defect.get('summary') or '—')}

## 基本信息

| 配置项 | 值 |
|---|---|
{table}

## 请求

```json
{request}
```

## 响应

```json
{response}
```

## 后端日志（traceId）

```text
{log or "（本次失败没有后端 500 堆栈）"}
```

## 代码定位

```text
位置：{location}
调用链：{chain}
```

```java
{snippet or "（无源码片段）"}
```

## 复现信息

- 仓库：https://gitee.com/{owner}/{repo}
- 报告缺陷单：`{link or "本地 defects 目录"}`
- 运行轮次：`{run_id}`，Commit：`{commit}`
{screenshot_block}
---

_由自动化缺陷报告生成；请按缺陷实际情况补充负责人/里程碑/标签。_
"""
    return body[:50000]


def _existing_issues(owner: str, repo: str, token: str) -> dict[str, dict]:
    if not token:
        return {}
    result = {}
    for page in range(1, 11):
        try:
            response = requests.get(
                f"{API}/repos/{owner}/{repo}/issues",
                params={"access_token": token, "state": "all", "per_page": 100, "page": page},
                timeout=20,
            )
            if response.status_code != 200:
                break
            rows = response.json() or []
        except Exception:  # noqa: BLE001
            break
        for issue in rows:
            body = str(issue.get("body") or "")
            for match in re.finditer(rf"<!--\s*{MARKER}:\s*([^\n]*?)\s*-->", body):
                defect_id = match.group(1).strip()
                current = result.get(defect_id)
                # 同一缺陷可能有历史重复；固定保留最早创建的 issue，后续只读复用。
                if current is None or str(issue.get("created_at") or "") < str(current.get("created_at") or ""):
                    result[defect_id] = issue
        if len(rows) < 100:
            break
    return result


def _ensure_priority_labels(owner: str, repo: str, token: str) -> None:
    if not token:
        return
    try:
        existing = requests.get(
            f"{API}/repos/{owner}/{repo}/labels",
            params={"access_token": token, "per_page": 100}, timeout=15,
        ).json()
        names = {item.get("name") for item in existing or []}
    except Exception:  # noqa: BLE001
        return
    colors = {"P0": "DB2828", "P1": "F59A23", "P2": "1F9D61"}
    for name, color in colors.items():
        if name in names:
            continue
        try:
            requests.post(
                f"{API}/repos/{owner}/{repo}/labels",
                params={"access_token": token},
                data={"access_token": token, "name": name, "color": color},
                timeout=15,
            )
        except Exception:  # noqa: BLE001
            pass


def _submit(owner: str, repo: str, token: str, payload: dict) -> dict:
    data = {
        "access_token": token,
        "repo": repo,
        "title": payload["title"],
        "body": payload["body"],
        "labels": payload.get("labels") or os.getenv("GITEE_LABELS", "bug"),
        "security_hole": "false",
    }
    if payload.get("branch"):
        data["branch"] = payload["branch"]
    if payload.get("assignee"):
        data["assignee"] = payload["assignee"]
    if payload.get("priority"):
        data["priority"] = str(payload["priority"])
    response = requests.post(
        f"{API}/repos/{owner}/issues",
        params={"access_token": token},
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"},
        timeout=30,
    )
    if response.status_code not in (200, 201):
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")
    return response.json()


def _update_issue(owner: str, repo: str, token: str, number: str, payload: dict) -> dict:
    data = {
        "access_token": token,
        "repo": repo,
        "title": payload["title"],
        "labels": payload.get("labels") or os.getenv("GITEE_LABELS", "bug"),
    }
    if "body" in payload:
        data["body"] = payload["body"]
    if payload.get("branch"):
        data["branch"] = payload["branch"]
    if payload.get("assignee"):
        data["assignee"] = payload["assignee"]
    if payload.get("priority"):
        data["priority"] = str(payload["priority"])
    response = requests.patch(
        f"{API}/repos/{owner}/issues/{number}",
        data=data, timeout=30,
    )
    if response.status_code not in (200, 201):
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", default=str(REPORT))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = Path(args.report_dir)
    defects_file = report / "ext" / "data" / "defects.json"
    data = load(defects_file, {})
    defects = data.get("defects") or []
    if not defects:
        print("[skip] 没有缺陷单可同步")
        return

    owner, repo = repo_parts()
    token = os.getenv("GITEE_TOKEN", "").strip()
    submit = bool(token) and not args.dry_run
    existing = _existing_issues(owner, repo, token) if submit else {}
    collaborators: set[str] = set()
    if submit:
        _ensure_priority_labels(owner, repo, token)
        try:
            response = requests.get(
                f"{API}/repos/{owner}/{repo}/collaborators",
                params={"access_token": token, "per_page": 100}, timeout=15,
            )
            if response.ok:
                collaborators = {str(item.get("login") or "") for item in response.json() or []}
        except Exception:  # noqa: BLE001
            collaborators = set()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "repository": f"https://gitee.com/{owner}/{repo}",
        "tokenConfigured": bool(token),
        "dryRun": not submit,
        "issues": {},
    }
    payloads = []
    updated = 0
    for defect in defects:
        defect["priority"] = defect.get("priority") or "P2"
        code = defect.get("code") or {}
        author_login = _author_login(code.get("author") or "", token)
        assignee = author_login if author_login in collaborators else ""
        branch = code.get("branch") or ""
        priority = defect.get("priority") or "P2"
        payload = {
            "title": issue_title(defect),
            "body": issue_body(
                defect,
                data.get("runId") or "",
                data.get("git") or "",
                owner,
                repo,
                author_login=author_login,
            ),
            "labels": f"bug,{priority}",
            "branch": branch,
            "assignee": assignee,
            "priority": PRIORITY_VALUE.get(priority, 2),
        }
        payloads.append({
            "defect_id": defect.get("id"), "title": payload["title"],
            "body": payload["body"], "labels": payload["labels"],
            "branch": branch, "assignee": assignee,
        })
        existing_issue = existing.get(str(defect.get("id")))
        record = {
            "status": "not_submitted",
            "number": None,
            "htmlUrl": "",
            "error": "",
        }
        if existing_issue:
            current_labels = {item.get("name") for item in existing_issue.get("labels") or []}
            current_title = existing_issue.get("title") or ""
            current_body = existing_issue.get("body") or ""
            # 平台拦截后的占位/精简正文不再用大段日志覆盖，避免再次触发内容审核。
            update_body = payload["body"] != current_body and "精简正文" not in current_body
            current_priority = int(existing_issue.get("priority") or 0)
            current_assignee = (existing_issue.get("assignee") or {}).get("login") or ""
            needs_update = (
                current_title != payload["title"]
                or current_labels != {"bug", priority}
                or current_priority != int(payload["priority"])
                or (assignee and current_assignee != assignee)
                or update_body
            )
            record.update({
                "status": "existing",
                "number": existing_issue.get("number"),
                "htmlUrl": existing_issue.get("html_url") or "",
            })
            if submit and needs_update:
                try:
                    patch_payload = dict(payload)
                    if not update_body:
                        patch_payload.pop("body", None)
                    _update_issue(
                        owner, repo, token, str(existing_issue.get("number")), patch_payload
                    )
                    record["status"] = "updated"
                    updated += 1
                except Exception as exc:  # noqa: BLE001
                    record["error"] = f"metadata update failed: {exc}"
        elif submit:
            try:
                issue = _submit(owner, repo, token, payload)
                record.update({
                    "status": "submitted",
                    "number": issue.get("number"),
                    "htmlUrl": issue.get("html_url") or "",
                })
            except Exception as exc:  # noqa: BLE001
                record.update({"status": "error", "error": str(exc)})
        elif not token:
            record["error"] = "GITEE_TOKEN 未配置，已生成 payload 未提交"
        else:
            record["error"] = "dry-run：未提交"
        manifest["issues"][defect.get("id")] = record
        defect["gitee"] = record

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "payloads.json").write_text(
        json.dumps(payloads, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (report / "ext" / "data" / "gitee_issues.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    defects_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    submitted = sum(1 for item in manifest["issues"].values() if item["status"] == "submitted")
    existing_count = sum(1 for item in manifest["issues"].values() if item["status"] in ("existing", "updated"))
    errors = sum(1 for item in manifest["issues"].values() if item["status"] == "error")
    print(
        f"[gitee] 缺陷 {len(defects)}：已提交 {submitted}，已存在/更新 {existing_count}，"
        f"本次更新 {updated}，错误 {errors}，"
        f"未提交 {sum(1 for i in manifest['issues'].values() if i['status'] == 'not_submitted')} "
        f"-> {report / 'ext' / 'data' / 'gitee_issues.json'}"
    )
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
