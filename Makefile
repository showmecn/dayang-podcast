.PHONY: install dev dev-db migrate seed test lint clean

# === Local Development ===

install:
	pip install -r requirements.txt

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8088

dev-db:
	docker-compose up -d postgres redis

migrate:
	python -m app.database migrate

seed:
	python scripts/seed_data.py

test:
	python -m pytest tests/ -v --cov=app --cov-report=term-missing

test-cov:
	python -m pytest tests/ -v --cov=app --cov-report=html

lint:
	python -m ruff check app/ tests/
	python -m mypy app/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
	rm -rf .pytest_cache .coverage htmlcov
