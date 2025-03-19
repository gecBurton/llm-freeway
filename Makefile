web:
	poetry run fastapi run llm_freeway/api.py

test:
	poetry run pytest --cov-report term-missing --cov=llm_freeway --cov-fail-under=90 tests

format:
	poetry run ruff check . --fix
	poetry run ruff format .
