# 尚品汇自动化测试用例库

> 本文件由 `scripts/export_cases.py` 从 pytest 实际收集结果生成，请勿手工修改。
> 用例标题与验证点维护在 `data/case_meta.yaml`；新增/删除用例后重跑导出脚本。

- 生成时间：2026-10-19 17:41:16
- 用例总数：**145**
- 数据源：`pytest --collect-only`（与实际执行条目一致）

## 概览

| 类型 | 条数 |
|---|---:|
| API | 97 |
| UI | 46 |
| E2E | 2 |
| **合计** | **145** |

## API 用例（97 条）

### 认证（13 条）

| 用例ID | 优先级 | 用例标题 | 验证点 | 参数 | 自动化脚本 |
|---|---|---|---|---|---|
| API-AUTH-001 | P0 | 发送短信验证码 | 返回 cooldownSec 且大于 0；演示环境验证码固定 123456 | - | `tests/api/test_auth.py::TestCustomerAuth::test_send_sms` |
| API-AUTH-002 | P1 | 发送验证码时手机号格式错误 | HTTP 400，业务码 40000，提示手机号格式不正确 | - | `tests/api/test_auth.py::TestCustomerAuth::test_send_sms_rejects_bad_phone` |
| API-AUTH-003 | P0 | 商城验证码登录响应契约 | 返回 accessToken、refreshToken、expiresIn（字符串）与 customer 资料 | - | `tests/api/test_auth.py::TestCustomerAuth::test_login_contract` |
| API-AUTH-004 | P1 | 验证码错误时登录失败 | 业务码 40101，提示验证码错误或已过期 | - | `tests/api/test_auth.py::TestCustomerAuth::test_login_wrong_code` |
| API-AUTH-005 | P0 | 查询当前会员资料 | 返回会员 id 与登录账号一致，status=NORMAL | - | `tests/api/test_auth.py::TestCustomerAuth::test_me_returns_current_customer` |
| API-AUTH-006 | P1 | 未登录访问会员资料 | HTTP 401，业务码 40100/40103 | - | `tests/api/test_auth.py::TestCustomerAuth::test_me_requires_token` |
| API-AUTH-007 | P1 | 刷新访问令牌 | 返回新的 accessToken 与 expiresIn | - | `tests/api/test_auth.py::TestCustomerAuth::test_refresh_token` |
| API-AUTH-008 | P1 | 登出后访问令牌立即失效 | 登出成功后再访问 /api/me 返回 401 | - | `tests/api/test_auth.py::TestCustomerAuth::test_logout_revokes_token` |
| API-AUTH-009 | P1 | 修改会员昵称 | 返回新昵称并与资料接口一致 | - | `tests/api/test_auth.py::TestCustomerAuth::test_update_profile` |
| API-AUTH-010 | P0 | 管理员登录并查询当前用户 | username 匹配，返回 roles/permissions/menus | - | `tests/api/test_auth.py::TestAdminAuth::test_admin_login_and_me` |
| API-AUTH-011 | P1 | 管理员密码错误 | 业务码 40101 | - | `tests/api/test_auth.py::TestAdminAuth::test_admin_wrong_password` |
| API-AUTH-012 | P1 | 管理端接口未认证 | HTTP 401，业务码 40100/40103 | - | `tests/api/test_auth.py::TestAdminAuth::test_admin_requires_token` |
| API-AUTH-013 | P2 | 响应 traceId 契约 | body.traceId 为 32 位十六进制且与响应头 X-Trace-Id 一致 | - | `tests/api/test_auth.py::TestAdminAuth::test_response_has_trace_id` |

### 商品与搜索（16 条）

| 用例ID | 优先级 | 用例标题 | 验证点 | 参数 | 自动化脚本 |
|---|---|---|---|---|---|
| API-CAT-001 | P0 | 首页 feed 与运营位 | feed/slots 非空，商品含 spuId/name/price | - | `tests/api/test_catalog.py::TestHome::test_home_feed_and_slots` |
| API-CAT-002 | P1 | 站点品牌信息 | 返回品牌 name 与 slogan | - | `tests/api/test_catalog.py::TestHome::test_site_brand` |
| API-CAT-003 | P1 | 商品分类列表 | 返回非空列表且含分类 id/name | - | `tests/api/test_catalog.py::TestHome::test_categories` |
| API-CAT-004 | P0 | 商品分页查询 | 分页结构正确，total>0，本页条数不超过 size | - | `tests/api/test_catalog.py::TestProducts::test_products_pagination` |
| API-CAT-005 | P1 | 商品价格排序 | price_asc 价格升序，price_desc 价格降序 | sort=price_asc, descending=False | `tests/api/test_catalog.py::TestProducts::test_price_sort[price_asc]` |
| API-CAT-006 | P1 | 商品价格排序 | price_asc 价格升序，price_desc 价格降序 | sort=price_desc, descending=True | `tests/api/test_catalog.py::TestProducts::test_price_sort[price_desc]` |
| API-CAT-007 | P0 | 商品详情契约 | 返回 spu/skus/favorited；skuId 为字符串，库存为非负整数 | - | `tests/api/test_catalog.py::TestProducts::test_product_detail` |
| API-CAT-008 | P1 | 查询不存在的商品 | 业务码 40410，提示商品不存在或未上架 | - | `tests/api/test_catalog.py::TestProducts::test_product_not_found` |
| API-CAT-009 | P2 | 负数页码稳定性 | 不返回 5xx，分页结构仍然合法 | - | `tests/api/test_catalog.py::TestProducts::test_out_of_range_page_is_stable` |
| API-CAT-010 | P2 | 超大 size 参数稳定性 | HTTP 200，不返回 5xx | - | `tests/api/test_catalog.py::TestProducts::test_huge_size_is_stable` |
| API-CAT-011 | P1 | 关键字搜索命中商品 | total>0，结果名称包含关键字 | keyword=iPhone | `tests/api/test_catalog.py::TestSearch::test_search_hit[iPhone]` |
| API-CAT-012 | P1 | 关键字搜索命中商品 | total>0，结果名称包含关键字 | keyword=MacBook | `tests/api/test_catalog.py::TestSearch::test_search_hit[MacBook]` |
| API-CAT-013 | P1 | 关键字搜索命中商品 | total>0，结果名称包含关键字 | keyword=戴森 | `tests/api/test_catalog.py::TestSearch::test_search_hit[\u6234\u68ee]` |
| API-CAT-014 | P1 | 搜索无结果 | total=0，records 为空列表 | - | `tests/api/test_catalog.py::TestSearch::test_search_no_result` |
| API-CAT-015 | P2 | 空关键字搜索 | 返回合法分页结构 | - | `tests/api/test_catalog.py::TestSearch::test_search_empty_keyword` |
| API-CAT-016 | P2 | 搜索参数 SQL 注入安全 | 注入串返回空结果，无 5xx，traceId 正常 | - | `tests/api/test_catalog.py::TestSearch::test_search_sql_injection_is_safe` |

### 购物车（11 条）

| 用例ID | 优先级 | 用例标题 | 验证点 | 参数 | 自动化脚本 |
|---|---|---|---|---|---|
| API-CART-001 | P0 | 加购并读取购物车 | 数量与选中金额正确，条目 selected=true | - | `tests/api/test_cart.py::TestCart::test_add_and_read_cart` |
| API-CART-002 | P1 | 修改购物车商品数量 | 数量更新为 3，购物车回显一致 | - | `tests/api/test_cart.py::TestCart::test_update_quantity` |
| API-CART-003 | P1 | 取消勾选购物车商品 | 条目 selected=false，selectedAmount=0 | - | `tests/api/test_cart.py::TestCart::test_unselect_item` |
| API-CART-004 | P1 | 删除购物车商品 | 购物车列表不再包含该条目 | - | `tests/api/test_cart.py::TestCart::test_remove_item` |
| API-CART-005 | P1 | 清理失效商品 | 操作成功，有效商品保留 | - | `tests/api/test_cart.py::TestCart::test_clear_invalid` |
| API-CART-006 | P1 | 未登录加购 | HTTP 401，业务码 40100/40103 | - | `tests/api/test_cart.py::TestCart::test_cart_requires_auth` |
| API-CART-007 | P2 | 加购不存在的 SKU | 业务码 40410 | - | `tests/api/test_cart.py::TestCart::test_add_unknown_sku` |
| API-CART-008 | P2 | 加购数量非法 | 业务码 40000，提示数量须 ≥ 1 | quantity=0 | `tests/api/test_cart.py::TestCart::test_add_invalid_quantity[zero]` |
| API-CART-009 | P2 | 加购数量非法 | 业务码 40000，提示数量须 ≥ 1 | quantity=-1 | `tests/api/test_cart.py::TestCart::test_add_invalid_quantity[negative]` |
| API-CART-010 | P2 | 加购数量超过库存 | 业务码 40901，提示库存不足 | - | `tests/api/test_cart.py::TestCart::test_add_over_stock` |
| API-CART-011 | P2 | 修改不存在的购物车项 | 业务码 40400 | - | `tests/api/test_cart.py::TestCart::test_update_missing_cart_item` |

### 收货地址（7 条）

| 用例ID | 优先级 | 用例标题 | 验证点 | 参数 | 自动化脚本 |
|---|---|---|---|---|---|
| API-ADDR-001 | P0 | 新增地址并查询列表 | 创建成功，列表回显姓名/详细地址，默认地址为 true | - | `tests/api/test_address.py::TestAddress::test_create_and_list` |
| API-ADDR-002 | P1 | 修改收货地址 | 更新详细地址后列表回显新值 | - | `tests/api/test_address.py::TestAddress::test_update_address` |
| API-ADDR-003 | P1 | 设置默认地址 | 新地址成为唯一默认，原默认地址被取消 | - | `tests/api/test_address.py::TestAddress::test_set_default_address` |
| API-ADDR-004 | P2 | 地址必填项缺失 | 业务码 40000，提示收货信息不完整 | - | `tests/api/test_address.py::TestAddress::test_incomplete_address_rejected` |
| API-ADDR-005 | P2 | 删除不存在的地址 | 业务码 40400 | - | `tests/api/test_address.py::TestAddress::test_delete_missing_address` |
| API-ADDR-006 | P2 | 越权修改他人地址 | 业务码 40400，不能修改非本人地址 | - | `tests/api/test_address.py::TestAddress::test_cannot_update_other_users_address` |
| API-ADDR-007 | P2 | 越权删除他人地址 | 业务码 40400，不能删除非本人地址 | - | `tests/api/test_address.py::TestAddress::test_cannot_delete_other_users_address` |

### 订单（16 条）

| 用例ID | 优先级 | 用例标题 | 验证点 | 参数 | 自动化脚本 |
|---|---|---|---|---|---|
| API-ORDER-001 | P0 | 购物车提交订单 | 状态 PENDING_PAY，订单号/商品金额/运费/明细正确 | - | `tests/api/test_order.py::TestSubmitOrder::test_submit_from_cart` |
| API-ORDER-002 | P1 | 下单幂等 | 相同 idempotentKey 两次提交返回同一订单 | - | `tests/api/test_order.py::TestSubmitOrder::test_submit_is_idempotent` |
| API-ORDER-003 | P1 | 立即购买下单 | 不经过购物车直接创建待支付订单 | - | `tests/api/test_order.py::TestSubmitOrder::test_buy_now_without_cart` |
| API-ORDER-004 | P2 | 下单缺少幂等键 | 业务码 40000，提示 idempotentKey 必填 | - | `tests/api/test_order.py::TestSubmitOrder::test_missing_idempotent_key` |
| API-ORDER-005 | P2 | 下单地址不存在 | 业务码 40000，提示收货地址无效 | - | `tests/api/test_order.py::TestSubmitOrder::test_invalid_address` |
| API-ORDER-006 | P2 | 使用他人地址下单 | 业务码 40000，地址归属校验生效 | - | `tests/api/test_order.py::TestSubmitOrder::test_cannot_use_other_users_address` |
| API-ORDER-007 | P1 | 我的订单列表 | 按状态过滤，列表包含新订单 | - | `tests/api/test_order.py::TestOrderQuery::test_order_list` |
| API-ORDER-008 | P1 | 订单详情与地址快照 | 返回订单明细与地址快照，shipments 为空 | - | `tests/api/test_order.py::TestOrderQuery::test_order_detail_has_items_and_snapshot` |
| API-ORDER-009 | P2 | 查询不存在的订单 | 业务码 40400 | - | `tests/api/test_order.py::TestOrderQuery::test_order_not_found` |
| API-ORDER-010 | P2 | 越权读取他人订单 | 业务码 40400 | - | `tests/api/test_order.py::TestOrderQuery::test_cannot_read_other_users_order` |
| API-ORDER-011 | P1 | 取消待支付订单 | 状态变为 CLOSED，关闭原因为“用户取消” | - | `tests/api/test_order.py::TestOrderState::test_cancel_pending_order` |
| API-ORDER-012 | P1 | 重复取消订单幂等 | 两次取消均成功，不报错 | - | `tests/api/test_order.py::TestOrderState::test_cancel_is_idempotent` |
| API-ORDER-013 | P2 | 未发货订单确认收货 | 业务码 40902 | - | `tests/api/test_order.py::TestOrderState::test_confirm_receive_requires_shipped` |
| API-ORDER-014 | P0 | 沙箱支付 | 订单变为 PENDING_SHIP，支付单 PAID，tradeNo 正确 | - | `tests/api/test_order.py::TestOrderState::test_sandbox_payment` |
| API-ORDER-015 | P2 | 重复支付与取消已支付订单 | 两次操作均返回 40902 | - | `tests/api/test_order.py::TestOrderState::test_pay_twice_and_cancel_paid` |
| API-ORDER-016 | P2 | 商城令牌访问管理端 | HTTP 401，业务码 40100/40103 | - | `tests/api/test_order.py::test_customer_token_cannot_access_admin` |

### 收藏与足迹（4 条）

| 用例ID | 优先级 | 用例标题 | 验证点 | 参数 | 自动化脚本 |
|---|---|---|---|---|---|
| API-FAV-001 | P1 | 收藏、查询并取消收藏 | 收藏列表包含 spuId，商品详情 favorited 随收藏状态变化 | - | `tests/api/test_favorites_history.py::TestFavorites::test_add_list_remove_favorite` |
| API-FAV-002 | P2 | 重复取消收藏幂等 | 不返回 5xx | - | `tests/api/test_favorites_history.py::TestFavorites::test_remove_missing_favorite_is_safe` |
| API-FAV-003 | P1 | 浏览商品写入足迹 | 足迹列表包含刚浏览的 spuId | - | `tests/api/test_favorites_history.py::TestHistory::test_view_product_records_history` |
| API-FAV-004 | P1 | 清空浏览足迹 | 清空后足迹列表为空 | - | `tests/api/test_favorites_history.py::TestHistory::test_clear_history` |

### 售后与评价（6 条）

| 用例ID | 优先级 | 用例标题 | 验证点 | 参数 | 自动化脚本 |
|---|---|---|---|---|---|
| API-ASR-001 | P2 | 待支付订单申请售后 | 业务码 40902，当前状态不可申请 | - | `tests/api/test_after_sales_reviews.py::TestAfterSales::test_apply_rejected_for_pending_pay` |
| API-ASR-002 | P2 | 售后类型非法 | 业务码 40000，提示 type 无效 | - | `tests/api/test_after_sales_reviews.py::TestAfterSales::test_apply_rejects_invalid_type` |
| API-ASR-003 | P2 | 售后必填字段缺失 | 业务码 40000，提示订单/类型/原因必填 | - | `tests/api/test_after_sales_reviews.py::TestAfterSales::test_apply_requires_fields` |
| API-ASR-004 | P1 | 我的售后分页 | 返回合法分页结构 | - | `tests/api/test_after_sales_reviews.py::TestAfterSales::test_my_after_sales_page` |
| API-ASR-005 | P2 | 未完成订单发表评价 | 业务码 40902，仅已完成订单可评价 | - | `tests/api/test_after_sales_reviews.py::TestReviews::test_review_rejected_before_completed` |
| API-ASR-006 | P1 | 商品评价列表公开可读 | 未登录可访问，返回合法分页 | - | `tests/api/test_after_sales_reviews.py::TestReviews::test_product_reviews_public` |

### 管理端（11 条）

| 用例ID | 优先级 | 用例标题 | 验证点 | 参数 | 自动化脚本 |
|---|---|---|---|---|---|
| API-ADMIN-001 | P0 | 管理端工作台指标 | 返回在售商品/SKU/低库存/待发货/订单总数，均为数字字符串 | - | `tests/api/test_admin.py::TestAdminDashboard::test_dashboard_stats` |
| API-ADMIN-002 | P0 | 管理端商品分页 | 分页结构正确，首行含 id/name/status/stock | - | `tests/api/test_admin.py::TestAdminCatalog::test_product_list` |
| API-ADMIN-003 | P1 | 管理端商品详情 | 按列表首条 id 查询成功 | - | `tests/api/test_admin.py::TestAdminCatalog::test_product_detail` |
| API-ADMIN-004 | P1 | 管理端类目树 | 返回非空树结构 | - | `tests/api/test_admin.py::TestAdminCatalog::test_category_tree` |
| API-ADMIN-005 | P1 | 管理端品牌分页 | 返回合法分页结构 | - | `tests/api/test_admin.py::TestAdminCatalog::test_brands_page` |
| API-ADMIN-006 | P2 | 管理端字典分页 | 返回合法分页结构 | - | `tests/api/test_admin.py::TestAdminCatalog::test_dicts_page` |
| API-ADMIN-007 | P0 | 管理端订单分页 | 返回合法分页结构 | - | `tests/api/test_admin.py::TestAdminOrders::test_order_list` |
| API-ADMIN-008 | P1 | 管理端订单详情 | 按列表首条 id 查询成功；列表为空时先用隔离会员造单再查询 | - | `tests/api/test_admin.py::TestAdminOrders::test_order_detail` |
| API-ADMIN-009 | P1 | 管理端会员分页 | 返回合法分页结构 | - | `tests/api/test_admin.py::TestAdminMembers::test_customers_page` |
| API-ADMIN-010 | P2 | 管理端操作日志分页 | 返回合法分页结构 | - | `tests/api/test_admin.py::TestAdminMembers::test_operation_logs` |
| API-ADMIN-011 | P2 | 管理端查询不存在商品 | 返回 40400/40410，不返回 5xx | - | `tests/api/test_admin.py::TestAdminMembers::test_missing_product_is_business_error` |

### 安全（6 条）

| 用例ID | 优先级 | 用例标题 | 验证点 | 参数 | 自动化脚本 |
|---|---|---|---|---|---|
| API-SEC-001 | P2 | 篡改访问令牌 | HTTP 401，业务码 40100/40103 | - | `tests/api/test_security.py::test_tampered_token_rejected` |
| API-SEC-002 | P2 | 商城令牌访问管理端 | HTTP 401，业务码 40100/40103 | - | `tests/api/test_security.py::test_customer_token_rejected_by_admin` |
| API-SEC-003 | P2 | 登录手机号 SQL 注入 | HTTP 400，业务码 40000，参数校验拦截 | - | `tests/api/test_security.py::test_login_phone_sql_injection` |
| API-SEC-004 | P2 | 搜索 XSS 载荷 | 返回空结果，响应不包含原始脚本标签 | - | `tests/api/test_security.py::test_search_xss_payload_is_inert` |
| API-SEC-005 | P2 | 超大分页参数 | HTTP 200，不返回 5xx | - | `tests/api/test_security.py::test_oversized_page_does_not_500` |
| API-SEC-006 | P2 | 错误响应 traceId | traceId 为 32 位十六进制且与响应头一致 | - | `tests/api/test_security.py::test_error_response_keeps_trace_id` |

### 数据驱动校验（4 条）

| 用例ID | 优先级 | 用例标题 | 验证点 | 参数 | 自动化脚本 |
|---|---|---|---|---|---|
| API-DATA-001 | P1 | 登录输入参数校验 | HTTP 400，业务码 40000，提示对应字段错误 | case=phone-too-short | `tests/api/test_data_driven.py::test_login_input_validation[phone-too-short]` |
| API-DATA-002 | P1 | 登录输入参数校验 | HTTP 400，业务码 40000，提示对应字段错误 | case=phone-contains-letter | `tests/api/test_data_driven.py::test_login_input_validation[phone-contains-letter]` |
| API-DATA-003 | P1 | 登录输入参数校验 | HTTP 400，业务码 40000，提示对应字段错误 | case=code-blank | `tests/api/test_data_driven.py::test_login_input_validation[code-blank]` |
| API-DATA-004 | P1 | 登录输入参数校验 | HTTP 400，业务码 40000，提示对应字段错误 | case=client-type-invalid | `tests/api/test_data_driven.py::test_login_input_validation[client-type-invalid]` |

### 冒烟（3 条）

| 用例ID | 优先级 | 用例标题 | 验证点 | 参数 | 自动化脚本 |
|---|---|---|---|---|---|
| API-SMOKE-001 | P0 | 商城商品接口可达 | 商品列表返回非空数据 | - | `tests/api/test_smoke.py::test_storefront_is_reachable` |
| API-SMOKE-002 | P0 | 会员登录态可用 | /api/me 返回 NORMAL 状态 | - | `tests/api/test_smoke.py::test_customer_can_login` |
| API-SMOKE-003 | P0 | 管理员登录态可用 | /admin/auth/me 返回用户名 | - | `tests/api/test_smoke.py::test_admin_can_login` |

## UI 用例（46 条）

### 商城浏览（4 条）

| 用例ID | 优先级 | 用例标题 | 验证点 | 参数 | 自动化脚本 |
|---|---|---|---|---|---|
| UI-BROWSE-001 | P0 | 商城首页加载商品 | 商品链接与“热门精选”可见 | - | `tests/ui/test_mall_browse.py::TestMallBrowse::test_home_loads_products[chromium]` |
| UI-BROWSE-002 | P1 | 商城搜索商品 | 搜索结果包含 iPhone | - | `tests/ui/test_mall_browse.py::TestMallBrowse::test_search_shows_matching_products[chromium]` |
| UI-BROWSE-003 | P2 | 商城分类页加载 | 分类页标题、商品链接与综合/销量排序可见 | - | `tests/ui/test_mall_browse.py::TestMallBrowse::test_category_page_loads[chromium]` |
| UI-BROWSE-004 | P1 | 搜索无结果显示空态 | 展示“没有找到相关商品”与“为你推荐” | - | `tests/ui/test_mall_browse.py::TestMallBrowse::test_search_no_result_shows_empty_state[chromium]` |

### 商城登录（3 条）

| 用例ID | 优先级 | 用例标题 | 验证点 | 参数 | 自动化脚本 |
|---|---|---|---|---|---|
| UI-LOGIN-001 | P0 | 商城验证码登录成功 | 登录后顶栏显示“Hi，昵称” | - | `tests/ui/test_mall_login.py::TestMallLogin::test_login_success[chromium]` |
| UI-LOGIN-002 | P1 | 错误验证码内联提示 | 表单下方显示“验证码错误，请重新获取” | - | `tests/ui/test_mall_login.py::TestMallLogin::test_login_wrong_code_shows_inline_error[chromium]` |
| UI-LOGIN-003 | P2 | 手机号格式内联提示 | 表单下方显示“请输入正确的手机号” | - | `tests/ui/test_mall_login.py::TestMallLogin::test_login_invalid_phone_shows_inline_error[chromium]` |

### 商城购物车与结算（5 条）

| 用例ID | 优先级 | 用例标题 | 验证点 | 参数 | 自动化脚本 |
|---|---|---|---|---|---|
| UI-CART-001 | P0 | 商品详情页加入购物车 | 购物车出现 iPhone 商品 | - | `tests/ui/test_mall_cart_checkout.py::TestMallCart::test_add_to_cart_from_product_detail[chromium]` |
| UI-CART-002 | P1 | 未勾选商品去结算 | 提示“请先勾选商品”，停留在购物车页 | - | `tests/ui/test_mall_cart_checkout.py::TestMallCart::test_checkout_requires_selected_item[chromium]` |
| UI-CART-003 | P1 | 修改购物车商品数量 | 点击数量加号后数量 +1，接口与页面同步 | - | `tests/ui/test_mall_cart_checkout.py::TestMallCart::test_update_cart_quantity[chromium]` |
| UI-CART-004 | P1 | 删除购物车商品 | 二次确认后购物车清空 | - | `tests/ui/test_mall_cart_checkout.py::TestMallCart::test_remove_cart_item[chromium]` |
| UI-CART-005 | P0 | 购物车结算并提交订单 | 确认订单页有地址与应付金额，提交后生成待支付或已支付订单 | - | `tests/ui/test_mall_cart_checkout.py::TestMallCheckout::test_submit_order_from_cart[chromium]` |

### 商城订单（4 条）

| 用例ID | 优先级 | 用例标题 | 验证点 | 参数 | 自动化脚本 |
|---|---|---|---|---|---|
| UI-ORDER-001 | P1 | 订单列表展示待付款订单 | 显示订单号与“待付款”状态 | - | `tests/ui/test_mall_orders.py::TestMallOrders::test_order_list_shows_pending_order[chromium]` |
| UI-ORDER-002 | P2 | 订单详情页 | 详情页显示订单号 | - | `tests/ui/test_mall_orders.py::TestMallOrders::test_order_detail_page[chromium]` |
| UI-ORDER-003 | P1 | 页面取消待付款订单 | 确认弹窗后订单状态变为 CLOSED | - | `tests/ui/test_mall_orders.py::TestMallOrders::test_cancel_pending_order_from_ui[chromium]` |
| UI-ORDER-004 | P1 | 收银台沙箱支付 | 打开待支付订单后显示支付成功，订单变为 PENDING_SHIP | - | `tests/ui/test_mall_orders.py::TestMallPay::test_pay_page_auto_pays[chromium]` |

### 后台控制台（20 条）

| 用例ID | 优先级 | 用例标题 | 验证点 | 参数 | 自动化脚本 |
|---|---|---|---|---|---|
| UI-ADMIN-001 | P0 | 管理员登录进入工作台 | 登录后跳转 /dashboard 并显示工作台 | - | `tests/ui/test_admin_console.py::TestAdminLogin::test_admin_login_lands_on_dashboard[chromium]` |
| UI-ADMIN-002 | P0 | 后台工作台指标 | 页面显示在售商品等指标 | - | `tests/ui/test_admin_console.py::TestAdminConsole::test_dashboard_loads[chromium]` |
| UI-ADMIN-003 | P1 | 后台商品列表与搜索 | 列表有数据，搜索 iPhone 结果命中 | - | `tests/ui/test_admin_console.py::TestAdminConsole::test_product_list_and_search[chromium]` |
| UI-ADMIN-004 | P1 | 后台订单列表 | 表格有数据且标题为订单列表 | - | `tests/ui/test_admin_console.py::TestAdminConsole::test_order_list_loads[chromium]` |
| UI-ADMIN-005 | P1 | 后台会员列表 | 会员管理页表格有数据 | - | `tests/ui/test_admin_console.py::TestAdminConsole::test_customers_page_loads[chromium]` |
| UI-ADMIN-006 | P1 | 类目与品牌页 | 页面标题正确，无加载失败/系统异常 | path=/categories, title=类目与品牌 | `tests/ui/test_admin_console.py::TestAdminConsole::test_admin_pages_load[chromium-categories]` |
| UI-ADMIN-007 | P2 | 新增商品表单加载 | 显示新增商品页与“存为草稿”按钮 | - | `tests/ui/test_admin_console.py::TestAdminConsole::test_product_create_form_loads[chromium]` |
| UI-ADMIN-008 | P1 | 库存管理页 | 页面标题正确，无加载失败/系统异常 | path=/inventory, title=库存管理 | `tests/ui/test_admin_console.py::TestAdminConsole::test_admin_pages_load[chromium-inventory]` |
| UI-ADMIN-009 | P1 | 出入库单页 | 页面标题正确，无加载失败/系统异常 | path=/in-out, title=出入库单 | `tests/ui/test_admin_console.py::TestAdminConsole::test_admin_pages_load[chromium-in-out]` |
| UI-ADMIN-010 | P1 | 售后管理页 | 页面标题正确，无加载失败/系统异常 | path=/aftersales, title=售后管理 | `tests/ui/test_admin_console.py::TestAdminConsole::test_admin_pages_load[chromium-aftersales]` |
| UI-ADMIN-011 | P1 | 评价管理页 | 页面标题正确，无加载失败/系统异常 | path=/reviews, title=评价管理 | `tests/ui/test_admin_console.py::TestAdminConsole::test_admin_pages_load[chromium-reviews]` |
| UI-ADMIN-012 | P1 | 站点品牌页 | 页面标题正确，无加载失败/系统异常 | path=/site-brand, title=站点品牌 | `tests/ui/test_admin_console.py::TestAdminConsole::test_admin_pages_load[chromium-site-brand]` |
| UI-ADMIN-013 | P1 | 首页运营位页 | 页面标题正确，无加载失败/系统异常 | path=/home-slots, title=首页运营位 | `tests/ui/test_admin_console.py::TestAdminConsole::test_admin_pages_load[chromium-home-slots]` |
| UI-ADMIN-014 | P1 | 用户管理页 | 页面标题正确，无加载失败/系统异常 | path=/users, title=用户管理 | `tests/ui/test_admin_console.py::TestAdminConsole::test_admin_pages_load[chromium-users]` |
| UI-ADMIN-015 | P1 | 角色管理页 | 页面标题正确，无加载失败/系统异常 | path=/roles, title=角色管理 | `tests/ui/test_admin_console.py::TestAdminConsole::test_admin_pages_load[chromium-roles]` |
| UI-ADMIN-016 | P1 | 菜单与权限页 | 页面标题正确，无加载失败/系统异常 | path=/menus, title=菜单与权限 | `tests/ui/test_admin_console.py::TestAdminConsole::test_admin_pages_load[chromium-menus]` |
| UI-ADMIN-017 | P1 | 部门管理页 | 页面标题正确，无加载失败/系统异常 | path=/depts, title=部门管理 | `tests/ui/test_admin_console.py::TestAdminConsole::test_admin_pages_load[chromium-depts]` |
| UI-ADMIN-018 | P1 | 字典管理页 | 页面标题正确，无加载失败/系统异常 | path=/dicts, title=字典管理 | `tests/ui/test_admin_console.py::TestAdminConsole::test_admin_pages_load[chromium-dicts]` |
| UI-ADMIN-019 | P1 | 操作日志页 | 页面标题正确，无加载失败/系统异常 | path=/logs, title=操作日志 | `tests/ui/test_admin_console.py::TestAdminConsole::test_admin_pages_load[chromium-logs]` |
| UI-ADMIN-020 | P1 | 系统设置页 | 页面标题正确，无加载失败/系统异常 | path=/settings, title=系统设置 | `tests/ui/test_admin_console.py::TestAdminConsole::test_admin_pages_load[chromium-settings]` |

### 商城个人中心（8 条）

| 用例ID | 优先级 | 用例标题 | 验证点 | 参数 | 自动化脚本 |
|---|---|---|---|---|---|
| UI-ACCOUNT-001 | P1 | 个人中心页面加载 | 显示退出登录、收货地址、我的收藏入口 | - | `tests/ui/test_mall_account.py::TestMallProfile::test_profile_page_loads[chromium]` |
| UI-ACCOUNT-002 | P2 | 设置页加载 | 显示登录手机号与 Web/H5 登录态说明 | - | `tests/ui/test_mall_account.py::TestMallProfile::test_settings_page_loads[chromium]` |
| UI-ACCOUNT-003 | P2 | 我的售后页加载 | 页面标题与空态/列表可见 | - | `tests/ui/test_mall_account.py::TestMallProfile::test_after_sales_page_loads[chromium]` |
| UI-ACCOUNT-004 | P1 | 地址页展示已有地址 | 显示收货人、详细地址与默认标记 | - | `tests/ui/test_mall_account.py::TestMallAddress::test_address_page_shows_api_address[chromium]` |
| UI-ACCOUNT-005 | P1 | 页面新增并删除地址 | 表单保存后列表出现，删除后回到暂无地址 | - | `tests/ui/test_mall_account.py::TestMallAddress::test_add_and_delete_address_via_ui[chromium]` |
| UI-ACCOUNT-006 | P1 | 收藏页取消收藏 | 收藏列表显示商品，确认后回到空态 | - | `tests/ui/test_mall_account.py::TestMallFavorites::test_favorites_page_and_remove[chromium]` |
| UI-ACCOUNT-007 | P1 | 足迹页清空 | 浏览记录显示，确认清空后回到空态 | - | `tests/ui/test_mall_account.py::TestMallHistory::test_history_page_and_clear[chromium]` |
| UI-ACCOUNT-008 | P2 | 活动位页面加载 | 显示活动标题与商品列表 | - | `tests/ui/test_mall_account.py::TestMallPromo::test_promo_page_loads[chromium]` |

### 商城商品详情（2 条）

| 用例ID | 优先级 | 用例标题 | 验证点 | 参数 | 自动化脚本 |
|---|---|---|---|---|---|
| UI-PRODUCT-001 | P1 | 商品详情展示规格 | 商品名称、规格选项与收藏入口可见 | - | `tests/ui/test_mall_product.py::TestMallProduct::test_product_detail_shows_skus[chromium]` |
| UI-PRODUCT-002 | P1 | 商品收藏与取消收藏 | 收藏后显示“已收藏”，再次点击恢复“收藏” | - | `tests/ui/test_mall_product.py::TestMallProduct::test_favorite_toggle[chromium]` |

## E2E 用例（2 条）

### 端到端购买（2 条）

| 用例ID | 优先级 | 用例标题 | 验证点 | 参数 | 自动化脚本 |
|---|---|---|---|---|---|
| E2E-001 | P0 | API 全链路购买 | 登录 → 地址 → 加购 → 下单 → 沙箱支付，订单待发货 | - | `tests/e2e/test_purchase_flow.py::test_api_purchase_flow` |
| E2E-002 | P1 | UI 全链路购买 | 加购 → 购物车 → 确认订单 → 提交 → 支付成功 | - | `tests/e2e/test_purchase_flow.py::test_ui_purchase_flow[chromium]` |
