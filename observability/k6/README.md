# k6 压测脚本（尚品汇）

共享库 `lib/shang.js`，四个脚本按"先预检、再压读、再压写"的顺序用。
脚本**在服务器上跑**（`/root/k6/shang/`，由 `scripts/deploy-platform-to-server.sh` 同步），
压内网入口 `127.0.0.1:8090`（C 端）/ `127.0.0.1:8091`（管理端），
客户端指标用 remote write 写入服务器的 Prometheus（带 `app="shang-pivot"` 标签，仪表板据此过滤）。

| 脚本 | 用途 | 关键环境变量 |
| --- | --- | --- |
| `preflight.js` | 压测前预检：哪些接口真能压、写链路是否可用（单次执行，不产生负载） | `BASE_URL` `ADMIN_BASE_URL` `PHONE` `ACCOUNT` `PASSWORD` |
| `browse-load.js` | 浏览型混合负载：列表 40% / 搜索 25% / 详情 20% / 首页 15%，登录后叠加受保护读 | `BASE_URL` `PHONE` `STAGES` 或 `VUS`+`DURATION` |
| `login-load.js` | 登录风暴：`LOGIN_TARGET=customer`（手机号+验证码）或 `admin`（用户名+密码，BCrypt 纯 CPU） | `PHONES`/`ACCOUNTS` `RATE` `DURATION` |
| `checkout-smoke.js` | 写链路：登录 → 加购 → 查购物车 → 下单 → 沙箱支付（**一账号一 VU**，会真实扣库存） | `PHONES` `VUS` `DURATION` `SKIP_SCAN` |

## 跑法（本机一条命令，实际在服务器执行）

```bash
cd observability

# 1) 预检
bash ./scripts/platform.sh k6 preflight.js \
  -e BASE_URL=http://127.0.0.1:8090/api -e ADMIN_BASE_URL=http://127.0.0.1:8091/admin \
  -e PHONE=13800000001
# ACCOUNT/PASSWORD 等敏感项放服务器 /root/k6/shang/.env，platform.sh 会在远端自动读取
# k6 客户端指标默认写入目标服务器 127.0.0.1:9090/api/v1/write；
# 若目标机没有 Prometheus，先设置 K6_PROMETHEUS_RW_SERVER_URL 指向可达的 remote write。

# 2) 浏览读链路（RPS 基线；RPS>0 时使用 ramping-arrival-rate）
bash ./scripts/platform.sh k6 browse-load.js -e BASE_URL=http://127.0.0.1:8090/api \
  -e PHONE=13800000001 -e RPS=50 -e STAGES=1m:20,2m:50,3m:50 \
  -e PRE_ALLOCATED_VUS=50 -e MAX_VUS=200

# 兼容旧 VU 阶梯：不传 RPS 时，STAGES 表示 VU 阶梯
bash ./scripts/platform.sh k6 browse-load.js -e BASE_URL=http://127.0.0.1:8090/api \
  -e PHONE=13800000001 -e STAGES=30s:10,2m:50,3m:100

# 3) 登录风暴（到达速率模式）
bash ./scripts/platform.sh k6 login-load.js -e LOGIN_TARGET=customer \
  -e BASE_URL=http://127.0.0.1:8090/api \
  -e PHONES=13800000001,13800000002,13800000003 -e RATE=20 -e DURATION=2m

# 4) 写链路（一账号一 VU）
bash ./scripts/platform.sh k6 checkout-smoke.js \
  -e BASE_URL=http://127.0.0.1:8090/api -e PHONES=13800000001,13800000002 -e VUS=2 -e DURATION=1m
```

也可以在服务器上手工跑：

```bash
ssh -i ~/.ssh/projectku_psyidc -p 28536 root@111.170.33.2
cd /root/k6/shang
K6_PROMETHEUS_RW_SERVER_URL=http://127.0.0.1:9090/api/v1/write \
K6_PROMETHEUS_RW_TREND_STATS='p(95),p(99),avg,min,max' \
k6 run -o experimental-prometheus-rw --tag app=shang-pivot browse-load.js \
  -e BASE_URL=http://127.0.0.1:8090/api -e PHONE=13800000001 \
  -e RPS=30 -e STAGES=1m:10,2m:30,3m:30
```

> 下方公网/SSH 示例仍保留历史平台 `111.170.33.2` 口径；本次 49.233.135.247 目标环境请以 `docs/性能测试实施方案.md` 为准。
> 从本机直接压公网入口也可以，但会掺进公网波动，且指标不会带上 `app` 标签；定位服务端容量时优先用服务器内网入口。

## 与元气购脚本的差异（照抄会全错）

| 项 | 尚品汇 | 元气购 |
| --- | --- | --- |
| 成功业务码 | **`code: 0`** | `code: 200` |
| 入口 | 两套：C 端 `/api/**`、管理端 `/admin/**`（令牌不通用） | 单套 `/api` |
| 登录 | C 端 `{phone, code, clientType}`（演示验证码固定 `123456`）；管理端 `{username, password}` | `{account, password}` |
| 商品 ID | 列表字段 `spuId`，详情 SKU 字段 `skuId`、库存 `availableStock` | `id` / `skuList[].stock` |
| 搜索参数 | `?q=` | `?keyword=` |
| 下单 | `POST /api/orders` `{addressId, skuId, quantity, idempotentKey}` | `/v1/orders/checkout` |
| 支付 | `POST /api/payment/sandbox` `{orderId}` | `/v1/payments/{id}/pay` |
| **ID 类型** | 19 位雪花号（**必须按字符串传**，`Number()` 会丢精度） | 小整数 |

## 脚本公共能力（2026-11-04 升级）

- 所有请求自动注入 `X-Perf-Run-Id` / `X-Perf-Scenario`，并输出 `run_id`、`scenario` 标签；
- `platform.sh k6` 自动生成 `PERF_RUN_ID`，summary 写入 `PERF_ARTIFACT_DIR/summary-<run_id>.json`；
- 默认请求 timeout 为 `REQUEST_TIMEOUT_MS=5000`；
- `browse-load.js` 使用 token provider，长跑时自动刷新 900 秒有效的登录 token；
- `checkout-smoke.js` 强制“一账号一 VU”，并按 SKU 可用库存加权选择商品；
- 下单幂等键包含 run_id，便于 `check_perf_invariants.py` 做订单/支付/库存/MQ 不变量校验。

## 阈值与告警

`lib/shang.js` 的默认阈值：失败率 <1%、断言通过率 >99%、`http_req_duration` p95 < 800ms / p99 < 1500ms。
命令行可覆盖：`THRESHOLD_P95_MS` / `THRESHOLD_P99_MS` / `THRESHOLD_FAIL_RATE` / `THRESHOLD_CHECK_RATE`。

服务端侧的告警规则在 `../prometheus/rules/shang-pivot-alerts.yml`（部署到服务器
`/opt/monitoring/prometheus/rules/`）。阈值尚未做容量压测标定，规则里标注为经验值。
