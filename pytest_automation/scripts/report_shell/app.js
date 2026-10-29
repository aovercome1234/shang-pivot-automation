/* 报告视图容器（可扩展多 tab）。
 *
 * 新增视图（例如后续的 UI 视图）只需：
 *   1) 在 manifest.json 的 views 里追加 { id, title, type, data }
 *   2) 在 RENDERERS 里注册同名 type 的渲染函数
 * 容器负责 tab 切换（hash 路由 #/id）、数据加载与错误兜底。
 */
(function () {
  "use strict";

  const RENDERERS = {
    api: renderApiView,
    stats: renderStatsView,
    placeholder: renderPlaceholder,
    // ui: renderUiView,   // 预留：UI 结果单独 tab 时接入
  };

  const state = {
    manifest: null,
    view: null,
    data: null,
    query: "",
    method: "",
    onlyFailed: false,
  };

  const el = {
    tabs: document.getElementById("tabs"),
    subtabs: document.getElementById("subtabs"),
    title: document.getElementById("view-title"),
    desc: document.getElementById("view-desc"),
    stats: document.getElementById("stats"),
    search: document.getElementById("search"),
    method: document.getElementById("method-filter"),
    onlyFailed: document.getElementById("only-failed"),
    filterSummary: document.getElementById("filter-summary"),
    body: document.getElementById("matrix-body"),
    empty: document.getElementById("empty"),
    tooltip: document.getElementById("tooltip"),
    tooltipTitle: document.getElementById("tooltip-title"),
    tooltipBody: document.getElementById("tooltip-body"),
    tooltipCopy: document.getElementById("tooltip-copy"),
    drawer: document.getElementById("drawer"),
    drawerMask: document.getElementById("drawer-mask"),
    drawerTitle: document.getElementById("drawer-title"),
    drawerMethod: document.getElementById("drawer-method"),
    drawerSub: document.getElementById("drawer-sub"),
    drawerBody: document.getElementById("drawer-body"),
    drawerClose: document.getElementById("drawer-close"),
    exportAll: document.getElementById("export-all"),
    statsView: document.getElementById("stats-view"),
    toolbar: document.getElementById("toolbar"),
    reconcileBox: document.getElementById("reconcile-box"),
    tableBox: document.getElementById("table-box"),
    statsCardWrap: document.getElementById("stats"),
    reconcileLine: document.getElementById("reconcile-line"),
    unattributed: document.getElementById("unattributed"),
    unattributedSummary: document.getElementById("unattributed-summary"),
    unattributedList: document.getElementById("unattributed-list"),
  };

  const METHOD_ORDER = ["GET", "POST", "PUT", "DELETE", "PATCH"];

  // ---------- 基础工具 ----------
  function escapeHtml(text) {
    return String(text == null ? "" : text)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function jsonText(value) {
    if (value === null || value === undefined) return "null";
    try { return JSON.stringify(value, null, 2); } catch (e) { return String(value); }
  }

  function highlightJson(text) {
    const escaped = escapeHtml(text);
    return escaped.replace(
      /("(?:[^"\\]|\\.)*")(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?/g,
      function (match, str, colon, bool) {
        if (str) return colon ? '<span class="k">' + str + "</span>" + colon
                              : '<span class="s">' + str + "</span>";
        if (bool) return '<span class="b">' + match + "</span>";
        return '<span class="n">' + match + "</span>";
      }
    );
  }

  function statusBadge(status) {
    const map = { passed: "通过", failed: "失败", broken: "阻断", skipped: "跳过" };
    return '<span class="badge ' + status + '">' + (map[status] || status) + "</span>";
  }

  function methodBadge(method) {
    return '<span class="method ' + escapeHtml(method) + '">' + escapeHtml(method) + "</span>";
  }

  function copyText(text, button) {
    const done = function () {
      const old = button.textContent;
      button.textContent = "已复制";
      button.classList.add("copied");
      setTimeout(function () { button.textContent = old; button.classList.remove("copied"); }, 1400);
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done).catch(function () { fallback(); });
    } else { fallback(); }
    function fallback() {
      const area = document.createElement("textarea");
      area.value = text;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      try { document.execCommand("copy"); done(); } catch (e) { /* 忽略 */ }
      document.body.removeChild(area);
    }
  }

  // ---------- 悬浮示例 ----------
  let tooltipTimer = null;
  let activeTrigger = null;
  function showTooltip(trigger, title, value, asText) {
    activeTrigger = trigger;
    clearTimeout(tooltipTimer);
    el.tooltipTitle.textContent = title;
    if (asText) {
      el.tooltipBody.textContent = String(value);
      el.tooltipBody.classList.add("text-mode");
      el.tooltipCopy.dataset.raw = String(value);
    } else {
      el.tooltipBody.innerHTML = highlightJson(jsonText(value));
      el.tooltipBody.classList.remove("text-mode");
      el.tooltipCopy.dataset.raw = jsonText(value);
    }
    el.tooltip.hidden = false;
    const rect = trigger.getBoundingClientRect();
    const width = Math.min(560, window.innerWidth * 0.46);
    let left = Math.min(rect.left, window.innerWidth - width - 16);
    left = Math.max(12, left);
    const estimated = Math.min(360, el.tooltipBody.scrollHeight + 44);
    let top = rect.bottom + 8;
    if (top + estimated > window.innerHeight - 12) top = Math.max(12, rect.top - estimated - 8);
    el.tooltip.style.left = left + "px";
    el.tooltip.style.top = top + "px";
  }
  function hideTooltipSoon() {
    tooltipTimer = setTimeout(function () { el.tooltip.hidden = true; }, 160);
  }
  el.tooltip.addEventListener("mouseenter", function () { clearTimeout(tooltipTimer); });
  el.tooltip.addEventListener("mouseleave", hideTooltipSoon);
  // 鼠标移出「触发器 + 浮层」范围即隐藏：避免浮层挡住表格里其他按钮/行
  document.addEventListener("mousemove", function (event) {
    if (el.tooltip.hidden) return;
    const target = event.target;
    if (el.tooltip.contains(target)) return;
    if (activeTrigger && activeTrigger.contains(target)) return;
    el.tooltip.hidden = true;
  });
  el.tooltipCopy.addEventListener("click", function () {
    copyText(el.tooltipCopy.dataset.raw || "", el.tooltipCopy);
  });

  // ---------- 抽屉 ----------
  function openDrawer(item) {
    drawerState.item = item;
    drawerState.dim = "";
    drawerState.status = "";
    drawerState.priority = "";
    drawerState.query = "";
    drawerState.sortKey = "";
    drawerState.sortDir = 1;
    el.drawerMethod.innerHTML = methodBadge(item.method) +
      ' &nbsp;<span class="risk ' + escapeHtml(item.risk || "P2") + '">' +
      escapeHtml(item.risk || "P2") + "</span>" +
      " &nbsp;<span class=\"path\">" + escapeHtml(item.path) + "</span>";
    el.drawerTitle.textContent = item.name;
    renderDrawer();
    el.drawer.hidden = false;
    el.drawerMask.hidden = false;
    document.body.style.overflow = "hidden";
  }

  function renderDrawer() {
    const item = drawerState.item;
    if (!item) return;
    const failed = item.stats.failed;
    el.drawerSub.textContent = "共 " + item.stats.total + " 条测试点" +
      (failed ? "，其中失败 " + failed + " 条" : "，全部通过");
    const dimensions = [];
    item.testPoints.forEach(function (point) {
      if (point.dimension && dimensions.indexOf(point.dimension) === -1) dimensions.push(point.dimension);
    });
    const points = filterPoints(item.testPoints);
    el.drawerBody.innerHTML = renderDrawerToolbar(dimensions, points, item.testPoints.length) +
      renderPointTable(points, item);
    bindDrawerToolbar(points, item);
    bindDrawerSort();
    bindDrawerCells();
    bindAllureLinks(el.drawerBody);
  }

  function filterPoints(points) {
    const query = drawerState.query.trim().toLowerCase();
    let rows = points.filter(function (point) {
      if (drawerState.dim && point.dimension !== drawerState.dim) return false;
      if (drawerState.status && point.status !== drawerState.status) return false;
      if (drawerState.priority && (point.priority || drawerState.item.risk) !== drawerState.priority) return false;
      if (query && (point.name + " " + (point.caseId || "")).toLowerCase().indexOf(query) === -1) return false;
      return true;
    });
    if (drawerState.sortKey) {
      const key = drawerState.sortKey;
      rows = rows.slice().sort(function (a, b) {
        let left = key === "priority" ? (a.priority || drawerState.item.risk) : a[key];
        let right = key === "priority" ? (b.priority || drawerState.item.risk) : b[key];
        if (key === "durationMs") { left = a.durationMs || 0; right = b.durationMs || 0; }
        if (left === right) return 0;
        return (left > right ? 1 : -1) * drawerState.sortDir;
      });
    }
    return rows;
  }

  function renderDrawerToolbar(dimensions, points, total) {
    const shown = points.length;
    const hasFailed = points.some(function (p) {
      return p.status === "failed" || p.status === "broken";
    });
    const statuses = [["", "全部结果"], ["passed", "通过"], ["failed", "失败"], ["broken", "阻断"], ["skipped", "跳过"]];
    const priorities = [["", "全部优先级"], ["P0", "P0"], ["P1", "P1"], ["P2", "P2"]];
    return '<div class="drawer-toolbar">' +
      '<select id="df-dim" class="select small-select"><option value="">全部分类</option>' +
        dimensions.map(function (dim) {
          return '<option value="' + escapeHtml(dim) + '"' + (drawerState.dim === dim ? " selected" : "") + ">" + escapeHtml(dim) + "</option>";
        }).join("") + "</select>" +
      '<select id="df-status" class="select small-select">' +
        statuses.map(function (pair) {
          return '<option value="' + pair[0] + '"' + (drawerState.status === pair[0] ? " selected" : "") + ">" + pair[1] + "</option>";
        }).join("") + "</select>" +
      '<select id="df-priority" class="select small-select">' +
        priorities.map(function (pair) {
          return '<option value="' + pair[0] + '"' + (drawerState.priority === pair[0] ? " selected" : "") + ">" + pair[1] + "</option>";
        }).join("") + "</select>" +
      '<input id="df-query" class="search small-search" type="search" placeholder="搜索测试点 / 用例编号" value="' + escapeHtml(drawerState.query) + '">' +
      '<span class="muted">显示 ' + shown + " / " + total + "</span>" +
      '<span class="grow"></span>' +
      (hasFailed
        ? '<button id="df-copy-failed" class="detail-btn" type="button">复制全部失败缺陷</button>' : "") +
      '<button id="df-export" class="detail-btn" type="button">导出 CSV</button>' +
      "</div>";
  }

  function bindDrawerToolbar(points, item) {
    function rerender(keepFocus) {
      renderDrawer();
      if (keepFocus) {
        const input = document.getElementById("df-query");
        if (input) { input.focus(); input.setSelectionRange(input.value.length, input.value.length); }
      }
    }
    const dim = document.getElementById("df-dim");
    const status = document.getElementById("df-status");
    const priority = document.getElementById("df-priority");
    const query = document.getElementById("df-query");
    if (dim) dim.addEventListener("change", function () { drawerState.dim = dim.value; rerender(false); });
    if (status) status.addEventListener("change", function () { drawerState.status = status.value; rerender(false); });
    if (priority) priority.addEventListener("change", function () { drawerState.priority = priority.value; rerender(false); });
    if (query) query.addEventListener("input", function () { drawerState.query = query.value; rerender(true); });
    const exportBtn = document.getElementById("df-export");
    if (exportBtn) exportBtn.addEventListener("click", function () { exportCsv(points, item); });
    const copyFailed = document.getElementById("df-copy-failed");
    if (copyFailed) copyFailed.addEventListener("click", function () {
      const failed = points.filter(function (p) { return p.status === "failed" || p.status === "broken"; });
      copyText(failed.map(function (p) { return defectText(p, item); }).join("\n\n---\n\n"), copyFailed);
    });
    el.drawerBody.querySelectorAll(".mini-copy").forEach(function (button) {
      button.addEventListener("click", function () {
        const key = button.getAttribute("data-defect") || "";
        const nodeid = key.split("|")[0];
        const target = points.find(function (p) { return p.nodeid === nodeid; });
        if (target) copyText(defectText(target, item), button);
      });
    });
  }

  function defectText(point, item) {
    const request = detailPayload(point, "request");
    const response = detailPayload(point, "response");
    const link = point.link ? new URL(point.link, location.href).href : "—";
    return [
      "【缺陷】" + (point.caseId ? point.caseId + " " : "") + point.name,
      "接口：" + item.method + " " + item.path + "（" + (item.risk || "P2") + "）",
      "分类：" + (point.dimension || "其他") + "｜优先级：" + (point.priority || item.risk || "P2"),
      "断言意图：" + (point.verify || "—"),
      "实际结果：" + (point.message || "—"),
      "请求：" + (request ? JSON.stringify(request, null, 2) : "—"),
      "响应：" + (response ? JSON.stringify(response, null, 2) : "—"),
      "报告：" + link,
      "生成时间：" + ((state.data && state.data.generatedAt) || "—"),
    ].join("\n");
  }

  function csvCell(value) {
    const text = value === null || value === undefined ? "" : String(value);
    return '"' + text.replace(/"/g, '""').replace(/\r?\n/g, " ") + '"';
  }

  function exportCsv(points, item) {
    const headers = ["测试分类", "测试点", "用例编号", "来源", "优先级", "接口参数", "接口返回值",
      "测试结果", "耗时(ms)", "失败原因", "验证点", "报告详情"];
    const lines = [headers.map(csvCell).join(",")];
    points.forEach(function (point) {
      const request = detailPayload(point, "request");
      const response = detailPayload(point, "response");
      const link = point.link ? new URL(point.link, location.href).href : "";
      lines.push([
        point.dimension || "",
        point.name || "",
        point.caseId || "",
        point.origin === "setup" ? "前置数据" : "用例主体",
        point.priority || item.risk || "",
        request ? JSON.stringify(request) : "",
        response ? JSON.stringify(response) : "",
        point.status || "",
        point.durationMs || 0,
        point.message || "",
        point.verify || "",
        link,
      ].map(csvCell).join(","));
    });
    const blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const safe = (item.method + "_" + item.path).replace(/[^0-9A-Za-z]+/g, "_");
    const anchor = document.createElement("a");
    anchor.href = URL.createObjectURL(blob);
    anchor.download = "testpoints_" + safe + ".csv";
    document.body.appendChild(anchor);
    anchor.click();
    setTimeout(function () { URL.revokeObjectURL(anchor.href); document.body.removeChild(anchor); }, 500);
  }
  function closeDrawer() {
    el.drawer.hidden = true;
    el.drawerMask.hidden = true;
    document.body.style.overflow = "";
  }
  el.drawerClose.addEventListener("click", closeDrawer);
  el.drawerMask.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !el.drawer.hidden) closeDrawer();
  });

  let drawerCells = [];
  const drawerState = {
    item: null,
    dim: "",
    status: "",
    priority: "",
    query: "",
    sortKey: "",
    sortDir: 1,
  };

  function jsonPreview(value) {
    if (value === null || value === undefined) return "—";
    if (typeof value !== "object") return String(value);
    // 优先展示业务报文（body/query），避免只显示 "status, body" 这样的外层壳
    const inner = value.body !== undefined ? value.body
      : (value.query !== undefined ? value.query : value);
    if (inner && typeof inner === "object" && !Array.isArray(inner)) {
      const keys = Object.keys(inner);
      if (!keys.length) return "{}";
      return "{" + keys.slice(0, 3).join(", ") + (keys.length > 3 ? ", …" : "") + "}";
    }
    if (Array.isArray(inner)) return "[" + inner.length + " 项]";
    const keys = Object.keys(value);
    return "{" + keys.slice(0, 3).join(", ") + (keys.length > 3 ? ", …" : "") + "}";
  }

  function detailPayload(point, kind) {
    if (kind === "request") {
      const request = point.request || {};
      const payload = {};
      if (request.query) payload.query = request.query;
      if (request.body) payload.body = request.body;
      if (request.raw) payload.raw = request.raw;
      if (!Object.keys(payload).length) return null;
      return payload;
    }
    const response = point.response || {};
    if (!response || !Object.keys(response).length) return null;
    const payload = { status: response.status };
    if (response.body !== undefined && response.body !== null) payload.body = response.body;
    return payload;
  }

  function cellTrigger(point, kind, label, fallback) {
    let payload = detailPayload(point, kind);
    let title = label;
    if (!payload) {
      // 该用例没有独立快照（如会话级夹具已登录）：回退到接口级示例，并标注来源
      const value = kind === "request" ? fallback.params : fallback.response;
      if (value && (typeof value !== "object" || Object.keys(value).length)) {
        payload = value;
        title = label + "（接口级示例）";
      }
    }
    if (!payload) {
      return '<span class="mini-trigger empty">' + escapeHtml(label) + " 无</span>";
    }
    const index = drawerCells.push({ title: title, payload }) - 1;
    return '<span class="mini-trigger" data-cell="' + index + '" tabindex="0" title="悬浮查看' +
      escapeHtml(label) + '并复制">' + escapeHtml(label + " · " + jsonPreview(payload)) + "</span>";
  }

  function shortReason(message) {
    if (!message) return "—";
    const text = String(message).replace(/^AssertionError:\s*/, "").replace(/\s+/g, " ").trim();
    if (/HTTP 500|50000|系统异常/.test(text)) return "HTTP 500 系统异常";
    const biz = text.match(/业务码期望 (\d+) 实际 (\d+)/);
    if (biz) return "业务码 " + biz[2] + "（期望 " + biz[1] + "）";
    const http = text.match(/HTTP 期望 (\d+) 实际 (\d+)/);
    if (http) return "HTTP " + http[2] + "（期望 " + http[1] + "）";
    if (/Timeout|timeout/.test(text)) return "请求超时";
    return text.length > 36 ? text.slice(0, 36) + "…" : text;
  }

  function renderPointTable(points, item) {
    const endpointRisk = (item && item.risk) || "P2";
    drawerCells = [];
    if (!points.length) return '<p class="muted">暂无测试点</p>';
    const rows = points.map(function (point) {
      const href = point.link || "";
      const duration = point.durationMs ? (point.durationMs >= 1000
        ? (point.durationMs / 1000).toFixed(2) + "s" : point.durationMs + "ms") : "—";
      // 抽屉本身已按接口聚合，去掉标题里重复的「｜METHOD path」后缀
      const suffix = "｜" + item.method + " " + item.path;
      const baseName = point.name.endsWith(suffix)
        ? point.name.slice(0, -suffix.length) : point.name;
      let failCell = "—";
      if (point.status === "failed" || point.status === "broken") {
        const index = drawerCells.push({
          title: "失败详情（悬浮查看 / 可复制）",
          payload: point.message || "（无堆栈信息）",
          asText: true,
        }) - 1;
        failCell = '<span class="fail-short" data-cell="' + index + '" tabindex="0">' +
          escapeHtml(shortReason(point.message)) + "</span>";
      }
      return "<tr>" +
        '<td><span class="dim-tag">' + escapeHtml(point.dimension || "其他") + "</span></td>" +
        '<td><div class="pt-name">' +
          escapeHtml(baseName.replace(point.caseId ? point.caseId + " " : "", "")) +
        "</div></td>" +
        '<td class="verify-cell">' + (point.verify
          ? '<span title="' + escapeHtml(point.verify) + '">' + escapeHtml(point.verify) + "</span>"
          : "—") + "</td>" +
        "<td>" + (point.origin === "setup"
          ? '<span class="badge setup" title="接口调用发生在夹具（数据准备）中">前置数据</span>'
          : '<span class="muted">用例主体</span>') + "</td>" +
        '<td><span class="risk ' + escapeHtml(point.priority || endpointRisk) + '"' +
          (point.priority ? "" : ' title="用例未标优先级，沿用接口风险级别"') + ">" +
          escapeHtml(point.priority || endpointRisk) + "</span></td>" +
        '<td><div class="example-chips">' +
          cellTrigger(point, "request", "参数", item) +
          cellTrigger(point, "response", "返回", item) +
        "</div></td>" +
        "<td>" + statusBadge(point.status) + "</td>" +
        '<td class="muted">' + duration + "</td>" +
        '<td class="fail-cell">' + failCell + "</td>" +
        '<td><div class="detail-actions">' +
          (href ? '<a class="allure-open" href="' + href + '" data-search="' +
                  escapeHtml(point.searchLink || "") + '" target="_blank" rel="noopener">打开</a>'
                : '<span class="muted">—</span>') +
          (point.status === "failed" || point.status === "broken"
            ? '<button class="mini-copy" data-defect="' + escapeHtml(point.nodeid + "|" + item.id) + '">复制缺陷</button>'
            : "") +
        "</div></td>" +
      "</tr>";
    }).join("");
    function sortHead(key, label) {
      const active = drawerState.sortKey === key;
      const arrow = active ? (drawerState.sortDir > 0 ? " ▲" : " ▼") : "";
      return '<th class="sortable" data-sort="' + key + '">' + label + arrow + "</th>";
    }
    return '<table class="drawer-table"><thead><tr>' +
      sortHead("dimension", "测试分类") + "<th>测试点</th><th>验证点</th><th>来源</th>" +
      sortHead("priority", "优先级") + "<th>示例（参数 / 返回）</th>" +
      sortHead("status", "测试结果") + sortHead("durationMs", "耗时") +
      "<th>失败原因</th><th>报告详情</th>" +
      "</tr></thead><tbody>" + rows + "</tbody></table>";
  }

  function bindDrawerSort() {
    el.drawerBody.querySelectorAll(".drawer-table th.sortable").forEach(function (th) {
      th.addEventListener("click", function () {
        const key = th.dataset.sort;
        if (drawerState.sortKey === key) drawerState.sortDir *= -1;
        else { drawerState.sortKey = key; drawerState.sortDir = 1; }
        renderDrawer();
      });
    });
  }

  function bindAllureLinks(root) {
    root.querySelectorAll("a.allure-open").forEach(function (anchor) {
      anchor.addEventListener("click", function (event) {
        const href = anchor.getAttribute("href") || "";
        const match = href.match(/#\/suites\/[^/]+\/([^/]+)\//);
        if (!match) return;
        event.preventDefault();
        const uid = match[1];
        const fallback = anchor.dataset.search || "../index.html#/suites";
        fetch("../data/test-cases/" + uid + ".json", { cache: "no-store" })
          .then(function (response) {
            window.open(response.ok ? href : fallback, "_blank");
          })
          .catch(function () { window.open(fallback, "_blank"); });
      });
    });
  }

  function bindDrawerCells() {
    el.drawerBody.querySelectorAll(".mini-trigger, .fail-short").forEach(function (trigger) {
      const cell = drawerCells[Number(trigger.dataset.cell)];
      if (!cell) return;
      trigger.addEventListener("mouseenter", function () {
        showTooltip(trigger, cell.title, cell.payload, cell.asText);
      });
      trigger.addEventListener("mouseleave", hideTooltipSoon);
    });
  }

  // ---------- 接口视图 ----------
  function renderApiView(data) {
    el.statsView.hidden = true;
    el.toolbar.hidden = false;
    el.reconcileBox.hidden = false;
    el.tableBox.hidden = false;
    el.stats.hidden = false;
    el.stats.innerHTML =
      statCard(data.summary.interfaces, "接口总数") +
      statCard(data.summary.covered, "有测试点的接口") +
      statCard(data.summary.tests, "关联用例") +
      statCard(data.summary.failedTests, "失败用例", true);

    const methods = METHOD_ORDER.filter(function (m) {
      return data.interfaces.some(function (i) { return i.method === m; });
    });
    renderReconciliation(data);
    el.method.innerHTML = '<option value="">全部方法</option>' +
      methods.map(function (m) { return '<option value="' + m + '">' + m + "</option>"; }).join("");

    applyFilters();
  }

  function renderReconciliation(data) {
    const summary = data.summary || {};
    el.reconcileLine.innerHTML =
      "原报告 <b>" + (summary.reportTotal || "-") + "</b> 条用例 · 已归属接口 <b>" +
      (summary.apiTests || 0) + "</b> 条 · UI 用例 <b>" + (summary.uiTests || 0) +
      "</b> 条（后续独立视图）· 未归属 <b>" + (summary.unattributed || 0) + "</b> 条";
    const items = data.unattributedTests || [];
    el.unattributed.hidden = items.length === 0;
    el.unattributedSummary.textContent = "未归属接口的用例（" + items.length + "）";
    el.unattributedList.innerHTML = items.map(function (item) {
      const link = item.link
        ? '<a href="' + item.link + '" target="_blank" rel="noopener">在 Allure 打开</a>'
        : "";
      return '<div class="unattributed-item">' + statusBadge(item.status) +
        "<span>" + escapeHtml(item.name) + "</span>" +
        '<span class="muted">' + escapeHtml(item.file) + "</span>" + link + "</div>";
    }).join("");
  }

  function buildDimensionIndex(data) {
    const index = new Map();
    (data.interfaces || []).forEach(function (item) {
      (item.testPoints || []).forEach(function (point) {
        const dim = point.dimension || "其他";
        if (!index.has(dim)) index.set(dim, new Map());
        const cases = index.get(dim);
        if (!cases.has(point.nodeid)) {
          cases.set(point.nodeid, {
            point: point,
            interfaces: [],
            risk: item.risk || "P2",
          });
        }
        const entry = cases.get(point.nodeid);
        const label = item.method + " " + item.path;
        if (entry.interfaces.indexOf(label) === -1) entry.interfaces.push(label);
      });
    });
    return index;
  }

  let statsState = { data: null, dimension: "", onlyFailed: true };

  function renderStatsView(data) {
    statsState.data = data;
    statsState.dimension = "";
    statsState.onlyFailed = true;
    el.statsView.hidden = false;
    el.toolbar.hidden = true;
    el.reconcileBox.hidden = true;
    el.tableBox.hidden = true;
    el.stats.hidden = true;

    const stats = data.dimensionStats || [];
    const summary = data.summary || {};
    const total = stats.reduce(function (sum, d) { return sum + (d.total || 0); }, 0);
    const failed = stats.reduce(function (sum, d) { return sum + (d.failed || 0) + (d.broken || 0); }, 0);
    const passed = stats.reduce(function (sum, d) { return sum + (d.passed || 0); }, 0);
    const rate = total ? (passed / total * 100).toFixed(1) : "0.0";

    const kpis = '<div class="stats-kpi">' +
      kpiCard(total, "已归属用例") + kpiCard(rate + "%", "通过率") +
      kpiCard(failed, "失败用例", true) + kpiCard(stats.length, "测试分类") +
    "</div>" +
    '<p class="muted stats-note">原报告共 ' + (summary.reportTotal || "-") + " 条；本页统计已归属接口的用例，" +
      "UI 用例 " + (summary.uiTests || 0) + " 条与未归属 " + (summary.unattributed || 0) + " 条不计入。</p>";

    el.statsView.innerHTML = kpis +
      '<div class="charts">' +
        '<div class="chart-panel">' +
          '<div class="chart-head"><strong>各分类用例数量与结果构成</strong>' +
            '<span class="grow"></span>' +
            '<div class="legend"><span><i class="pass"></i>通过</span>' +
            '<span><i class="fail"></i>失败</span><span><i class="skip"></i>跳过</span></div>' +
          "</div>" +
          columnChartSvg(stats) +
        "</div>" +
        '<div class="chart-panel">' +
          '<div class="chart-head"><strong>失败用例构成</strong><span class="muted">按分类</span></div>' +
          failureDonut(stats) +
        "</div>" +
      "</div>" +
      '<div class="drill-card" id="drill-card"><div class="drill-head"><strong>分类明细</strong>' +
      '<span class="muted">点击柱状图、饼图或右侧图例查看用例</span></div>' +
      '<div class="drill-body muted">尚未选择分类</div></div>';

    const index = buildDimensionIndex(data);
    el.statsView.querySelectorAll("[data-dim]").forEach(function (node) {
      node.addEventListener("click", function () {
        selectDimension(node.dataset.dim, index);
      });
    });
  }

  function selectDimension(dimension, index) {
    statsState.dimension = dimension;
    el.statsView.querySelectorAll(".col").forEach(function (col) {
      col.classList.toggle("active", col.dataset.dim === dimension);
    });
    el.statsView.querySelectorAll(".fail-legend-item").forEach(function (item) {
      item.classList.toggle("active", item.dataset.dim === dimension);
    });
    renderDrill(index);
    const card = document.getElementById("drill-card");
    if (card) card.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function columnChartSvg(stats) {
    const W = 1000, H = 340, left = 46, right = 16, top = 14, bottom = 70;
    const plotW = W - left - right, plotH = H - top - bottom;
    const maxTotal = Math.max.apply(null, stats.map(function (s) { return s.total || 0; }).concat([1]));
    const step = Math.max(10, Math.ceil(maxTotal / 4 / 10) * 10);
    const niceMax = step * 4;
    const band = plotW / stats.length;
    const barW = Math.min(70, band * 0.52);
    const parts = [];
    for (let i = 0; i <= 4; i += 1) {
      const y = top + plotH - (i * plotH / 4);
      parts.push('<line x1="' + left + '" y1="' + y + '" x2="' + (W - right) +
        '" y2="' + y + '" class="grid"/>');
      parts.push('<text x="' + (left - 8) + '" y="' + (y + 4) +
        '" text-anchor="end">' + Math.round(niceMax * i / 4) + "</text>");
    }
    const scale = plotH / niceMax;
    stats.forEach(function (dim, index) {
      const x = left + index * band + (band - barW) / 2;
      const pass = dim.passed || 0;
      const fail = (dim.failed || 0) + (dim.broken || 0);
      const skip = dim.skipped || 0;
      let cursor = top + plotH;
      function segment(count, cls, label) {
        if (!count) return "";
        const height = count * scale;
        cursor -= height;
        return '<rect x="' + x + '" y="' + cursor + '" width="' + barW +
          '" height="' + height + '" class="seg ' + cls + '"><title>' +
          dim.dimension + " " + label + " " + count + "</title></rect>";
      }
      parts.push('<g class="col" data-dim="' + escapeHtml(dim.dimension) + '">');
      parts.push(segment(pass, "pass", "通过"));
      parts.push(segment(fail, "fail", "失败"));
      parts.push(segment(skip, "skip", "跳过"));
      parts.push('<rect x="' + (x - 6) + '" y="' + top + '" width="' + (barW + 12) +
        '" height="' + plotH + '" class="col-hit"><title>' +
        dim.dimension + " 共 " + dim.total + " 条，失败 " + fail + "</title></rect>");
      const lx = x + barW / 2, ly = top + plotH + 18;
      parts.push('<text class="x-label" x="' + lx + '" y="' + ly +
        '" transform="rotate(-28 ' + lx + " " + ly + ')" text-anchor="end">' +
        escapeHtml(dim.dimension) + "</text>");
      parts.push("</g>");
    });
    return '<svg viewBox="0 0 ' + W + " " + H +
      '" class="chart-svg" role="img" aria-label="各分类用例数量柱状图">' + parts.join("") + "</svg>";
  }

  function failureDonut(stats) {
    const failures = stats
      .map(function (dim) {
        return { name: dim.dimension, count: (dim.failed || 0) + (dim.broken || 0) };
      })
      .filter(function (item) { return item.count > 0; });
    const total = failures.reduce(function (sum, item) { return sum + item.count; }, 0);
    if (!total) return '<p class="muted">当前没有失败用例</p>';
    const colors = ["#d64545", "#e8833a", "#b08900", "#7a5af8", "#1f9d61", "#3b82f6", "#ec4899", "#14b8a6"];
    const circumference = 2 * Math.PI * 78;
    let offset = 0;
    const segments = failures.map(function (item, index) {
      const length = circumference * item.count / total;
      const color = colors[index % colors.length];
      const seg = '<circle r="78" cx="110" cy="110" fill="none" stroke="' + color +
        '" stroke-width="30" stroke-dasharray="' + length + " " + (circumference - length) +
        '" stroke-dashoffset="' + (-offset) + '" transform="rotate(-90 110 110)"' +
        ' class="donut-seg" data-dim="' + escapeHtml(item.name) + '"><title>' +
        item.name + " " + item.count + " 条（" + (item.count / total * 100).toFixed(1) + "%）</title></circle>";
      offset += length;
      return seg;
    }).join("");
    const legend = failures.map(function (item, index) {
      const color = colors[index % colors.length];
      return '<button class="fail-legend-item" data-dim="' + escapeHtml(item.name) + '">' +
        '<i style="background:' + color + '"></i><span>' + escapeHtml(item.name) + "</span>" +
        "<b>" + item.count + "</b><em>" + (item.count / total * 100).toFixed(1) + "%</em></button>";
    }).join("");
    return '<div class="donut-wrap">' +
      '<svg viewBox="0 0 220 220" class="donut-svg" role="img" aria-label="失败用例分类构成">' +
        segments +
        '<text x="110" y="104" text-anchor="middle" class="donut-total">' + total + "</text>" +
        '<text x="110" y="126" text-anchor="middle" class="donut-label">失败用例</text>' +
      "</svg>" +
      '<div class="donut-legend">' + legend + "</div>" +
    "</div>";
  }

  function kpiCard(value, label, bad) {
    return '<div class="stat' + (bad && value ? " bad" : "") + '"><b>' + value +
      "</b><span>" + label + "</span></div>";
  }

  function renderDrill(index) {
    const dimension = statsState.dimension;
    const cases = index.get(dimension);
    const card = document.getElementById("drill-card");
    if (!cases || !cases.size) {
      card.innerHTML = '<div class="drill-head"><strong>分类明细</strong></div>' +
        '<div class="drill-body muted">该分类暂无用例</div>';
      return;
    }
    let rows = Array.from(cases.values());
    const failedCount = rows.filter(function (entry) {
      return entry.point.status === "failed" || entry.point.status === "broken";
    }).length;
    rows = rows.filter(function (entry) {
      if (!statsState.onlyFailed) return true;
      return entry.point.status === "failed" || entry.point.status === "broken";
    }).sort(function (a, b) {
      const order = { failed: 0, broken: 0, skipped: 2, passed: 1 };
      return (order[a.point.status] || 3) - (order[b.point.status] || 3);
    });

    const body = rows.map(function (entry) {
      const point = entry.point;
      const short = shortReason(point.message);
      const href = point.link || "";
      const duration = point.durationMs ? (point.durationMs >= 1000
        ? (point.durationMs / 1000).toFixed(2) + "s" : point.durationMs + "ms") : "—";
      return "<tr>" +
        '<td class="muted">' + escapeHtml(entry.interfaces.join("、")) + "</td>" +
        "<td>" + escapeHtml(String(point.name).split("｜")[0]) + "</td>" +
        '<td><span class="risk ' + escapeHtml(point.priority || entry.risk) + '">' +
          escapeHtml(point.priority || entry.risk) + "</span></td>" +
        "<td>" + statusBadge(point.status) + "</td>" +
        '<td class="muted">' + duration + "</td>" +
        '<td class="fail-cell">' + (short === "—" ? "—" : escapeHtml(short)) + "</td>" +
        '<td>' + (href ? '<a class="allure-open" href="' + href + '" data-search="' +
          escapeHtml(point.searchLink || "") + '" target="_blank" rel="noopener">打开</a>'
          : '<span class="muted">—</span>') + "</td>" +
      "</tr>";
    }).join("");

    card.innerHTML = '<div class="drill-head"><strong>' + escapeHtml(dimension) + " 用例明细</strong>" +
      '<span class="muted">共 ' + cases.size + " 条，失败 " + failedCount + " 条</span>" +
      '<span class="grow"></span>' +
      '<label class="check"><input type="checkbox" id="drill-only-failed"' +
        (statsState.onlyFailed ? " checked" : "") + "> 仅看失败</label></div>" +
      '<div class="drill-table-wrap"><table class="drawer-table drill-table"><thead><tr>' +
      "<th>接口</th><th>测试点</th><th>优先级</th><th>结果</th><th>耗时</th><th>失败原因</th><th>报告</th>" +
      "</tr></thead><tbody>" + (body || '<tr><td colspan="7" class="muted">没有符合条件的用例</td></tr>') +
      "</tbody></table></div>";

    bindAllureLinks(card);
    const toggle = document.getElementById("drill-only-failed");
    if (toggle) toggle.addEventListener("change", function () {
      statsState.onlyFailed = toggle.checked;
      renderDrill(index);
    });
  }

  function statCard(value, label, bad) {
    return '<div class="stat' + (bad && value ? " bad" : "") + '"><b>' + value + "</b><span>" + label + "</span></div>";
  }

  function matchQuery(item, query) {
    if (!query) return true;
    const haystack = (item.name + " " + item.id + " " + item.path).toLowerCase();
    return haystack.indexOf(query) !== -1;
  }

  function applyFilters() {
    if (!state.data) return;
    const query = state.query.trim().toLowerCase();
    const rows = state.data.interfaces.filter(function (item) {
      if (state.method && item.method !== state.method) return false;
      if (state.onlyFailed && !item.stats.failed) return false;
      return matchQuery(item, query);
    });
    el.body.innerHTML = rows.map(renderRow).join("");
    el.empty.hidden = rows.length !== 0;
    // 过滤后回到顶部：避免首行被 sticky 表头遮住
    window.scrollTo(0, 0);
    el.filterSummary.textContent = "显示 " + rows.length + " / " + state.data.interfaces.length + " 个接口";
    bindRowEvents();
  }

  function renderRow(item) {
    const exampleHtml =
      '<div class="example-chips">' +
        exampleCell(item, "params", "参数") +
        exampleCell(item, "response", "返回") +
      "</div>";
    const dims = item.stats.dimensions || [];
    const detailLabel = item.stats.total
      ? '详情 <span class="muted">(' + item.stats.total + (item.stats.failed ? "，<span class='fail-num'>" + item.stats.failed + " 失败</span>" : "") + ")</span>"
      : "详情";
    return "<tr>" +
      '<td><div class="api-name">' + escapeHtml(item.name) + "</div>" +
        '<div class="api-auth">' + escapeHtml(item.auth || "免认证") + "</div></td>" +
      '<td><div class="path">' + escapeHtml(item.path) + "</div></td>" +
      "<td>" + methodBadge(item.method) + "</td>" +
      '<td><span class="risk ' + escapeHtml(item.risk || "P2") + '">' +
        escapeHtml(item.risk || "P2") + "</span></td>" +
      "<td>" + exampleHtml + "</td>" +
      '<td><button class="detail-btn" data-id="' + escapeHtml(item.id) + '"' +
        (item.stats.total ? "" : " disabled") + ">" + detailLabel + "</button>" +
        (dims.length ? '<div class="muted" style="margin-top:6px;font-size:12px">' + escapeHtml(dims.join(" / ")) + "</div>" : "") +
      "</td></tr>";
  }

  function exampleCell(item, kind, label) {
    const value = item[kind];
    const has = value && (typeof value !== "object" || Object.keys(value).length > 0);
    const text = has ? label : "无" + label;
    return '<span class="example-trigger' + (has ? " has-data" : "") + '"' +
      (has ? ' data-kind="' + kind + '" data-id="' + escapeHtml(item.id) + '"' : "") +
      ' title="悬浮查看' + escapeHtml(label) + '，浮层内可复制">' +
      '<span class="dot"></span>' + escapeHtml(text) + "</span>";
  }

  function previewKeys(value) {
    if (!value || typeof value !== "object") return "";
    if (Array.isArray(value)) return "[" + value.length + " 项]";
    const keys = Object.keys(value);
    if (!keys.length) return "";
    const head = keys.slice(0, 3).join(", ");
    return "{" + head + (keys.length > 3 ? ", …" : "") + "}";
  }

  function bindRowEvents() {
    el.body.querySelectorAll(".example-trigger.has-data").forEach(function (trigger) {
      trigger.addEventListener("mouseenter", function () {
        const item = findItem(trigger.dataset.id);
        if (!item) return;
        const kind = trigger.dataset.kind;
        const source = kind === "params" ? item.paramsSource : item.responseSource;
        showTooltip(trigger, (kind === "params" ? "参数示例" : "返回值示例") +
          (source ? "（" + source + "）" : "（hover 查看 / 可复制）"), item[kind]);
      });
      trigger.addEventListener("mouseleave", hideTooltipSoon);
      trigger.addEventListener("focus", function () {
        const item = findItem(trigger.dataset.id);
        if (item) showTooltip(trigger, "示例", item[trigger.dataset.kind]);
      });
      trigger.setAttribute("tabindex", "0");
    });
    el.body.querySelectorAll(".detail-btn").forEach(function (button) {
      button.addEventListener("click", function () {
        const item = findItem(button.dataset.id);
        if (item) openDrawer(item);
      });
    });
  }

  function findItem(id) {
    return (state.data.interfaces || []).find(function (item) { return item.id === id; });
  }

  // ---------- 视图容器（两级：大类 → 视图） ----------
  const dataCache = new Map();

  function groups() {
    return (state.manifest && state.manifest.groups) || [];
  }

  function route() {
    const parts = (location.hash || "").replace(/^#\/?/, "").split("/").filter(Boolean);
    let group = groups().find(function (g) { return g.id === parts[0]; }) || groups()[0];
    if (!group) return null;
    const views = group.views || [];
    const view = views.find(function (v) { return v.id === parts[1]; }) || views[0];
    return view ? { group: group, view: view } : null;
  }

  function renderNav(active) {
    el.tabs.innerHTML = groups().map(function (group) {
      const first = (group.views || [])[0];
      const href = "#/" + encodeURIComponent(group.id) + "/" + (first ? encodeURIComponent(first.id) : "");
      return '<a class="tab' + (group.id === active.group.id ? " active" : "") +
        '" href="' + href + '">' + escapeHtml(group.title) + "</a>";
    }).join("");
    const views = active.group.views || [];
    el.subtabs.innerHTML = views.length > 1 ? views.map(function (view) {
      return '<a class="subtab' + (view.id === active.view.id ? " active" : "") +
        '" href="#/' + encodeURIComponent(active.group.id) + "/" + encodeURIComponent(view.id) + '">' +
        escapeHtml(view.title) + "</a>";
    }).join("") : "";
    el.subtabs.hidden = views.length <= 1;
  }

  const DESCRIPTIONS = {
    api: "按接口聚合参数示例、返回值示例与全部测试点；鼠标悬浮示例可查看格式化 JSON 并复制。",
    stats: "按测试分类聚合的通过率与失败分布；点击柱状图、饼图或图例可下钻用例并跳转 Allure。",
    placeholder: "",
  };

  async function loadRoute() {
    const current = route();
    if (!current) {
      el.empty.hidden = false;
      el.empty.textContent = "manifest 中没有可用的视图";
      return;
    }
    state.group = current.group;
    state.view = current.view;
    el.title.textContent = current.view.title;
    el.desc.textContent = DESCRIPTIONS[current.view.type] || "";
    renderNav(current);

    const renderer = RENDERERS[current.view.type];
    if (!renderer) {
      el.statsView.hidden = true;
      el.empty.hidden = false;
      el.empty.textContent = "视图类型 " + current.view.type + " 尚未注册渲染器";
      return;
    }
    if (current.view.type === "placeholder") {
      renderer(current);
      return;
    }
    try {
      const version = state.manifest.version ? "?v=" + state.manifest.version : "";
      let data = dataCache.get(current.view.data);
      if (!data) {
        const response = await fetch(current.view.data + version, { cache: "no-store" });
        if (!response.ok) throw new Error("HTTP " + response.status);
        data = await response.json();
        dataCache.set(current.view.data, data);
      }
      state.data = data;
      renderer(data);
    } catch (error) {
      el.statsView.hidden = true;
      el.empty.hidden = false;
      el.empty.textContent = "数据加载失败：" + error.message;
    }
  }

  function renderPlaceholder(view) {
    el.toolbar.hidden = true;
    el.reconcileBox.hidden = true;
    el.tableBox.hidden = true;
    el.stats.hidden = true;
    el.statsView.hidden = false;
    el.statsView.innerHTML =
      '<div class="placeholder-card">' +
        '<h2>' + escapeHtml(view.title) + '</h2>' +
        "<p class=\"muted\">UI 自动化视图规划中：将复用当前的表格与统计组件，按页面/场景展示 47 条 UI 用例的" +
        "执行结果、截图与 Playwright trace。</p>" +
        '<p class="muted">当前可在 <a href="../index.html#/suites" target="_blank" rel="noopener">Allure 报告</a> 中查看 UI 用例。</p>' +
      "</div>";
  }

  async function boot() {
    try {
      const response = await fetch("manifest.json", { cache: "no-store" });
      if (!response.ok) throw new Error("manifest HTTP " + response.status);
      state.manifest = await response.json();
      if (!groups().length) throw new Error("manifest 中没有视图分组");
      window.addEventListener("hashchange", loadRoute);
      await loadRoute();
    } catch (error) {
      el.empty.hidden = false;
      el.empty.textContent = "页面初始化失败：" + error.message;
    }
  }

  function exportAll() {
    if (!state.data) return;
    const headers = ["接口", "方法", "风险", "测试分类", "测试点", "用例编号", "来源", "优先级",
      "接口参数", "接口返回值", "测试结果", "耗时(ms)", "失败原因", "验证点", "报告详情"];
    const lines = [headers.map(csvCell).join(",")];
    state.data.interfaces.forEach(function (item) {
      item.testPoints.forEach(function (point) {
        const request = detailPayload(point, "request");
        const response = detailPayload(point, "response");
        const link = point.link ? new URL(point.link, location.href).href : "";
        lines.push([
          item.path, item.method, item.risk || "", point.dimension || "", point.name || "",
          point.caseId || "", point.origin === "setup" ? "前置数据" : "用例主体",
          point.priority || item.risk || "",
          request ? JSON.stringify(request) : "",
          response ? JSON.stringify(response) : "",
          point.status || "", point.durationMs || 0, point.message || "",
          point.verify || "", link,
        ].map(csvCell).join(","));
      });
    });
    const blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const anchor = document.createElement("a");
    anchor.href = URL.createObjectURL(blob);
    anchor.download = "testpoints_all.csv";
    document.body.appendChild(anchor);
    anchor.click();
    setTimeout(function () { URL.revokeObjectURL(anchor.href); document.body.removeChild(anchor); }, 500);
  }

  el.exportAll.addEventListener("click", exportAll);

  el.search.addEventListener("input", function () {
    state.query = el.search.value;
    applyFilters();
  });
  el.method.addEventListener("change", function () {
    state.method = el.method.value;
    applyFilters();
  });
  el.onlyFailed.addEventListener("change", function () {
    state.onlyFailed = el.onlyFailed.checked;
    applyFilters();
  });

  boot();
})();
