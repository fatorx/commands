# Commands — Backend Infrastructure (`commands-stack`)

Reference documentation of the Commands backend stack, captured from its
`Dockerfile` and `docker-compose.yaml`. It exists to **support the v1 plan**: this
is the real workspace the multimodal cockpit brings up (`subir_containers`), tears
down (`derrubar_containers`), and monitors (Day 2 live telemetry). The service
names, ports, and healthchecks below are the concrete targets the cockpit's Infra
Worker watches.

> Values in `${...}` come from a `.env` file loaded by every service (see
> [Environment](#environment-env)).

## Topology at a glance

The stack is **one application image run in many roles** plus managed
infrastructure images, all on a single bridge network (`commands-network`). The same
FastAPI image (`app.main:app`) is launched as the API, the WebSocket server, and
five background workers — differentiated only by the `APP_ROLE` env var and the
command. PostgreSQL, Redis, RabbitMQ and Nginx are stock images; a Playwright
container runs the client tests.

This is a **development** configuration: the source tree is bind-mounted
(`./:/core`) and Uvicorn runs with `--reload`, so it is live-reload, not a
production build.

Worth noting: the backend is FastAPI + WebSocket + workers over Redis/RabbitMQ —
the same family as the cockpit's own `/bus`. No impedance mismatch when the cockpit
controls it.

## Application image (`Dockerfile`)

Multi-stage build; the compose services target the `runtime` stage.

| Aspect | Value |
|---|---|
| Base image | `python:3.14-slim` (both stages) |
| Build stages | `builder` (WORKDIR `/api`) → `runtime` (WORKDIR `/core`) |
| Dependency manager | Poetry `1.8.2` (via pip), `pyproject.toml`, virtualenvs disabled (installs into system site-packages) |
| Builder system deps | `build-essential`, `curl`, `libpq-dev`, `pkg-config`, `protobuf-compiler` |
| Runtime system deps | `libpq5`, `curl`, `protobuf-compiler` |
| Dev tooling in runtime | Poetry (to allow `poetry add` during dev); `pydevd-pycharm ~=253.32098.74` (PyCharm remote debug, best-effort) |
| Exposed port | `8000` |
| Default command | `uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| Python env | `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1` |

PostgreSQL access is native (`libpq`), implying a psycopg-family driver. The image
also carries `protobuf-compiler`.

**Note (minor bug):** both stages run `rm -rf /var/lib/apt/collections/*`, but the
apt cache lives at `/var/lib/apt/lists/*` — so the intended cleanup is a no-op and
the images keep the apt index. Harmless, but worth fixing to trim image size.

**Note (versions):** `python:3.14-slim` is very recent; expect occasional lag in
prebuilt wheels for native dependencies. A deliberate bleeding-edge choice.

## Services

All app-role services share: build target `runtime`, working dir `/core`, bind
mount `./:/core`, `env_file: .env`, `restart: unless-stopped`,
`TZ=America/Sao_Paulo`, network `commands-network`.

| Service | Image / build | `APP_ROLE` | Command | Host→Container | Healthcheck | Depends on (healthy) |
|---|---|---|---|---|---|---|
| `app` | build (`runtime`) | `api` | `uvicorn app.main:app … --reload` | `${APP_EXTERNAL_PORT:-8006}` → 8000 | `curl -f localhost:8000/health` — 15s / 10s / ×3, start 20s | db, redis, queue |
| `ws-server` | build (`runtime`) | `websocket` | `uvicorn app.main:app … --reload` | `8007` → 8000 | `curl -f localhost:8000/health` — 15s / 10s / ×3, start 20s | db, redis, queue |
| `worker` | build (`runtime`) | `worker` | `python app/workers/worker.py` | — | — | queue, db, redis |
| `telemetry-worker` | build (`runtime`) | `telemetry-worker` | `python app/workers/telemetry_worker.py` | — | — | redis |
| `log_worker` | build (`runtime`) | `log-worker` | `python app/workers/log_worker.py` | — | — | redis, db |
| `director-worker` | build (`runtime`) | `director-worker` | `python app/workers/director_worker.py` | — | — | redis, db |
| `email-worker` | build (`runtime`) | `email-worker` | `python app/workers/email_worker.py` | — | — | queue, redis |
| `db` | `postgres:15-alpine` | — | — | `${POSTGRES_EXTERNAL_PORT:-5432}` → 5432 | `pg_isready -U $POSTGRES_USER -d $POSTGRES_DB` — 10s / 5s / ×5, start 10s | — |
| `redis` | `redis:alpine` | — | — | `${REDIS_EXTERNAL_PORT:-6379}` → 6379 | `redis-cli ping` — 10s / 5s / ×5 | — |
| `queue` | `rabbitmq:4-management-alpine` | — | — | `5673` → 5672 (AMQP); `15673` → 15672 (mgmt UI) | `rabbitmq-diagnostics -q check_running` — 10s / 5s / ×5, start 10s | — |
| `client-server` | `nginx:alpine` | — | serves `./client` | `${CLIENT_PORT:-8080}` → 80 | `wget -qO- localhost/` — 10s / 5s / ×3 | — |
| `tester` | `mcr.microsoft.com/playwright:v1.58.2-noble` | — | `npx playwright test` | `9323` → 9323 (report) | — | client-server, app, ws-server |

`db` additionally sets `shm_size: 1024mb` (shared-memory tuning for PostgreSQL).
The `tester` mounts `./client` at `/work` and runs from `/work/mobile-html`, with
`API_URL=http://app:8000` and `WS_URL=ws://ws-server:8000`.

## Managed image versions

| Component | Image tag | Pinned? |
|---|---|---|
| PostgreSQL | `postgres:15-alpine` | Yes (major 15) |
| Redis | `redis:alpine` | **No** — floating `alpine` tag |
| RabbitMQ | `rabbitmq:4-management-alpine` | Yes (major 4, with management UI) |
| Nginx | `nginx:alpine` | Floating `alpine` tag |
| Playwright | `mcr.microsoft.com/playwright:v1.58.2-noble` | Yes (exact) |

**Note (reproducibility):** `redis:alpine` and `nginx:alpine` are unpinned; a
`docker compose pull` can move them to newer releases. Pin to a major (e.g.
`redis:7-alpine`) for a reproducible telemetry baseline.

## Consolidated host ports (defaults)

| Host port | Service | Purpose |
|---|---|---|
| 8006 | `app` | FastAPI API (→ 8000) |
| 8007 | `ws-server` | WebSocket (→ 8000) |
| 5432 | `db` | PostgreSQL |
| 6379 | `redis` | Redis |
| 5673 | `queue` | RabbitMQ AMQP (→ 5672) |
| 15673 | `queue` | RabbitMQ management UI (→ 15672) |
| 8080 | `client-server` | Nginx static client |
| 9323 | `tester` | Playwright HTML report |

RabbitMQ, Nginx-client and Playwright ports are hard-coded in compose; the
app / db / redis / client ports are `.env`-overridable with the defaults shown.

## Environment (`.env`)

Every service loads `.env`. Variables referenced by compose:

| Variable | Used by | Notes |
|---|---|---|
| `APP_NAME` | container names (`${APP_NAME}-*`) | prefix for all containers |
| `DOCKER_FILE` | build | Dockerfile override; defaults to `Dockerfile` |
| `APP_EXTERNAL_PORT` | `app` | default `8006` |
| `POSTGRES_EXTERNAL_PORT` | `db` | default `5432` |
| `REDIS_EXTERNAL_PORT` | `redis` | default `6379` |
| `CLIENT_PORT` | `client-server` | default `8080` |
| `PGDATA` | `db` volume target | PostgreSQL data dir inside the container |
| `POSTGRES_USER`, `POSTGRES_DB` | `db` healthcheck | (`POSTGRES_PASSWORD` also expected by the image) |

The application reads further configuration from `.env` (DB DSN, broker URL, etc.)
that compose does not reference directly.

## Persistent data (volumes)

| Host path | Mounted at | Holds |
|---|---|---|
| `./data/volumes/postgres` | `${PGDATA}` | PostgreSQL data |
| `./data/rabbitmq` | `/var/lib/rabbitmq/mnesia` | RabbitMQ state |
| `./data/rabbitmq/log` | `/var/log/rabbitmq` | RabbitMQ logs |
| `./data/telemetry_storage` | `/core/data/telemetry_storage` | telemetry-worker output |
| `./docs/sql/` | `/docker-entrypoint-initdb.d/` | PostgreSQL init SQL (first boot only) |
| `./client` | Nginx html / tester `/work` | static client + Playwright test root |

## Bring-up & health gating

```bash
docker compose up -d          # build the app image, start the whole stack
docker compose down           # stop and remove
docker compose ps             # health status per container
docker compose logs -f app    # follow the API
```

`app` and `ws-server` declare `depends_on` with `condition: service_healthy` for
`db`, `redis` and `queue`, so the API only starts once its backing services report
healthy. Startup therefore proceeds in dependency order — infra (db / redis /
queue) → app / ws → workers / tester — which is exactly what makes the cockpit's
semaphores move yellow→green in a meaningful sequence.

## How this supports the v1 plan

**Day 2 — live infrastructure telemetry.** These are the concrete health signals
the cockpit's Infra Worker monitors, one semaphore each:

| Semaphore | Signal | Green when |
|---|---|---|
| PostgreSQL | `pg_isready` / TCP 5432 | accepting connections |
| Redis | `redis-cli ping` / TCP 6379 | replies `PONG` |
| RabbitMQ | `rabbitmq-diagnostics check_running` / mgmt 15673 | node running |
| FastAPI API | `GET /health` on 8006 | 2xx |
| WebSocket | `GET /health` on 8007 | 2xx |
| Client (Nginx) | `GET /` on 8080 | 2xx |

Because these healthchecks already exist in compose, the cockpit can read container
health directly (`docker compose ps` / `docker inspect` health status) instead of
re-implementing probes — a lighter path than polling each service itself. The five
workers have no ports or healthchecks; monitor them by container running-state if
needed.

**Day 3 — workspace context + real commands.** This stack is the workspace behind
`Workspace: commands`. `subir_containers` → `docker compose up -d` here;
`derrubar_containers` → `docker compose down`. The cockpit's own demo
`docker-compose.yml` can be replaced by pointing at this project's compose. This is
**separate** from the Local Code Analyzer that feeds `saude_codigo` — the analyzer
is its own FastAPI/PostgreSQL service, and its `/health-report` shape still needs to
be captured (see `server/schemas.py`).

**Wiring note.** If the cockpit runs on the **host**, it watches the external ports
above (8006 / 8007 / 5432 / …). If it runs **inside** `commands-network`, it uses
service names and internal ports (`app:8000`, `ws-server:8000`, `db:5432`,
`redis:6379`, `queue:5672`) — the same names the Playwright `tester` already uses.