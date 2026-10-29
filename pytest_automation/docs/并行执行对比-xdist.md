# pytest-xdist 并行执行对比

> 环境：macOS 12 核 / Python 3.13 / 后端 `localhost:8086`（单实例）/ PostgreSQL 16 本地容器。
> 方法：每轮开始前用基线快照恢复数据库；除 `-n` 与 `--dist` 外参数完全一致（`-m api -q --alluredir`，含 `--reruns 1`）。

## 1. 结果总览

| 模式 | 命令 | 墙钟耗时 | 相对串行 | 通过 | 失败 | 跳过 |
|---|---|---|---|---|---|---|
| 串行基线 | `pytest -m api` | **224.45s** | 1.00x | 605 | 93 | 3 |
| 模块级并行 | `pytest -m api -n 4 --dist loadscope` | **156.92s** | **1.43x** | 605 | 93 | 3 |
| 用例级并行 | `pytest -m api -n 4` | **63.27s** | **3.55x** | 603 | 95 | 3 |
| 用例级并行（8 worker） | `pytest -m api -n 8` | **40.22s** | **5.58x** | 602 | 96 | 3 |

## 2. 为什么提速不是线性的

1. **巡检模块是长尾**：`test_endpoint_sweep.py` 有 487 条用例，`--dist loadscope` 会把整个模块压到一个 worker，
   因此模块级并行只有 1.43x；改成用例级分发（默认 `load`）后变成 3.55x。
2. **失败用例的两次执行**：当前 93 条失败会各自重跑一次，这部分时间并行下仍存在（96 次 rerun）。
3. **后端单实例 + 数据库瓶颈**：登录、建单、库存更新都是写操作，worker 再多也受后端吞吐限制；`-n 8` 相对 `-n 4`
   只再快 1.57x（63s → 40s），且 user 时间上升（131s），说明是 I/O 争用而非 CPU。
4. **xdist 启动与收集开销**：每个 worker 独立收集 701 条用例，纯开销约 3~6s。

## 3. 并行暴露的共享状态问题（重要）

用例级并行比串行多出 3 条失败，均非产品缺陷，而是**测试间共享状态竞争**：

| 用例 | 失败原因 | 根因 |
|---|---|---|
| `test_boundary_quantity_exceeds_available_stock` / `test_idempotency_replay_same_payload` / `test_stock_conservation_on_order_and_cancel` | 库存锁定断言不满足 | 多个 worker 同时对同一 SKU 下单/取消，`physical/locked` 读数被交叉修改 |
| `test_admin_login_parameter_interactions[非管理员…]` / `test_admin_login_rejects_member_account` | 业务码 40104「登录失败次数过多，请15分钟后再试」 | 管理端登录失败次数限流是全局状态，多个 worker 同时打失败登录触发限流 |

模块级并行（`loadscope`）结果与串行完全一致（93 失败），因为库存/登录相关用例被归入同一 worker 顺序执行。

## 4. 建议

- **日常回归 / CI 门禁**：`make api-parallel`（`-n 4 --dist loadscope`）——稳定、结果与串行一致，约 1.4x；
- **本地快速反馈**：`make api-fast`（`-n 4`）——约 3.5x，接受上述 3 条竞争导致的重跑/偶发失败；
- 若要在用例级并行下彻底消除竞争，需要：
  1. 库存敏感用例按 worker 分配独立 SKU（或串行标记）；
  2. 登录失败类用例单独串行执行（限流窗口 15 分钟）；
  3. 或将它们放到第二阶段单 worker 执行（两段式流水线）。

## 5. 复现命令

```bash
# 串行
TEST_ENV=dev ADMIN_PASSWORD='***' python3 -m pytest -m api -q --alluredir=/tmp/allure-serial --clean-alluredir

# 稳定并行
TEST_ENV=dev ADMIN_PASSWORD='***' DISABLE_RECORDER=1 DISABLE_DB_GUARD=1 \
  python3 -m pytest -m api -q -n 4 --dist loadscope --alluredir=/tmp/allure-par --clean-alluredir

# 极限并行
TEST_ENV=dev ADMIN_PASSWORD='***' DISABLE_RECORDER=1 DISABLE_DB_GUARD=1 \
  python3 -m pytest -m api -q -n 8 --alluredir=/tmp/allure-par8 --clean-alluredir
```

> 并行时通过 `DISABLE_RECORDER=1`、`DISABLE_DB_GUARD=1` 关闭「用例→接口映射」与「基线指纹」落盘，
> 避免多个 worker 争写同一文件；映射与指纹仍由串行全量运行维护。
