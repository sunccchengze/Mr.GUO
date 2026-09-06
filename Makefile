# Mr.GUO 仓库一键入口
#
# 约定：所有目标都用当前虚拟环境的 python3；未建 venv 时 `PYTHON=` 覆盖即可。
#   make venv                     # 建 .venv 并装齐依赖（numpy + pypdf + pytest）
#   make corpus                   # 抽取 13 PDF + 2 HTML 正文到 corpus/txt/（不入库）
#   make whitepaper               # 由 docs/lectures/ 装配白皮书
#   make checks                   # code/ 模块自检 + tests/ 单元测试
#   make verify                   # 全仓验收（目标 A–F），任一 FAIL 即退出码 1
#   make wp-strict                  # 白皮书逐讲明细校验（目标 A 定位用）
#   make selftest                 # 反身测试：确认验收器对缺陷真的敏感
#   make all                      # corpus + whitepaper + checks + verify
#   make clean                    # 清除派生产物（corpus/txt、__pycache__）

PYTHON ?= python3
VENV   ?= .venv

.PHONY: all venv corpus whitepaper checks tests modules verify wp-strict selftest clean help

help:
	@grep -E '^#   make ' Makefile | sed 's/^#   //'

venv:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -q --upgrade pip
	$(VENV)/bin/pip install -q -r code/requirements.txt -r tools/requirements.txt
	@echo "已就绪：后续用 'make verify PYTHON=$(VENV)/bin/python' 或直接激活 $(VENV)"

corpus:
	$(PYTHON) tools/extract_corpus.py

whitepaper:
	$(PYTHON) tools/build_whitepaper.py

modules:
	$(PYTHON) tools/run_checks.py --modules

tests:
	$(PYTHON) tools/run_checks.py --tests

checks:
	$(PYTHON) tools/run_checks.py

verify:
	$(PYTHON) tools/verify_all.py

wp-strict:
	$(PYTHON) tools/verify_whitepaper.py

selftest:
	$(PYTHON) tools/selftest_verifier.py

all: whitepaper checks verify selftest

clean:
	rm -rf corpus/txt __pycache__ */__pycache__ .pytest_cache
	@echo "已清除派生产物（corpus/txt 可用 'make corpus' 重建）"
