web:
	poetry run fastapi run src/api.py

test:
	poetry run pytest --cov-report term-missing --cov=src --cov-fail-under=90 tests

format:
	poetry run ruff check . --fix
	poetry run ruff format .
