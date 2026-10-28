#!/usr/bin/env bash
# 生成 / 预览 Allure HTML 报告。
# 依赖 allure CLI：优先用 api_testcases 下已装的 allure-commandline，其次全局 allure。
set -euo pipefail

cd "$(dirname "$0")/.."
RESULTS="artifacts/allure"
REPORT="artifacts/allure-report"
SERVE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --serve) SERVE=1; shift ;;
    --results) RESULTS="${2:?--results 需要目录}"; shift 2 ;;
    --report) REPORT="${2:?--report 需要目录}"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

ALLURE=""
if [ -x "../api_testcases/node_modules/allure-commandline/bin/allure" ]; then
  ALLURE="node ../api_testcases/node_modules/allure-commandline/bin/allure"
elif command -v allure >/dev/null 2>&1; then
  ALLURE="allure"
else
  echo "未找到 allure CLI。二选一：" >&2
  echo "  (cd ../api_testcases && npm install --no-save allure-commandline)" >&2
  echo "  brew install allure" >&2
  exit 3
fi

if [ ! -d "$RESULTS" ]; then
  echo "结果目录不存在：$RESULTS；先跑 pytest --alluredir=$RESULTS" >&2
  exit 4
fi

$ALLURE generate "$RESULTS" -o "$REPORT" --clean
echo "报告已生成：$(cd "$REPORT" && pwd)/index.html"

if [ "$SERVE" = "1" ]; then
  $ALLURE open "$REPORT"
fi
