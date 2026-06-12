.PHONY: test test-v lint lint-fix format typecheck clean install ci

# ── Основные команды ──────────────────────────────────────────

install:
	pip3 install .

test:
	python3 -m pytest tests/ -v

test-quick:
	pm pytest tests/ -q

# ── Линтинг и форматирование ──────────────────────────────────

lint:
	ruff check .

lint-fix:
	ruff check --fix .

format:
	ruff format .

# ── Типизация ─────────────────────────────────────────────────

typecheck:
	mypy --explicit-package-bases .

# ── CI pipeline ───────────────────────────────────────────────

ci: lint typecheck test

# ── Очистка ───────────────────────────────────────────────────

clean:
	rm -rf __pycache__ .pytest_cache *.egg-info build dist
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
