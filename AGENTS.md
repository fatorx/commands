# AGENTS.md

## Repo state

Implementation of `docs/PLAN_V1.md` is in progress (per `docs/plans/PLAN_V1_EXEC_10D.md`).
Not a git repo. Current layout:

- `server/` — the cockpit server: `core.py` (spine: `IntentEnvelope`, `Registry`,
  `Dispatcher` + protocol models), `commands.py` (command catalog), `app.py`
  (WebSocket sessions + `Broadcast`), `services.py` (`InfraWorker` +
  `HealthWorker`, push of `panel`), `telemetry.py` (static `git` sample panel),
  `analyzer.py` (adapter to the real analyzer), `schemas.py` (validated boundary
  model).
- `client/` — vanilla JS, build-free: `index.html` (zone grid), `styles.css`, `conexao.js` (WS + reconnect),
  `app.js` (routing + Zone C render), `scanner.js` (row-column scanning,
  passo/autoscan config, earcons, confirm).
- `engine/schemas.py` — thin re-export of `server/schemas.py` (kept so
  `python3 engine/schemas.py` still works).
- `fake_analyzer.py` — double of the analyzer (validated contract fixture).
- `run.py` — boot: serves `client/` static + WebSocket on one port.
- `tests/` — pytest (`test_flow.py`, `test_services.py`, `test_analyzer.py`,
  `test_migrations.py`).
- `migrations/` + `alembic.ini` — Alembic (PostgreSQL via psycopg); head atual é a
  marcadora `0001_infra_base` (sem domínio ainda).
- `docker-compose.yml` (demo workspace stack the cockpit controls),
  `docker-compose.cockpit.yml` + `Dockerfile` (the cockpit itself in Docker;
  `docker-compose.cockpit.yml` also runs the cockpit's own `db` postgres).
- `docs/` — `PLAN_V1.md` (roadmap), `infra/DEFINITION-01.md` (real stack),
  `plans/PLAN_V1_EXEC_10D.md` (10-day execution plan).

## Source of truth

`docs/PLAN_V1.md` is the roadmap and the record of settled design decisions. Honor
these when writing new code:

- **Zone split (design correction #2):** the ACTION surface (Zone B — scannable,
  driven by the `options` message) is strictly separate from the TELEMETRY surface
  (Zone C — glanceable cards, pushed by a `panel` message). Telemetry must NOT
  participate in scanning (`client/scanner.js` enforces `data-scan="true"` on its
  container). Keep this split in the protocol.
- **Scanning modes:** `passo` (default, hold-to-select) and `autoscan` (auto-advance
  with dwell) — chosen via query string (`?modo=autoscan&dwell=700&aceite=600`).
  Row-column scanning: groups are scanned first, then items within a group
  (pseudo-item "↑ Grupos" returns). Zone B is a `role="listbox"` driven by
  `aria-activedescendant`; `.acao` elements are not tab stops.
- **No mic state machine in the header (design correction #1):** no voice in v1;
  header shows workspace context + connection state, nothing else.
- **Scope:** Voice (Phase 2) and the LLM router (Phase 3) are explicitly out of
  scope for v1.
- **Runtime is fixed to Docker**; the stack the cockpit controls is documented in
  `docs/infra/DEFINITION-01.md` (service names, ports, healthchecks).
- **Client is vanilla JS, build-free.** No bundler, no framework.

## Protocol (server → client)

`status` (Zone A), `options` (Zone B, scannable), `result` (action outcome), `panel`
(Zone C, regions `infra|git|health`; never scanned). Client → server:
`{"type":"intent","intent":...,"params":...}`. `voltar` is a client-agnostic nav
intent handled by `server/app.py` `Session`.

## Key commands

- Run: `python3 run.py` → http://localhost:8000 (HTTP + WebSocket, one port).
- Env vars: `PORT` (default 8000, HTTP+WS in `run.py`), `WORKSPACE` (Zone A label),
  `STACK_DIR` (compose dir for `subir/derrubar/status_containers`), `ANALYZER_URL`
  (real analyzer), `INFRA_POLL_SECONDS` / `HEALTH_POLL_SECONDS` (worker poll
  intervals), `DATABASE_URL` (migrations). `WS_HOST`/`WS_PORT` in `server/app.py`
  are fallbacks only — `run.py` serves everything on `PORT`.
- Tests: `python3 -m pytest` (needs `poetry install`).
- Contract fixture validation:
  ```
  python3 engine/schemas.py   # or python3 server/schemas.py
  ```
  Requires Python 3.10+ and pydantic v2 (verified with pydantic 2.12.5).
- Docker: `docker compose -f docker-compose.cockpit.yml up -d --build` runs the
  cockpit (+ its `db` postgres); `docker-compose.yml` is the demo workspace stack that
  `subir/derrubar/status_containers` act on (`STACK_DIR` overrides the directory).
- Migrations: Alembic + PostgreSQL (psycopg). `DATABASE_URL` env overrides the
  default `postgresql+psycopg://cockpit:cockpit@localhost:5432/cockpit`. Apply with
  `alembic upgrade head` (inside the container: `docker compose -f
  docker-compose.cockpit.yml exec cockpit alembic upgrade head`). The current head is
  the marker `0001_infra_base` — no domain tables yet, so `target_metadata = None` in
  `migrations/env.py` and `alembic check`/`autogenerate` don't work until models exist.

## Conventions & gotchas

- Code comments and domain data are in **pt-BR** (`titulo`, `detalhe_fala`,
  `saude_codigo`, `duplicacoes`); plan docs in English. Match the language of the
  file you edit; keep pt-BR for user-facing strings/field names.
- `server/schemas.py` is the **single source** of the `/health-report` boundary
  model (PROVISIONAL until the real analyzer output is pasted). `engine/schemas.py`
  only re-exports it — don't duplicate or fork the models.
- `ANALYZER_URL` unset ⇒ the analyzer adapter uses `fake_analyzer.py` (validated
  against `server/schemas.py`). Set it to hit the real `/health-report`.
- The `testes` command runs the real pytest suite via subprocess. Don't write tests
  that call `testes` over the wire — it recurses (pytest spawning pytest). The e2e
  test uses `saude_codigo` for this reason.
- Workers in `server/services.py`: `InfraWorker` reads the controlled stack via
  `docker compose ps` / `docker compose config --services` (healthchecks already in
  the compose — don't reimplement probes) and pushes `panel` region `infra`;
  `HealthWorker` pushes `panel` region `health` from the validated analyzer report
  (`ANALYZER_URL` or the fake). Both send **only on change**; `Broadcast` replays
  the last panel per region to new connections. The `git` region is still a static
  sample in `server/telemetry.py`.
- Workers never die on unexpected errors: each cycle is wrapped, logged
  (`log.exception`) and retried; analyzer failures keep the last state.
- `item::N` / `detalhe_item::N` are **prefix commands** (`Registry.register_prefix`)
  resolved against a per-session snapshot in `registry.state["achados"]`, filled by
  `saude_codigo` (fetch runs in `asyncio.to_thread`). `build_registry()` must not
  call the analyzer — it runs on every connection.
- The cockpit image bundles the docker CLI + compose plugin and
  `docker-compose.cockpit.yml` mounts `/var/run/docker.sock` (root-equivalent access).
- Security: `run.py` binds `127.0.0.1` by default and `process_request` runs
  `server/security.py` `check_request` on every request (Host ∈ `ALLOWED_HOSTS`,
  Origin == Host or ∈ `ALLOWED_ORIGINS`; missing Origin is allowed). The cockpit
  controls the host's docker, so don't loosen this; the Docker compose publishes only
  `127.0.0.1:8000`.
- Client link: `client/conexao.js` (`Cockpit.Conexao`) owns the WebSocket with
  exponential-backoff reconnect. Intents sent while disconnected are **never queued**
  (`enviar` returns false → `app.js` warns); don't add a replay queue — replaying a
  stale destructive intent is unsafe. Its logic is tested in Node
  (`tests/client/conexao_test.js`, invoked from `tests/test_client_conexao.py`).
- The docker-py package is not installed; all docker access is via `subprocess`.