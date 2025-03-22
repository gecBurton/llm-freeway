FROM python:3.13-slim
RUN apt-get clean && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install --yes build-essential

RUN pip install poetry poetry-plugin-bundle

WORKDIR /app
COPY . .
COPY .env .env

RUN poetry install

ENV DJANGO_SETTINGS_MODULE='llm_freeway.settings'
ENV PYTHONPATH "${PYTHONPATH}:/."

EXPOSE 8000

ENTRYPOINT [ "poetry", "run", "fastapi", "run", "llm_freeway/api.py" ]
