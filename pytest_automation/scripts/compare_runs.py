#!/usr/bin/env python3
"""两轮运行对比 + 趋势数据，输出报告 ext/data/compare.json / trend.json。"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.business_taxonomy import classify  # noqa: E402
from core.known_failures import evaluate as evaluate_known  # noqa: E402
from core.known_failures import load_ledger  # noqa: E402

HISTORY = ROOT / "artifacts" / "history"
DB = HISTORY / "index.sqlite"
REPORT = ROOT / "artifacts" / "allure-report"


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def registry() -> tuple[dict, dict, dict]:
    data = load(ROOT / "data" / "case_registry.json", {})
    titles, hashes, case_ids = {}, {}, {}
    for nodeid, item in (data.get("cases") or {}).items():
        titles[nodeid] = item.get("title") or nodeid
        hashes[nodeid] = item.get("content_hash") or ""
        case_ids[nodeid] = item.get("case_id") or ""
    return titles, hashes, case_ids


def run_results(run: dict, titles: dict, hashes: dict,
                case_ids: dict | None = None) -> dict[str, dict]:
    path = ROOT / run["path"] / "results.json"
    payload = load(path, {})
    result = {}
    for item in payload.get("results") or []:
        nodeid = item.get("nodeid") or ""
        if not nodeid:
            continue
        classification = classify(nodeid)
        result[nodeid] = {
            "nodeid": nodeid,
            "title": titles.get(nodeid, nodeid),
            "case_id": (item.get("case_id") or (case_ids or {}).get(nodeid) or ""),
            "status": item.get("outcome") or "unknown",
            "duration_ms": round(float(item.get("duration_seconds") or 0) * 1000, 1),
            "content_hash": hashes.get(nodeid, ""),
            "domain": classification.domain,
            "module": classification.module,
            "dimension": classification.dimension,
        }
    return result


def module_stats(after: dict[str, dict]) -> list[dict]:
    """按业务模块汇总本轮结果，供失败集中度和图表使用。"""
    buckets: dict[str, dict] = {}
    for item in after.values():
        key = f"{item.get('domain') or '未分类'}/{item.get('module') or '未分类'}"
        bucket = buckets.setdefault(key, {
            "module": key,
            "domain": item.get("domain") or "未分类",
            "name": item.get("module") or "未分类",
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
        })
        bucket["total"] += 1
        status = item.get("status")
        if status == "passed":
            bucket["passed"] += 1
        elif status in ("failed", "broken"):
            bucket["failed"] += 1
        elif status == "skipped":
            bucket["skipped"] += 1
    result = list(buckets.values())
    for item in result:
        item["failRate"] = round(
            item["failed"] / item["total"] * 100, 1
        ) if item["total"] else 0.0
    return sorted(result, key=lambda item: (-item["failed"], -item["total"], item["module"]))


def build_insights(
    baseline: dict,
    current: dict,
    diff: dict,
    comparability: dict,
    modules: list[dict],
    known: dict | None = None,
) -> dict:
    """基于本轮实际差异生成风险、关注点和建议；所有结论都带数据证据。"""
    risks: list[dict] = []
    focus: list[dict] = []
    suggestions: list[str] = []
    counts = diff.get("counts") or {}
    total = int(current.get("total") or 0)
    failed = int(current.get("failed") or 0)
    fail_rate = (failed / total * 100) if total else 0.0
    new_failures = int(counts.get("newFailures") or 0)
    fixed = int(counts.get("fixed") or 0)
    still_failing = int(counts.get("stillFailing") or 0)
    added = int(counts.get("added") or 0)
    removed = int(counts.get("removed") or 0)
    known = known or {}
    unexpected = int(known.get("unexpectedCount") or 0)
    expired = int(known.get("expiredCount") or 0)
    known_count = int(known.get("knownCount") or 0)
    fixed_known = int(known.get("fixedCount") or 0)
    unmapped = int(known.get("unmappedCount") or 0)
    failing_modules = [item for item in modules if item["failed"] > 0]
    top_modules = failing_modules[:5]
    top_text = "、".join(
        f"{item['module']}（{item['failed']}/{item['total']}）" for item in top_modules
    ) or "无"

    def add_risk(level: str, title: str, detail: str, evidence: str, action: str) -> None:
        risks.append({
            "level": level, "title": title, "detail": detail,
            "evidence": evidence, "action": action,
        })

    def add_focus(title: str, detail: str, count: int | None = None) -> None:
        item = {"title": title, "detail": detail}
        if count is not None:
            item["count"] = count
        focus.append(item)

    problems = []
    if not all(comparability.values()):
        problems.append("commit/env/分支或完整性不一致")
        add_risk(
            "high",
            "两轮运行不可比",
            "基线与本轮的 commit、环境、分支或完整性不一致，覆盖率/耗时差异不能直接作为回归结论。",
            json.dumps(comparability, ensure_ascii=False),
            "在相同 commit、相同环境重跑后再判断；报告中的差异仅作参考。",
        )

    if new_failures or unexpected:
        examples = "；".join(
            f"{item.get('case_id') or '-'} {item.get('title') or item.get('nodeid')}"
            for item in (diff.get("newFailures") or known.get("unexpected") or [])[:5]
        )
        add_risk(
            "high",
            f"新增/未登记失败 {new_failures or unexpected} 条",
            "本轮出现基线未失败或未登记到 known_failures 的失败，需优先确认是新缺陷还是环境/数据抖动。",
            f"新增失败 {new_failures}；未登记 {unexpected}；示例：{examples or '见明细'}",
            "阻断合并或发布；按失败模块定位首个异常接口、traceId 与缺陷单。",
        )
        add_focus("新增失败优先分诊", f"共 {new_failures or unexpected} 条，先排查最近代码变更和共享数据状态。", new_failures or unexpected)
    else:
        add_focus("新增失败", "本轮相对基线没有新增失败，发布门禁可继续以存量失败为基线。", 0)

    if expired:
        add_risk(
            "high",
            f"已知失败豁免过期 {expired} 条",
            "台账中的已知失败已超过到期日，必须修复、续期并重新确认 owner。",
            f"expired={expired}",
            "处理过期条目后再发布；不能把过期豁免当作通过。",
        )
    if unmapped:
        add_focus(
            "待归因失败",
            f"{unmapped} 条已知失败暂未匹配缺陷单，需补齐 bug_id/owner 后才能长期豁免。",
            unmapped,
        )
    if known_count:
        add_focus(
            "已知失败台账",
            f"{known_count} 条失败已在 known_failures 台账；修复后请从台账清理（待清理 {fixed_known} 条）。",
            known_count,
        )

    if still_failing:
        level = "high" if fail_rate >= 20 else "medium"
        add_risk(
            level,
            f"存量失败 {still_failing} 条（{fail_rate:.1f}%）",
            f"失败集中在 {len(failing_modules)} 个业务模块，存量失败尚未修复，直接发布仍会带着已知风险。",
            f"failed {failed} / total {total}；失败模块前五：{top_text}",
            "按失败模块分配 owner，先处理失败数最多的前三个模块；对每条失败补充缺陷定位和复现路径。",
        )
        add_focus(
            "存量失败集中模块",
            f"前五：{top_text}；优先从失败密度最高且影响核心链路的模块开始。",
            still_failing,
        )
        suggestions.append(
            "将存量失败按业务模块拆成修复批次；每个批次回归时对比本页新增失败/修复列表，避免修复引入回归。"
        )
    else:
        add_focus("存量失败", "本轮没有失败用例，维持当前基线即可。", 0)

    coverage_items = [
        ("行覆盖率", "line_rate", 100.0, 60.0),
        ("方法覆盖率", "method_rate", 1.0, 60.0),
        ("DB 落库断言率", "db_rate", 1.0, 60.0),
        ("接口覆盖率", "interface_rate", 1.0, 90.0),
    ]
    for label, key, scale, floor in coverage_items:
        pair = [baseline.get(key), current.get(key)]
        both = [
            float(value) * scale for value in pair if value is not None
        ]
        if len(both) == 2:
            delta = both[1] - both[0]
            if delta <= -1.0:
                add_risk(
                    "medium",
                    f"{label}下降 {abs(delta):.1f} 个百分点",
                    "覆盖率相对基线下降，可能是新增代码未被用例覆盖或用例被删除/跳过。",
                    f"基线 {both[0]:.1f}% → 本轮 {both[1]:.1f}%",
                    "检查新增/变更接口与链路，补对应业务模块用例；确认没有误删或误跳过。",
                )
        if both and both[-1] < floor:
            suggestions.append(
                f"{label}当前 {both[-1]:.1f}%，低于建议基线 {floor:.0f}%；下一轮优先补核心业务链路的断言。"
            )

    baseline_wall = baseline.get("wall_seconds")
    current_wall = current.get("wall_seconds")
    if baseline_wall and current_wall:
        delta = current_wall - baseline_wall
        delta_pct = delta / baseline_wall * 100 if baseline_wall else 0
        if delta > 60 and delta_pct > 20:
            add_risk(
                "medium",
                f"总耗时增加 {delta_pct:.1f}%（+{delta:.1f}s）",
                "本轮墙钟耗时明显高于基线，可能来自新增用例、重试、环境变慢或串行阻塞。",
                f"基线 {baseline_wall:.1f}s → 本轮 {current_wall:.1f}s",
                "结合趋势页确认是否持续；检查新增失败重试、等待/轮询和串行 lane 的耗时。",
            )
        elif delta < -60 and delta_pct < -20:
            suggestions.append(
                f"总耗时下降 {abs(delta_pct):.1f}%（{delta:.1f}s），可确认并行分组/用例精简是否影响了覆盖。"
            )

    if added:
        add_focus("新增用例", f"本轮新增 {added} 条，确认已通过评审并纳入稳定编号。", added)
        suggestions.append("确认新增用例的评审状态和稳定编号；把新增用例纳入下一轮基线。")
    if removed:
        add_risk(
            "medium",
            f"用例减少 {removed} 条",
            "本轮相对基线少执行了用例，可能是退役、收集条件变化或误删。",
            f"removed {removed}",
            "核对用例注册表的 retired 记录；非预期减少时恢复用例后再发布。",
        )
    skipped_pair = [baseline.get("skipped"), current.get("skipped")]
    if all(value is not None for value in skipped_pair) and skipped_pair[1] > skipped_pair[0]:
        add_risk(
            "low",
            f"跳过用例增加 {skipped_pair[1] - skipped_pair[0]} 条",
            "跳过增加会降低有效覆盖，需确认是环境依赖还是稳定的业务前置条件缺失。",
            f"跳过 {skipped_pair[0]} → {skipped_pair[1]}",
            "逐条检查 skip 原因；可自动化的前置条件不要长期跳过。",
        )
    if fixed:
        add_focus("已修复", f"本轮修复 {fixed} 条，确认修复用例进入回归集合。", fixed)
        suggestions.append(f"本轮修复 {fixed} 条，建议将对应接口加入冒烟/回归集，防止回退。")

    if not suggestions:
        suggestions.append("本轮没有明显风险；保持当前基线，下一轮继续关注新增失败和覆盖率变化。")

    level_rank = {"high": 3, "medium": 2, "low": 1}
    risk_level = max((item["level"] for item in risks), key=lambda level: level_rank[level], default="low")
    if new_failures or unexpected:
        verdict = f"发现 {new_failures or unexpected} 条新增/未登记失败，建议先阻断发布并完成分诊。"
    elif expired:
        verdict = f"有 {expired} 条已知失败豁免过期，需先处理或续期。"
    elif still_failing:
        verdict = (
            f"无新增失败；仍有 {still_failing} 条存量失败（{fail_rate:.1f}%），"
            f"其中 {known_count} 条已在已知台账；集中在 {len(failing_modules)} 个业务模块，建议按模块分批治理。"
        )
    elif failed:
        verdict = f"本轮失败 {failed} 条，需结合明细确认是否属于预期异常。"
    else:
        verdict = "本轮无失败，版本对比未发现回归。"

    return {
        "verdict": verdict,
        "riskLevel": risk_level,
        "risks": risks,
        "focus": focus,
        "suggestions": suggestions,
        "failureModules": failing_modules[:8],
        "knownFailures": {
            "knownCount": known_count,
            "unexpectedCount": unexpected,
            "expiredCount": expired,
            "fixedCount": fixed_known,
            "unmappedCount": unmapped,
        },
    }


def compare(before: dict, after: dict) -> dict:
    before_ids, after_ids = set(before), set(after)
    added = [after[key] for key in sorted(after_ids - before_ids)]
    removed = [before[key] for key in sorted(before_ids - after_ids)]
    transitions = Counter()
    new_failures, fixed, still_failing, modified = [], [], [], []
    for nodeid in sorted(before_ids & after_ids):
        old, new = before[nodeid], after[nodeid]
        transitions[f"{old['status']}->{new['status']}"] += 1
        if old["content_hash"] != new["content_hash"]:
            modified.append({**new, "before_hash": old["content_hash"]})
        if old["status"] in ("passed", "skipped") and new["status"] in ("failed", "broken"):
            new_failures.append(new)
        elif old["status"] in ("failed", "broken") and new["status"] == "passed":
            fixed.append(new)
        elif old["status"] in ("failed", "broken") and new["status"] in ("failed", "broken"):
            still_failing.append(new)
    return {
        "added": added, "removed": removed, "modified": modified,
        "newFailures": new_failures, "fixed": fixed,
        "stillFailing": still_failing,
        "transitions": dict(transitions),
        "counts": {
            "added": len(added), "removed": len(removed), "modified": len(modified),
            "newFailures": len(new_failures), "fixed": len(fixed),
            "stillFailing": len(still_failing),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline")
    parser.add_argument("--current")
    parser.add_argument("--report-dir", default=str(REPORT))
    args = parser.parse_args()
    metrics = load(HISTORY / "metrics.json", [])
    complete = [run for run in metrics if run.get("complete")]
    complete.sort(key=lambda run: run.get("started_at") or "")
    if len(complete) < 2:
        print("[skip] 完整运行不足两轮")
        return
    by_id = {run["run_id"]: run for run in metrics}
    current = by_id.get(args.current) if args.current else complete[-1]
    baseline = by_id.get(args.baseline) if args.baseline else complete[-2]
    if not current or not baseline:
        raise SystemExit("指定的 run 不存在")

    titles, hashes, case_ids = registry()
    before = run_results(baseline, titles, hashes, case_ids)
    after = run_results(current, titles, hashes, case_ids)
    diff = compare(before, after)
    modules = module_stats(after)
    known = evaluate_known(list(after.values()), load_ledger())
    comparability = {
        "sameCommit": baseline.get("commit") == current.get("commit"),
        "sameEnv": baseline.get("env") == current.get("env"),
        "sameBranch": baseline.get("branch") == current.get("branch"),
        "complete": bool(baseline.get("complete") and current.get("complete")),
    }
    insights = build_insights(baseline, current, diff, comparability, modules, known)

    bsum = baseline
    summary = {
        "baseline": baseline,
        "current": current,
        "comparability": comparability,
        "totals": {
            "passed": [bsum.get("passed"), current.get("passed")],
            "failed": [bsum.get("failed"), current.get("failed")],
            "skipped": [bsum.get("skipped"), current.get("skipped")],
            "total": [bsum.get("total"), current.get("total")],
            "interfaceRate": [bsum.get("interface_rate"), current.get("interface_rate")],
            "dbRate": [bsum.get("db_rate"), current.get("db_rate")],
            "methodRate": [bsum.get("method_rate"), current.get("method_rate")],
            "lineRate": [bsum.get("line_rate"), current.get("line_rate")],
            "wallSeconds": [bsum.get("wall_seconds"), current.get("wall_seconds")],
        },
        "moduleStats": modules,
        "knownFailures": {
            "knownCount": known["knownCount"],
            "unexpectedCount": known["unexpectedCount"],
            "expiredCount": known["expiredCount"],
            "fixedCount": known["fixedCount"],
            "unmappedCount": known["unmappedCount"],
            "unownedCount": known["unownedCount"],
        },
        "insights": insights,
        "diff": diff,
    }
    out_dir = Path(args.report_dir) / "ext" / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "compare.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (HISTORY / current["run_id"] / f"compare-{baseline['run_id']}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (out_dir / "trend.json").write_text(
        json.dumps({"runs": metrics}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(
        f"[done] 对比 {baseline['run_id']} → {current['run_id']}："
        f"新增失败 {diff['counts']['newFailures']}，修复 {diff['counts']['fixed']}，"
        f"新增 {diff['counts']['added']}，删除 {diff['counts']['removed']}"
    )


if __name__ == "__main__":
    main()
