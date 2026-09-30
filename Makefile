.PHONY: help install run-api run-worker seed demo-dedup test docker-up docker-scale docker-down clean

help:
	@echo "Available commands:"
	@echo "  make install       - Create .venv with uv and install backend/requirements.txt"
	@echo "  make run-api       - Run FastAPI web server locally"
	@echo "  make run-worker    - Run standalone background event worker"
	@echo "  make seed          - Seed synthetic demo data (10 campaigns, 500 customers)"
	@echo "  make demo-dedup    - Run concurrent batch deduplication demonstration"
	@echo "  make test          - Run full pytest test suite"
	@echo "  make docker-up     - Start PostgreSQL, Redis, API, and Worker via Docker"
	@echo "  make docker-scale  - Start and scale workers to 3 parallel processes"
	@echo "  make docker-down   - Stop and tear down Docker containers"
	@echo "  make clean         - Clean Python build and cache artifacts"

# Dependency management is uv-only (uv resolves the Python pinned in
# .python-version and downloads it if missing). pip is not used anywhere.
install:
	uv venv --clear
	uv pip install -r backend/requirements.txt

run-api:
	cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

run-worker:
	cd backend && uv run python -m app.workers

seed:
	cd backend && uv run python -m scripts.generate_synthetic_data --customers 200 --events 500 --campaigns 10

demo-dedup:
	cd backend && uv run python -m scripts.demo_deduplication

test:
	cd backend && uv run pytest app/tests -q

docker-up:
	cd backend && docker compose up --build

docker-scale:
	cd backend && docker compose up --build --scale worker=3

docker-down:
	cd backend && docker compose down -v

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	rm -rf backend/.pytest_cache
