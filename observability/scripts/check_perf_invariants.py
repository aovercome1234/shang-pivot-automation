#!/usr/bin/env python3
"""性能写链路压测后的数据库不变量校验。

用途：checkout-smoke 等写链路执行后，验证“订单唯一、支付唯一、库存非负、MQ 事件落库”。
连接串从 --dsn、DATABASE_URL 或 PERF_DATABASE_URL 读取，避免把数据库凭据写入文档。

示例：
  python3 observability/scripts/check_perf_invariants.py \
    --prefix 'k6-checkout-perf-20261104-' \
    --minutes 30 \
    --expect-orders \
    --out artifacts/performance/perf-xxx/invariants.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

try:
    import psycopg2
    import psycopg2.extras
except ImportError:  # pragma: no cover - 部署机器需安装 psycopg2
    psycopg2 = None
    psycopg2_extras = None
else:
    psycopg2_extras = psycopg2.extras


def query_all(conn, sql: str, params: tuple | list = ()) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2_extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def collect(conn, prefix: str, window_minutes: int, event_type: str) -> dict:
    like = f"{prefix}%"

    orders = query_all(
        conn,
        '''
        SELECT id, order_no, idempotent_key, status, created_at
        FROM "commerce"."order"
        WHERE idempotent_key LIKE %s
          AND created_at >= NOW() - (%s || ' minutes')::interval
          AND deleted = FALSE
        ORDER BY id
        ''',
        (like, window_minutes),
    )
    order_ids = [int(row["id"]) for row in orders]

    duplicate_order_keys = query_all(
        conn,
        '''
        SELECT idempotent_key, COUNT(*) AS count
        FROM "commerce"."order"
        WHERE idempotent_key LIKE %s
          AND created_at >= NOW() - (%s || ' minutes')::interval
          AND deleted = FALSE
        GROUP BY idempotent_key
        HAVING COUNT(*) > 1
        ORDER BY count DESC, idempotent_key
        ''',
        (like, window_minutes),
    )

    payment_rows = []
    duplicate_payments = []
    paid_order_ids = []
    event_rows = []
    missing_events = []
    duplicate_events = []
    if order_ids:
        payment_rows = query_all(
            conn,
            '''
            SELECT order_id, COUNT(*) AS count, COUNT(*) FILTER (WHERE status = 'PAID') AS paid_count
            FROM commerce.payment
            WHERE order_id = ANY(%s) AND deleted = FALSE
            GROUP BY order_id
            ORDER BY order_id
            ''',
            (order_ids,),
        )
        duplicate_payments = [row for row in payment_rows if int(row["count"]) > 1]
        paid_order_ids = [int(row["order_id"]) for row in payment_rows if int(row["paid_count"] or 0) > 0]
        event_rows = query_all(
            conn,
            '''
            SELECT order_id, COUNT(*) AS count
            FROM commerce.order_event_log
            WHERE order_id = ANY(%s)
              AND event_type = %s
              AND deleted = FALSE
            GROUP BY order_id
            ORDER BY order_id
            ''',
            (paid_order_ids, event_type),
        ) if paid_order_ids else []
        event_count_by_order = {int(row["order_id"]): int(row["count"]) for row in event_rows}
        missing_events = [
            {"orderId": order_id, "eventType": event_type, "actual": 0}
            for order_id in paid_order_ids
            if event_count_by_order.get(order_id, 0) < 1
        ]
        duplicate_events = [
            {"orderId": order_id, "eventType": event_type, "actual": count}
            for order_id, count in event_count_by_order.items()
            if count > 1
        ]

    negative_stock = query_all(
        conn,
        '''
        SELECT sku_id, warehouse_id, physical_stock, locked_stock,
               physical_stock - locked_stock AS available_stock
        FROM commerce.stock
        WHERE deleted = FALSE
          AND (physical_stock < 0 OR locked_stock < 0 OR physical_stock < locked_stock)
        ORDER BY sku_id, warehouse_id
        ''',
    )

    return {
        "window": {
            "minutes": window_minutes,
            "sinceExpression": "NOW() - (%d || ' minutes')::interval" % window_minutes,
        },
        "prefix": prefix,
        "orders": {
            "count": len(orders),
            "sample": orders[:20],
            "duplicateIdempotentKeys": duplicate_order_keys,
        },
        "payments": {
            "ordersWithPayment": len(payment_rows),
            "duplicateOrderPayments": duplicate_payments,
        },
        "mqEvents": {
            "eventType": event_type,
            "paidOrders": len(paid_order_ids),
            "ordersWithEvent": len(event_rows),
            "missingEvents": missing_events,
            "duplicateEvents": duplicate_events,
        },
        "stock": {
            "negativeOrOverLockedRows": negative_stock[:50],
            "negativeOrOverLockedCount": len(negative_stock),
        },
    }


def build_checks(result: dict, expect_orders: bool) -> dict:
    return {
        "orders_present": (not expect_orders) or result["orders"]["count"] > 0,
        "order_idempotency_unique": len(result["orders"]["duplicateIdempotentKeys"]) == 0,
        "payment_once_per_order": len(result["payments"]["duplicateOrderPayments"]) == 0,
        "stock_not_negative_or_over_locked": result["stock"]["negativeOrOverLockedCount"] == 0,
        "mq_event_present_for_paid_orders": len(result["mqEvents"]["missingEvents"]) == 0,
        "mq_event_not_duplicated": len(result["mqEvents"]["duplicateEvents"]) == 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=os.getenv("DATABASE_URL") or os.getenv("PERF_DATABASE_URL") or "")
    parser.add_argument("--prefix", required=True, help="k6 下单幂等键前缀，如 k6-checkout-perf-20261104-")
    parser.add_argument("--minutes", type=int, default=30)
    parser.add_argument("--event-type", default="ORDER_PAID")
    parser.add_argument("--expect-orders", action="store_true")
    parser.add_argument("--retries", type=int, default=3, help="MQ 事件落库可能有短暂延迟，默认重试 3 次")
    parser.add_argument("--retry-delay", type=int, default=5)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    if psycopg2 is None:
        raise SystemExit("缺少 psycopg2：请先安装 psycopg2-binary 或使用项目 pytest_automation/.venv")
    if not args.dsn:
        raise SystemExit("缺少数据库连接串：请设置 DATABASE_URL/PERF_DATABASE_URL 或传 --dsn")

    last = None
    checks = {}
    actual_attempts = 0
    for attempt in range(1, args.retries + 1):
        actual_attempts = attempt
        conn = psycopg2.connect(args.dsn)
        try:
            last = collect(conn, args.prefix, args.minutes, args.event_type)
            checks = build_checks(last, args.expect_orders)
        finally:
            conn.close()
        if checks.get("mq_event_present_for_paid_orders", True) and all(checks.values()):
            break
        if attempt < args.retries:
            time.sleep(args.retry_delay)

    assert last is not None
    payload = {
        "checkedAt": dt.datetime.now().isoformat(timespec="seconds"),
        "attempts": actual_attempts,
        "checks": checks,
        "result": last,
    }
    out = Path(args.out) if args.out else Path(f"invariants-{args.prefix.rstrip('-')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(json.dumps({
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "orders": last["orders"]["count"],
        "paidOrders": last["mqEvents"]["paidOrders"],
        "ordersWithEvent": last["mqEvents"]["ordersWithEvent"],
        "negativeStockRows": last["stock"]["negativeOrOverLockedCount"],
        "evidence": str(out),
    }, ensure_ascii=False, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - CLI 直接输出可读失败原因
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
