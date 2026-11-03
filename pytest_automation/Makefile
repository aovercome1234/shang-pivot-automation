PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: help api ui smoke full report clean api-parallel api-parallel-publish api-fast known-gate coverage-gate p0-review p0-review-apply gitee-issues

help:
	@echo "make api      只跑接口用例"
	@echo "make ui       只跑浏览器用例（需要 ADMIN_PASSWORD 才能跑后台用例）"
	@echo "make smoke    只跑冒烟用例"
	@echo "make full     全量（API + UI + E2E）"
	@echo "make api-parallel          两阶段并行（分片+serial lane，结果与串行一致）"
	@echo "make api-parallel-publish  两阶段并行并发布到报告（保留 UI 结果）"
	@echo "make api-fast              朴素并行 -n 4（最快，有共享状态竞争）"
	@echo "make report   汇总本轮结果并用 allure 生成 HTML 报告"
	@echo "make known-gate    已知失败/过期豁免门禁"
	@echo "make coverage-gate 静态覆盖率门禁（可加 REQUIRE_RUNTIME=1）"
	@echo "make p0-review    生成 P0 逐条评审单"
	@echo "make p0-review-apply 对证据齐全的 P0 legacy 执行静态复核"
	@echo "make gitee-issues 同步缺陷到 Gitee（需 GITEE_TOKEN；无 token 仅 dry-run）"
	@echo "make clean    清理 pytest 缓存与运行产物"

api:
	$(PYTHON) -m pytest -m api -q --alluredir=artifacts/allure --clean-alluredir

ui:
	$(PYTHON) -m pytest -m ui -q --alluredir=artifacts/allure --clean-alluredir

smoke:
	$(PYTHON) -m pytest -m smoke -q --alluredir=artifacts/allure --clean-alluredir

full:
	$(PYTHON) -m pytest -q --alluredir=artifacts/allure --clean-alluredir

api-parallel:
	bash scripts/run_parallel.sh --workers 4

api-parallel-publish:
	bash scripts/run_parallel.sh --workers 4 --publish

api-fast:
	DISABLE_RECORDER=1 DISABLE_DB_GUARD=1 \
	$(PYTHON) -m pytest -m api -q -n 4 \
	--alluredir=artifacts/allure --clean-alluredir

report:
	$(PYTHON) scripts/finalize_run.py
	bash scripts/allure_report.sh

known-gate:
	$(PYTHON) scripts/check_known_failures.py

coverage-gate:
	$(PYTHON) scripts/check_coverage_gate.py $(if $(REQUIRE_RUNTIME),--require-runtime,)

p0-review:
	$(PYTHON) scripts/review_p0.py

p0-review-apply:
	$(PYTHON) scripts/review_p0.py --apply-static

gitee-issues:
	$(PYTHON) scripts/gitee_issues.py --report-dir artifacts/allure-report

clean:
	rm -rf .pytest_cache .pytest_tmp artifacts
