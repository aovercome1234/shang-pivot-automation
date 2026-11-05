/**
 * 浏览链路混合负载（只读为主）。
 *
 * 用户模型参考电商真实流量：
 *   35% 商品列表翻页（首页/分类页瀑布流）
 *   25% 关键词搜索（含少量无结果冷门词，模拟热点倾斜）
 *   20% 商品详情
 *   15% 首页聚合（品牌 + 运营位 + 推荐流，接口最重的只读路径）
 * 登录可用时叠加：受保护读约 5%（类目、我的、购物车、订单、收藏）。
 *
 * RPS 基线（推荐）：
 *   k6 run -e BASE_URL=http://127.0.0.1:8090/api \
 *          -e PHONE=13800000001 \
 *          -e RPS=50 -e STAGES=1m:20,2m:50,3m:50 k6/browse-load.js
 * VU 阶梯（探索容量）：
 *   k6 run -e STAGES=30s:10,2m:50,3m:100 k6/browse-load.js
 */
import http from 'k6/http';
import { sleep } from 'k6';
import {
  buildOptions,
  customerLogin,
  expectOk,
  getBaseUrl,
  getPhone,
  handlePerfSummary,
  jsonHeaders,
  loadSpuIds,
  parseStages,
  pickRandom,
  randomInt,
  thinkTime,
  tokenProvider,
  verifyTokenUsable,
} from './lib/shang.js';

const RPS = Number(__ENV.RPS || 0);
const RATE_STAGES = parseStages(__ENV.STAGES || '');

function browseOptions() {
  const base = buildOptions(20, '3m');
  if (RPS <= 0) {
    return base;
  }
  const stages = RATE_STAGES.length > 0
    ? RATE_STAGES
    : [{ duration: __ENV.DURATION || '3m', target: RPS }];
  return {
    thresholds: base.thresholds,
    summaryTrendStats: base.summaryTrendStats,
    scenarios: {
      browse_rps: {
        executor: 'ramping-arrival-rate',
        startRate: Math.max(1, Math.floor(stages[0].target / 2)),
        timeUnit: '1s',
        preAllocatedVUs: Number(__ENV.PRE_ALLOCATED_VUS || 50),
        maxVUs: Number(__ENV.MAX_VUS || 200),
        stages,
      },
    },
  };
}

export const options = browseOptions();
export const handleSummary = handlePerfSummary;

// 关键词可注入：-e KEYWORDS=帐篷,咖啡,笔记本,口红,跑步鞋,zzz不存在
// 默认取自种子商品真实名称（搜索按名称匹配）；“zzz不存在”用于观察无结果分支。
const KEYWORDS = (__ENV.KEYWORDS || '帐篷,咖啡,笔记本,口红,跑步鞋,zzz不存在')
  .split(',')
  .map((item) => item.trim())
  .filter(Boolean);

export function setup() {
  const baseUrl = getBaseUrl();
  const spuIds = loadSpuIds(baseUrl, '', 40);

  let authNote = '未启用鉴权链路';

  const login = customerLogin(baseUrl, getPhone(), __ENV.CODE || '123456');
  let initialToken = '';

  if (login.token) {
    const verdict = verifyTokenUsable(baseUrl, login.token, '/me');
    if (verdict.usable) {
      initialToken = login.token;
      authNote = '鉴权可用，已叠加受保护读链路';
    } else {
      authNote = `鉴权不可用（${verdict.detail}），降级为公开读链路`;
    }
  } else if (login.reason) {
    authNote = `登录未成功（${login.reason}），降级为公开读链路`;
  }

  // token 只能返回可序列化数据；provider 在 VU 侧构造，避免 setup 返回函数。
  console.log(`[browse-load] run_id=${__ENV.PERF_RUN_ID || '(自动生成)'} 商品池 ${spuIds.length} 条；${authNote}`);

  return { baseUrl, initialToken, spuIds };
}

let vuTokenProvider = null;
function getVuToken(baseUrl, initialToken) {
  if (!vuTokenProvider) {
    vuTokenProvider = tokenProvider(initialToken, () =>
      customerLogin(baseUrl, getPhone(), __ENV.CODE || '123456'));
  }
  return vuTokenProvider();
}

export default function (data) {
  const baseUrl = data.baseUrl;
  const token = getVuToken(baseUrl, data.initialToken);
  const roll = Math.random();

  // 与《性能测试实施方案》§2.3 对齐：列表35%、搜索25%、详情20%、首页15%、受保护读5%。
  if (roll < 0.35) {
    const page = randomInt(1, 4);
    const size = randomInt(8, 20);
    const response = http.get(`${baseUrl}/products?page=${page}&size=${size}`, jsonHeaders(token));
    expectOk(response, 'products list');
  } else if (roll < 0.60) {
    const keyword = pickRandom(KEYWORDS);
    const response = http.get(
      `${baseUrl}/search?q=${encodeURIComponent(keyword)}&page=1&size=10`,
      jsonHeaders(token),
    );
    expectOk(response, 'search');
  } else if (roll < 0.80) {
    const spuId = pickRandom(data.spuIds);
    if (spuId !== null) {
      const response = http.get(`${baseUrl}/products/${spuId}`, jsonHeaders(token));
      expectOk(response, 'product detail');
    }
  } else if (roll < 0.95 || !token) {
    // 首页聚合：品牌 + 运营位 + 推荐流，一次请求里包含多段查询
    expectOk(http.get(`${baseUrl}/home`, jsonHeaders(token)), 'home');
  } else {
    const extra = Math.random();
    if (extra < 0.2) {
      expectOk(http.get(`${baseUrl}/categories`, jsonHeaders(token)), 'categories');
    } else if (extra < 0.4) {
      expectOk(http.get(`${baseUrl}/me`, jsonHeaders(token)), 'current customer');
    } else if (extra < 0.6) {
      expectOk(http.get(`${baseUrl}/cart`, jsonHeaders(token)), 'cart');
    } else if (extra < 0.8) {
      expectOk(http.get(`${baseUrl}/orders?page=1&size=5`, jsonHeaders(token)), 'orders');
    } else {
      expectOk(http.get(`${baseUrl}/favorites?page=1&size=10`, jsonHeaders(token)), 'favorites');
    }
  }

  sleep(thinkTime());
}
