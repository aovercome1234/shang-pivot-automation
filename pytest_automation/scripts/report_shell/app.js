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
    benchmark: renderBenchmarkView,
    coverage: renderCoverageView,
    defects: renderDefectsView,
    history: renderHistoryView,
    ui: renderUiView,
    enhancements: renderEnhancementsView,
    thirdparty: renderThirdpartyView,
    thirdpartyDatabase: renderThirdpartyDatabase,
    thirdpartySql: renderThirdpartySql,
    thirdpartyRepro: renderThirdpartyRepro,
    thirdpartyRedis: renderThirdpartyRedis,
    thirdpartyMq: renderThirdpartyMq,
    compare: renderCompareView,
    compareTrend: renderCompareTrend,
    placeholder: renderPlaceholder,
  };

  const state = {
    manifest: null,
    view: null,
    data: null,
    query: "",
    method: "",
    onlyFailed: false,
    coverageRows: [],
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
    logDrawer: document.getElementById("log-drawer"),
    logMask: document.getElementById("log-mask"),
    logDrawerTitle: document.getElementById("log-drawer-title"),
    logDrawerSub: document.getElementById("log-drawer-sub"),
    logBody: document.getElementById("log-body"),
    logCopy: document.getElementById("log-copy"),
    logClose: document.getElementById("log-drawer-close"),
    chainDrawer: document.getElementById("chain-drawer"),
    chainMask: document.getElementById("chain-mask"),
    chainTitle: document.getElementById("chain-drawer-title"),
    chainSub: document.getElementById("chain-drawer-sub"),
    chainBody: document.getElementById("chain-body"),
    chainClose: document.getElementById("chain-drawer-close"),
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
      (point.dimensions && point.dimensions.length
        ? point.dimensions : [point.dimension]).forEach(function (dim) {
        if (dim && dimensions.indexOf(dim) === -1) dimensions.push(dim);
      });
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
      if (drawerState.dim) {
        const dims = point.dimensions && point.dimensions.length
          ? point.dimensions : [point.dimension];
        if (dims.indexOf(drawerState.dim) === -1) return false;
      }
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

  function openChainDrawer(row) {
    el.chainTitle.textContent = row.name || row.id;
    el.chainSub.textContent = row.method + " " + row.path + " · 静态链路（call-graph）" +
      " · 覆盖 " + (row.chainCovered || 0) + " / " + (row.chainNodes || 0) + " 节点";
    const typeLabel = { controller: "入口 Controller", service: "Service", mapper: "Mapper",
      cross_api: "跨上下文 API", table: "数据表" };
    const statusLabel = { covered: "已覆盖", partial: "部分覆盖", uncovered: "未覆盖" };
    const nodes = (row.chain || []).map(function (node, index) {
      const cov = node.coverage || {};
      const badge = node.method
        ? '<span class="cov-badge ' + escapeHtml(cov.status || "unknown") + '">' +
          escapeHtml(statusLabel[cov.status] || "未采集") + "</span>"
        : "";
      const lines = node.method && cov.lineCovered !== undefined
        ? '<span class="muted chain-lines">行 ' + cov.lineCovered + " / " +
          (cov.lineCovered + cov.lineMissed) + "</span>" : "";
      const loc = node.file ? '<span class="muted chain-file">' + escapeHtml(node.file) +
        (node.line ? ":" + node.line : "") + "</span>" : "";
      const clickable = node.method ? ' data-class="' + escapeHtml(node.name) +
        '" data-method="' + escapeHtml(node.method) + '" tabindex="0"' : "";
      return '<li class="chain-node' + (node.method ? " clickable" : "") + '"' + clickable +
        ' data-node-index="' + index + '"><span class="chain-index">' + (index + 1) + "</span>" +
        '<span class="chain-type ' + escapeHtml(node.type) + '">' +
        escapeHtml(typeLabel[node.type] || node.type) + "</span>" +
        '<div class="chain-main"><b>' + escapeHtml(node.label || node.name) + "</b>" + loc + "</div>" +
        badge + lines + "</li>";
    }).join("");
    const attention = (row.chain || []).filter(function (node) {
      const status = (node.coverage || {}).status;
      return node.method && (status === "partial" || status === "uncovered");
    });
    const attentionHtml = attention.length
      ? '<div class="attention-list">' + attention.map(function (node, index) {
          const cov = node.coverage || {};
          return '<button class="attention-item" data-attention="' + index + '">' +
            '<b>' + escapeHtml(node.label) + "</b>" +
            '<span class="cov-badge ' + escapeHtml(cov.status) + '">' +
            (cov.status === "partial" ? "部分覆盖" : "未覆盖") + "</span>" +
            '<span class="muted">行 ' + (cov.lineCovered || 0) + " / " +
            ((cov.lineCovered || 0) + (cov.lineMissed || 0)) + "</span></button>";
        }).join("") + "</div>"
      : '<p class="muted chain-line-empty">链路方法均无未覆盖行。</p>';
    const suggestions = (row.suggestions || []).map(function (text) {
      return "<li>" + escapeHtml(text) + "</li>";
    }).join("");
    state.currentChainAttention = attention;
    state.currentChain = row.chain || [];
    el.chainBody.innerHTML =
      '<p class="muted chain-note">代码入口 → 业务 Service → Mapper → 数据表；' +
        "覆盖状态来自 JaCoCo 上次运行，接口测试点 " + (row.tests || 0) + " 条" +
        (row.chainCovered ? "（链路节点静态可达）" : "") + "。</p>" +
      '<ol class="chain-list">' + (nodes || '<li class="muted">暂无链路数据</li>') + "</ol>" +
      '<h3 class="chain-subtitle">未完全覆盖方法（' + attention.length + '）</h3>' +
      attentionHtml +
      '<div id="chain-class-panel" class="chain-class-panel"></div>' +
      '<h3 class="chain-subtitle">补充建议</h3>' +
      (suggestions ? '<ul class="suggest-list">' + suggestions + "</ul>"
        : '<p class="muted">当前链路方法均已覆盖，建议补充异常/并发/幂等场景。</p>');
    el.chainDrawer.hidden = false;
    el.chainMask.hidden = false;
    document.body.style.overflow = "hidden";
    bindChainNodes();
  }

  function bindChainNodes() {
    const nodes = el.chainBody.querySelectorAll(".chain-node.clickable");
    nodes.forEach(function (node) {
      const show = function () {
        nodes.forEach(function (item) { item.classList.remove("selected"); });
        node.classList.add("selected");
        showClassCoverage(node.dataset.class, node.dataset.method);
      };
      node.addEventListener("click", show);
      node.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); show(); }
      });
    });
    if (nodes.length) nodes[0].click();
    el.chainBody.querySelectorAll("[data-attention]").forEach(function (button) {
      button.addEventListener("click", function () {
        const node = (state.currentChainAttention || [])[Number(button.dataset.attention)];
        if (node) {
          showClassCoverage(node.name, node.method);
          document.getElementById("chain-class-panel").scrollIntoView({
            behavior: "smooth", block: "nearest",
          });
        }
      });
    });
  }

  function showClassCoverage(className, selectedMethod) {
    const panel = document.getElementById("chain-class-panel");
    if (!panel) return;
    const info = (state.coverageClasses || {})[className];
    if (!info) {
      panel.innerHTML = '<div class="chain-panel-head"><strong>' + escapeHtml(className) +
        '</strong><span class="muted">未采集该类的方法覆盖率（第三方类或未加载）</span></div>';
      return;
    }
    const statusLabel = { covered: "已覆盖", partial: "部分覆盖", uncovered: "未覆盖", unknown: "无数据" };
    const chainMethods = new Set((state.currentChain || [])
      .filter(function (node) { return node.name === className && node.method; })
      .map(function (node) { return node.method; }));
    const methods = (info.methods || []).filter(function (method) {
      return chainMethods.has(method.name);
    });
    if (!methods.length) {
      panel.innerHTML = '<div class="chain-panel-head"><strong>' + escapeHtml(className) +
        '</strong><span class="muted">该类在当前接口链路中没有方法节点</span></div>';
      return;
    }
    const rows = methods.map(function (method) {
      const total = method.lineCovered + method.lineMissed;
      const active = method.name === selectedMethod;
      return '<tr data-method="' + escapeHtml(method.name) + '"' + (active ? ' class="active"' : "") +
        '><td><code>' + escapeHtml(method.name) + "</code></td><td>" + method.lineCovered + " / " + total +
        '</td><td><span class="cov-badge ' + method.status + '">' +
        (statusLabel[method.status] || method.status) + "</span></td></tr>";
    }).join("");
    panel.innerHTML = '<div class="chain-panel-head"><strong>' + escapeHtml(className) +
      '</strong><span class="muted">' + escapeHtml(info.package || "") + "</span>" +
      '<a href="' + escapeHtml(info.html) + '" target="_blank" rel="noopener">JaCoCo 类报告</a></div>' +
      '<div class="drill-table-wrap"><table class="chain-method-table"><thead><tr>' +
        "<th>方法</th><th>行覆盖</th><th>状态</th>" +
      "</tr></thead><tbody>" + rows + "</tbody></table></div>" +
      '<div id="chain-line-panel" class="chain-line-panel"></div>';
    panel.querySelectorAll("tr[data-method]").forEach(function (row) {
      row.addEventListener("click", function () {
        panel.querySelectorAll("tr[data-method]").forEach(function (item) {
          item.classList.remove("active");
        });
        row.classList.add("active");
        showMethodLines(info, row.dataset.method);
      });
    });
    showMethodLines(info, selectedMethod);
  }

  function showMethodLines(info, methodName) {
    const panel = document.getElementById("chain-line-panel");
    if (!panel) return;
    const method = (info.methods || []).find(function (item) { return item.name === methodName; });
    if (!method) {
      panel.innerHTML = "";
      return;
    }
    const lines = method.lines || [];
    if (!lines.length) {
      panel.innerHTML = '<p class="muted chain-line-empty">该类为 Mapper/第三方类，未采集行覆盖数据。</p>';
      return;
    }
    const statusLabel = { covered: "覆盖", partial: "部分", uncovered: "未覆盖", unknown: "—" };
    const rows = lines.map(function (line) {
      return '<tr class="line-' + (line.status || "unknown") + '"><td class="line-no">' + line.nr +
        '</td><td><span class="cov-badge ' + (line.status || "unknown") + '">' +
        (statusLabel[line.status] || "—") + '</span></td><td><code>' +
        escapeHtml(line.code || "") + "</code></td></tr>";
    }).join("");
    const covered = lines.filter(function (line) { return line.status === "covered"; }).length;
    const missing = lines.filter(function (line) { return line.status === "uncovered"; }).length;
    const missingLines = lines.filter(function (line) { return line.status === "uncovered"; })
      .map(function (line) { return line.nr; });
    panel.innerHTML = '<div class="chain-line-head"><strong>' + escapeHtml(method.name) +
      '</strong><span class="muted">行 ' + method.startLine + "–" + method.endLine +
      " · 已覆盖 " + covered + " · 未覆盖 " + missing +
      (missingLines.length ? "（" + missingLines.join(", ") + "）" : "") + "</span></div>" +
      '<div class="chain-line-wrap"><table class="chain-line-table"><tbody>' + rows +
      "</tbody></table></div>";
    const wrap = panel.querySelector(".chain-line-wrap");
    if (wrap) wrap.scrollTop = 0;
  }
  function closeChainDrawer() {
    el.chainDrawer.hidden = true;
    el.chainMask.hidden = true;
    document.body.style.overflow = "";
  }
  el.chainClose.addEventListener("click", closeChainDrawer);
  el.chainMask.addEventListener("click", closeChainDrawer);
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !el.chainDrawer.hidden) closeChainDrawer();
  });

  function openLogDrawer(entry) {
    const point = entry.point;
    const item = entry.item;
    const http = point.httpStatus || (point.response || {}).status || "-";
    const biz = point.bizCode == null ? "-" : point.bizCode;
    el.logDrawerTitle.textContent = point.caseId || point.name || "500 错误日志";
    el.logDrawerSub.textContent = item.method + " " + item.path +
      " · HTTP " + http + " / 业务码 " + biz +
      (point.traceId ? " · traceId " + point.traceId : "");
    el.logBody.textContent = point.backendLog || point.message || "（无后端日志）";
    el.logDrawer.hidden = false;
    el.logMask.hidden = false;
    document.body.style.overflow = "hidden";
  }
  function closeLogDrawer() {
    el.logDrawer.hidden = true;
    el.logMask.hidden = true;
    document.body.style.overflow = "";
  }
  el.logClose.addEventListener("click", closeLogDrawer);
  el.logMask.addEventListener("click", closeLogDrawer);
  el.logCopy.addEventListener("click", function () {
    copyText(el.logBody.textContent || "", el.logCopy);
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !el.logDrawer.hidden) closeLogDrawer();
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
        const logText = point.backendLog
          ? (point.message || "") + "\n\n--- 后端日志（traceId） ---\n" + point.backendLog
          : (point.message || "");
        const index = drawerCells.push({
          title: point.backendLog ? "失败详情 + 后端日志（悬浮查看 / 可复制）" : "失败详情（悬浮查看 / 可复制）",
          payload: logText || "（无堆栈信息）",
          asText: true,
        }) - 1;
        failCell = '<span class="fail-short" data-cell="' + index + '" tabindex="0">' +
          escapeHtml(shortReason(point.message)) + "</span>";
      }
      const pointDims = point.dimensions && point.dimensions.length
        ? point.dimensions : [point.dimension || "其他"];
      return "<tr>" +
        '<td>' + pointDims.map(function (dim) {
          return '<span class="dim-tag">' + escapeHtml(dim) + "</span>";
        }).join(" ") + "</td>" +
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
        const dims = point.dimensions && point.dimensions.length
          ? point.dimensions : [point.dimension || "其他"];
        dims.forEach(function (dim) {
          if (!index.has(dim)) index.set(dim, new Map());
          const cases = index.get(dim);
          if (!cases.has(point.nodeid)) {
            cases.set(point.nodeid, {
              point: point,
              item: item,
              interfaces: [],
              risk: item.risk || "P2",
            });
          }
          const entry = cases.get(point.nodeid);
          const label = item.method + " " + item.path;
          if (entry.interfaces.indexOf(label) === -1) entry.interfaces.push(label);
        });
      });
    });
    return index;
  }

  let statsState = { data: null, dimension: "", onlyFailed: true, logs: [] };

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
    const primaryStats = data.primaryDimensionStats || stats;
    const summary = data.summary || {};
    const total = primaryStats.reduce(function (sum, d) { return sum + (d.total || 0); }, 0);
    const failed = primaryStats.reduce(function (sum, d) { return sum + (d.failed || 0) + (d.broken || 0); }, 0);
    const passed = primaryStats.reduce(function (sum, d) { return sum + (d.passed || 0); }, 0);
    const rate = total ? (passed / total * 100).toFixed(1) : "0.0";
    const checks = (data.dimensionStats || []).filter(function (item) {
      return ["DB校验", "Redis校验", "MQ校验", "请求方式校验"].indexOf(item.dimension) !== -1;
    });

    const kpis = '<div class="stats-kpi">' +
      kpiCard(total, "已归属用例") + kpiCard(rate + "%", "通过率") +
      kpiCard(failed, "失败用例", true) + kpiCard(stats.length, "测试分类") +
    "</div>" +
    '<p class="muted stats-note">原报告共 ' + (summary.reportTotal || "-") + " 条；本页统计已归属接口的用例，" +
      "UI 用例 " + (summary.uiTests || 0) + " 条与未归属 " + (summary.unattributed || 0) + " 条不计入。" +
      "柱状图为多标签统计（同一测试点可计入多个分类，DB/Redis/MQ/请求方式为附加分类），" +
      "通过率与饼图按主分类计算。</p>";

    const checkChips = checks.length
      ? '<div class="check-strip">' + checks.map(function (item) {
          return '<span class="check-chip"><b>' + escapeHtml(item.dimension) + "</b>" +
            (item.total || 0) + " 条</span>";
        }).join("") + "</div>"
      : "";

    el.statsView.innerHTML = kpis + checkChips +
      '<div class="charts">' +
        '<div class="chart-panel">' +
          '<div class="chart-head"><strong>各分类用例数量与结果构成</strong>' +
            '<span class="grow"></span>' +
            '<div class="legend"><span><i class="pass"></i>通过</span>' +
            '<span><i class="fail"></i>失败</span><span><i class="skip"></i>跳过</span></div>' +
          "</div>" +
          columnChartSvg(stats) +
          '<p class="muted chart-foot">多标签口径：DB/Redis/MQ/请求方式为附加分类，故各柱之和大于用例总数。</p>' +
        "</div>" +
        '<div class="chart-panel">' +
          '<div class="chart-head"><strong>失败用例构成</strong><span class="muted">按主分类</span></div>' +
          failureDonut(primaryStats) +
        "</div>" +
      "</div>" +
      '<div class="drill-card" id="drill-card"><div class="drill-head"><strong>分类明细</strong>' +
      '<span class="muted">点击柱状图、饼图或右侧图例查看用例</span></div>' +
      '<div class="drill-body muted">尚未选择分类</div></div>' +
      renderErrorLogPanel(data);

    const index = buildDimensionIndex(data);
    el.statsView.querySelectorAll("[data-dim]").forEach(function (node) {
      node.addEventListener("click", function () {
        selectDimension(node.dataset.dim, index);
      });
    });
    el.statsView.querySelectorAll("[data-log-index]").forEach(function (node) {
      node.addEventListener("click", function () {
        const entry = statsState.logs[Number(node.dataset.logIndex)];
        if (entry) openLogDrawer(entry);
      });
    });
  }

  function collectErrorLogs(data) {
    const logs = [];
    const seen = new Set();
    (data.interfaces || []).forEach(function (item) {
      (item.testPoints || []).forEach(function (point) {
        if (point.status !== "failed" && point.status !== "broken") return;
        const http = Number(point.httpStatus || (point.response || {}).status || 0);
        const biz = Number(point.bizCode);
        if (http < 500 && biz !== 50000) return;
        const key = (point.nodeid || "") + "|" + item.id;
        if (seen.has(key)) return;
        seen.add(key);
        logs.push({ point: point, item: item });
      });
    });
    return logs;
  }

  function renderErrorLogPanel(data) {
    const logs = collectErrorLogs(data);
    statsState.logs = logs;
    if (!logs.length) {
      return '<div class="chart-panel"><div class="chart-head"><strong>500 错误日志</strong>' +
        '<span class="muted">0 条</span></div><p class="muted chart-foot">本轮没有 HTTP 500 / 业务码 50000 的失败点。</p></div>';
    }
    const rows = logs.map(function (entry, index) {
      const point = entry.point;
      const item = entry.item;
      const http = point.httpStatus || (point.response || {}).status || "-";
      const biz = point.bizCode == null ? "-" : point.bizCode;
      const trace = point.traceId || "-";
      const dims = point.dimensions && point.dimensions.length
        ? point.dimensions : [point.dimension || "其他"];
      const label = point.caseId || point.name || point.nodeid;
      return "<tr><td>" + escapeHtml(label) + "</td>" +
        "<td><code>" + escapeHtml(item.method + " " + item.path) + "</code></td>" +
        "<td>" + dims.map(function (dim) {
          return '<span class="dim-tag">' + escapeHtml(dim) + "</span>";
        }).join(" ") + "</td>" +
        "<td>" + escapeHtml(String(http)) + " / " + escapeHtml(String(biz)) + "</td>" +
        '<td class="mono muted">' + escapeHtml(String(trace).slice(0, 12)) + "</td>" +
        '<td><button class="detail-btn" data-log-index="' + index + '">查看日志</button></td></tr>';
    }).join("");
    return '<div class="chart-panel"><div class="chart-head"><strong>500 错误日志</strong>' +
      '<span class="muted">' + logs.length + " 条 · 数据来自 Allure 后端日志附件</span></div>" +
      '<div class="drill-table-wrap log-table-wrap"><table class="drawer-table drill-table bench-table"><thead><tr>' +
        "<th>用例</th><th>接口</th><th>分类</th><th>HTTP / 业务码</th><th>traceId</th><th>日志</th>" +
      "</tr></thead><tbody>" + rows + "</tbody></table></div></div>";
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

    const body = rows.map(function (entry, index) {
      const point = entry.point;
      const short = shortReason(point.message);
      const href = point.link || "";
      const duration = point.durationMs ? (point.durationMs >= 1000
        ? (point.durationMs / 1000).toFixed(2) + "s" : point.durationMs + "ms") : "—";
      const logCell = point.backendLog
        ? '<button class="mini-copy" data-drill-log="' + index + '">查看日志</button>'
        : '<span class="muted">—</span>';
      return "<tr>" +
        '<td class="muted">' + escapeHtml(entry.interfaces.join("、")) + "</td>" +
        "<td>" + escapeHtml(String(point.name).split("｜")[0]) + "</td>" +
        '<td><span class="risk ' + escapeHtml(point.priority || entry.risk) + '">' +
          escapeHtml(point.priority || entry.risk) + "</span></td>" +
        "<td>" + statusBadge(point.status) + "</td>" +
        '<td class="muted">' + duration + "</td>" +
        '<td class="fail-cell">' + (short === "—" ? "—" : escapeHtml(short)) + "</td>" +
        "<td>" + logCell + "</td>" +
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
      "<th>接口</th><th>测试点</th><th>优先级</th><th>结果</th><th>耗时</th><th>失败原因</th><th>错误日志</th><th>报告</th>" +
      "</tr></thead><tbody>" + (body || '<tr><td colspan="8" class="muted">没有符合条件的用例</td></tr>') +
      "</tbody></table></div>";

    card.querySelectorAll("[data-drill-log]").forEach(function (button) {
      button.addEventListener("click", function () {
        const entry = rows[Number(button.dataset.drillLog)];
        if (entry) openLogDrawer({ point: entry.point, item: entry.item });
      });
    });
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
    benchmark: "API / UI 两层分别对比「串行 vs 并行」的分组墙钟；API 每接口独立并发，方法耗时构成作为辅助。",
    coverage: "接口有用例/请求方式校验/写接口 DB 落库/代码链路节点覆盖的静态矩阵；行覆盖由夜间 JaCoCo 补充。",
    defects: "失败用例自动生成的缺陷单：接口、分类、请求/响应、traceId 日志、代码位置（取堆栈最底层应用帧；详情先展示调用链，无堆栈时按端点映射到 Controller）。",
    history: "上一轮与本轮用例库/执行结果/覆盖率的差异：新增、删除、修改、结果迁移与修复情况。",
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

  function fmtSeconds(value) {
    const seconds = Number(value || 0);
    if (!seconds) return "—";
    const minutes = Math.floor(seconds / 60);
    const rest = Math.round(seconds - minutes * 60);
    return minutes ? minutes + "分" + rest + "秒" : Math.round(seconds) + "s";
  }

  function layerBars(serial, median) {
    const width = serial ? (median / serial * 100).toFixed(1) : 0;
    return '<div class="compare-bars">' +
      '<div class="cmp-row"><span class="cmp-label">串行</span>' +
        '<div class="cmp-track"><div class="cmp-fill serial" style="width:100%">' + fmtSeconds(serial) + "</div></div>" +
        '<span class="cmp-meta">1 个进程依次执行</span></div>' +
      '<div class="cmp-row"><span class="cmp-label">并行</span>' +
        '<div class="cmp-track"><div class="cmp-fill parallel" style="width:' + width + '%">' +
          fmtSeconds(median) + "</div></div>" +
        '<span class="cmp-meta">中位数（' + (serial && median ? (serial / median).toFixed(2) : "—") + " 倍）</span></div>" +
    "</div>";
  }

  function layerRunsTable(layer) {
    const serial = layer.serial || {};
    const rows = (layer.runs || []).map(function (run) {
      const total = Number(run.total_seconds || 0);
      const speed = serial.total_seconds && total ? (serial.total_seconds / total).toFixed(2) + "x" : "—";
      const counts = run.passed !== undefined
        ? run.passed + " / " + run.failed + " / " + (run.skipped || 0) : "—";
      return "<tr><td>" + escapeHtml(run.dir || "") + "</td><td>并行</td><td>" +
        (run.workers || "—") + "</td><td>" + escapeHtml(run.dist || "—") + "</td>" +
        "<td>" + (run.stage1_seconds !== undefined
          ? (run.stage1_seconds + "s" + (run.stage1_cases ? '<span class="muted"> / ' + run.stage1_cases + " 条</span>" : ""))
          : "—") + "</td>" +
        "<td>" + (run.stage2_seconds !== undefined
          ? (run.stage2_seconds + "s" + (run.stage2_cases ? '<span class="muted"> / ' + run.stage2_cases + " 条</span>" : ""))
          : "—") + "</td>" +
        "<td><b>" + fmtSeconds(total) + "</b></td><td><b>" + speed + "</b></td><td>" + counts + "</td></tr>";
    }).join("");
    const serialRow = "<tr><td>" + escapeHtml(serial.dir || "serial") + "</td><td>串行</td><td>1</td><td>—</td>" +
      "<td>—</td><td>—</td><td><b>" + fmtSeconds(serial.total_seconds) + "</b></td>" +
      "<td>1.00x（基准）</td><td>" + (serial.passed || 0) + " / " + (serial.failed || 0) +
      " / " + (serial.skipped || 0) + "</td></tr>";
    return '<div class="drill-table-wrap"><table class="drawer-table drill-table bench-table"><thead><tr>' +
      "<th>批次</th><th>模式</th><th>workers</th><th>分发</th><th>阶段一</th><th>阶段二</th>" +
      "<th>总耗时</th><th>相对串行</th><th>通过 / 失败 / 跳过</th></tr></thead><tbody>" +
      serialRow + rows + "</tbody></table></div>";
  }

  function layerConsistency(layer) {
    const serial = layer.serial || {};
    const runs = layer.runs || [];
    if (!runs.length) return { text: "—", ok: true };
    const same = runs.filter(function (run) {
      return run.passed === serial.passed && run.failed === serial.failed &&
        (run.skipped || 0) === (serial.skipped || 0);
    }).length;
    return { text: same + "/" + runs.length + " 一致", ok: same === runs.length };
  }

  function renderLayerSection(layer, title, note) {
    const serial = Number((layer.serial || {}).total_seconds || 0);
    const median = Number(layer.median_seconds || 0);
    const speedup = layer.speedup ? layer.speedup + "x" : "—";
    const consistency = layerConsistency(layer);
    return '<div class="chart-panel" style="margin-bottom:14px">' +
      '<div class="chart-head"><strong>' + title + '</strong><span class="muted">' + note + "</span></div>" +
      '<div class="stats-kpi" style="margin:8px 0 4px">' +
        kpiCard(fmtSeconds(serial), "串行（单进程）") +
        kpiCard(fmtSeconds(median), "并行中位数") +
        kpiCard(speedup, "加速比") +
        kpiCard(consistency.text, "结果一致性", !consistency.ok) +
      "</div>" + layerBars(serial, median) + layerRunsTable(layer) + "</div>";
  }

  function renderMethodMix(mix) {
    if (!mix || !mix.serial || !mix.parallel) {
      return '<div class="chart-panel"><div class="chart-head"><strong>API 方法耗时构成</strong>' +
        '<span class="muted">缺少串行或并行结果</span></div></div>';
    }
    const order = ["GET", "POST", "PUT", "DELETE"];
    const serialTotal = order.reduce(function (sum, m) {
      return sum + ((mix.serial[m] || {}).seconds || 0);
    }, 0) || 1;
    const rows = order.map(function (method) {
      const s = mix.serial[method] || { count: 0, seconds: 0 };
      const p = mix.parallel[method] || { count: 0, seconds: 0 };
      const share = (s.seconds / serialTotal * 100).toFixed(1);
      return "<tr><td><b>" + method + "</b></td><td>" + s.count + "</td>" +
        "<td>" + s.seconds.toFixed(2) + "s</td><td>" + p.seconds.toFixed(2) + "s</td>" +
        "<td>" + share + "%</td>" +
        '<td><div class="mix-bar"><span style="width:' + share + '%"></span></div></td></tr>';
    }).join("");
    return '<div class="chart-panel"><div class="chart-head"><strong>API 方法耗时构成</strong>' +
      '<span class="muted">辅助口径：按主体接口方法汇总单测耗时，不代表墙钟；不按方法单独并发运行</span></div>' +
      '<div class="drill-table-wrap"><table class="drawer-table drill-table bench-table"><thead><tr>' +
        "<th>方法</th><th>用例数</th><th>串行耗时和</th><th>并行耗时和</th><th>串行占比</th><th>占比条</th>" +
      "</tr></thead><tbody>" + rows + "</tbody></table></div>" +
      '<p class="muted">说明：串行与并行各自的「耗时和」接近是预期——并行缩短的是整轮墙钟，不改变单条用例耗时；' +
      "该表用于看时间花在哪些方法上（GET 用例最多），并行轮取自中位数那一轮。</p></div>";
  }

  function renderBenchmarkView(data) {
    el.toolbar.hidden = true;
    el.reconcileBox.hidden = true;
    el.tableBox.hidden = true;
    el.stats.hidden = true;
    el.statsView.hidden = false;

    const layers = data.layers || {};
    const api = layers.api || { runs: [] };
    const ui = layers.ui || { runs: [] };
    const apiSerial = Number((api.serial || {}).total_seconds || 0);

    el.statsView.innerHTML =
      '<p class="muted stats-note" style="margin-top:0">正式对比口径：<b>分组墙钟</b>——API 与 UI 各自「串行 vs 并行」各测一轮以上；' +
        "并行一轮取中位数。串行 = 单进程；API 并行 = 4 worker，按<b>主体接口分组</b>分发（同接口用例同 worker 顺序执行，接口之间并行）；" +
        "UI 并行 = 3 worker，每 worker 独立浏览器与随机会员账号。" +
        "方法（GET/POST/PUT/DELETE）不做单独并发运行，仅以「耗时构成」辅助展示。</p>" +
      renderLayerSection(api, "API 自动化", "701 条接口用例；每接口独立并发（xdist loadgroup）") +
      renderLayerSection(ui, "UI 自动化", "47 条 Playwright 用例；3 worker，账号隔离") +
      renderMethodMix(api.methodMix) +
      '<div class="chart-panel"><div class="chart-head"><strong>如何解读</strong></div>' +
        '<div class="muted" style="font-size:12.5px;line-height:1.9">' +
        "① <b>串行时间</b>：单进程跑完该层全部用例的墙钟耗时（API " + fmtSeconds(apiSerial) + "、UI " +
          fmtSeconds((ui.serial || {}).total_seconds) + "），所有加速比以它为分母。<br>" +
        "② <b>加速比 = 串行 ÷ 并行</b>；API 并行按接口分组分发，同接口用例不会并发执行，避免共享数据互相影响；" +
          "库存敏感用例再按 worker 分 SKU，批量库存/登录限流类进入串行 lane。<br>" +
        "③ <b>结果一致性</b>：并行与串行的通过/失败/跳过完全一致才算通过；API 的 93 条失败是已知待修缺陷。<br>" +
        "④ <b>方法耗时构成</b>：仅辅助看时间分布（GET 用例最多），不是按方法并发跑的对比。" +
        "</div></div>";
  }

  function renderHistoryView(data) {
    el.toolbar.hidden = true;
    el.reconcileBox.hidden = true;
    el.tableBox.hidden = true;
    el.stats.hidden = true;
    el.statsView.hidden = false;
    if (!data || !data.current) {
      el.statsView.innerHTML = '<div class="placeholder-card"><h2>用例历史</h2>' +
        '<p class="muted">至少需要两轮归档运行才能生成 diff。运行后执行 scripts/archive_run.py 与 scripts/case_history.py。</p></div>';
      return;
    }
    const summary = data.summary || {};
    function listTable(title, rows, columns) {
      if (!rows || !rows.length) {
        return '<div class="chart-panel"><div class="chart-head"><strong>' + title +
          '</strong><span class="muted">无变化</span></div></div>';
      }
      const head = columns.map(function (c) { return "<th>" + c + "</th>"; }).join("");
      const body = rows.map(function (row) {
        return "<tr>" + columns.map(function (_, index) {
          return "<td>" + escapeHtml(String(row[index] == null ? "" : row[index])) + "</td>";
        }).join("") + "</tr>";
      }).join("");
      return '<div class="chart-panel"><div class="chart-head"><strong>' + title + "</strong>" +
        '<span class="muted">' + rows.length + " 条</span></div>" +
        '<div class="drill-table-wrap"><table class="drawer-table drill-table bench-table"><thead><tr>' +
        head + "</tr></thead><tbody>" + body + "</tbody></table></div></div>";
    }
    const transitions = (data.transitions || []).map(function (t) {
      return [t.case_id, t.title, t.from, t.to];
    });
    el.statsView.innerHTML =
      '<div class="stats-kpi">' +
        kpiCard(data.previous + " → " + data.current, "对比轮次") +
        kpiCard(summary.casesAdded + " / " + summary.casesRemoved, "新增 / 删除用例") +
        kpiCard(summary.casesModified, "修改用例") +
        kpiCard(summary.newFailures + " / " + summary.fixed, "新失败 / 修复", summary.newFailures > 0) +
      "</div>" +
      '<p class="muted stats-note">用例变更来自不可变注册表（content_hash）；结果迁移来自两轮 results.json；' +
        "覆盖变化来自 coverage.json 快照。git：" + escapeHtml((data.git || {}).current || "-") + "。</p>" +
      listTable("用例变更（新增）", data.added || [], ["脚本", "用例编号", "标题"]) +
      listTable("用例变更（修改）", data.modified || [], ["脚本", "用例编号", "标题"]) +
      listTable("用例变更（删除/退役）", data.removed || [], ["脚本", "用例编号", "标题"]) +
      listTable("结果迁移", transitions, ["用例编号", "标题", "上轮", "本轮"]);
  }

  function renderDefectsView(data) {
    el.toolbar.hidden = true;
    el.reconcileBox.hidden = true;
    el.tableBox.hidden = true;
    el.stats.hidden = true;
    el.statsView.hidden = false;
    const defects = data.defects || [];
    const rows = defects.map(function (item) {
      const code = item.code
        ? '<span class="code-loc" tabindex="0" data-loc="' + escapeHtml(item.code.location || "") +
          '" data-source="' + escapeHtml(item.code.source || "stack") +
          '" data-code="' + escapeHtml(item.code.snippet || "") + '">' +
          escapeHtml(item.code.className || item.code.location || "") +
          (item.code.source === "endpoint"
            ? ' <span class="entry-tag" title="参数解析/入口阶段，无更底层业务代码">入口</span>' : "") +
          "</span>"
        : '<span class="muted">未定位</span>';
      const gitee = item.gitee || {};
      const giteeHref = gitee.htmlUrl || gitee.issueUrl || "";
      const giteeButton = giteeHref
        ? '<a class="detail-btn" href="' + escapeHtml(giteeHref) +
          '" target="_blank" rel="noopener" title="打开 Gitee Issue' +
          (gitee.number ? " #" + escapeHtml(String(gitee.number)) : "") +
          '">Gitee 缺陷</a>'
        : '<span class="detail-btn disabled" title="' +
          escapeHtml(gitee.error || "尚未提交到 Gitee；配置 GITEE_TOKEN 后生成") +
          '">Gitee 缺陷</span>';
      return "<tr><td>" + escapeHtml(item.name || "") + "</td>" +
        "<td><code>" + escapeHtml(item.endpoint || "") + "</code></td>" +
        "<td>" + escapeHtml(item.dimension || "") + "</td>" +
        '<td class="fail-cell">' + escapeHtml(item.summary || "") + "</td>" + "<td>" + code + "</td>" +
        '<td class="defect-actions"><a class="detail-btn" href="' +
        escapeHtml(item.reportLink || "#") + '" target="_blank" rel="noopener">本地缺陷</a>' +
        giteeButton + "</td>" +
      "</tr>";
    }).join("");
    el.statsView.innerHTML =
      '<div class="stats-kpi">' +
        kpiCard(defects.length, "缺陷单") +
        kpiCard(defects.filter(function (d) { return d.code; }).length, "已定位代码") +
        kpiCard(defects.filter(function (d) { return d.gitee && d.gitee.htmlUrl; }).length, "Gitee 已提交") +
        kpiCard(data.runId || "—", "运行 ID") +
      "</div>" +
      '<p class="muted stats-note">由失败用例自动生成：包含请求/响应、traceId 后端日志与代码位置（取堆栈最底层应用帧；详情先展示调用链）；' +
        "缺陷单默认写入 defects/&lt;run_id&gt;/；「本地缺陷」打开归档 HTML，「Gitee 缺陷」跳转对应 issue（GITEE_TOKEN 未配置时只生成 payload，不伪造链接）。</p>" +
      '<div class="chart-panel"><div class="chart-head"><strong>缺陷列表</strong></div>' +
        '<div class="drill-table-wrap"><table class="drawer-table drill-table bench-table"><thead><tr>' +
          "<th>用例</th><th>接口</th><th>分类</th><th>失败摘要</th><th>代码位置</th><th>操作</th>" +
        "</tr></thead><tbody>" + (rows || '<tr><td colspan="6" class="muted">本轮没有失败用例</td></tr>') +
        "</tbody></table></div></div>";
    el.statsView.querySelectorAll(".code-loc").forEach(function (node) {
      const show = function () {
        const suffix = node.dataset.source === "endpoint" ? "（入口/参数解析阶段）" : "";
        showTooltip(node, "代码位置 · " + (node.dataset.loc || "") + suffix,
          node.dataset.code || "（无代码片段）", true);
      };
      node.addEventListener("mouseenter", show);
      node.addEventListener("focus", show);
      node.addEventListener("mouseleave", hideTooltipSoon);
      node.addEventListener("blur", hideTooltipSoon);
    });
  }

  function renderCoverageView(data) {
    el.toolbar.hidden = true;
    el.reconcileBox.hidden = true;
    el.tableBox.hidden = true;
    el.stats.hidden = true;
    el.statsView.hidden = false;
    const summary = data.summary || {};
    state.coverageRows = data.interfaces || [];
    state.coverageClasses = data.jacocoClasses || {};
    const rows = state.coverageRows.map(function (row, index) {
      const dims = (row.dimensions || []).join(" / ");
      let dbCell = '<span class="badge skipped">不适用</span>';
      if (row.method !== "GET" || row.dbStatus) {
        if (row.dbStatus === "covered") dbCell = '<span class="badge passed">已覆盖</span>';
        else if (row.dbStatus === "not_applicable") dbCell = '<span class="badge skipped" title="' +
          escapeHtml(row.dbReason || "") + '">不适用</span>';
        else if (row.dbStatus === "missing") dbCell = '<span class="badge warn" title="' +
          escapeHtml(row.dbReason || "") + '">待补</span>';
        else if (row.dbChecked) dbCell = '<span class="badge passed">已覆盖</span>';
      }
      const comps = (row.components || []).map(function (comp) {
        return '<span class="badge ' + (comp.checked ? "passed" : "warn") + '" title="' +
          escapeHtml(comp.checked ? "存在 " + comp.name + " 状态断言" : "接口使用 " + comp.name + "，缺少该维度的状态断言") +
          '">' + escapeHtml(comp.name) + (comp.checked ? "" : " 待补") + "</span>";
      }).join(" ") || '<span class="muted">—</span>';
      return "<tr><td>" + escapeHtml(row.id) + "</td><td>" + escapeHtml(row.name || "") + "</td>" +
        "<td>" + methodBadge(row.method) + "</td>" +
        '<td><span class="risk ' + escapeHtml(row.risk || "P2") + '">' + escapeHtml(row.risk || "P2") + "</span></td>" +
        "<td>" + (row.tests || 0) + "</td>" +
        "<td>" + (row.methodChecked ? '<span class="badge passed">已校验</span>' : '<span class="badge skipped">缺失</span>') + "</td>" +
        "<td>" + dbCell + "</td>" +
        "<td>" + comps + "</td>" +
        '<td><button class="chain-btn" data-chain-index="' + index + '">方法 ' +
          (row.methodCovered || 0) + " / " + (row.methodTotal || 0) + "</button></td>" +
        '<td class="suggest-col">' +
          (row.suggestions && row.suggestions.length
            ? '<div class="suggest-cell" tabindex="0" data-suggest-index="' + index + '">' +
              escapeHtml(row.suggestions[0]) +
              (row.suggestions.length > 1
                ? '<span class="suggest-more">+' + (row.suggestions.length - 1) + "</span>" : "") +
              "</div>"
            : '<span class="muted">—</span>') + "</td>" +
        '<td class="muted">' + escapeHtml(dims) + "</td></tr>";
    }).join("");
    const runtime = data.runtime || null;
    const runtimeRate = runtime && typeof runtime.lineRate === "number"
      ? (runtime.lineRate * 100).toFixed(1) + "%" : "—";
    const runtimeRows = runtime && runtime.packages
      ? runtime.packages.map(function (pkg) {
          const href = pkg.html || "#";
          return '<tr><td><a class="pkg-link" href="' + escapeHtml(href) +
            '" target="_blank" rel="noopener">' + escapeHtml(pkg.name || "") + "</a></td>" +
            "<td>" + (pkg.classes || 0) + "</td>" +
            "<td>" + ((pkg.line_rate || 0) * 100).toFixed(1) + "%</td>" +
            "<td>" + (pkg.line_covered || 0) + " / " + ((pkg.line_covered || 0) + (pkg.line_missed || 0)) + "</td>" +
            '<td><a class="allure-open" href="' + escapeHtml(href) +
            '" target="_blank" rel="noopener">查看</a></td></tr>';
        }).join("")
      : "";
    el.statsView.innerHTML =
      '<div class="stats-kpi">' +
        kpiCard(summary.withTests + " / " + summary.interfaces, "有用例的接口") +
        kpiCard(summary.interfaceRate + "%", "接口覆盖率") +
        kpiCard(summary.writeDbCovered + " / " + (summary.writeApplicable || summary.writeTotal), "写接口 DB 断言", summary.writeDbCovered !== (summary.writeApplicable || summary.writeTotal)) +
        kpiCard((summary.componentCovered || 0) + " / " + (summary.componentTotal || 0), "组件校验（Redis/MQ）",
          (summary.componentCovered || 0) !== (summary.componentTotal || 0)) +
        kpiCard((summary.methodCovered || 0) + " / " + (summary.methodTotal || 0), "链路方法覆盖",
          (summary.methodCovered || 0) !== (summary.methodTotal || 0)) +
        kpiCard(summary.chainRate + "%", "调用链节点覆盖") +
        kpiCard(runtimeRate, "JaCoCo 行覆盖", !runtime) +
      "</div>" +
      '<p class="muted stats-note">口径：接口覆盖率 = 至少一条用例触达的接口；请求方式校验 = 用例实际调用方法与该接口定义一致；' +
        "写接口 DB 断言 = 存在“请求→落库行”校验；DB 不适用 = 认证/令牌等无业务表写入，" +
        "待补 = 已有用例但缺落库断言（本轮 " + (summary.writeDbCovered || 0) + " 覆盖 / " +
        (summary.dbNotApplicable || 0) + " 不适用 / " + (summary.dbMissing || 0) + " 待补；共 " + (summary.writeTotal || 0) + " 个写接口）；" +
        "组件校验 = 接口实际使用 Redis/MQ 时是否存在对应状态断言；链路节点 = Controller/Service/跨上下文/Mapper 表，静态来自 call-graph。" +
        (runtime
          ? "行覆盖率来自 JaCoCo（" + escapeHtml(runtime.generatedAt || "") + "，<a href=\"" +
            escapeHtml(runtime.html || "#") + "\" target=\"_blank\" rel=\"noopener\">HTML 明细</a>）。"
          : "行覆盖率由夜间 JaCoCo 任务补充（P1）：先执行 scripts/start_backend_jacoco.sh，跑完后 jacoco_dump.sh + jacoco_report.py。") +
      "</p>" +
      (runtimeRows
        ? '<div class="chart-panel"><div class="chart-head"><strong>运行时行覆盖率（按包）</strong><span class="muted">' +
          escapeHtml(runtime.generatedAt || "") + "</span></div>" +
          '<div class="drill-table-wrap"><table class="drawer-table drill-table bench-table"><thead><tr>' +
            "<th>包</th><th>类数</th><th>行覆盖率</th><th>覆盖 / 总行</th><th>明细</th>" +
          "</tr></thead><tbody>" + runtimeRows + "</tbody></table></div></div>"
        : "") +
      '<div class="chart-panel"><div class="chart-head"><strong>接口覆盖明细</strong><span class="muted">' +
        (data.generatedAt || "") + "</span></div>" +
        '<div class="drill-table-wrap"><table class="drawer-table drill-table bench-table coverage-table"><thead><tr>' +
          "<th>接口</th><th>名称</th><th>方法</th><th>风险</th><th>用例数</th>" +
          "<th>请求方式校验</th><th>DB 落库断言</th><th>组件校验</th><th>链路方法</th><th>补充建议</th><th>覆盖维度</th>" +
        "</tr></thead><tbody>" + rows + "</tbody></table></div></div>";
    el.statsView.querySelectorAll("[data-chain-index]").forEach(function (button) {
      button.addEventListener("click", function () {
        const row = state.coverageRows[Number(button.dataset.chainIndex)];
        if (row) openChainDrawer(row);
      });
    });
    el.statsView.querySelectorAll("[data-suggest-index]").forEach(function (node) {
      const show = function () {
        const row = state.coverageRows[Number(node.dataset.suggestIndex)];
        if (row && row.suggestions && row.suggestions.length) {
          showTooltip(node, "补充建议（共 " + row.suggestions.length + " 条，可复制）",
            row.suggestions.join("\n"), true);
        }
      };
      node.addEventListener("mouseenter", show);
      node.addEventListener("focus", show);
      node.addEventListener("mouseleave", hideTooltipSoon);
      node.addEventListener("blur", hideTooltipSoon);
    });
  }

  function tpShell(data) {
    el.toolbar.hidden = true;
    el.reconcileBox.hidden = true;
    el.tableBox.hidden = true;
    el.stats.hidden = true;
    el.statsView.hidden = false;
    state.tpCopyTexts = [];
    state.tpLongTexts = [];
  }

  function tpBanner(data) {
    return '<div class="tp-banner">数据源：<b>' + escapeHtml(data.source || "") + "</b>" +
      " · 采集时间：" + escapeHtml(data.generatedAt || "") +
      " · 运行：" + escapeHtml(data.runId || "-") +
      ' · <a href="../thirdparty/data.json" target="_blank" rel="noopener">下载原始 JSON</a>' +
      ' · <a href="#/thirdparty/database">数据库模型</a>' +
      ' · <a href="#/thirdparty/sql">SQL 证据</a>' +
      ' · <a href="#/thirdparty/reproduce">复现步骤</a></div>';
  }

  function tpRedisCount(redis) {
    return Object.keys(redis.counts || {}).reduce(function (sum, key) {
      return sum + (redis.counts[key] || 0);
    }, 0);
  }

  function tpKpis(db, redis, mq, redisCount) {
    return '<div class="stats-kpi">' +
      kpiCard((db.databases || []).length + " 库", "数据库 / " + (db.schemas || []).length + " schema") +
      kpiCard((db.tableCount || 0) + " 表", "数据库模型") +
      kpiCard((db.fieldCount || 0), "字段总数") +
      kpiCard(redisCount + " keys", "Redis 实时键", !redis.available) +
      kpiCard((mq.queues || []).length + " / " + (mq.eventCount || 0), "MQ 队列 / 事件", !mq.available) +
      "</div>";
  }

  function tpTable(headers, rows, emptyText, className) {
    return '<div class="drill-table-wrap"><table class="drawer-table drill-table bench-table' +
      (className ? " " + className : "") + '"><thead><tr>' +
      headers.map(function (head) { return "<th>" + head + "</th>"; }).join("") +
      "</tr></thead><tbody>" + (rows || '<tr><td colspan="' + headers.length +
        '" class="muted">' + escapeHtml(emptyText || "暂无数据") + "</td></tr>") +
      "</tbody></table></div>";
  }

  function tpCopyButton(text) {
    const index = state.tpCopyTexts.push(text) - 1;
    return '<button class="mini-copy" data-tp-copy="' + index + '">复制</button>';
  }

  function tpLongCell(text, label) {
    const value = String(text == null ? "" : text);
    const index = state.tpLongTexts.push(value) - 1;
    const summary = value.replace(/\s+/g, " ").slice(0, 64) || "—";
    return '<span class="tp-long-cell" tabindex="0" data-tp-long="' + index +
      '" data-label="' + escapeHtml(label) + '">' + escapeHtml(summary) +
      (value.length > 64 ? "…" : "") + "</span>";
  }

  function bindTpLongCells() {
    el.statsView.querySelectorAll("[data-tp-long]").forEach(function (node) {
      const show = function () {
        showTooltip(node, (node.dataset.label || "详情") + "（悬浮查看 / 可复制）",
          state.tpLongTexts[Number(node.dataset.tpLong)] || "", true);
      };
      node.addEventListener("mouseenter", show);
      node.addEventListener("focus", show);
      node.addEventListener("mouseleave", hideTooltipSoon);
      node.addEventListener("blur", hideTooltipSoon);
    });
  }

  function bindTpActions() {
    el.statsView.querySelectorAll("[data-tp-copy]").forEach(function (button) {
      button.addEventListener("click", function () {
        copyText(state.tpCopyTexts[Number(button.dataset.tpCopy)] || "", button);
      });
    });
    el.statsView.querySelectorAll("[data-tp-search]").forEach(function (input) {
      const rows = el.statsView.querySelectorAll("[data-tp-row]");
      const update = function () {
        const query = input.value.trim().toLowerCase();
        let shown = 0;
        rows.forEach(function (row) {
          const text = (row.dataset.tpText || row.innerText).toLowerCase();
          const match = !query || text.indexOf(query) !== -1;
          row.hidden = !match;
          if (match) shown += 1;
        });
        el.statsView.querySelectorAll(".tp-table-block").forEach(function (block) {
          block.hidden = block.querySelectorAll("[data-tp-row]:not([hidden])").length === 0;
        });
        el.statsView.querySelectorAll(".tp-module-block").forEach(function (block) {
          block.hidden = block.querySelectorAll(".tp-table-block:not([hidden])").length === 0;
        });
        const summary = el.statsView.querySelector("[data-tp-filter-summary]");
        if (summary) summary.textContent = "显示 " + shown + " / " + rows.length + " 条";
      };
      input.addEventListener("input", update);
      update();
    });
  }

  function renderThirdpartyView(data) {
    tpShell(data);
    const db = data.db || {};
    const redis = data.redis || {};
    const mq = data.mq || {};
    const knowledge = data.knowledge || {};
    const redisCount = tpRedisCount(redis);
    const dbPreview = (db.tables || []).slice(0, 10).map(function (table) {
      return "<tr><td>" + escapeHtml(table.schema) + "</td><td>" +
        escapeHtml(table.name) + "</td><td>" + (table.rows == null ? "—" : table.rows) +
        "</td><td>" + (table.fields || []).length + "</td></tr>";
    }).join("");
    const redisCounts = Object.keys(redis.counts || {}).map(function (pattern) {
      return '<span class="check-chip"><b>' + escapeHtml(pattern) + "</b>" +
        (redis.counts[pattern] || 0) + " keys</span>";
    }).join("");
    const redisRows = (redis.samples || []).slice(0, 8).map(function (item) {
      return "<tr><td><code>" + escapeHtml(item.key) + "</code></td><td>" +
        escapeHtml(item.type || "") + "</td><td>" + (item.ttl == null ? "—" : item.ttl) +
        "</td><td><code>" + escapeHtml(String(item.value == null ? "—" : item.value).slice(0, 60)) + "</code></td></tr>";
    }).join("");
    const queueRows = (mq.queues || []).map(function (item) {
      return "<tr><td><code>" + escapeHtml(item.name || "") + "</code></td><td>" +
        (item.messages == null ? "—" : item.messages) + "</td><td>" +
        (item.ready == null ? "—" : item.ready) + "</td><td>" +
        (item.unacked == null ? "—" : item.unacked) + "</td><td>" +
        (item.consumers == null ? "—" : item.consumers) + "</td></tr>";
    }).join("");
    const eventRows = (mq.events || []).slice(0, 8).map(function (item) {
      return "<tr><td>" + escapeHtml(item.order_id) + "</td><td>" +
        escapeHtml(item.event_type) + "</td><td><code>" + escapeHtml(item.trace_id || "") +
        '</code></td><td class="muted">' + escapeHtml(String(item.created_at || "")) + "</td></tr>";
    }).join("");
    const checks = knowledge.dbChecks || [];
    const latestChecks = checks.slice(-5).reverse().map(function (item) {
      return "<tr><td><code>" + escapeHtml(item.endpoint || "") + "</code></td><td>" +
        "<code>" + escapeHtml(item.table || "") + "</code></td><td>" +
        escapeHtml(item.case || "") + '</td><td class="muted">' +
        escapeHtml(item.at || "") + "</td></tr>";
    }).join("");
    el.statsView.innerHTML =
      tpKpis(db, redis, mq, redisCount) + tpBanner(data) +
      '<div class="tp-cards">' +
        '<div class="tp-card"><h3>数据库关系模型</h3><p class="muted">' +
          escapeHtml(db.database || "") + " · " + (db.schemas || []).join(" / ") + "</p>" +
          tpTable(["Schema", "表", "行数", "字段"], dbPreview, "数据库不可用") +
          '<a class="tp-more" href="#/thirdparty/database">查看 ' + (db.tableCount || 0) +
          ' 表与 ' + (db.fieldCount || 0) + ' 字段 →</a></div>' +
        '<div class="tp-card"><h3>Redis 实时状态</h3><p class="muted">' +
          escapeHtml(redis.host || "") + '</p><div class="check-strip">' + redisCounts + "</div>" +
          tpTable(["Key", "类型", "TTL", "值（脱敏）"], redisRows, "Redis 不可用") +
          '<a class="tp-more" href="#/thirdparty/sql">查看 SQL 与复现步骤 →</a></div>' +
      "</div>" +
      '<div class="tp-cards">' +
        '<div class="tp-card"><h3>RabbitMQ</h3>' +
          tpTable(["队列", "消息数", "Ready", "Unacked", "消费者"], queueRows, "RabbitMQ 不可用") + "</div>" +
        '<div class="tp-card"><h3>order_event_log 最新事件</h3>' +
          tpTable(["订单", "事件", "traceId", "时间"], eventRows, "暂无事件") + "</div>" +
      "</div>" +
      '<div class="chart-panel"><div class="chart-head"><strong>最近落库 SQL 证据</strong>' +
        '<span class="muted">共 ' + checks.length + ' 条</span></div>' +
        tpTable(["接口", "表", "用例", "时间"], latestChecks, "暂无证据") +
        '<a class="tp-more" href="#/thirdparty/sql">查看全部 SQL 证据 →</a></div>';
    bindTpActions();
  }

  function tpErSvg(er) {
    if (!er || !(er.nodes || []).length) {
      return '<p class="muted">暂无可推断的表关系</p>';
    }
    const width = 1080, height = er.height || 420;
    const byId = {};
    (er.nodes || []).forEach(function (node) { byId[node.id] = node; });
    const colors = { "认证与权限": "#3563e9", "商品与库存": "#1f9d61",
      "交易与履约": "#b26a00", "运营与内容": "#7a5af8", "系统": "#667085", "其他": "#667085" };
    const edges = (er.edges || []).map(function (edge) {
      const a = byId[edge.from], b = byId[edge.to];
      if (!a || !b) return "";
      const x1 = a.x + a.w, y1 = a.y + a.h / 2;
      const x2 = b.x, y2 = b.y + b.h / 2;
      const mid = (x1 + x2) / 2;
      return '<path d="M' + x1 + " " + y1 + " C" + mid + " " + y1 + " " + mid + " " +
        y2 + " " + x2 + " " + y2 + '" class="er-edge"/>' +
        '<text class="er-edge-label" x="' + mid + '" y="' + ((y1 + y2) / 2 - 3) +
        '" text-anchor="middle">' + escapeHtml(edge.fromField || "") + "</text>" +
        '<title>' + escapeHtml(edge.from + "." + edge.fromField + " → " + edge.to) + "</title>";
    }).join("");
    const nodes = (er.nodes || []).map(function (node) {
      const color = colors[node.module] || "#667085";
      return '<g class="er-node" data-er-table="' + escapeHtml(node.id) + '" tabindex="0">' +
        '<rect x="' + node.x + '" y="' + node.y + '" width="' +
        node.w + '" height="' + node.h + '" rx="8" stroke="' + color + '"/>' +
        '<text x="' + (node.x + 10) + '" y="' + (node.y + 17) + '">' +
        escapeHtml(node.label) + '</text><text class="er-module" x="' + (node.x + 10) +
        '" y="' + (node.y + 33) + '">' + escapeHtml(node.module) + "</text>" +
        '<title>' + escapeHtml(node.id) + "</title></g>";
    }).join("");
    return '<div class="er-wrap"><svg viewBox="0 0 ' + width + " " + height +
      '" class="er-svg" role="img" aria-label="数据库表关系图">' + edges + nodes + "</svg></div>";
  }

  function renderThirdpartyDatabase(data) {
    tpShell(data);
    const db = data.db || {};
    const knowledge = data.knowledge || {};
    const modules = {};
    (db.tables || []).forEach(function (table) {
      const name = table.module || "其他";
      (modules[name] = modules[name] || []).push(table);
    });
    const moduleHtml = Object.keys(modules).map(function (module) {
      const tables = modules[module].map(function (table) {
        const fields = (table.fields || []).filter(function (field) { return field.core; });
        const fieldRows = fields.map(function (field) {
          return '<tr data-tp-row data-tp-text="' + escapeHtml(
            table.schema + "." + table.name + " " + field.name + " " + (field.meaning || "")) +
            '"><td><code>' + escapeHtml(field.name) + "</code></td><td>" +
            escapeHtml(field.meaning || "") + "</td><td>" + escapeHtml(field.type) +
            "</td><td>" + (field.nullable ? "是" : "否") + "</td></tr>";
        }).join("");
        return '<details class="tp-table-block" open id="tp-table-' +
          escapeHtml((table.schema + "." + table.name).replace(/[^A-Za-z0-9]+/g, "-")) +
          '"><summary><b>' + escapeHtml(table.schema + "." + table.name) + "</b><span>" +
          (table.rows == null ? "—" : table.rows) + " 行 · " + fields.length +
          " 核心字段</span></summary>" +
          '<div class="drill-table-wrap"><table class="tp-field-table"><thead><tr>' +
          "<th>字段</th><th>含义</th><th>类型</th><th>可空</th>" +
          "</tr></thead><tbody>" + (fieldRows || '<tr><td colspan="4" class="muted">无核心字段</td></tr>') +
          "</tbody></table></div></details>";
      }).join("");
      return '<details class="tp-module-block" open><summary><b>' + escapeHtml(module) +
        "</b><span>" + modules[module].length + " 张表</span></summary>" + tables + "</details>";
    }).join("");
    const relationRows = (db.relations || []).map(function (rel) {
      return '<tr data-tp-row><td><code>' + escapeHtml(rel.from) + "</code></td><td><code>" +
        escapeHtml(rel.fromField) + "</code></td><td>→</td><td><code>" +
        escapeHtml(rel.to) + "</code></td><td>" + escapeHtml(rel.type || "") + "</td></tr>";
    }).join("");
    const mappingRows = (knowledge.apiMappings || []).map(function (item) {
      const status = item.status || (item.table ? "contract" : "not_applicable");
      const label = { covered: "已覆盖", contract: "契约无测试", missing_contract: "已映射·契约待补",
        mapped_table: "已映射（表级）", not_applicable: "不适用" }[status] || status;
      const badge = status === "covered" ? "passed" :
        status === "not_applicable" ? "skipped" : "warn";
      return '<tr data-tp-row data-tp-text="' + escapeHtml(item.endpoint + " " +
        (item.table || "") + " " + (item.locate || "")) + '"><td><code>' +
        escapeHtml(item.endpoint) + "</code></td><td>" +
        (item.table ? "<code>" + escapeHtml(item.table) + "</code>" :
          '<span class="muted">—</span>') + "</td><td>" +
        escapeHtml(item.locate || "—") + '</td><td><span class="badge ' + badge + '">' +
        label + "</span></td><td>" + (item.tests || []).length +
        '</td><td><code>' + escapeHtml(item.sqlExample || "—") + "</code></td></tr>";
    }).join("");
    el.statsView.innerHTML =
      tpKpis(db, data.redis || {}, data.mq || {}, tpRedisCount(data.redis || {})) + tpBanner(data) +
      '<div class="chart-panel"><div class="chart-head"><strong>表关系图（ER）</strong>' +
        '<span class="muted">按外键字段推断 · 核心表</span></div>' + tpErSvg(db.er) +
        '<div class="tp-er-legend"><span><i class="dot-identity"></i>认证与权限</span>' +
        '<span><i class="dot-product"></i>商品与库存</span><span><i class="dot-trade"></i>交易与履约</span></div>' +
        '<div class="drill-table-wrap tp-relation-table"><table class="drawer-table drill-table bench-table"><thead><tr>' +
          "<th>源表</th><th>字段</th><th></th><th>目标表</th><th>关系</th>" +
        "</tr></thead><tbody>" + (relationRows || '<tr><td colspan="5" class="muted">暂无外键关系</td></tr>') +
        "</tbody></table></div></div>" +
      '<div class="tp-toolbar"><input data-tp-search class="search" type="search" ' +
        'placeholder="搜索模块 / 表 / 字段 / 含义"><span class="muted" data-tp-filter-summary></span></div>' +
      '<div class="tp-modules">' + moduleHtml + "</div>" +
      '<div class="chart-panel"><div class="chart-head"><strong>接口 → 表 → SQL</strong>' +
        '<span class="muted">78 个写接口；契约待补表示已从调用链识别表，但尚未建立字段契约</span></div>' +
        tpTable(["接口", "表", "定位方式", "契约状态", "关联测试", "SQL 示例"], mappingRows, "暂无映射") + "</div>";
    bindTpActions();
    el.statsView.querySelectorAll(".er-node").forEach(function (node) {
      const jump = function () {
        const target = document.getElementById("tp-table-" +
          node.dataset.erTable.replace(/[^A-Za-z0-9]+/g, "-"));
        if (target) {
          target.open = true;
          target.scrollIntoView({ behavior: "smooth", block: "center" });
          target.classList.add("tp-highlight");
          setTimeout(function () { target.classList.remove("tp-highlight"); }, 1800);
        }
      };
      node.addEventListener("click", jump);
      node.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); jump(); }
      });
    });
  }
  function tpCommands(data, component) {
    const item = (data.reproduce || []).find(function (step) { return step.component === component; });
    if (!item) return "";
    return (item.commands || []).map(function (command) {
      return '<div class="tp-command"><code>' + escapeHtml(command) + "</code>" +
        tpCopyButton(command) + "</div>";
    }).join("");
  }

  function tpTestRows(tests) {
    return (tests || []).map(function (test) {
      return '<tr data-tp-row><td>' + escapeHtml(test.caseId || "—") + "</td><td>" +
        escapeHtml(test.name || "") + "</td><td>" + escapeHtml(test.endpoint || "") +
        "</td><td>" + statusBadge(test.status) + "</td></tr>";
    }).join("");
  }

  const TP_OPS_BASE = "http://127.0.0.1:8098";

  function tpShowResult(targetId, data) {
    const target = document.getElementById(targetId);
    if (!target) return;
    target.textContent = typeof data === "string" ? data : JSON.stringify(data, null, 2);
  }

  function tpOpsRequest(path, options, targetId) {
    tpShowResult(targetId, "请求中…");
    fetch(TP_OPS_BASE + path, options)
      .then(function (response) { return response.json(); })
      .then(function (data) { tpShowResult(targetId, data); })
      .catch(function (error) {
        tpShowResult(targetId, "操作服务不可用：" + error.message +
          "\n请先运行：.venv/bin/python scripts/thirdparty_server.py");
      });
  }

  function tpOpsStatus() {
    const node = document.getElementById("tp-ops-status");
    if (!node) return;
    fetch(TP_OPS_BASE + "/api/health")
      .then(function (response) { return response.json(); })
      .then(function (data) {
        node.textContent = "操作服务在线 · Redis " + (data.redis ? "OK" : "DOWN") +
          " · RabbitMQ " + (data.rabbitmq ? "OK" : "DOWN");
        node.className = "tp-ops-status " + (data.redis && data.rabbitmq ? "ok" : "warn");
      })
      .catch(function () {
        node.textContent = "操作服务未启动（只读模式）";
        node.className = "tp-ops-status warn";
      });
  }

  function tpBindRedisOps() {
    const get = function (id) { const node = document.getElementById(id); return node ? node.value : ""; };
    const scan = document.getElementById("tp-redis-scan");
    if (scan) scan.onclick = function () {
      tpOpsRequest("/api/redis/scan?pattern=" + encodeURIComponent(get("tp-redis-pattern") || "*"),
        {}, "tp-redis-result");
    };
    const query = document.getElementById("tp-redis-get");
    if (query) query.onclick = function () {
      tpOpsRequest("/api/redis/get?key=" + encodeURIComponent(get("tp-redis-key")), {}, "tp-redis-result");
    };
    const set = document.getElementById("tp-redis-set");
    if (set) set.onclick = function () {
      tpOpsRequest("/api/redis/set", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: get("tp-redis-key"), value: get("tp-redis-value"),
          ttl: Number(get("tp-redis-ttl") || 0) }),
      }, "tp-redis-result");
    };
    const del = document.getElementById("tp-redis-del");
    if (del) del.onclick = function () {
      if (!window.confirm("确认删除 key：" + get("tp-redis-key") + "？")) return;
      tpOpsRequest("/api/redis/delete", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: get("tp-redis-key") }),
      }, "tp-redis-result");
    };
    tpOpsStatus();
  }

  function tpBindMqOps() {
    const get = function (id) { const node = document.getElementById(id); return node ? node.value : ""; };
    const queues = document.getElementById("tp-mq-queues");
    if (queues) queues.onclick = function () {
      tpOpsRequest("/api/mq/queues", {}, "tp-mq-result");
    };
    const messages = document.getElementById("tp-mq-messages");
    if (messages) messages.onclick = function () {
      tpOpsRequest("/api/mq/messages?vhost=" + encodeURIComponent(get("tp-mq-vhost") || "/") +
        "&queue=" + encodeURIComponent(get("tp-mq-queue")) + "&count=10", {}, "tp-mq-result");
    };
    const publish = document.getElementById("tp-mq-publish");
    if (publish) publish.onclick = function () {
      let payload = get("tp-mq-payload");
      try { payload = JSON.parse(payload); } catch (error) { /* 保持字符串 */ }
      tpOpsRequest("/api/mq/publish", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ vhost: get("tp-mq-vhost") || "/", exchange: get("tp-mq-exchange"),
          routingKey: get("tp-mq-routing"), payload: payload }),
      }, "tp-mq-result");
    };
    const consume = document.getElementById("tp-mq-consume");
    if (consume) consume.onclick = function () {
      if (!window.confirm("确认从队列消费并删除 1 条消息？")) return;
      tpOpsRequest("/api/mq/consume", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ vhost: get("tp-mq-vhost") || "/", queue: get("tp-mq-queue") }),
      }, "tp-mq-result");
    };
    const purge = document.getElementById("tp-mq-purge");
    if (purge) purge.onclick = function () {
      if (!window.confirm("确认清空队列：" + get("tp-mq-queue") + "？")) return;
      tpOpsRequest("/api/mq/purge", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ vhost: get("tp-mq-vhost") || "/",
          queue: get("tp-mq-queue"), confirm: "PURGE" }),
      }, "tp-mq-result");
    };
    tpOpsStatus();
  }

  function tpTrendSvg(trend) {
    const items = (trend || []).slice(-40);
    if (!items.length) return '<p class="muted">最近 24 小时暂无事件</p>';
    const W = 980, H = 220, left = 40, bottom = 30, top = 12;
    const max = Math.max.apply(null, items.map(function (item) { return item.count || 0; }).concat([1]));
    const band = (W - left - 10) / items.length;
    const bars = items.map(function (item, index) {
      const height = (item.count || 0) / max * (H - top - bottom);
      const x = left + index * band + 2;
      return '<rect x="' + x + '" y="' + (H - bottom - height) + '" width="' +
        Math.max(2, band - 4) + '" height="' + height + '" class="mq-bar"><title>' +
        escapeHtml(item.label + " · " + item.count + " 条") + "</title></rect>";
    }).join("");
    return '<svg viewBox="0 0 ' + W + " " + H + '" class="mq-trend">' +
      '<line x1="' + left + '" y1="' + (H - bottom) + '" x2="' + (W - 10) +
      '" y2="' + (H - bottom) + '" class="grid"/>' +
      '<text x="4" y="' + (top + 10) + '">' + max + "</text>" +
      '<text x="' + left + '" y="' + (H - 10) + '">' + escapeHtml(items[0].label) + "</text>" +
      '<text x="' + (W - 10) + '" y="' + (H - 10) + '" text-anchor="end">' +
      escapeHtml(items[items.length - 1].label) + "</text>" + bars + "</svg>";
  }

  function renderThirdpartyRedis(data) {
    tpShell(data);
    const redis = data.redis || {};
    const counts = Object.keys(redis.counts || {}).map(function (pattern) {
      return '<span class="check-chip"><b>' + escapeHtml(pattern) + "</b>" +
        (redis.counts[pattern] || 0) + " keys</span>";
    }).join("");
    const rows = (redis.samples || []).map(function (item) {
      return '<tr data-tp-row><td><code>' + escapeHtml(item.key) + "</code></td><td>" +
        escapeHtml(item.type || "") + "</td><td>" + (item.ttl == null ? "—" : item.ttl) +
        "</td><td><code>" + escapeHtml(String(item.value == null ? "—" : item.value)) +
        "</code></td><td>" + escapeHtml(item.command || "") + "</td></tr>";
    }).join("");
    const mappings = (data.redisMappings || []).map(function (item) {
      const titles = (item.tests || []).map(function (test) { return test.title || test.name || ""; });
      const shown = titles.slice(0, 3).join("；") + (titles.length > 3 ? "（+" + (titles.length - 3) + "）" : "");
      return "<tr data-tp-row><td>" + escapeHtml(item.module) + "</td><td>" +
        escapeHtml(item.function) + "</td><td><code>" + escapeHtml(item.pattern) +
        '</code></td><td><div class="tp-cell-lines">' +
        (item.related || []).map(function (path) {
          return "<div><code>" + escapeHtml(path) + "</code></div>";
        }).join("") + '</div></td><td title="' + escapeHtml(titles.join("；")) +
        '"><div class="tp-cell-lines">' + (titles.length ? titles.map(function (title) {
          return "<div>" + escapeHtml(title) + "</div>";
        }).join("") : '<span class="muted">—</span>') + "</div></td></tr>";
    }).join("");
    const testCards = (data.redisTestDetails || []).map(function (test) {
      const steps = (test.steps || []).map(function (step) {
        const actualRequest = step.actualRequest || "—";
        const actualResponse = step.actualStatus
          ? "HTTP " + step.actualStatus + "\n" + (step.actualResponse || "")
          : "—";
        const redisRequest = step.redisCommand || "—";
        let redisResult = "—";
        if (step.redisTtl !== undefined && step.redisTtl !== null) {
          redisResult = "TTL=" + step.redisTtl;
        } else if (step.redisValue !== undefined && step.redisValue !== null) {
          redisResult = typeof step.redisValue === "string" ? step.redisValue :
            JSON.stringify(step.redisValue);
        }
        return "<tr><td>" + escapeHtml(step.step) + "</td><td>" +
          escapeHtml(step.action || "") + "</td><td><code>" + escapeHtml(step.key || "") +
          "</code></td><td><code>" + escapeHtml(step.command || "") +
          '</code></td><td class="tp-param-source">' + escapeHtml(step.paramSource || "") +
          '<div class="muted">' + escapeHtml(step.sourceRef || "") + "</div></td><td>" +
          escapeHtml(step.expected || "") + '</td><td><code class="tp-actual" title="' +
          escapeHtml(redisRequest) + '">' + escapeHtml(redisRequest) +
          '</code></td><td><code class="tp-actual">' + escapeHtml(redisResult.slice(0, 180)) +
          '</code></td><td><code class="tp-actual" title="' + escapeHtml(actualRequest) +
          '">' + escapeHtml(actualRequest.slice(0, 180)) +
          '</code></td><td><code class="tp-actual" title="' + escapeHtml(actualResponse) +
          '">' + escapeHtml(actualResponse.slice(0, 220)) + "</code></td></tr>";
      }).join("");
      return '<details class="tp-test-case" open><summary><b>' + escapeHtml(test.title) +
        "</b><span>" + statusBadge(test.status) + '</span><code>' +
        escapeHtml(test.endpoint || "") + '</code><span class="muted">' +
        ((test.steps || []).length) + " 个步骤</span></summary>" +
        '<div class="drill-table-wrap"><table class="tp-step-table"><thead><tr>' +
          "<th>步骤</th><th>操作</th><th>Redis Key</th><th>查询命令</th>" +
          "<th>参数来源</th><th>预期结果</th>" +
          "<th>Redis 实际请求</th><th>Redis 返回</th>" +
          "<th>API 真实请求参数</th><th>API 真实响应</th>" +
        "</tr></thead><tbody>" + steps + "</tbody></table></div>" +
        '<details class="tp-redis-actuals"><summary>Redis 实际执行记录（' +
          ((test.redisActuals || []).length) + ' 条）</summary>' +
        '<div class="drill-table-wrap"><table class="tp-step-table"><thead><tr>' +
          "<th>命令</th><th>Key</th><th>返回</th><th>TTL</th>" +
        "</tr></thead><tbody>" + (test.redisActuals || []).map(function (item) {
          const value = item.value === null || item.value === undefined ? "—" :
            (typeof item.value === "string" ? item.value : JSON.stringify(item.value));
          return "<tr><td><code>" + escapeHtml(item.command || "") + "</code></td><td><code>" +
            escapeHtml(item.key || "") + "</code></td><td><code>" +
            escapeHtml(String(value).slice(0, 200)) + "</code></td><td>" +
            (item.ttl == null ? "—" : item.ttl) + "</td></tr>";
        }).join("") + "</tbody></table></div></details>" +
        '<details class="tp-api-actuals"><summary>API 实际执行序列（' +
          ((test.actuals || []).length) + ' 条）</summary>' +
        '<div class="drill-table-wrap"><table class="tp-step-table"><thead><tr>' +
          "<th>#</th><th>方法 / 路径</th><th>请求参数</th><th>HTTP</th><th>响应</th><th>traceId</th>" +
        "</tr></thead><tbody>" + (test.actuals || []).map(function (item, index) {
          return "<tr><td>" + (index + 1) + "</td><td><code>" + escapeHtml(item.method || "") +
            " " + escapeHtml(item.path || "") + '</code></td><td><code class="tp-actual" title="' +
            escapeHtml(item.requestBody || "") + '">' +
            escapeHtml(String(item.requestBody || "").slice(0, 200)) + "</code></td><td>" +
            (item.status == null ? "—" : item.status) + '</td><td><code class="tp-actual" title="' +
            escapeHtml(item.responseBody || "") + '">' +
            escapeHtml(String(item.responseBody || "").slice(0, 240)) + "</code></td><td><code>" +
            escapeHtml(item.traceId || "") + "</code></td></tr>";
        }).join("") + "</tbody></table></div></details></details>";
    }).join("");
    const fallbackTests = '<div class="chart-panel"><div class="chart-head"><strong>相关测试用例</strong></div>' +
      tpTable(["用例", "名称", "接口", "状态"], tpTestRows((data.tests || {}).redis), "暂无 Redis 用例") + "</div>";
    el.statsView.innerHTML =
      tpKpis(data.db || {}, redis, data.mq || {}, tpRedisCount(redis)) + tpBanner(data) +
      '<div class="chart-panel"><div class="chart-head"><strong>Redis 功能映射</strong>' +
        '<span class="muted">业务模块 · 功能 · key 模式 · 相关接口（不含请求方式）</span></div>' +
        tpTable(["模块", "功能", "Key 模式", "相关接口", "相关用例标题"], mappings,
          "暂无映射", "tp-mapping-table") + "</div>" +
      '<div class="chart-panel"><div class="chart-head"><strong>Key 查询 / 写入 / 删除</strong>' +
        '<span id="tp-ops-status" class="tp-ops-status">检测操作服务…</span></div>' +
        '<div class="tp-op-grid">' +
          '<label>Pattern<input id="tp-redis-pattern" value="' +
            escapeHtml(redis.defaultPattern || "sms:phone:*") + '"></label>' +
          '<button class="detail-btn" id="tp-redis-scan">扫描</button>' +
          '<label>Key（默认取当前真实存在的 key）<input id="tp-redis-key" value="' +
            escapeHtml(redis.defaultKey || "") + '" placeholder="' +
            (redis.defaultKey ? "" : "当前无 key，请先写入") + '"></label>' +
          '<button class="detail-btn" id="tp-redis-get">读取</button>' +
          '<label>Value<input id="tp-redis-value" placeholder="写入值"></label>' +
          '<label>TTL（秒）<input id="tp-redis-ttl" type="number" value="300"></label>' +
          '<button class="detail-btn" id="tp-redis-set">写入</button>' +
          '<button class="detail-btn danger" id="tp-redis-del">删除</button>' +
        "</div>" +
        '<pre id="tp-redis-result" class="tp-op-result">操作结果将在这里显示</pre></div>' +
      '<div class="chart-panel"><div class="chart-head"><strong>Redis 键分布</strong>' +
        '<span class="muted">' + escapeHtml(redis.host || "") + "</span></div>" +
        '<div class="check-strip">' + (counts || '<span class="muted">暂无 key</span>') + "</div>" +
        tpTable(["Key", "类型", "TTL", "值（脱敏）", "查询命令"], rows, "Redis 不可用") + "</div>" +
      '<div class="chart-panel"><div class="chart-head"><strong>相关测试用例与 Redis 校验步骤</strong>' +
        '<span class="muted">每个用例一行，展开查看 key 与预期结果</span></div>' +
        (testCards || '<p class="muted">暂无 Redis 步骤数据</p>') + "</div>" +
      (testCards ? "" : fallbackTests) +
      '<div class="chart-panel"><div class="chart-head"><strong>手工核验命令</strong></div>' +
        '<div class="tp-commands">' + (tpCommands(data, "Redis") || '<span class="muted">无命令</span>') + "</div></div>" +
      '<div class="chart-panel"><div class="chart-head"><strong>判定标准</strong></div>' +
        '<ul class="suggest-list"><li>验证码 TTL 240–300s；冷却 ≤60s；</li>' +
        "<li>连续 5 次失败后 `login:fail:*` 存在且 TTL ≤900s；</li>" +
        "<li>`jwt:blacklist:*` 的 TTL 应大于 0；</li>" +
        "<li>页面只读数字与 SCAN/GET 结果不一致时，以命令结果为准。</li></ul></div>";
    bindTpActions();
    tpBindRedisOps();
  }
  function renderThirdpartyMq(data) {
    tpShell(data);
    const mq = data.mq || {};
    const queueRows = (mq.queues || []).map(function (item) {
      return '<tr data-tp-row><td><code>' + escapeHtml(item.name || "") + "</code></td><td>" +
        (item.messages == null ? "—" : item.messages) + "</td><td>" +
        (item.ready == null ? "—" : item.ready) + "</td><td>" +
        (item.unacked == null ? "—" : item.unacked) + "</td><td>" +
        (item.consumers == null ? "—" : item.consumers) + "</td></tr>";
    }).join("");
    const eventRows = (mq.events || []).map(function (item) {
      return "<tr data-tp-row><td>" + escapeHtml(item.order_id) + "</td><td>" +
        escapeHtml(item.event_type) + "</td><td><code>" + escapeHtml(item.trace_id || "") +
        '</code></td><td class="muted">' + escapeHtml(String(item.created_at || "")) +
        "</td><td><code>" + escapeHtml(String(item.payload || "").slice(0, 180)) + "</code></td></tr>";
    }).join("");
    const mappings = (data.mqMappings || []).map(function (item) {
      const titles = (item.tests || []).map(function (test) { return test.title || test.name || ""; });
      return "<tr data-tp-row><td>" + escapeHtml(item.module) + "</td><td>" +
        escapeHtml(item.function) + '</td><td><div class="tp-cell-lines"><div><code>' +
        escapeHtml(item.exchange) + "</code></div></div></td>" +
        '<td><div class="tp-cell-lines"><div><code>' + escapeHtml(item.routingKey) +
        "</code></div></div></td><td><div class=\"tp-cell-lines\"><div><code>" +
        escapeHtml(item.queue) + '</code></div></div></td><td><div class="tp-cell-lines">' +
        (item.related || []).map(function (path) {
          return "<div><code>" + escapeHtml(path) + "</code></div>";
        }).join("") + '</div></td><td><div class="tp-cell-lines">' +
        (titles.length ? titles.map(function (title) {
          return "<div>" + escapeHtml(title) + "</div>";
        }).join("") : '<span class="muted">—</span>') + "</div></td><td>" +
        tpLongCell(typeof item.payloadSample === "string"
          ? item.payloadSample : JSON.stringify(item.payloadSample || {}),
          "Payload 示例" + (item.payloadSource ? " · " + item.payloadSource : "")) +
        "</td></tr>";
    }).join("");
    const testCards = (data.mqTestDetails || []).map(function (test) {
      const steps = (test.steps || []).map(function (step) {
        const actualRequest = step.apiRequest || "—";
        const actualResponse = step.apiResponse || "—";
        const trace = [
          step.apiTraceId ? "API " + step.apiTraceId : "",
          step.mqTraceId ? "MQ " + step.mqTraceId : "",
        ].filter(Boolean).join(" / ") || step.traceNote || "—";
        return "<tr><td>" + escapeHtml(step.step) + "</td><td>" +
          escapeHtml(step.action || "") + '</td><td class="tp-param-source">' +
          escapeHtml(step.paramSource || "") + '<div class="muted">' +
          escapeHtml(step.sourceRef || "") + "</div></td><td>" + escapeHtml(step.expected || "") +
          "</td><td>" + tpLongCell(step.mqRequest, "MQ 实际请求 / Body") +
          "</td><td>" + tpLongCell(step.mqResult, "MQ 返回") +
          "</td><td>" + tpLongCell(actualRequest, "API 真实请求参数") +
          "</td><td>" + tpLongCell(actualResponse, "API 真实响应") +
          '</td><td><code class="tp-trace">' + escapeHtml(trace) + "</code></td></tr>";
      }).join("");
      const apiActuals = (test.actuals || []).map(function (item, index) {
        return "<tr><td>" + (index + 1) + "</td><td><code>" + escapeHtml(item.method || "") +
          " " + escapeHtml(item.path || "") + "</code></td><td><code>" +
          escapeHtml(String(item.requestBody || "").slice(0, 200)) + "</code></td><td>" +
          (item.status == null ? "—" : item.status) + "</td><td><code>" +
          escapeHtml(String(item.responseBody || "").slice(0, 240)) + "</code></td><td><code>" +
          escapeHtml(item.traceId || "") + "</code></td></tr>";
      }).join("");
      const events = (test.events || []).map(function (item) {
        return "<tr><td>" + escapeHtml(item.order_id) + "</td><td>" +
          escapeHtml(item.event_type) + "</td><td><code>" + escapeHtml(item.trace_id || "") +
          '</code></td><td class="muted">' + escapeHtml(String(item.created_at || "")) +
          "</td></tr>";
      }).join("");
      return '<details class="tp-test-case" open><summary><b>' + escapeHtml(test.title) +
        "</b><span>" + statusBadge(test.status) + '</span><code>' +
        escapeHtml(test.endpoint || "") + '</code><span class="muted">' +
        ((test.steps || []).length) + " 个步骤</span></summary>" +
        '<div class="drill-table-wrap"><table class="tp-step-table"><thead><tr>' +
          "<th>步骤</th><th>操作</th><th>参数来源</th><th>预期结果</th>" +
          "<th>MQ 实际请求 / Body</th><th>MQ 返回</th><th>API 真实请求参数</th>" +
          "<th>API 真实响应</th><th>traceId</th>" +
        "</tr></thead><tbody>" + steps + "</tbody></table></div>" +
        ((test.actuals || []).length ? '<details class="tp-api-actuals"><summary>API 实际执行序列（' +
          test.actuals.length + ' 条）</summary><div class="drill-table-wrap">' +
          '<table class="tp-step-table"><thead><tr><th>#</th><th>方法 / 路径</th><th>请求参数</th>' +
          '<th>HTTP</th><th>响应</th><th>traceId</th></tr></thead><tbody>' + apiActuals +
          "</tbody></table></div></details>" : "") +
        ((test.events || []).length ? '<details class="tp-redis-actuals"><summary>order_event_log 实际事件（' +
          test.events.length + ' 条）</summary><div class="drill-table-wrap">' +
          '<table class="tp-step-table"><thead><tr><th>订单</th><th>事件</th><th>traceId</th>' +
          '<th>时间</th></tr></thead><tbody>' + events + "</tbody></table></div></details>" : "") +
        '<details class="tp-mq-actuals"><summary>当前队列观测（' +
          ((data.mq.queues || []).length) + ' 个队列）</summary><div class="drill-table-wrap">' +
          '<table class="tp-step-table"><thead><tr><th>队列</th><th>消息数</th><th>Ready</th>' +
          '<th>Unacked</th><th>消费者</th></tr></thead><tbody>' +
          (data.mq.queues || []).map(function (queue) {
            return "<tr><td><code>" + escapeHtml(queue.name || "") + "</code></td><td>" +
              (queue.messages == null ? "—" : queue.messages) + "</td><td>" +
              (queue.ready == null ? "—" : queue.ready) + "</td><td>" +
              (queue.unacked == null ? "—" : queue.unacked) + "</td><td>" +
              (queue.consumers == null ? "—" : queue.consumers) + "</td></tr>";
          }).join("") + "</tbody></table></div></details>" +
        "</details>";
    }).join("");
    const sample = JSON.stringify({
      eventId: "demo-ORDER_PAID", eventType: "ORDER_PAID", orderId: "0",
      amount: "0.00", paidAt: new Date().toISOString(), traceId: "manual-check",
    }, null, 2);
    el.statsView.innerHTML =
      tpKpis(data.db || {}, data.redis || {}, mq, tpRedisCount(data.redis || {})) + tpBanner(data) +
      '<div class="chart-panel"><div class="chart-head"><strong>MQ 功能映射</strong>' +
        '<span class="muted">模块 · 功能 · Topic/Routing · Queue · 接口（不含请求方式）· 用例标题</span></div>' +
        tpTable(["模块", "功能", "Exchange", "Routing Key", "Queue", "相关接口", "相关用例标题", "Payload 示例"],
          mappings, "暂无映射", "tp-mapping-table") + "</div>" +
      '<div class="chart-panel"><div class="chart-head"><strong>请求趋势（order_event_log，最近 24 小时）</strong></div>' +
        tpTrendSvg(mq.trend) + "</div>" +
      '<div class="chart-panel"><div class="chart-head"><strong>相关测试用例与 MQ 校验步骤</strong>' +
        '<span class="muted">每个用例一行，展开查看实际事件与参数来源</span></div>' +
        (testCards || '<p class="muted">暂无 MQ 步骤数据</p>') + "</div>" +
      '<div class="chart-panel"><div class="chart-head"><strong>MQ 查询 / 发布 / 拉取 / 清空</strong>' +
        '<span id="tp-ops-status" class="tp-ops-status">检测操作服务…</span></div>' +
        '<div class="tp-op-grid">' +
          '<label>Namespace / VHost<input id="tp-mq-vhost" value="/"></label>' +
          '<label>Exchange / Topic<input id="tp-mq-exchange" value="commerce.order.event"></label>' +
          '<label>Routing Key<input id="tp-mq-routing" value="order.paid"></label>' +
          '<label>Queue<input id="tp-mq-queue" value="commerce.order.event.queue"></label>' +
          '<label class="wide">Payload<textarea id="tp-mq-payload" rows="6">' + escapeHtml(sample) + "</textarea></label>" +
          '<button class="detail-btn" id="tp-mq-queues">查询队列</button>' +
          '<button class="detail-btn" id="tp-mq-messages">拉取消息（不删除）</button>' +
          '<button class="detail-btn" id="tp-mq-consume">消费并删除 1 条</button>' +
          '<button class="detail-btn" id="tp-mq-publish">发布</button>' +
          '<button class="detail-btn danger" id="tp-mq-purge">清空队列</button>' +
        "</div>" +
        '<pre id="tp-mq-result" class="tp-op-result">操作结果将在这里显示</pre></div>' +
      '<div class="chart-panel"><div class="chart-head"><strong>队列状态</strong>' +
        '<span class="muted">' + escapeHtml(mq.base || "") + " · v" + escapeHtml(mq.version || "-") + "</span></div>" +
        tpTable(["队列", "消息数", "Ready", "Unacked", "消费者"], queueRows, "RabbitMQ 不可用") + "</div>" +
      '<div class="chart-panel"><div class="chart-head"><strong>order_event_log</strong>' +
        '<span class="muted">共 ' + (mq.eventCount || 0) + " 条，展示最新 20 条</span></div>" +
        tpTable(["订单", "事件", "traceId", "时间", "payload"], eventRows, "暂无事件") + "</div>" +
      '<div class="chart-panel"><div class="chart-head"><strong>手工核验命令</strong></div>' +
        '<div class="tp-commands">' + (tpCommands(data, "RabbitMQ") || '<span class="muted">无命令</span>') + "</div></div>" +
      '<div class="chart-panel"><div class="chart-head"><strong>判定标准</strong></div>' +
        '<ul class="suggest-list"><li>队列 messages/unacked 与消费者状态合理；</li>' +
        "<li>每笔支付成功应有一条 ORDER_PAID 事件；</li>" +
        "<li>重复投递后事件表仍只有 1 行；</li>" +
        "<li>非法事件进入 DLQ；</li>" +
        "<li>清空队列前必须输入确认，页面不会自动执行。</li></ul></div>";
    bindTpActions();
    tpBindMqOps();
    bindTpLongCells();
  }
  function renderThirdpartySql(data) {
    tpShell(data);
    const checks = (data.knowledge || {}).dbChecks || [];
    const rows = checks.slice().reverse().map(function (item) {
      const rowText = JSON.stringify(item.row || {});
      return '<tr data-tp-row><td><code>' + escapeHtml(item.endpoint || "") + "</code></td><td>" +
        "<code>" + escapeHtml(item.table || "") + "</code></td><td>" +
        escapeHtml(item.case || "") + '</td><td class="muted">' +
        escapeHtml(item.at || "") + "</td><td><code>" + escapeHtml(item.sql || "") +
        "</code><br><span class=\"muted\">" + escapeHtml(JSON.stringify(item.params || [])) +
        "</span></td><td><code>" + escapeHtml(rowText.slice(0, 360)) +
        (rowText.length > 360 ? "…" : "") + "</code>" +
        '<div class="tp-copy-row">' + tpCopyButton(item.sql + "\n-- params: " + JSON.stringify(item.params || [])) + "</div></td></tr>";
    }).join("");
    el.statsView.innerHTML =
      tpKpis(data.db || {}, data.redis || {}, data.mq || {}, tpRedisCount(data.redis || {})) + tpBanner(data) +
      '<div class="tp-toolbar"><input data-tp-search class="search" type="search" ' +
        'placeholder="搜索接口 / 表 / 用例 / SQL"><span class="muted" data-tp-filter-summary></span></div>' +
      '<div class="chart-panel"><div class="chart-head"><strong>落库 SQL 证据</strong>' +
        '<span class="muted">共 ' + checks.length + " 条 · db_contract 实际执行</span></div>" +
        tpTable(["接口", "表", "用例", "时间", "SQL / 参数", "结果行"], rows, "暂无 SQL 证据") + "</div>";
    bindTpActions();
  }

  function renderThirdpartyRepro(data) {
    tpShell(data);
    const steps = data.reproduce || [];
    const cards = steps.map(function (item) {
      const commands = (item.commands || []).map(function (command) {
        return '<div class="tp-command"><code>' + escapeHtml(command) + "</code>" +
          tpCopyButton(command) + "</div>";
      }).join("");
      return '<div class="tp-repro-item"><strong>' + escapeHtml(item.component) + "</strong>" +
        '<p class="muted">' + escapeHtml(item.goal || "") + "</p>" +
        '<div class="tp-commands">' + commands + "</div></div>";
    }).join("");
    el.statsView.innerHTML =
      tpKpis(data.db || {}, data.redis || {}, data.mq || {}, tpRedisCount(data.redis || {})) + tpBanner(data) +
      '<div class="chart-panel"><div class="chart-head"><strong>手工复现与核验</strong>' +
        '<span class="muted">先执行命令，再对照总览/SQL 证据中的数据</span></div>' +
        '<div class="tp-reproduce">' + cards + "</div></div>" +
      '<div class="chart-panel"><div class="chart-head"><strong>判定标准</strong></div>' +
        '<ul class="suggest-list"><li>DB：页面 SQL 与结果必须能在 psql 复现；</li>' +
        "<li>Redis：SCAN 到的 key、TTL 与页面一致；</li>" +
        "<li>MQ：队列 depth 与 order_event_log 行一致；</li>" +
        "<li>所有数据带采集时间与 runId，不接受无来源数字。</li></ul></div>";
    bindTpActions();
  }

  function compareRows(items, empty) {
    if (!items || !items.length) return '<tr><td colspan="3" class="muted">' + escapeHtml(empty) + "</td></tr>";
    return items.map(function (item) {
      return "<tr><td>" + escapeHtml(item.case_id || "—") + "</td><td>" +
        escapeHtml(item.title || item.nodeid || "") + "</td><td>" +
        statusBadge(item.status || "unknown") + "</td></tr>";
    }).join("");
  }

  function cmpDonut(title, run) {
    const passed = Number(run.passed || 0);
    const failed = Number(run.failed || 0);
    const skipped = Number(run.skipped || 0);
    const total = Number(run.total || passed + failed + skipped);
    if (!total) {
      return '<div class="cmp2-donut-card"><div class="cmp2-donut-head">' +
        escapeHtml(title) + "</div><p class=\"muted\">无数据</p></div>";
    }
    const pct = function (value) { return value / total * 100; };
    const p = pct(passed);
    const f = pct(failed);
    const s = pct(skipped);
    const gradient = "conic-gradient(var(--pass) 0 " + p.toFixed(2) + "%, var(--fail) " +
      p.toFixed(2) + "% " + (p + f).toFixed(2) + "%, var(--skip) " +
      (p + f).toFixed(2) + "% 100%)";
    const legend = [
      ["通过", passed, p, "pass"],
      ["失败", failed, f, "fail"],
      ["跳过", skipped, s, "skip"],
    ].map(function (item) {
      return '<span class="cmp2-legend-item"><i class="' + item[3] + '"></i>' +
        item[0] + " <b>" + item[1] + "</b>（" + item[2].toFixed(1) + "%）</span>";
    }).join("");
    return '<div class="cmp2-donut-card">' +
      '<div class="cmp2-donut-head">' + escapeHtml(title) + "</div>" +
      '<div class="cmp2-donut" style="background:' + gradient + '">' +
        '<div class="cmp2-donut-hole"><b>' + p.toFixed(1) + "%</b><span>通过率</span></div></div>" +
      '<div class="cmp2-donut-total">共 ' + total + " 条</div>" +
      '<div class="cmp2-legend">' + legend + "</div></div>";
  }

  function cmpMetric(label, pair, options) {
    const opts = options || {};
    const digits = opts.digits == null ? 0 : opts.digits;
    const suffix = opts.suffix || "";
    const values = (pair || []).map(function (value) {
      return value == null ? null : Number(value);
    });
    const known = values.filter(function (value) { return value != null; });
    const max = opts.max || Math.max.apply(null, known.concat([1]));
    const before = values[0];
    const after = values[1];
    let delta = "—";
    if (before != null && after != null) {
      const diff = after - before;
      delta = (diff > 0 ? "+" : "") + diff.toFixed(digits) + suffix;
    }
    let deltaClass = "muted";
    if (before != null && after != null) {
      const diff = after - before;
      if (Math.abs(diff) > 0.0001) {
        const good = opts.lowerBetter ? diff < 0 : diff > 0;
        deltaClass = good ? "pass" : "fail";
      }
    }
    const rows = [
      ["基线", before, "base"],
      ["本轮", after, "current"],
    ].map(function (item) {
      const value = item[1];
      const width = value == null ? 0 : Math.min(100, Math.max(0, value / max * 100));
      return '<div class="cmp2-bar-row"><span class="cmp2-bar-name">' + item[0] + "</span>" +
        '<div class="cmp2-track"><span class="cmp2-fill ' + item[2] + '" style="width:' +
          width.toFixed(1) + '%"></span></div><b>' +
          (value == null ? "—" : value.toFixed(digits) + suffix) + "</b></div>";
    }).join("");
    return '<div class="cmp2-metric"><div class="cmp2-metric-head"><strong>' +
      escapeHtml(label) + '</strong><span class="cmp2-delta ' + deltaClass + '">' +
      delta + "</span></div>" + rows + "</div>";
  }

  function cmpFailureChart(modules) {
    const items = (modules || []).filter(function (item) {
      return Number(item.failed || 0) > 0;
    }).slice(0, 8);
    if (!items.length) {
      return '<div class="chart-panel"><div class="chart-head"><strong>失败业务模块分布</strong></div>' +
        '<p class="muted">本轮没有失败用例。</p></div>';
    }
    const max = Math.max.apply(null, items.map(function (item) { return Number(item.failed || 0); }).concat([1]));
    const rows = items.map(function (item) {
      const failed = Number(item.failed || 0);
      return '<div class="cmp2-module-row" title="' + escapeHtml(item.module + "：失败 " +
        failed + " / " + item.total + "，失败率 " + item.failRate + "%") + '">' +
        '<span class="cmp2-module-name">' + escapeHtml(item.module) + "</span>" +
        '<div class="cmp2-track"><span class="cmp2-fill fail" style="width:' +
          (failed / max * 100).toFixed(1) + '%"></span></div>' +
        '<b>' + failed + "</b><span class=\"muted\">/" + item.total + " · " +
          item.failRate + "%</span></div>";
    }).join("");
    return '<div class="chart-panel"><div class="chart-head"><strong>失败业务模块分布</strong>' +
      '<span class="muted">按本轮失败数排序；明细可在“接口列表 / 缺陷”中继续下钻</span></div>' +
      '<div class="cmp2-module-chart">' + rows + "</div></div>";
  }

  function renderCompareInsights(insights) {
    if (!insights) return "";
    const level = insights.riskLevel || "low";
    const levelText = {high: "高", medium: "中", low: "低"}[level] || level;
    const risks = (insights.risks || []).map(function (item) {
      const itemLevel = item.level || "low";
      return '<div class="cmp2-risk-item ' + escapeHtml(itemLevel) + '">' +
        '<div class="cmp2-risk-title"><span class="cmp2-risk-dot"></span>' +
          escapeHtml(item.title || "") + "</div>" +
        '<p>' + escapeHtml(item.detail || "") + "</p>" +
        (item.evidence ? '<div class="cmp2-evidence">证据：' + escapeHtml(item.evidence) + "</div>" : "") +
        (item.action ? '<div class="cmp2-action">建议：' + escapeHtml(item.action) + "</div>" : "") +
        "</div>";
    }).join("");
    const focus = (insights.focus || []).map(function (item) {
      return '<li><b>' + escapeHtml(item.title || "") + "</b>" +
        (item.count != null ? ' <span class="badge skipped">' + item.count + "</span>" : "") +
        "<br><span>" + escapeHtml(item.detail || "") + "</span></li>";
    }).join("");
    const suggestions = (insights.suggestions || []).map(function (item) {
      return "<li>" + escapeHtml(item) + "</li>";
    }).join("");
    return '<div class="cmp2-verdict ' + escapeHtml(level) + '">' +
        '<div><span class="cmp2-verdict-label">版本结论</span>&nbsp;' +
          escapeHtml(insights.verdict || "") + "</div>" +
        '<span class="cmp2-level">风险等级：' + levelText + "</span></div>" +
      '<div class="cmp2-insight-grid">' +
        '<div class="cmp2-insight-card"><h3>风险点</h3>' +
          (risks || '<p class="muted">未发现阻断性风险。</p>') + "</div>" +
        '<div class="cmp2-insight-card"><h3>测试关注点</h3>' +
          (focus ? "<ul>" + focus + "</ul>" : '<p class="muted">暂无额外关注点。</p>') + "</div>" +
        '<div class="cmp2-insight-card"><h3>下一步建议</h3>' +
          (suggestions ? "<ol>" + suggestions + "</ol>" : '<p class="muted">保持当前基线。</p>') + "</div>" +
      "</div>";
  }

  function comparePair(label, pair, suffix, digits) {
    const before = pair && pair[0] != null ? Number(pair[0]) : null;
    const after = pair && pair[1] != null ? Number(pair[1]) : null;
    let delta = "—";
    if (before != null && after != null) {
      const value = after - before;
      delta = (value > 0 ? "+" : "") + value.toFixed(digits == null ? 0 : digits) +
        (suffix || "");
    }
    const cls = delta === "—" ? "muted" : (delta.indexOf("-") === 0 ? "pass" : "fail");
    return "<tr><td>" + label + "</td><td>" + (before == null ? "—" : before.toFixed(digits || 0)) +
      "</td><td>" + (after == null ? "—" : after.toFixed(digits || 0)) + "</td><td class=\"" +
      cls + "\">" + delta + "</td></tr>";
  }

  function renderCompareView(data) {
    el.toolbar.hidden = true;
    el.reconcileBox.hidden = true;
    el.tableBox.hidden = true;
    el.stats.hidden = true;
    el.statsView.hidden = false;
    const base = data.baseline || {};
    const current = data.current || {};
    const totals = data.totals || {};
    const diff = data.diff || {};
    const counts = diff.counts || {};
    const comparator = data.comparability || {};
    const comparable = comparator.sameCommit && comparator.sameEnv && comparator.complete;
    const rate = function (run) {
      const total = Number(run.total || 0);
      return total ? (Number(run.passed || 0) / total * 100).toFixed(1) + "%" : "—";
    };
    const warning = comparable ? "" :
      '<div class="compare-warning">⚠ 两轮 commit/env/完整性不一致，覆盖率与性能差异仅供参考。</div>';
    const wallTotals = totals.wallSeconds || [];
    const wallPair = [wallTotals[0] ? wallTotals[0] : null, wallTotals[1] ? wallTotals[1] : null];
    const known = data.knownFailures || {};
    const knownStrip = known.knownCount == null ? "" :
      '<div class="cmp2-known">' +
        '<span class="cmp2-known-title">已知失败台账</span>' +
        '<span>已知 <b>' + (known.knownCount || 0) + "</b></span>" +
        '<span class="cmp2-known-ok">未登记 <b>' + (known.unexpectedCount || 0) + "</b></span>" +
        '<span class="cmp2-known-warn">过期 <b>' + (known.expiredCount || 0) + "</b></span>" +
        '<span>待清理 <b>' + (known.fixedCount || 0) + "</b></span>" +
        '<span class="muted">待缺陷归因 ' + (known.unmappedCount || 0) + "</span>" +
      "</div>";
    const passRate = function (run) {
      const total = Number(run.total || 0);
      return total ? Number(run.passed || 0) / total * 100 : null;
    };
    const lineRatePair = (totals.lineRate || [null, null]).map(function (value) {
      return value == null ? null : Number(value) * 100;
    });
    const charts =
      '<div class="chart-panel"><div class="chart-head"><strong>通过 / 失败 / 跳过构成</strong>' +
        '<span class="muted">同一用例口径；绿色为通过、红色为失败、黄色为跳过</span></div>' +
        '<div class="cmp2-donut-grid">' +
          cmpDonut("基线 " + (base.run_id || "-"), base) +
          cmpDonut("本轮 " + (current.run_id || "-"), current) +
        "</div></div>" +
      '<div class="chart-panel"><div class="chart-head"><strong>关键指标对比</strong>' +
        '<span class="muted">条形长度按两轮最大值归一化；百分比指标按 100% 显示</span></div>' +
        '<div class="cmp2-metrics">' +
          cmpMetric("通过率", [passRate(base), passRate(current)], {suffix: "%", digits: 1, max: 100}) +
          cmpMetric("失败数", totals.failed, {digits: 0, lowerBetter: true}) +
          cmpMetric("接口覆盖率", totals.interfaceRate, {suffix: "%", digits: 1, max: 100}) +
          cmpMetric("DB 落库断言率", totals.dbRate, {suffix: "%", digits: 1, max: 100}) +
          cmpMetric("方法覆盖率", totals.methodRate, {suffix: "%", digits: 1, max: 100}) +
          cmpMetric("行覆盖率", lineRatePair, {suffix: "%", digits: 1, max: 100}) +
          cmpMetric("总耗时", wallPair, {suffix: "s", digits: 1, lowerBetter: true}) +
        "</div></div>" +
      cmpFailureChart(data.moduleStats || []) +
      renderCompareInsights(data.insights || {});
    const transitions = Object.keys(diff.transitions || {}).map(function (key) {
      const parts = key.split("->");
      return "<tr><td>" + escapeHtml(parts[0]) + "</td><td>" + escapeHtml(parts[1]) +
        "</td><td>" + diff.transitions[key] + "</td></tr>";
    }).join("");
    el.statsView.innerHTML =
      '<div class="stats-kpi">' +
        kpiCard(rate(current), "本轮通过率") +
        kpiCard((counts.newFailures || 0) + " / " + (counts.fixed || 0), "新增失败 / 修复", (counts.newFailures || 0) > 0) +
        kpiCard(rate(base) + " → " + rate(current), "基线 → 本轮") +
        kpiCard(current.line_rate == null ? "—" : (current.line_rate * 100).toFixed(1) + "%", "本轮行覆盖") +
      "</div>" +
      '<p class="muted stats-note">基线 <b>' + escapeHtml(base.run_id || "-") +
        "</b>（" + escapeHtml(base.commit || "-") + " / " + escapeHtml(base.env || "-") +
        "） → 本轮 <b>" + escapeHtml(current.run_id || "-") + "</b>（" +
        escapeHtml(current.commit || "-") + " / " + escapeHtml(current.env || "-") + "）</p>" +
      warning +
      knownStrip +
      charts +
      '<div class="chart-panel"><div class="chart-head"><strong>结果差异</strong></div>' +
        '<div class="drill-table-wrap"><table class="drawer-table drill-table bench-table"><thead><tr>' +
          "<th>指标</th><th>基线</th><th>本轮</th><th>变化</th>" +
        "</tr></thead><tbody>" +
          comparePair("通过", totals.passed) +
          comparePair("失败", totals.failed) +
          comparePair("跳过", totals.skipped) +
          comparePair("总数", totals.total) +
          comparePair("接口覆盖率 %", totals.interfaceRate, "pp", 1) +
          comparePair("DB 断言率 %", totals.dbRate, "pp", 1) +
          comparePair("方法覆盖率 %", totals.methodRate, "pp", 1) +
          comparePair("行覆盖率 %", [totals.lineRate && totals.lineRate[0] * 100,
            totals.lineRate && totals.lineRate[1] * 100], "pp", 1) +
          comparePair("总耗时 s", wallPair, "s", 1) +
        "</tbody></table></div></div>" +
      '<div class="tp-cards">' +
        '<div class="tp-card"><h3>新增失败（' + (counts.newFailures || 0) + '）</h3>' +
          '<div class="drill-table-wrap"><table class="drawer-table drill-table bench-table"><thead><tr>' +
          "<th>用例</th><th>标题</th><th>状态</th></tr></thead><tbody>" +
          compareRows(diff.newFailures, "无新增失败") + "</tbody></table></div></div>" +
        '<div class="tp-card"><h3>修复（' + (counts.fixed || 0) + '）</h3>' +
          '<div class="drill-table-wrap"><table class="drawer-table drill-table bench-table"><thead><tr>' +
          "<th>用例</th><th>标题</th><th>状态</th></tr></thead><tbody>" +
          compareRows(diff.fixed, "无修复") + "</tbody></table></div></div>" +
      "</div>" +
      '<div class="tp-cards">' +
        '<div class="tp-card"><h3>新增用例（' + (counts.added || 0) + '）</h3>' +
          '<div class="drill-table-wrap"><table class="drawer-table drill-table bench-table"><thead><tr>' +
          "<th>用例</th><th>标题</th><th>状态</th></tr></thead><tbody>" +
          compareRows(diff.added, "无新增") + "</tbody></table></div></div>" +
        '<div class="tp-card"><h3>删除/退役（' + (counts.removed || 0) + '）</h3>' +
          '<div class="drill-table-wrap"><table class="drawer-table drill-table bench-table"><thead><tr>' +
          "<th>用例</th><th>标题</th><th>状态</th></tr></thead><tbody>" +
          compareRows(diff.removed, "无删除") + "</tbody></table></div></div>" +
      "</div>" +
      '<div class="chart-panel"><div class="chart-head"><strong>结果迁移</strong></div>' +
        '<div class="drill-table-wrap"><table class="drawer-table drill-table bench-table"><thead><tr>' +
          "<th>基线状态</th><th>本轮状态</th><th>数量</th>" +
        "</tr></thead><tbody>" + (transitions || '<tr><td colspan="3" class="muted">无迁移</td></tr>') +
        "</tbody></table></div></div>";
  }

  function trendSvg(runs, field, label, scale) {
    const items = runs.map(function (run) {
      return {run: run, value: run[field] == null ? null : Number(run[field])};
    }).filter(function (item) { return item.value != null; });
    if (!items.length) return '<p class="muted">暂无趋势数据</p>';
    const W = 900, H = 220, left = 50, right = 16, top = 16, bottom = 36;
    const values = items.map(function (item) { return item.value; });
    let max = Math.max.apply(null, values);
    let min = Math.min.apply(null, values);
    const pad = max === min ? Math.abs(max * 0.1) || 1 : (max - min) * 0.15;
    max += pad;
    min = Math.max(0, min - pad);
    const span = max - min || 1;
    const stepX = (W - left - right) / Math.max(1, items.length - 1);
    const points = items.map(function (item, index) {
      const x = left + index * stepX;
      const y = top + (max - item.value) / span * (H - top - bottom);
      return {x: x, y: y, item: item};
    });
    const line = points.map(function (point, index) {
      return (index ? "L" : "M") + point.x.toFixed(1) + " " + point.y.toFixed(1);
    }).join(" ");
    const dots = points.map(function (point) {
      return '<circle cx="' + point.x + '" cy="' + point.y + '" r="3" class="trend-dot"><title>' +
        escapeHtml(point.item.run.run_id + " · " + point.item.run.started_at + " · " +
          point.item.value + (scale || "")) + "</title></circle>";
    }).join("");
    return '<div class="trend-chart"><div class="trend-title">' + escapeHtml(label) + "</div>" +
      '<svg viewBox="0 0 ' + W + " " + H + '" class="trend-svg">' +
      '<line x1="' + left + '" y1="' + (H - bottom) + '" x2="' + (W - right) +
      '" y2="' + (H - bottom) + '" class="grid"/>' +
      '<text x="4" y="' + (top + 8) + '">' + max.toFixed(1) + "</text>" +
      '<text x="4" y="' + (H - bottom) + '">' + min.toFixed(1) + "</text>" +
      '<path d="' + line + '" class="trend-line"/>' + dots + "</svg></div>";
  }

  function renderCompareTrend(data) {
    el.toolbar.hidden = true;
    el.reconcileBox.hidden = true;
    el.tableBox.hidden = true;
    el.stats.hidden = true;
    el.statsView.hidden = false;
    const runs = (data.runs || []).filter(function (run) { return run.complete; })
      .sort(function (a, b) { return (a.started_at || "").localeCompare(b.started_at || ""); })
      .slice(-20);
    const rows = runs.slice().reverse().map(function (run) {
      return "<tr><td>" + escapeHtml(run.run_id) + "</td><td>" + escapeHtml(run.started_at) +
        "</td><td>" + escapeHtml(run.commit || "-") + "</td><td>" + (run.total || 0) +
        "</td><td>" + (run.failed || 0) + "</td><td>" +
        (run.line_rate == null ? "—" : (run.line_rate * 100).toFixed(1) + "%") +
        "</td><td>" + (run.wall_seconds ? run.wall_seconds + "s" : "—") + "</td></tr>";
    }).join("");
    el.statsView.innerHTML =
      '<div class="stats-kpi">' +
        kpiCard(runs.length, "完整运行轮次") +
        kpiCard(runs.length ? runs[runs.length - 1].failed : "—", "最新失败数", true) +
        kpiCard(runs.length && runs[runs.length - 1].line_rate != null
          ? (runs[runs.length - 1].line_rate * 100).toFixed(1) + "%" : "—", "最新行覆盖") +
      "</div>" +
      '<p class="muted stats-note">仅统计 complete=true 的运行；趋势按 started_at 升序，最近 20 轮。</p>' +
      '<div class="chart-panel"><div class="chart-head"><strong>失败数趋势</strong></div>' +
        trendSvg(runs, "failed", "failed", "") + "</div>" +
      '<div class="chart-panel"><div class="chart-head"><strong>行覆盖率趋势</strong></div>' +
        trendSvg(runs.map(function (run) {
          return Object.assign({}, run, {line_rate_pct: run.line_rate == null ? null : run.line_rate * 100});
        }), "line_rate_pct", "line rate %", "%") + "</div>" +
      '<div class="chart-panel"><div class="chart-head"><strong>总耗时趋势</strong>' +
        '<span class="muted">仅展示有起止时间记录的轮次</span></div>' +
        trendSvg(runs.filter(function (run) { return Number(run.wall_seconds) > 0; }),
          "wall_seconds", "wall seconds", "s") + "</div>" +
      '<div class="chart-panel"><div class="chart-head"><strong>运行列表</strong></div>' +
        '<div class="drill-table-wrap"><table class="drawer-table drill-table bench-table"><thead><tr>' +
          "<th>run_id</th><th>开始</th><th>commit</th><th>总数</th><th>失败</th><th>行覆盖</th><th>耗时</th>" +
        "</tr></thead><tbody>" + rows + "</tbody></table></div></div>";
  }

  function renderUiView(data) {
    el.toolbar.hidden = true;
    el.reconcileBox.hidden = true;
    el.tableBox.hidden = true;
    el.stats.hidden = true;
    el.statsView.hidden = false;
    const summary = data.summary || {};
    const browsers = summary.browsers || [];
    if (!browsers.length) {
      el.statsView.innerHTML =
        '<div class="placeholder-card"><h2>UI 自动化</h2>' +
        '<p class="muted">本轮没有 UI 结果。执行：<code>pytest -m ui --browser chromium --browser firefox --browser webkit -n 3 --dist loadscope</code></p>' +
        "</div>";
      return;
    }
    const kpis = browsers.map(function (item) {
      return kpiCard(item.passed + " / " + item.total,
        item.name + " 通过率 " + item.passRate + "%",
        item.failed + item.broken > 0);
    }).join("");
    const head = browsers.map(function (item) {
      return "<th>" + escapeHtml(item.name) + "</th>";
    }).join("");
    const rows = (data.rows || []).map(function (row) {
      const cells = browsers.map(function (browser) {
        const item = (row.browsers || {})[browser.name];
        if (!item) return '<td class="muted">未执行</td>';
        return "<td>" + statusBadge(item.status) +
          ' <span class="muted">' + (item.durationMs / 1000).toFixed(1) + "s</span></td>";
      }).join("");
      return "<tr><td>" + escapeHtml(row.caseId || "-") + "</td><td>" +
        escapeHtml(row.name || "") + "</td>" + cells + "</tr>";
    }).join("");
    el.statsView.innerHTML =
      '<div class="stats-kpi">' + kpis + "</div>" +
      '<p class="muted stats-note">口径：同一逻辑用例在每个已执行浏览器下分别执行（本轮 ' +
        escapeHtml(browsers.map(function (item) { return item.name; }).join(" / ")) +
        "，多浏览器并行运行）；状态取该浏览器最后一次尝试，耗时为用例本体。PR 默认只跑 Chromium。（" +
        escapeHtml(data.generatedAt || "") + "）</p>" +
      '<div class="chart-panel"><div class="chart-head"><strong>浏览器 × 用例矩阵</strong></div>' +
        '<div class="drill-table-wrap"><table class="drawer-table drill-table bench-table"><thead><tr>' +
          "<th>用例编号</th><th>用例</th>" + head +
        "</tr></thead><tbody>" + rows + "</tbody></table></div></div>";
  }

  function renderEnhancementsView(data) {
    el.toolbar.hidden = true;
    el.reconcileBox.hidden = true;
    el.tableBox.hidden = true;
    el.stats.hidden = true;
    el.statsView.hidden = false;
    const items = data.optimizations || [];
    const enhancements = data.enhancements || [];
    const limitations = data.limitations || [];
    const done = enhancements.filter(function (item) { return item.status === "done"; }).length;
    const partial = enhancements.filter(function (item) { return item.status === "partial"; }).length;
    const statusText = { done: "已完成", partial: "部分完成" };
    const statusCell = function (status) {
      return '<span class="badge ' + (status === "done" ? "passed" : "skipped") + '">' +
        (statusText[status] || escapeHtml(status || "")) + "</span>";
    };
    const optimizationRows = items.map(function (item) {
      return "<tr><td>" + escapeHtml(item.title || "") + "</td>" +
        '<td class="muted">' + escapeHtml(item.before || "") + "</td>" +
        "<td>" + escapeHtml(item.after || "") + "</td>" +
        '<td class="muted">' + escapeHtml(item.evidence || "") + "</td>" +
        "<td>" + statusCell(item.status) + "</td></tr>";
    }).join("");
    const enhancementRows = enhancements.map(function (item) {
      return "<tr><td>" + (item.no || "") + "</td><td>" + escapeHtml(item.title || "") + "</td>" +
        "<td>" + escapeHtml(item.result || "") + "</td><td>" + statusCell(item.status) + "</td></tr>";
    }).join("");
    const limitationRows = limitations.map(function (item) {
      return "<tr><td>" + escapeHtml(item.title || "") + "</td><td>" +
        escapeHtml(item.detail || "") + "</td></tr>";
    }).join("");
    el.statsView.innerHTML =
      '<div class="stats-kpi">' +
        kpiCard(items.length, "本轮优化项") +
        kpiCard(done + " / " + enhancements.length, "9 项增强已完成", partial > 0) +
        kpiCard(limitations.length, "限制 / 待办") +
      "</div>" +
      '<p class="muted stats-note">同步自 2026-10-30 回归：性能、计数、缺陷定位、MQ、JaCoCo、CI、报告与数据基线。' +
        "（" + escapeHtml(data.updatedAt || "") + "）</p>" +
      '<div class="chart-panel"><div class="chart-head"><strong>本轮优化</strong></div>' +
        '<div class="drill-table-wrap"><table class="drawer-table drill-table bench-table"><thead><tr>' +
          "<th>优化点</th><th>优化前</th><th>优化后</th><th>验证</th><th>状态</th>" +
        "</tr></thead><tbody>" + optimizationRows + "</tbody></table></div></div>" +
      '<div class="chart-panel"><div class="chart-head"><strong>9 项增强落地</strong></div>' +
        '<div class="drill-table-wrap"><table class="drawer-table drill-table bench-table"><thead><tr>' +
          "<th>#</th><th>增强项</th><th>落地结果</th><th>状态</th>" +
        "</tr></thead><tbody>" + enhancementRows + "</tbody></table></div></div>" +
      '<div class="chart-panel"><div class="chart-head"><strong>限制与待办</strong></div>' +
        '<div class="drill-table-wrap"><table class="drawer-table drill-table bench-table"><thead><tr>' +
          "<th>项</th><th>说明</th>" +
        "</tr></thead><tbody>" + limitationRows + "</tbody></table></div></div>";
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
          item.path, item.method, item.risk || "",
          (point.dimensions && point.dimensions.length ? point.dimensions : [point.dimension]).join("/"),
          point.name || "",
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
