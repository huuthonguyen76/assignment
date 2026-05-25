.PHONY: dev test backend ui install demo

install:
	uv venv && uv pip install -e ".[dev]"

backend:
	uv run uvicorn backend.main:app --reload --port 8000

ui:
	uv run streamlit run streamlit_app/app.py --server.port 8501

dev:
	@echo "Run 'make backend' and 'make ui' in two terminals."

test:
	uv run pytest -v

demo: install
	@cp -n .env.example .env || true
	@echo "Edit .env with your API keys, then run 'make backend' and 'make ui'."
