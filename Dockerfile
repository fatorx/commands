# Imagem do servidor do cockpit (o comando `subir_containers` controla a stack
# de demonstração em docker-compose.yml — manifestos separados).
FROM python:3.12-slim

ENV POETRY_VIRTUALENVS_CREATE=false \
    POETRY_VERSION=2.4.1

WORKDIR /app

RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"

COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root

COPY . .

EXPOSE 8000

CMD ["python3", "run.py"]