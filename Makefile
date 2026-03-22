# ── RepoMind Makefile ──
# Quick commands for development

.PHONY: install install-dev format lint typecheck test test-cov all clean run

# ── Setup ──
install:
	pip install -r requirements.txt

install-dev: install
	pip install -r requirements-dev.txt

# ── Code Quality ──
format:
	black shared/ step1/ step2/ step3/ step4/ step5/ step6/ step7/ step8/ step9/ tests/
	ruff check --fix shared/ step1/ step2/ step3/ step4/ step5/ step6/ step7/ step8/ step9/ tests/

lint:
	ruff check shared/ step1/ step2/ step3/ step4/ step5/ step6/ step7/ step8/ step9/ tests/

format-check:
	black --check shared/ step1/ step2/ step3/ step4/ step5/ step6/ step7/ step8/ step9/ tests/

typecheck:
	mypy shared/ step1/ step2/ step3/ step4/ step5/ step6/ step7/ step8/ step9/

# ── Testing ──
test:
	pytest tests/ -v

test-cov:
	pytest tests/ -v --cov --cov-report=term-missing --cov-report=html

test-step9:
	pytest tests/test_step9.py -v

# ── All checks (CI equivalent) ──
all: lint format-check typecheck test

# ── Run locally ──
run:
	python run_local.py

# ── Clean ──
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf htmlcov/ .coverage
