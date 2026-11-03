# API 自动化框架体系搭建与亮点分析

> 范围：`pytest_automation/` 下的 API 自动化体系（UI 作为同框架的扩展一并说明）
> 文档版本：v1.6 ｜ 最后更新：2026-11-03 ｜ 变更记录见文末第 21 节
> 当前基线：845 条逻辑用例；本轮执行 890 条结果（API 796 + UI 47 × 2 浏览器）
> 结果：794 通过 / 93 失败 / 3 跳过；Allure 套件叶子 890，与 Overview 一致
> 业务分类：5 个业务域、14 个业务模块、141 个接口聚合组
> P0 门禁：known_failures 93 条、覆盖率门禁通过、写接口 DB 断言 68/68、P0 评审债 0
> 报告入口：`artifacts/allure-report/ext/index.html`；版本对比：`#/compare/diff`

---

## 1. 摘要

这套框架解决的问题不是“能不能跑 pytest”，而是：

1. **用例能稳定重复执行**：随机会员、SKU 分片、串行 lane、DB 基线恢复；
2. **接口能测全**：135 个端点、487 条巡检、接口矩阵、校验/不变量/幂等/安全/大数据量；
3. **结果能解释**：请求/响应、traceId 后端日志、DB 落库、调用链、缺陷代码位置；
4. **视图能聚焦**：Allure 按“业务域 → 业务模块 → 接口 → 用例”组织，MQ/Redis/DB/大数据量/参数联动等维度收敛为标签；
5. **变化能判断**：两轮结果/覆盖率/耗时对比、趋势、风险点与测试建议自动生成；
6. **体系能持续演进**：稳定用例 ID、评审门禁、覆盖率、历史 diff、知识库、夜间 CI。

最终形成“**用例资产 + 执行引擎 + 数据隔离 + 诊断证据 + 治理门禁**”的闭环。

---

## 2. 目标与边界

### 2.1 目标

| 目标 | 落地方式 |
|---|---|
| 业务正确性 | 正向链路、状态机、金额/库存守恒 |
| 接口完备性 | 端点模型驱动巡检，不依赖人工枚举 |
| 输入健壮性 | 等价类、边界值、参数联动、异常体 |
| 安全 | 越权、匿名、注入、XSS、超大分页 |
| 数据一致性 | 请求→DB 行逐字段断言、库存/金额不变量 |
| 中间件 | Redis TTL/锁定/黑名单、RabbitMQ 消费/幂等/DLQ |
| 可重复 | 基线快照、随机数据、限流清理、串行 lane |
| 可诊断 | traceId 日志、失败附件、缺陷单、代码定位 |
| 可治理 | 注册表、评审、质量门禁、覆盖率、CI |

### 2.2 边界

- 不是压测框架：并发只验证正确性，不做容量结论；
- 不是全量 UI 框架：UI 覆盖关键旅程，接口是主体；
- 不是生产监控：所有写操作使用隔离会员/演示数据；
- 93 条失败是已知缺陷护栏（D-06～D-23），修复后自动转绿；
- 报告中的“接口聚合”是对 Allure 静态 `suites.json` 的派生视图，不改变用例结果和稳定 ID。

---

## 3. 总体架构

```text
┌────────────────────────────────────────────────────────────────┐
│                        Test Layer                              │
│  tests/api/*.py   tests/ui/*.py   tests/e2e/*.py               │
│  端点矩阵 / 校验边界 / 不变量 / 幂等 / 安全 / 大数据量 / MQ/Redis │
└───────────────────────────┬────────────────────────────────────┘
                            │ pytest fixtures / markers
┌───────────────────────────▼────────────────────────────────────┐
│                      Framework Layer                           │
│  conftest.py       业务域/模块标签、用例 ID、xdist、失败证据     │
│  core/api_client   Session / 重试 / traceId / 请求响应附件       │
│  core/business_taxonomy  业务分类器、主接口选择                  │
│  core/assertions   HTTP / 业务码 / 分页 / traceId                │
│  core/recorder     用例→接口映射、请求响应样本                   │
│  fixtures/         customer / admin / sku / order / page         │
│  helpers/          auth / data_factory / db / db_contract        │
└───────────────────────────┬────────────────────────────────────┘
                            │ HTTP / SQL / Redis / AMQP
┌───────────────────────────▼────────────────────────────────────┐
│                     System Under Test                          │
│  Spring Boot API  +  PostgreSQL  +  Redis  +  RabbitMQ         │
└───────────────────────────┬────────────────────────────────────┘
                            │ Allure result / jacoco / logs
┌───────────────────────────▼────────────────────────────────────┐
│                     Reporting & Governance                     │
│  Allure：业务域 → 模块 → 接口 → 用例；维度 tags                 │
│  ext：接口/统计/覆盖/缺陷/历史/版本对比/趋势/三方/UI             │
│  注册表 / 评审 / 门禁 / 归档索引 / 缺陷 / 知识库 / CI            │
└────────────────────────────────────────────────────────────────┘
```

分层原则：

- 用例只写业务意图，不直接管理 HTTP/Session/日志；
- 客户端统一处理重试、超时、traceId、附件、埋点；
- 夹具负责数据准备与清理，用例不共享可变数据；
- 断言分层：HTTP → 业务码 → schema → DB → 不变量；
- 报告消费结果与证据，不反向依赖用例内部实现。

---

## 4. 目录与模块

```text
pytest_automation/
├── pytest.ini                 # markers / addopts / pythonpath
├── conftest.py                # 插件、用例 ID、标签、失败证据、xdist 分组
├── Makefile                   # api / ui / smoke / full / parallel / report
├── config/
│   ├── settings.py            # 环境变量 > .env.local > env YAML
│   └── env/{dev,demo}.yaml
├── core/
│   ├── api_client.py          # requests Session、GET 重试、traceId、Allure
│   ├── business_taxonomy.py   # 业务域/模块分类、主接口选择
│   ├── assertions.py          # ok/error、分页、traceId 断言
│   ├── endpoint_recorder.py   # 用例 → 接口映射 + 请求响应样本
│   ├── step_recorder.py       # UI 步骤截图
│   └── logger.py
├── fixtures/
│   ├── api_fixtures.py        # customer/admin/sku/address/cart/order
│   └── ui_fixtures.py         # page / login state / trace
├── helpers/
│   ├── auth_helper.py         # 登录、加购、下单、发货
│   ├── data_factory.py        # 唯一手机号、地址、订单、幂等键
│   ├── db.py                  # 只读 SQL、库存/订单/指纹
│   ├── db_contract.py         # 写接口 → DB 行逐字段校验
│   ├── diagnose.py            # traceId 日志摘录
│   └── parallel.py            # worker 分片
├── data/
│   ├── case_meta.yaml         # 标题/验证点/模块
│   ├── business_taxonomy.yaml # 业务域/模块/维度/接口优先级规则
│   ├── case_registry.json     # 稳定 ID / content_hash / 生命周期
│   ├── case_review.yaml       # 评审台账
│   ├── write_contracts.yaml   # 写接口 DB 契约
│   ├── endpoint_matrix.json   # 487 条巡检数据
│   └── quality_gate_allowlist.yaml
├── tests/api/                 # 25 个文件，覆盖契约/校验/安全/幂等/DB/MQ
├── tests/ui/                  # 7 个文件，47 条 × 浏览器
├── tests/e2e/                 # 2 条全链路
├── scripts/
│   ├── build_api_matrix.py    # 接口视图
│   ├── group_suites_by_endpoint.py  # 业务模块下按接口聚合
│   ├── run_index.py / compare_runs.py  # 跨轮索引、对比、趋势
│   ├── audit_taxonomy.py      # 业务分类审计
│   └── ...                    # 覆盖率、缺陷、三方、CI
└── docs/                      # 方案、并行、评审、JaCoCo、技术原理
```

---

## 5. 请求生命周期

以一条“下单落库”用例为例：

```text
pytest test_order_submit_persisted
  │
  ├─ customer fixture
  │    ├─ unique_phone()
  │    ├─ POST /api/auth/sms/send
  │    ├─ POST /api/auth/login
  │    └─ 返回隔离会员 client
  │
  ├─ address fixture / sku fixture
  │    ├─ POST /api/addresses
  │    └─ 按 worker 分片选择在售 SKU
  │
  ├─ ApiClient.post("/api/orders")
  │    ├─ Session + timeout + 不代理
  │    ├─ traceId 提取（body / X-Trace-Id）
  │    ├─ Allure 请求/响应附件
  │    └─ endpoint_recorder.record()
  │
  ├─ assertions.ok()
  │    ├─ HTTP 200
  │    ├─ code=0
  │    └─ traceId 非空
  │
  ├─ db_contract.verify_write()
  │    ├─ 响应 ID 定位 commerce.order
  │    ├─ 字段逐项比对
  │    └─ 生成列只断言非空
  │
  ├─ 库存不变量
  │    ├─ locked_stock 增加
  │    └─ 取消后释放
  │
  └─ 失败时
       ├─ 最后请求/响应
       ├─ traceId 后端日志
       ├─ 失败依据附件
       └─ results.json + Allure
```

---

## 6. 用例体系

### 6.1 分层设计

| 层 | 文件 | 作用 |
|---|---|---|
| 契约 | `test_auth/catalog/cart/order/address` | 正常路径、响应结构 |
| 端点巡检 | `test_endpoint_sweep` | 135 端点 × 安全/逆向/边界/异常 |
| 输入校验 | `test_validation` | 必填、长度、格式、范围 |
| 参数联动 | `test_validation_interactions` | 手机号×验证码×clientType、订单字段组合 |
| 业务不变量 | `test_invariants` | 金额守恒、库存守恒、状态机 |
| 幂等 | `test_idempotency` | 重复下单、重复支付、重复发货 |
| 安全 | `test_security` / `test_security_idor` | 匿名、角色、越权、注入、XSS |
| 大数据量 | `test_bulk_data` | 大分页、深翻页、批量 SKU |
| 写接口落库 | `test_write_persistence` | 请求→DB 行 |
| 中间件 | `test_mq_order_events` / `test_redis_state` | MQ 消费/幂等/DLQ、Redis TTL/锁定/黑名单 |
| 管理端 CRUD | `test_admin_crud_roundtrip` | 创建→更新→删除 |
| 数据驱动 | `test_data_driven` / YAML | 同一逻辑多组数据 |

### 6.2 用例设计方法

- 等价类：合法/非法/边界/空值；
- 边界值：0、-1、上限、上限+1；
- 判定表：多字段组合（登录、订单）；
- 状态机：待支付→待发货→待收货→完成/取消；
- 错误猜测：畸形 JSON、路径参数类型错误、超长字段；
- 不变量：金额、库存、订单明细、支付流水；
- 幂等：重复请求不产生重复副作用；
- 安全：越权、匿名、注入、XSS、超大分页；
- 数据驱动：`endpoint_matrix.json` 生成 487 条巡检。

### 6.3 命名与标识

- 每条用例有稳定 `case_id`（如 `API-VAL-019`）；
- 注册表保存 `content_hash`、`title_hash`、`first_seen/last_seen/status`；
- 重命名/改内容会被检测，评审门禁要求重新 approved；
- Allure `pytest_nodeid` 标签用于报告精确关联。

### 6.4 业务分类与接口聚合

Allure Suites 从“按测试文件分组”改为业务视图：

```text
接口自动化
  会员中心     → 登录与令牌 / 会员资料 / 收货地址 / 收藏与足迹
  商品中心     → 商品与搜索 / 商品管理
  交易中心     → 购物车 / 订单与支付 / 库存与履约
                 └─ 库存与履约
                      ├─ GET /admin/in-out
                      │    ├─ 功能正向校验
                      │    ├─ 逆向校验
                      │    ├─ 边界值校验
                      │    ├─ 异常校验
                      │    └─ 特殊场景校验
                      ├─ GET /admin/stocks
                      ├─ POST /admin/orders/{id}/ship
                      └─ 跨接口 / 业务校验
  售后与评价   → 售后服务 / 评价管理
  平台治理     → 身份与权限 / 配置与审计 / 文件服务
```

关键点：

- **分类依据不是文件名**：优先读取用例实际调用的接口，选择业务动作优先级最高的主接口；
  多接口用例（如“地址 + 购物车 + 下单”）归入订单，而不是工具性前置接口；
- **横切维度不再拆套件**：MQ、Redis、数据库落库、大数据量、参数联动、安全、幂等、越权等
  统一通过 `验证维度：<维度>` 标签和详情描述展示；
- **接口聚合**：在业务模块下再插入 `METHOD /path` 分组；同一接口的 CRUD、边界、安全、
  DB 落库、大数据量用例聚合在一起；接口组按名称（METHOD/path）排序，组内按稳定用例编号排序；
- **测试大分类**：接口组下再按“功能正向校验 / 逆向校验 / 边界值校验 / 异常校验 /
  特殊场景校验”聚合；细粒度维度仍是 `验证维度` 标签，不丢失边界、安全、幂等、DB、MQ、Redis 信息；
- **模板归一**：`/api/orders/123/cancel` 归一到 `/api/orders/{id}/cancel`；未关联接口的用例
  进入“跨接口 / 业务校验”；
- **无遗漏校验**：`audit_taxonomy.py` 输出业务域/模块/维度分布，当前 890 条、未归类 0 条。

规则文件为 `data/business_taxonomy.yaml`，分类器为 `core/business_taxonomy.py`，
接口树注入脚本为 `scripts/group_suites_by_endpoint.py`。当前 5 个业务域、14 个模块、
141 个接口组、362 个测试大分类；`接口自动化` 795 条、`端到端链路` 1 条、`UI 自动化` 94 条，总计 890 条。

### 6.5 接口级场景迁移（订单 / 购物车 / 地址 / 认证支付售后评价 / 管理端基础 CRUD）

在保留原专项用例的同时，将核心链路按“接口为组织边界、场景为执行单元、维度为标签”迁移：

- `tests/api/endpoints/test_orders.py`：`POST /api/orders`，类级上下文复用会员、地址、SKU；参数化逆向/边界保留独立失败粒度；正向一次下单 + 支付，按 API → DB → MQ 分层断言；幂等、20 项批量、他人地址、未认证独立成特殊场景。
- `tests/api/endpoints/test_cart_address.py`：`POST /api/cart/items`、`POST /api/addresses`，类级只读上下文 + 函数级可变链路，验证加购合并与默认地址。
- `tests/api/endpoints/test_auth_payment_after_sales.py`：短信登录（Redis 验证码/TTL + DB 会员）、沙箱支付（API/DB/MQ）、重复支付幂等、售后申请/审核、评价创建/隐藏；逆向校验参数化。
- `tests/api/endpoints/test_admin_crud.py`：品牌、类目、字典、部门、仓库的创建/更新/删除，逐接口归属到 `POST`/`PUT`/`DELETE`，正向同时校验响应 ID 与 DB 行；字典重复编码单独作为冲突场景。
- `endpoint_attribution.yaml` 显式声明主体接口，避免夹具登录、列表查询和 setup 请求抢占接口归属；
- 四个接口文件共新增 34 条用例（认证支付售后评价 9 条、管理端 CRUD 25 条）；原专项用例保留作回归对照。

当前迁移状态：

| 接口 | 迁移状态 |
|---|---|
| `POST /api/orders` | 已完成（接口级场景 + API/DB/MQ） |
| `POST /api/cart/items` | 已完成（含同 SKU 合并） |
| `POST /api/addresses` | 已完成（含默认地址） |
| `POST /api/auth/sms/send`、`POST /api/auth/login` | 已完成（Redis + DB） |
| `POST /api/payment/sandbox` | 已完成（API/DB/MQ + 幂等） |
| `POST /api/after-sales`、`POST /admin/after-sales/{id}/audit` | 已完成 |
| `POST /api/reviews`、`PUT /admin/reviews/{id}/status` | 已完成 |
| `POST/PUT/DELETE /admin/brands`、`/admin/categories`、`/admin/dicts`、`/admin/depts`、`/admin/warehouses` | 已完成（基础数据 CRUD） |

商品、角色、用户等已有独立深度落库用例（`test_write_persistence_extended.py`），此次不重复迁移；后续新增接口按同一模板扩展，并优先保持 nodeid 稳定，避免破坏稳定 ID、known_failures、历史 diff 和 Gitee issue 映射。

迁移后的报告结构：Suites 仍为“业务域 → 业务模块 → 接口 → 测试大分类 → 用例”，接口下固定按“功能正向校验 → 逆向校验 → 边界值校验 → 异常校验 → 特殊场景校验 → 其他校验”排序；本轮共 141 个接口组、362 个测试大分类。

---

## 7. 测试数据与环境

### 7.1 环境配置

优先级：

```text
真实环境变量 > pytest_automation/.env.local > config/env/<TEST_ENV>.yaml
```

- `TEST_ENV=dev`：本地后端 8086；UI 默认指向本地 Vite `127.0.0.1:5174/5173`；
- `TEST_ENV=demo`：演示站；
- `ADMIN_PASSWORD` 不落仓库，缺失时管理端用例 skip；
- `UI_MALL_URL/UI_ADMIN_URL` 可覆盖前端地址。

本地 UI 回归前先启动仓库内前端：

```bash
(cd ../shang-mall && npm ci && npm run dev)          # 默认 5174
(cd ../shang-admin-web && npm ci && npm run dev)     # 默认 5173
```

### 7.2 数据隔离

| 场景 | 策略 |
|---|---|
| 会员 | 每次用例随机手机号，自动注册；teardown 不删除业务数据，靠随机数据隔离并保留核验证据 |
| SKU | 按 worker 分片 `sku_id % worker_count`，避免抢库存 |
| 批量库存 | `serial` lane，串行执行 |
| 登录限流 | 每轮清理 `login:fail:*`，失败类用例串行 |
| DB 基线 | 执行前快照、执行后指纹 diff |
| 订单 | 幂等键 + 随机会员，取消/发货/确认收尾 |
| MQ | 每轮清理事件表/队列，幂等唯一键 |
| Redis | 用例内清理 SMS/cooldown/blacklist 键 |

### 7.3 可重复性

- `artifacts/db-baseline.sql` 快照恢复；
- `db-baseline-diff.json` 记录预期外变化；
- 失败后保留请求/响应、DB 行、Redis/MQ 证据，不清理测试数据；
- 管理端登录失败计数每轮重置；
- 用例级随机数据，避免顺序依赖。

---

## 8. 并行与稳定性

### 8.1 xdist 分组

- `conftest.py` 为每个用例动态生成 `xdist_group=ep::<主体接口>`；
- `--dist loadgroup` 保证同一接口的用例落到同一 worker，避免同接口共享数据竞争；
- 不按 GET/POST/PUT/DELETE 分组，按业务接口分组。

### 8.2 两阶段执行

```text
阶段 1：并行（排除 serial）
阶段 2：串行（serial：批量库存、登录失败限流）
```

`run_parallel.sh` 负责：

- 清理 Redis 登录失败计数；
- 启动并行与串行；
- 合并各 worker 的 results/mapping；
- 可选发布到 Allure 报告，保留 UI 结果。

### 8.3 实测

| 层 | 串行 | 并行 | 加速比 |
|---|---|---|---|
| API（701 条历史基线） | 253–271s | 84s 中位 | 3.23x |
| UI（47 条） | 174s | 83s 中位 | 2.10x |

失败集合、通过/失败/跳过数量与串行一致；worksteal 更快，但放弃接口级隔离，不作为正式对比口径。
当前结果规模已增长到 890 条（API 796 + UI 94），上述 701 条 API 数据是历史基准；
正式汇报前需用当前规模重跑串行/并行基准。

### 8.4 失败重试

- `pytest-rerunfailures` 默认重试 1 次；
- 结果按 nodeid 取最后一次尝试，避免计数虚高；
- 不掩盖真实失败：失败仍进入报告与缺陷单。

---

## 9. 断言与诊断

### 9.1 断言分层

| 层 | 示例 |
|---|---|
| HTTP | 状态码 200/400/401/404/409 |
| 业务码 | code=0 / 40000 / 40101 / 40901 |
| Schema | 字段存在、类型（Long→String、Decimal） |
| 分页 | total/page/size/records |
| traceId | 每个响应都有 traceId |
| DB | 请求字段 ↔ 表列 |
| 不变量 | 金额、库存、状态机 |
| 中间件 | Redis TTL、MQ 事件行 |

### 9.2 失败证据

每个失败用例自动附加：

- 最后请求方法/路径；
- HTTP 状态；
- 响应体（脱敏）；
- traceId；
- 后端日志（按 traceId）；
- 500 时额外日志附件；
- 失败依据文本。

`diagnose.py` 的工程细节：

- 只读日志尾部 8MB，避免百 MB 日志全量扫描；
- traceId 去重，最多保留最近 5 条；
- 跨 `backend/logs`、`pytest_automation/logs` 搜索；
- 排除 `access` 日志，优先应用日志；
- 日志缺失时给出明确提示，不伪造内容。

### 9.3 数据库双检

- `db.py`：只读查询，库存/订单/指纹；
- `db_contract.py`：写接口契约校验；
- 68 个适用写接口全部有落库断言（68/68）；
- 删除类校验 `deleted=true`；
- JSONB/Decimal/Long 做类型归一。

---

## 10. 报告体系

### 10.1 Allure 原生

- 用例状态、附件、历史趋势、分类、套件；
- 失败请求/响应/截图/trace；
- 稳定用例 ID 与 Allure 深链；
- Suites：业务域 → 业务模块 → 接口 → 用例；
- Behaviors：业务域（epic）→ 业务模块（feature）→ 用例（story）；
- 验证维度以 `验证维度：xxx` 标签展示，不再单独成为平级套件。

### 10.2 扩展视图

| 视图 | 内容 |
|---|---|
| 接口列表 | 135 接口、风险排序、参数/返回、测试点抽屉、失败日志 |
| 分类统计 | 维度柱状图/饼图、下钻、500 日志、错误日志列（横切统计，不影响业务套件树） |
| 并行对比 | 串行/并行墙钟、加速比、结果一致性 |
| 覆盖率 | 接口/DB/组件/方法/行、调用链抽屉、补充建议 |
| 缺陷 | 真实失败请求、代码位置、Git 溯源、UTF-8 缺陷单 |
| 用例历史 | 新增/删除/修改/结果迁移 |
| 版本对比 | 两轮状态构成环形图、关键指标条形图、失败模块分布、风险/关注点/建议 |
| 趋势 | 最近 20 轮失败数、行覆盖率、墙钟耗时 |
| 三方组件 | DB/Redis/MQ 实时核验、SQL 证据、复现步骤 |
| UI | Chromium/Firefox 浏览器矩阵 |

技术实现：原生 HTML/CSS/JS + manifest + JSON，随 Allure 静态发布。

### 10.3 覆盖率

- 接口覆盖 135/135；
- 请求方式校验 135/135；
- 写接口 DB 断言 68/68（100%）；
- Redis/MQ 组件 9/9；
- 链路方法覆盖 230/465（49.5%）；
- JaCoCo 行覆盖 72.99%。

方法链来自 call-graph + Java 源码解析，行覆盖来自 JaCoCo XML。

### 10.4 缺陷与 Gitee Issues

- 92 条接口缺陷，92 条可定位；UI 失败会额外生成带浏览器的缺陷并内嵌失败截图；
- 使用 Allure「失败依据」的真实请求/响应/traceId；
- 路径归一为端点模板；
- 堆栈取最底层应用帧；
- 参数解析类标记「入口」，业务异常落到 Service；
- Git 仓库、分支、Commit、作者、blame 行链接；
- 报告内 HTML（UTF-8），仓库内 Markdown；
- `gitee_issues.py` 可自动创建 Gitee Issues：
  - 字段：`title`、`body`、`labels=bug`；优先级/分支/Commit/作者/代码位置等 Gitee 标准字段没有的内容写入正文表格；
  - 幂等：body 中 `zcode-defect-id` 标记，已有 issue 不重复创建；
  - 自包含：无 `GITEE_TOKEN` 时只生成 payload 和 not_submitted 状态，不伪造 URL；
  - 优先级：P0/P1/P2 自动映射 Gitee 原生 priority 4/3/2，并同步 P0/P1/P2 标签；
  - 分支：正文写入可点击的运行分支链接；Gitee 个人仓库 API 的 branch 字段可能返回 null；
  - 作者：按代码作者解析 Gitee login 并在正文 @ 提及；原生 assignee 要求作者是仓库成员；
  - 报告每行提供「本地缺陷」「Gitee 缺陷」两个操作，按钮只显示名称，issue 编号放在 tooltip，href 携带完整 issue URL。

### 10.5 业务分类与接口聚合

- `conftest.py` 不再按测试文件设置 suite，而是调用 `core/business_taxonomy.py`；
- Allure 原生标签只支持 `parentSuite/suite/subSuite` 三层，`group_suites_by_endpoint.py`
  在 `data/suites.json` 的模块节点下插入接口分组节点，形成 4 层视图；
- 接口组显示为 `METHOD /path`，与 `case_endpoint_map.json`、接口矩阵一致；
- 当前：5 个业务域、14 个业务模块、141 个接口组；分类审计 890 条、未归类 0；
- `audit_taxonomy.py` 已接入 `allure_report.sh`，分类漂移会输出告警。

代表性归并：

| 横切验证点 | 归属 |
|---|---|
| MQ 支付事件 | 交易中心 / 订单与支付（标签：消息队列） |
| Redis 验证码/锁定/黑名单 | 会员中心 / 登录与令牌；管理端令牌 → 平台治理 / 身份与权限（标签：缓存一致性） |
| 写接口落库 | 对应业务模块（标签：数据库落库） |
| 大分页/批量写入 | 对应业务模块（标签：大数据量） |
| 参数联动 | 对应业务模块（标签：参数联动） |

### 10.6 版本对比与风险建议

- 归档：`artifacts/history/<run_id>/` 保存不可变 results/manifest/coverage；
- 索引：`artifacts/history/index.sqlite` 保存 runs/case_results，当前 30 轮、27 轮完整；
- 对比：`compare_runs.py` 输出 `ext/data/compare.json` / `trend.json`；
- 图表：通过/失败/跳过环形图、关键指标归一化条形图、失败业务模块条形图；
- 结论：按新增失败、存量失败、覆盖率、耗时、用例增减、可比性生成风险点、关注点和建议；
- 已知失败：`data/known_failures.yaml` 93 条；报告显示已知/未登记/过期/待清理/待归因；
- 最近一轮：`20261103-185052 → 20261103-192352`，890 条，新增 34 条用例，
  新增失败 0、修复 0，存量失败 93（10.4%），本轮完整墙钟 294.9s，综合风险等级“中”；
- 失败集中模块：商品管理 18、身份与权限 15、配置与审计 10、订单与支付 9、收货地址 7。

### 10.7 三方组件查询

- 数据库 38 表/377 字段、ER 图、字段字典、接口 → 表 → SQL；
- Redis 实际 key/命令/返回值、MQ 队列与事件表；
- 仅本机回环的 `thirdparty_server.py`（127.0.0.1:8098）提供受控读写；
- 证据来自真实 DB/Redis/MQ 查询，不使用无来源数字。

---

## 11. 用例治理

| 机制 | 脚本 | 说明 |
|---|---|---|
| 注册表 | `export_cases.py` | 845 条，稳定 ID、内容哈希 |
| 评审台账 | `review_cases.py` | draft/reviewed/approved/legacy |
| 评审门禁 | `review_cases.py --check` | 新增/修改必须 approved |
| 质量门禁 | `case_quality_gate.py` | 元数据、端点方法、DB 覆盖、硬编码 |
| 报告契约 | `check_report_contract.py` | 报告数据结构不漂移 |
| 运行清单 | `finalize_run.py` | 合并多次 pytest、run_id/git/counts/墙钟 |
| 归档/历史 | `archive_run.py` / `case_history.py` | 不可变快照与跨轮 diff |
| 版本对比 | `run_index.py` / `compare_runs.py` | SQLite 索引、两轮对比、趋势、风险建议 |
| 已知失败 | `known_failures.py` + `check_known_failures.py` | 93 条台账；未登记/过期阻断，修复提示清理 |
| 覆盖率门禁 | `check_coverage_gate.py` | 静态 ratchet；夜间行覆盖；DB 100% |
| P0 评审 | `review_p0.py` | 逐条复核单 + 静态证据回填；P0 债 0 |
| 分类审计 | `audit_taxonomy.py` | 业务域/模块/维度分布，未归类检查 |
| 知识库 | `build_knowledge_index.py` | SQLite FTS5 |
| 选测 | `select_tests.py` | git diff → 端点 → 用例 |

门禁策略：

- 新增/内容变更用例必须 approved；
- 存量 P0 已完成逐条静态复核：79 条 P0 全部 approved，P0 债 0；
- 新 P0 未 approved 时 `--strict-p0` 阻断；
- 405 等系统级用例通过 allowlist 豁免。

---

## 12. CI/CD

### 12.1 GitHub Actions

`.github/workflows/nightly-pytest.yml`：

- 每日 02:00（北京时间）触发；
- 起 PG/Redis/MinIO/RabbitMQ；
- 构建后端、起前后端；
- 全量/affected 模式；
- 质量/评审/契约门禁；
- P0 门禁：known_failures、coverage_gate、P0 评审债；
- 报告、归档、知识库；
- 上传 artifacts。

### 12.2 选测

`select_tests.py`：

```text
git diff
  → Java 类 / SQL 迁移表
  → call-graph 端点
  → case_endpoint_map 用例
  → pytest nodeid 清单
```

无命中时回退 smoke，避免“变更没测到”。

### 12.3 发布

`run_parallel.sh --publish`、`publish_parallel.py`、`merge_parallel_artifacts.py`：

- 保留 UI 结果；
- 合并 tests/details/samples；
- 生成 run-manifest；
- 报告深链与映射一致。

---

## 13. 亮点分析

| # | 亮点 | 解决的问题 | 做法 | 价值 |
|---|---|---|---|---|
| 1 | 端点模型驱动 | 人工枚举漏接口 | 135 端点生成 487 巡检 | 接口覆盖 100% |
| 2 | 动态 xdist 分组 | 同接口并发互相污染 | `xdist_group=ep::主体接口` + loadgroup | 并行且隔离 |
| 3 | 两阶段 + serial lane | 库存/限流不能并行 | 阶段 1 并行、阶段 2 串行 | 结果与串行一致 |
| 4 | SKU worker 分片 | 抢库存导致 flaky | `sku_id % worker_count` | 并行稳定 |
| 5 | 随机会员 | 账号共享、脏数据 | unique_phone + 随机数据隔离，保留核验证据 | 用例可重复 |
| 6 | DB 契约 | 只测响应不测落库 | 请求字段 → 表列逐项比对 | 发现真实 500 缺陷 |
| 7 | DB 三态面板 | 把“不适用”误报缺失 | covered/not_applicable/missing | 指标不虚高 |
| 8 | traceId 日志 | 500 只有一句“系统异常” | 日志尾部检索 + 附件 | 可直接定位 |
| 9 | 多层断言 | 只断 HTTP 200 | HTTP/业务码/schema/DB/不变量 | 发现业务错误 |
| 10 | 稳定用例 ID | 重命名导致历史断裂 | registry + content_hash | 历史可追溯 |
| 11 | 评审/质量门禁 | 用例数量涨、质量降 | 元数据/方法/DB/评审 | 资产可治理 |
| 12 | 失败证据 | 复现困难 | 请求/响应/traceId/截图 | 缺陷可复盘 |
| 13 | 缺陷代码定位 | 失败只报用例 | 堆栈最底层应用帧 + 路径归一 | 定位到 Service |
| 14 | Git 溯源 | 缺陷无法追责 | blame 行级作者 + commit | 可追溯 |
| 15 | 方法级链路 | 只有接口级覆盖 | call-graph + 源码解析 + JaCoCo | 看到未覆盖方法 |
| 16 | 逐行覆盖 | 只知道方法部分覆盖 | JaCoCo line counter | 精确到行 |
| 17 | 500 日志抽屉 | 日志埋在附件 | 分类统计内嵌 | 一键查看 |
| 18 | 历史 diff | 不知道本轮变化 | registry/results/coverage diff | 可解释回归 |
| 19 | 知识库 | 经验散落 | SQLite FTS5 + commit/baseline | 可检索 |
| 20 | 夜间选测 | 全量太慢 | git diff → 端点 → 用例 | 快速反馈 |
| 21 | 业务分类 + 接口聚合 | 套件按文件散落、专项割裂 | 5 域/14 模块/141 接口组；维度转标签 | 按业务聚焦 |
| 22 | 版本对比图表与风险建议 | 只看数字不知道风险 | 环形图/条形图/失败模块 + 规则化结论 | 可决策 |
| 23 | 归档索引与趋势 | 历史轮次不可比 | 不可变快照 + SQLite + 25 轮趋势 | 可追溯 |
| 24 | 已知失败台账 | 93 条失败每轮全红、掩盖新回归 | known_failures + 未登记/过期门禁 + 报告 KPI | 新失败可阻断 |
| 25 | 覆盖率 ratchet 门禁 | 覆盖率只展示、悄悄回退 | 接口/链路/DB 绝对下限 + 方法/行 delta | 指标不回退 |
| 26 | 35 个写接口 DB 断言 | 写接口只测响应不测落库 | 契约 + 14 条扩展用例 + SQL 证据 | DB 68/68 |
| 27 | P0 评审清零 | 65 条 legacy(auto) 长期挂账 | P0 复核单 + 逐条静态/代码复核 | P0 债 0 |
| 28 | 接口级场景试点 | 维度文件重复 setup、链路分散 | 订单/购物车/地址接口类 + 参数化校验 + 正向 API/DB/MQ 分层 | 减少重复、保留隔离 |

### 13.1 关键工程决策

1. **不按 HTTP 方法并发，按接口并发**
   同一接口的 GET/POST/PUT/DELETE 共享数据，按方法拆并发会制造竞态；按主体接口分组更符合业务隔离。

2. **静态覆盖与运行时覆盖分开**
   静态回答“有没有测到”，JaCoCo 回答“执行了多少行”；两者不能互相替代。

3. **报告数据与 Allure 解耦**
   扩展页消费 JSON，不直接解析 Allure HTML；Allure 升级不影响视图。

4. **横切维度用标签，不拆业务套件**
   MQ/Redis/DB/大数据量/参数联动是验证维度，不是业务归属；套件树只表达业务域和模块，
   维度通过 tag 筛选，避免同一业务被拆成多个“专项套件”。

5. **接口聚合是对 Allure 树的派生，不改原始结果**
   Allure 原生标签不足时，在 `data/suites.json` 插入接口分组；失败结果、稳定 ID、详情附件不变。

6. **失败证据优先于日志猜测**
   先读请求/响应/traceId，再查日志；日志缺失时明确标注，不编造堆栈。

7. **门禁只拦“新债务”**
   P0 评审债已清零；新增/修改仍严格 approved，known_failures 未登记/过期仍阻断。
   P1/P2 存量评审债继续告警，不与 P0 一起一次性阻塞。

---

## 14. 当前指标

| 指标 | 当前值 |
|---|---|
| 逻辑用例 / 执行结果 | 845 条逻辑用例；890 条结果（API 796 + UI 94） |
| 执行状态 | 794 通过 / 93 失败 / 3 跳过 |
| Allure 计数 | Overview 890；Suites 叶子 890 |
| 业务分类 | 5 业务域 / 14 业务模块 / 141 接口组 / 362 测试大分类；未归类 0 |
| UI | Chromium 47/47、Firefox 47/47（本地 Vite，并行） |
| 接口覆盖 | 135/135 |
| 请求方式校验 | 135/135 |
| 写接口 DB 断言 | 68/68 适用（100%；10 个认证/令牌不适用） |
| Redis/MQ 组件 | 9/9 |
| 链路方法覆盖 | 230/465（49.5%） |
| JaCoCo 行覆盖 | 72.99%（2421/3317） |
| 已知失败 | 93 条台账；未登记 0、过期 0、待缺陷归因 13 |
| P0 评审 | 90/90 approved；P0 债 0 |
| 缺陷 | 92 条，92 条可定位 |
| 历史 / 趋势 | 30 轮归档、27 轮完整；最近对比 185052→192352 |
| 版本对比 | 新增失败 0、修复 0、新增用例 34；风险等级中 |
| 本轮墙钟 | 294.9s（上一基线 315.5s） |
| 知识库 | 1550 条 |

> 93 条失败为已知缺陷护栏（D-06～D-23），不是框架误报；修复后自动转绿。

---

## 15. 新增一条 API 用例

1. 在 `data/case_meta.yaml` 增加标题/验证点；
2. 写测试：使用 `customer/admin/sku/order` 夹具，不直接 new ApiClient；
3. 断言：`ok/error` + schema + traceId + DB（写接口）；
4. 标记 `P0/P1/P2`、`smoke/security/...`；
5. `python scripts/export_cases.py` 生成稳定 ID；
6. `case_quality_gate.py` + `review_cases.py --check`；
7. 跑单测 → 全量 → `make report`（自动 finalize、分类、接口聚合、归档/索引/对比）；
8. 新接口写入 `endpoint_matrix.json`（或运行生成脚本）。

---

## 16. 风险与后续

| 风险/缺口 | 说明 | 计划 |
|---|---|---|
| 93 条已知失败 | 已入台账；其中 13 条暂无缺陷单归因 | 逐步补 bug_id/owner；修复后清理台账 |
| 35 个写接口 DB 缺口 | 已补齐契约+用例+证据 | 已 closed：68/68，门禁保护不回退 |
| P0 评审债 | 65 条已逐条静态复核，2 条代码级复核 | 已 closed：P0 债 0；owner 会签建议保留 |
| 已知失败与缺陷单差异 | 13 条 unmapped（运行失败但未生成缺陷单） | 补缺陷归因，禁止长期 `qa-team` |
| WebKit 未纳入 | 本机 new_page 挂起 | 换环境/单 worker 验证 |
| JaCoCo 整轮口径 | 非单接口归属 | 夜间按接口 reset 可选 |
| 方法链正则解析 | 不处理反射/动态代理 | 后续可接 AST |
| 并行基准历史 | 仍是 701 条历史基线 | 用例已增至 848，需重跑正式对比 |
| UI 前端依赖 | dev 环境需要本地 Vite 5174/5173 | 文档/启动命令已补充；CI 可注入 URL |
| Allure 接口聚合 | 依赖 `suites.json` 结构 | 脚本失败只告警；Allure 升级需回归验证 |

---

## 17. 常用命令

```bash
cd pytest_automation

# API
TEST_ENV=dev ADMIN_PASSWORD=... make api
# 并行（两阶段）
TEST_ENV=dev ADMIN_PASSWORD=... make api-parallel-publish

# UI：先启动仓库内前端（dev 默认 5174/5173）
(cd ../shang-mall && npm ci && npm run dev)
(cd ../shang-admin-web && npm ci && npm run dev)
TEST_ENV=dev ADMIN_PASSWORD=... bash scripts/run_ui_parallel.sh
UI_HEADED=0 ADMIN_PASSWORD=... bash scripts/run_ui_parallel.sh

# 报告：自动 finalize → Allure → 业务分类/接口聚合 → 归档/索引/对比/趋势
make report
# 或启动本地静态服务
bash scripts/allure_report.sh --serve

# 版本对比与分类审计
python3 scripts/compare_runs.py
python3 scripts/audit_taxonomy.py

# 缺陷同步（无 token 仅生成 payload，不提交）
GITEE_TOKEN=... make gitee-issues

# P0 门禁
python3 scripts/check_known_failures.py      # 未登记/过期失败阻断
python3 scripts/check_coverage_gate.py      # 静态 ratchet；nightly 加 --require-runtime
python3 scripts/review_cases.py --check --strict-p0
python3 scripts/review_p0.py                # 生成 P0 逐条评审单

# 质量/评审/契约
python3 scripts/case_quality_gate.py
python3 scripts/review_cases.py --check
python3 scripts/check_report_contract.py \
  --baseline artifacts/api-matrix.baseline.json \
  --current artifacts/allure-report/ext/data/api-matrix.json
```

---

## 18. 关键文件索引

| 文件 | 作用 |
|---|---|
| `conftest.py` | 业务域/模块标签、用例 ID、失败证据、xdist 分组、运行清单 |
| `core/api_client.py` | HTTP 客户端、重试、traceId、Allure、埋点 |
| `core/business_taxonomy.py` | 业务分类、主接口选择、维度解析 |
| `core/endpoint_recorder.py` | 用例→接口、请求响应样本 |
| `helpers/db_contract.py` | 写接口 DB 契约 |
| `helpers/diagnose.py` | traceId 日志 |
| `data/business_taxonomy.yaml` | 业务域/模块/维度/接口优先级规则 |
| `data/endpoint_attribution.yaml` | 用例 → 主体接口显式归属（避免 setup 端点抢占） |
| `tests/api/endpoints/test_orders.py` | 订单接口场景：复用上下文 + 参数化 + API/DB/MQ 分层 |
| `tests/api/endpoints/test_cart_address.py` | 购物车/地址接口场景：复用上下文 + 参数化 + API/DB 分层 |
| `tests/api/endpoints/test_auth_payment_after_sales.py` | 认证/支付/售后/评价接口场景：Redis、DB、MQ、幂等 |
| `tests/api/endpoints/test_admin_crud.py` | 管理端基础 CRUD 接口场景：按 POST/PUT/DELETE 归属 + DB 分层 |
| `scripts/run_parallel.sh` | 两阶段并行 |
| `scripts/build_api_matrix.py` | 接口视图数据 |
| `scripts/group_suites_by_endpoint.py` | 业务模块下按接口聚合 Allure Suites |
| `scripts/build_coverage_matrix.py` | 覆盖率/方法链 |
| `scripts/build_defects.py` | 缺陷/代码定位/Git、UI 截图 |
| `scripts/gitee_issues.py` | Gitee Issues 幂等创建/UTF-8 正文 |
| `scripts/run_index.py` / `compare_runs.py` | 运行索引、两轮对比、趋势、风险建议 |
| `scripts/check_known_failures.py` | 已知失败/过期豁免门禁 |
| `scripts/check_coverage_gate.py` | 覆盖率 ratchet 门禁 |
| `scripts/review_p0.py` | P0 逐条评审单/静态复核回填 |
| `data/known_failures.yaml` | 93 条已知失败台账 |
| `data/coverage_gate.yaml` | 覆盖率阈值配置 |
| `tests/api/test_write_persistence_extended.py` | 35 个缺口的落库断言 |
| `scripts/audit_taxonomy.py` | 业务分类审计 |
| `scripts/report_shell/app.js` | 扩展视图（含版本对比图表/建议） |
| `.github/workflows/nightly-pytest.yml` | 夜间 CI |

---

## 19. 结论

这套框架的核心不是“用例数量”，而是把 API 自动化从“脚本集合”提升为可运营的测试资产：

- **执行层**：隔离、并行、可重复；
- **断言层**：HTTP/业务/DB/不变量/中间件；
- **证据层**：请求响应、traceId 日志、调用链、代码位置；
- **视图层**：业务域/模块/接口/用例、维度标签、接口聚合；
- **对比层**：运行归档、SQLite 索引、两轮 diff、趋势、风险与建议；
- **治理层**：注册表、评审、门禁、覆盖率、历史、CI。

当前 135/135 接口覆盖、68/68 写接口 DB 断言、9/9 组件校验、230/465 方法覆盖；本轮 890 条结果
794 通过 / 93 已知失败 / 3 跳过，版本对比确认新增失败 0。后续重点是给 13 条已知失败补缺陷归因、
降低 93 条存量缺陷、把方法覆盖推进到 70% 以上，并启用新增 Java 行覆盖门禁。

---

## 20. 进一步可完善的方向与建议

> 原则：先解决“指标是否可信、回归是否可阻断”，再补“更深覆盖、更复杂场景”。
> 下面的优先级按“风险 × 收益 ÷ 成本”排序，不建议一次性全做。

### 20.1 成熟度评估

| 维度 | 当前水平 | 依据 | 主要短板 |
|---|---|---|---|
| 执行稳定性 | 较高 | 随机会员、SKU 分片、serial lane、基线恢复 | flaky 没有量化与隔离 |
| 接口完备性 | 高 | 135/135 接口、487 巡检、68/68 DB 断言 | 粗粒度响应 schema 契约仍不足 |
| 断言深度 | 中高 | HTTP/业务码/DB/不变量/MQ/Redis | schema 契约、分支覆盖不足 |
| 缺陷闭环 | 中高 | 93 条已知失败入账、92 条缺陷、代码/Git 溯源、Gitee 双入口 | 13 条待缺陷归因；Gitee 状态同步待完善 |
| 覆盖率治理 | 中高 | 静态 ratchet 门禁、JaCoCo 行覆盖 | 新增 Java 行覆盖 70% 仍待第二阶段 |
| 安全测试 | 中 | 匿名/越权/注入/XSS | 缺完整权限矩阵、限流/上传/SSRF |
| 中间件测试 | 中 | Redis 9 项、MQ 3 项 | 缺故障注入、积压、outbox |
| CI/反馈速度 | 中 | nightly + 选测 | 缺 PR 快速门禁、UI/需求选测 |
| 报告体验 | 中高 | 10+ 视图/子页、业务分类、接口聚合、版本对比图表 | 大数据量渲染、可访问性、移动端 |

### 20.2 P0：已交付（原 1–2 周窗口）

> 状态：**四项已落地**。总验收由“新失败可阻断、覆盖率不回退、DB 断言 68/68、P0 评审债 0”构成。
> 实现仍遵循“有证据、可复现、可豁免但会过期”，不做只改报告数字的假闭环。

| # | 事项 | 状态 | 落地证据 | 阻断点 |
|---|---|---|---|---|
| 1 | 已知失败/隔离 | 已落地 | 93 条台账；未登记 0/过期 0；13 条待缺陷归因 | 未登记失败、过期豁免 |
| 2 | 覆盖率门禁 | 已落地 | `coverage_gate.yaml` + `check_coverage_gate.py`；门禁通过 | 指标回退 |
| 3 | 35 个写接口 DB 断言 | 已落地 | 68/68 covered；14 条扩展落库用例 | 适用端点覆盖率下降 |
| 4 | 65 条 P0 评审债 | 已落地 | P0 90/90 approved；P0 债 0 | 新 P0 未评审 |

> 说明：P0 评审由 `zcode-static-review` 做逐条静态复核，其中 2 条缺端点映射的用例做了代码级复核；
> ledger 记录 reviewer/date/comment/hash，业务 owner 仍建议会签，不把 AI 复核伪装成人工签字。

#### 1. 建立“已知失败/隔离”机制

**当前状态**

- 已生成 `data/known_failures.yaml`：93 条当前失败全部入账；未登记 0、过期 0；
- 93 条中 80 条关联缺陷单，13 条为 `DEF-UNMAPPED-*`，已标记“待缺陷归因”，不伪造 bug 编号；
- 版本对比页已显示已知/未登记/过期/待清理/待归因；`check_known_failures.py` 门禁通过；
- 每轮失败仍会全红，但只有未登记或过期失败会阻断，已知失败保留红色与缺陷链接。

**目标**

- 把失败分成三类：**未登记失败（unexpected）**、**已知失败（known）**、**已修复待清理（fixed）**；
- 只有未登记失败阻断合并/发布；已知失败必须有缺陷编号、owner、原因、到期日；
- 到期未续期的豁免自动失效，防止“永久红”。

**落地步骤**

1. 新增 `data/known_failures.yaml`，以 `case_id` 为主键、`nodeid` 为运行期锚点；首版只录入已确认的 93 条，先核对 92 条缺陷单的差异；
2. 新增 `scripts/check_known_failures.py`，读取 `results.json` + `compare.json`：
   - `failed` 且不在台账 → 退出码 1，列出 case_id、标题、模块、接口；
   - `failed` 且台账存在但 `expires_at` 过期 → 退出码 1；
   - 台账中标记 known 但本轮 passed → 输出“可清理”清单，退出码 0；
   - 同一 `case_id` 重复/无缺陷编号/无 owner → 退出码 1；
3. 在 `compare_runs.py` 的 `insights` 中增加 `knownFailures`、`unexpectedFailures`、`expiredWaivers`，报告 KPI 增加“已知失败数 / 未登记失败数 / 隔离率”；
4. CI 顺序改为：跑测试 → `compare_runs.py` → `check_known_failures.py` → 报告；新增失败阻断，已知失败不阻断但保留红色标记与缺陷链接；
5. 修复流程：缺陷关闭后按 `case_id` 清理台账，下一轮 `fixed` 列表应包含该用例；清理动作由修复 PR 完成，避免自动删除掩盖问题。

**数据结构**

```yaml
version: 1
entries:
  - case_id: API-ORDER-012
    nodeid: tests/api/test_order.py::TestOrderState::test_sandbox_payment
    bug_id: BUG-ORDER-003
    severity: P0
    owner: backend-order
    reason: "沙箱支付回调延迟，已知缺陷"
    expires_at: 2026-12-31
    status: active
```

**验收**

- 人为把一条通过用例改成失败：未登记 → CI 失败，报告显示“未登记失败 1”；
- 登记录入后重跑：CI 通过，但报告仍显示已知失败和到期日；
- 把该用例修好：`fixed` 列表出现，CI 提示清理台账；
- 把 `expires_at` 改为过去时间：CI 失败并指出过期条目；
- 93 条失败全部有 case_id 与 owner；80 条有缺陷单，13 条 `DEF-UNMAPPED-*` 进入待归因清单；
- `check_known_failures.py` 在未登记失败/过期豁免/缺 owner 时退出 1。

**风险与边界**

- 不能把“本轮不想修”批量塞进台账；每条必须有缺陷单和到期日；
- 已知失败不等于忽略，报告仍保留红色、接口视图仍可下钻；
- 与版本对比分开：`stillFailing` 是事实，`known` 是管理决策，二者不能混为一个指标。

#### 2. 覆盖率门禁与增量阈值

**当前状态**

- 静态覆盖率：接口 135/135（100%）、写接口 DB 断言 68/68（100%）、链路方法 230/465（49.5%）、链路节点 475/475；
- 运行时行覆盖 72.99%（2421/3317），版本对比页显示相对基线变化；
- `data/coverage_gate.yaml` + `scripts/check_coverage_gate.py` 已落地；`make coverage-gate` 与 nightly 均通过；
- 门禁已从“只展示”变成可阻断：接口/链路/DB 绝对下限，方法/DB/行覆盖 ratchet；
- `new_java_line_rate_enabled=false`，新增行覆盖 70% 仍标为第二阶段，避免虚报。

**目标**

- 先做 **ratchet 门禁**（不允许比上一轮更差），再逐步提高绝对目标；
- PR 只跑静态门禁，夜间额外跑 JaCoCo 行覆盖；
- 任何豁免必须写在配置中并带原因、owner、到期日。

**阈值设计**

```yaml
# data/coverage_gate.yaml
version: 1
static:
  interface_rate_min: 100.0          # 不允许漏接口
  chain_rate_min: 100.0              # 静态链路节点完整
  chain_method_rate_min: 49.5        # 当前基线，只升不降
  write_db_rate_min: 100.0           # 68/68；已补齐，不允许回退
  write_db_delta_min_pp: -1.0        # 相对上一轮最多允许 -1pp
runtime:
  line_rate_delta_min_pp: -1.0       # 相对上一轮最多允许 -1pp
  new_java_line_rate_min: 70.0       # 第二阶段接入 diff 覆盖
  require_in_nightly: true           # PR 无 JaCoCo 时只告警，夜间必须执行
```

**落地步骤**

1. 新增 `scripts/check_coverage_gate.py`，读取：
   - `ext/data/coverage.json`（静态接口/DB/方法/链路）；
   - `ext/data/compare.json`（上一轮 vs 本轮）；
   - `artifacts/jacoco/report.xml`（夜间运行时）；
2. 比较基准从 `artifacts/history/index.sqlite` 的上一轮完整运行取，禁止读取“当前覆盖文件”自比；
3. 失败信息必须包含：指标、当前值、基线值、允许下限、差距、责任模块/接口；
4. 接入 `make report` 后置检查和 nightly；PR 快速门禁只跑静态，夜间 `--require-runtime`；
5. “新增 Java 代码行覆盖 ≥70%”放在第二阶段：先用 JaCoCo + git diff 生成新增行集合，再纳入门禁；当前 P0 不虚报这一项。

**验收**

- 删除任意一条 `db_contract` 断言：DB 断言率下降，CI 失败并指出具体端点；
- 某一轮方法覆盖率从 49.5 降到 48.0：门禁失败（超过 -1pp）；
- 夜间缺失 JaCoCo XML：`--require-runtime` 模式失败，PR 模式明确告警；
- 修改阈值或豁免：必须提交配置 diff，报告展示豁免原因和到期日；
- 连续两轮指标不下降时，门禁通过并生成趋势点。

**风险与边界**

- 当前方法覆盖仅 49.5%，不能直接设 60% 绝对门槛；先 ratchet，避免“为了过门禁批量删弱断言”；
- 覆盖率是“充分性线索”不是“正确性证明”，不能替代业务断言、DB 校验和缺陷回归；
- JaCoCo 整轮口径不能归因到单接口；按接口切分放 P1，不作为 P0 阻断条件。

#### 3. 补齐 35 个写接口的 DB 断言

**当前状态**

- 适用写端点 68 个，已全部有 DB 断言（68/68，100%）；10 个认证/令牌端点明确 `not_applicable`；
- 新增 `tests/api/test_write_persistence_extended.py` 14 条用例，覆盖 35 个原缺口；
- 商品管理 11、身份与权限 8、配置与审计 4、文件服务 4、收藏与足迹 3、库存与履约 2、
  订单与支付 1、购物车 1、会员资料 1 均已补齐；
- `/api/orders`、`/api/me`、`/api/cart/clear-invalid` 等原“有接口用例但未归因”的端点已补契约并验证；
- 扩展用例单跑 14/14 通过，全量回归 752 通过 / 93 已知失败 / 3 跳过。

**目标与分批**

已按两周批次把 35 个缺口全部补到 covered；**最终 68/68（100%）**。原分批计划如下，已完成：

| 批次 | 范围 | 数量 | 时间 | 重点 |
|---|---|---:|---|---|
| A | 商品管理 11 + 库存与履约 2 + 购物车 1 + 订单与支付 1 + 会员资料 1 + 收藏/足迹 2 | 18 | 第 1 周 | P0 交易/商品链路，优先复用现有夹具 |
| B | 身份与权限 8 + 配置与审计 4 + 文件服务 4 + 收藏/足迹 1 | 17 | 第 2 周 | 管理端权限、字典/配置、文件元数据 |

**每个端点的完成定义（DoD）**

1. `data/write_contracts.yaml` 增加端点 → 表/字段/定位键/生成列/类型归一；
2. `tests/api/test_write_persistence.py`（或对应管理端往返测试）增加“正常写 + 关键字段比对”；
3. 用响应 ID、自然唯一键或路径参数定位刚写入行；复杂端点使用“响应 ID + DB 行 + 状态机”组合；
4. Allure 出现“DB 查询 / 字段比对”步骤和 SQL/结果行附件；
5. `coverage.json` 的该端点 `dbStatus=covered`，且 `dbReason` 为空；
6. 有失败时保留证据，不通过删除数据/放宽断言转绿。

**验收**

- 35 个缺口全部有契约、用例、证据和 covered 状态；最终 68/68（100%）；
- 每批提交后覆盖率页与 `coverage.json` 同步，版本对比 `dbRate` 不下降；
- 至少抽查 5 个端点，用 SQL 手工复核请求字段确实落库；
- 失败端点进入缺陷库并关联 owner，不以“待补”长期挂账。

**风险与边界**

- 文件上传、出入库、库存调整等端点构造成本高，优先使用现有 `admin`/`db_ready` 夹具；
- 不为了覆盖率给只读查询/认证接口强加 DB 断言，10 个不适用端点保持 `not_applicable`；
- 商品/库存写入会影响后续用例，继续使用随机 SKU/独立会员，不清理证据数据。

#### 4. 清理 65 条 P0 评审债

**当前状态**

- 注册表 845 条中 P0 90 条，已全部 approved；P0 债 0；
- 65 条原 `legacy(auto)` 已通过 `scripts/review_p0.py` 逐条静态复核；
- 其中 API-AUTH-003、API-INV-002 因端点映射缺失，做了代码级复核；
- 新增 14 条落库用例（含 3 条 P0）已评审并 approved；
- `review_cases.py --check --strict-p0` 已通过，后续新 P0 未评审会阻断。

**评审批次**

| 批次 | 业务模块 | P0 债 | 评审重点 |
|---|---|---:|---|
| 1 | 订单与支付 22、购物车 5、库存与履约 1 | 28 | 金额/库存/状态机/幂等 |
| 2 | 登录与令牌 13、收货地址 5、会员资料 2 | 20 | 认证、越权、字段校验 |
| 3 | 商品与搜索 5、商品管理 3、售后服务 1、评价管理 2 | 11 | 商品状态、评价/售后规则 |
| 4 | 身份与权限 3、配置与审计 2、管理端基础 1 | 6 | 管理端权限与配置 |

**落地步骤**

1. 从注册表生成 `artifacts/review/p0-debt.csv`：case_id、标题、模块、owner、当前状态；
2. 4 次评审会（每次 60–90 分钟）逐条确认：保留 / 修改 / 退役；禁止“批量 approve”；
3. 评审结论写回 `data/case_review.yaml`：status、reviewer、date、comment、title_hash、content_hash；
4. 确认无效的用例在注册表标记 `retired`，保留历史记录；不直接删除 nodeid 导致历史断裂；
5. P0 债 ≤10 后，把 `review_cases.py --check --strict-p0` 纳入 PR 必跑；
6. 新 P0 用例必须先 approved 才能合并，评审人与作者分离（至少一人复核）。

**验收**

- P0 债 0；每条的 reviewer/date/comment/内容哈希齐全；
- 新增 P0 未评审时 CI 阻断；retired 用例有退役原因和替代用例（如有）；
- `review_cases.py --check --strict-p0` 在 P0 债达标后稳定通过；
- 评审结果可在报告筛选，不再只靠 YAML 人工查看。

**风险与边界**

- 评审不是“点通过”，重点是验证点是否可执行、断言是否有意义、数据是否隔离；
- 65 条已按 4 个批次逐条复核（其中 2 条做了代码复核）；业务 owner 仍建议会签；
- 对存量 P1/P2 继续 `legacy(auto)` 告警，不与 P0 一起一次性阻塞。

### 20.3 P1：1–2 个月

#### 5. MQ 可靠性：outbox + 故障注入

**现状**：支付成功后 `@TransactionalEventListener(AFTER_COMMIT)` 直接发 MQ；RabbitMQ 不可用时事件会丢；测试只覆盖正常消费/重复/DLQ。

**建议**：

- 引入 **Transactional Outbox**：业务事务内写 `order_event_outbox`，独立 relay 投递 MQ；
- relay 支持重试、退避、死信、积压监控；
- 测试补：
  - broker 停止时业务成功、outbox 保留、恢复后补发；
  - 消费者异常重试/DLQ；
  - 积压恢复；
  - 事件顺序/重复投递；
- 报告中增加 MQ 积压与消费延迟指标。

**验收**：RabbitMQ 停机不影响支付主流程；恢复后事件最终一致；有积压告警。

#### 6. Redis 故障与缓存一致性

**现状**：验证码 TTL、登录锁定、黑名单；测试直接操作 Redis。

**建议**：

- 补 Redis 不可用/超时降级用例；
- 补缓存与 DB 一致性：验证码消费、登录锁定计数、黑名单 TTL；
- 键命名空间按 run_id 隔离，避免并行污染；
- 对关键键增加 TTL 上限/下限断言与清理验证。

**验收**：Redis 故障时接口行为明确（降级/报错），不出现静默脏状态。

#### 7. 权限矩阵与安全扩展

**现状**：匿名、会员/管理员越权、SQL 注入、XSS、超大分页。

**建议**：

- 建立 `role × endpoint` 权限矩阵，自动生成“应允许/应拒绝”用例；
- 补 OWASP API Top 10：
  - BOLA/IDOR（已有部分）；
  - 批量赋值（mass assignment）；
  - 速率限制/暴力破解；
  - 文件上传类型/大小/路径穿越；
  - SSRF/URL 白名单；
  - 错误信息泄露。
- 安全用例保持业务模块归属，通过 `验证维度：安全` 标签和“分类统计”维度视图筛选，不单独拆散业务套件。

**验收**：每个受保护端点至少有 1 条允许 + 1 条拒绝；高风险端点有专项。

#### 8. OpenAPI/Schema 契约漂移

**现状**：端点模型是静态 JSON；没有 schema 断言和 OpenAPI diff。

**建议**：

- 从后端生成/导出 OpenAPI，CI 对比上一版本；
- 测试响应按 JSON Schema 校验（字段类型、必填、枚举、格式）；
- 对 breaking change 阻断（删字段、改类型、改必填）；
- 将 schema 版本写入 run-manifest，报告可追溯。

**验收**：后端改字段类型/删字段，CI 能发现并定位到端点。

#### 9. 覆盖率归属：按接口/按测试

**现状**：JaCoCo 是整轮覆盖；方法/行覆盖无法精确归属到单个接口或单条用例。

**建议**：

- 夜间按 `xdist_group=ep::接口` 串行执行 + JaCoCo dump/reset，生成接口级行覆盖；
- 或接入 OpenTelemetry/JaCoCo per-test listener，把执行数据按测试切分；
- 报告中增加“接口行覆盖率”和“新增代码覆盖率”；
- 保留整轮覆盖率作为兜底。

**验收**：任选 10 个 P0 接口，能看到各自行覆盖；新增代码覆盖率可门禁。

#### 10. PR 快速门禁与选测扩展

**现状**：nightly 全量 + 后端选测；PR 反馈仍偏慢。

**建议**：

- PR 流水线：静态检查 + 质量/评审 + smoke + impacted API（≤10 分钟）；
- 选测扩展：
  - 后端 Java 变更 → 端点（已有）；
  - SQL 迁移 → 表 → 端点（已有）；
  - 前端变更 → UI 用例（新增）；
  - 需求文档 diff → requirement_id → 用例（新增）；
- 夜间保留全量 + JaCoCo + 多浏览器。

**验收**：PR 10 分钟内给出“影响范围 + 必跑用例 + 结果”。

#### 11. Flaky 治理与顺序独立性

**现状**：`--reruns 1` 掩盖部分不稳定；没有 flaky 率。

**建议**：

- 记录每次尝试结果，统计 flaky 率（首次失败/最终通过）；
- 报告增加“flaky 用例 Top N、按接口分布”；
- 对 flaky 用例自动打标签/隔离，要求 owner 处理；
- 增加 `pytest-randomly` 夜间任务验证顺序独立性；
- 串行 lane 用例单独统计。

**验收**：flaky 率可见；连续两轮随机顺序结果一致。

#### 12. 测试数据工厂与清理验证

**现状**：随机会员和 SKU 分片较好，但复杂实体（商品、角色、出入库）缺统一工厂；清理失败只记录。

**建议**：

- 建 `helpers/factories/`：product、user、role、permission、in-out、file；
- 每个工厂返回“实体 + 清理器”，用例结束自动回收；
- 清理后做存在性校验，失败写入 `cleanup-leaks.json`；
- 报告增加“数据泄漏”指标。

**验收**：全量跑完无残留会员/订单/商品；清理失败可追踪。

### 20.4 P2：季度级

#### 13. 方法链从正则升级到 AST/字节码

**现状**：正则解析字段/方法/调用，无法处理重载、lambda、动态代理、反射。

**建议**：

- 使用 JavaParser/tree-sitter 或后端构建期生成方法调用图；
- 结合 Spring Actuator mappings + bytecode call graph；
- 对动态代理/Feign/MQ 消费者单独建模；
- 报告中标注“静态推断/运行时确认”。

**验收**：复杂 Service 调用链准确率 ≥ 90%，误报可解释。

#### 14. 测试有效性：变异测试/属性测试

**现状**：用例通过不代表能发现缺陷。

**建议**：

- 对核心 Service 跑 PIT mutation testing（夜间/周级）；
- 用 Hypothesis 做输入属性测试（金额、数量、分页、字符串边界）；
- 对 JSON 解析、金额计算、库存扣减做 property-based；
- 结果进入报告“测试有效性”视图。

**验收**：核心模块 mutation score ≥ 60%；发现的新缺陷进入缺陷库。

#### 15. 性能与稳定性专项

**现状**：只验证正确性，不做容量。

**建议**：

- 选 5 条 P0 链路做 k6/Gatling 基准（登录、商品列表、加购、下单、支付）；
- 关注 P95/P99、错误率、库存锁竞争、DB 连接池；
- 与功能测试分离，独立环境/数据；
- 总耗时趋势已进入版本对比页；后续补 P95/P99 与按接口耗时，不与功能通过率混在一起。

**验收**：P0 链路有基线；性能回退可告警。

#### 16. 可视化/可访问性/移动端

**现状**：Chromium + Firefox 关键旅程；无视觉回归、无障碍、移动端。

**建议**：

- Playwright 截图对比（关键页面）+ axe 可访问性扫描；
- 增加 375×812 移动视口用例；
- WebKit 在稳定环境纳入夜间；
- 视觉差异进入独立报告，不阻断功能门禁。

**验收**：关键页面视觉基线；a11y 严重问题为 0；移动端主流程通过。

#### 17. 需求追踪与知识库增强

**现状**：注册表/端点/用例/缺陷可检索；需求文档没有机器映射。

**建议**：

- `case_meta.yaml` 增加 `requirement_id`，与 `requirementTracking.markdown` 对齐；
- 报告增加“需求覆盖率/无用例需求/无需求用例”；
- 知识库在关键词 FTS5 基础上增加 embedding 检索（可选）；
- 每条结论保留 commit/baseline 版本。

**验收**：任一需求可查到用例/结果/缺陷；反向可查用例来源。

#### 18. 缺陷闭环与 Gitee

**现状**：本地缺陷库 + Gitee Issues 自动创建（需 `GITEE_TOKEN`）；无 token 时生成 payload，不伪造 issue。状态同步尚未实现。

**建议**：

- 完善 Gitee 适配层：状态回写、指派人/里程碑、UI 截图上传；
- 稳定缺陷 ID（case_id + 失败签名）跨轮去重；
- 同步修复状态，自动把“已修复”用例转绿并关闭缺陷；
- 凭据仅环境变量，操作留审计日志。

**验收**：缺陷单可一键推送；状态双向同步；无重复单。

#### 19. 报告性能与可访问性

**现状**：coverage.json 约 1.3MB，135 行全量渲染；报告附件约 1.5GB。

**建议**：

- 覆盖表分页/虚拟滚动；大 JSON 按接口懒加载；
- 语义化 table/aria、键盘可达、对比度检查；
- 报告产物按保留策略清理（如 30 天），大附件外置；
- 增加“报告加载耗时/体积”监控。

**验收**：报告首屏 < 2s；键盘可完成主要操作；体积可控。

#### 20. 工程与供应链

**现状**：requirements 使用范围约束；无 lint/type/secret scan；Python 3.13。

**建议**：

- 使用 uv/pip-tools 锁定依赖，生成 lock 文件；
- pre-commit：ruff、mypy（渐进）、gitleaks；
- CI 增加依赖漏洞扫描（pip-audit）；
- 统一 Python/Node/Java 版本矩阵；
- 测试代码也纳入格式化与静态检查。

**验收**：依赖可复现；无高危漏洞；提交前自动检查。

### 20.5 不建议短期投入

| 项 | 原因 |
|---|---|
| 全量三浏览器每 PR 跑 | 成本高、WebKit 本机不稳定；夜间足够 |
| 每接口 JaCoCo 每次 PR | 需串行 dump/reset，时长不可接受；夜间按需 |
| 向量 RAG/大模型自动生成用例 | 先保证用例治理与覆盖率门禁，收益不确定 |
| 大规模性能压测 | 需要独立环境与数据，先做 5 条 P0 基线 |
| 全量变异测试 | 运行时间长，先对核心 Service 周级跑 |

### 20.6 建议路线图

| 阶段 | 时间 | 交付 | 验收指标 | 状态 |
|---|---|---|---|---|
| P0-1 | 第 1 周 | known_failures + 覆盖率门禁 | 新失败阻断；覆盖不回退 | 已完成 |
| P0-2 | 第 1–2 周 | 35 个 DB 断言分批补齐 | DB 68/68 | 已完成 |
| P0-3 | 第 2 周 | 65 条 P0 评审清理 | P0 债务 0 | 已完成 |
| P1-1 | 第 3–4 周 | MQ outbox + Redis 故障 | 停机不丢事件 |
| P1-2 | 第 4–6 周 | 权限矩阵 + Schema 契约 | 受保护端点 allow/deny 全覆盖 |
| P1-3 | 第 6–8 周 | PR 快速门禁 + flaky 治理 | PR ≤ 10 分钟；flaky 可见 |
| P2-1 | 季度 | AST/字节码链路 + 变异测试 | 链路准确率 ≥ 90% |
| P2-2 | 季度 | 视觉/a11y/移动端 + 性能基线 | P0 链路有基线 |

### 20.7 一句话建议

**先把“失败是否可信、覆盖是否回退、数据是否脏”三件事做成门禁，再投入更深的链路分析和更复杂的场景。**
当前框架已经具备“能跑全、能定位、能治理”的基础，下一步的重点不是继续堆用例，而是让指标和门禁真正驱动质量决策。

---

## 21. 变更记录

| 版本 | 日期 | 变更内容 | 影响章节 |
|---|---|---|---|
| v1.6 | 2026-11-03 | 完成 6.5 剩余接口迁移：短信登录/支付/售后/评价 9 条，品牌/类目/字典/部门/仓库 CRUD 25 条；新增接口归因与参数化逆向，报告聚合 141 个接口组、362 个测试大分类；避免新增类目抢占商城分类页默认类目；完整回归 890 条 / 794 通过 / 93 失败 / 3 跳过，新增失败 0 | 6.5、13、14、21 |
| v1.5 | 2026-11-03 | 新增订单/购物车/地址接口级场景试点和接口下测试大分类（正向/逆向/边界/异常/特殊场景）；参数化逆向/边界、API/DB/MQ 正向分层、特殊场景独立；完整回归 856 条 / 760 通过 / 93 失败 / 3 跳过 | 6.5、13、14、21 |
| v1.4 | 2026-11-03 | MQ 校验页补充真实 Payload/API/MQ 请求响应/traceId；缺陷支持 Gitee Issues 幂等同步、原生优先级/分支/作者元数据与本地/Gitee 双入口；UI 缺陷截图进入缺陷单 | 10.4、10.7、17、18 |
| v1.3 | 2026-11-03 | 落地 20.2 四项 P0：已知失败台账与门禁、覆盖率 ratchet 门禁、35 个写接口 DB 断言（68/68）、65 条 P0 评审清理（P0 债 0）；新增 14 条落库用例和报告 KPI；更新 837 条执行口径 | 6.4、9.3、10.3–10.6、11、13、14、16、17、18、20.2、20.6 |
| v1.2 | 2026-11-03 | Allure 改为“业务域 → 业务模块 → 接口 → 用例”；新增 141 个接口聚合组；版本对比增加环形图、指标条形图、失败模块分布和风险/关注点/建议；补充本地 Vite UI 执行方式；更新指标、命令、文件索引；细化 20.2 四项 P0 的现状、落地步骤、阈值和验收 | 3、4、6.4、7、10.5–10.7、11、13、14、16、17、18、20.2 |
| v1.1 | 2026-10-30 | 9 项体系增强：用例注册/评审/质量门禁、写接口 DB 契约、缺陷单与代码定位、历史 diff/知识库、JaCoCo、RabbitMQ/Redis、多浏览器并行、500 日志；新增扩展报告与三方组件视图 | 2、6、9、10、11、12、14 |
| v1.0 | 2026-10-28 | 初版：框架分层、请求生命周期、用例体系、数据隔离、断言诊断、报告、CI 与当前指标 | 全文 |

维护约定：

- 每次调整报告口径、业务分类、覆盖率/门禁阈值、关键指标或命令，必须更新本表；
- 版本号采用 `v<major>.<minor>`：口径/结构变化升 minor，纯文字修正只更新日期；
- 变更记录需写明“改了什么、为什么改、影响哪些章节”，不写无法复现的结论；
- 文档中的指标必须能由 `artifacts/results.json`、`coverage.json`、`compare.json` 或归档快照复算。
