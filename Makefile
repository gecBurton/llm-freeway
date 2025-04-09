web:
	poetry run fastapi run llm_freeway/api.py

test-keycloak:
	poetry run pytest --cov-report term-missing --cov=llm_freeway --cov-fail-under=77 tests

test-native:
	poetry run pytest --cov-report term-missing --cov=llm_freeway --cov-fail-under=91 tests


format:
	poetry run ruff check . --fix
	poetry run ruff format .
