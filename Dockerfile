# Imagem do servidor do cockpit (o comando `subir_containers` controla a stack
# de demonstração em docker-compose.yml — manifestos separados).
FROM python:3.12-slim

ENV POETRY_VIRTUALENVS_CREATE=false \
    POETRY_VERSION=2.4.1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# CLI do docker + plugin compose (binários estáticos): o cockpit controla a stack
# via `docker compose`, falando com o daemon do host pelo socket montado no
# docker-compose.cockpit.yml. Sem isso, subir/derrubar/status e o InfraWorker
# falhariam com "docker não encontrado".
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker:27-cli /usr/local/libexec/docker/cli-plugins/docker-compose \
     /usr/local/libexec/docker/cli-plugins/docker-compose

RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"

COPY pyproject.toml poetry.lock ./
# Inclui o grupo dev: o comando `testes` roda o pytest dentro do container.
RUN poetry install --no-root

COPY . .

EXPOSE 8000

CMD ["python3", "run.py"]