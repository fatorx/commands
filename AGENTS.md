# AGENTS.md

## Repo state

Implementation of `docs/PLAN_V1.md` is in progress (per `docs/plans/PLAN_V1_EXEC_10D.md`).
Not a git repo. Current layout:

- `server/` — the cockpit server: `core.py` (spine: `IntentEnvelope`, `Registry`,
  `Dispatcher` + protocol models), `commands.py` (command catalog), `app.py`
  (WebSocket sessions + `Broadcast`), `services.py` (Infra Worker, push of `panel`),
  `telemetry.py` (sample `panel` messages), `analyzer.py` (adapter to the real
  analyzer), `schemas.py` (validated boundary model).
- `client/` — vanilla JS, build-free: `index.html` (zone grid), `styles.css`,
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
- Infra Worker (`server/services.py`) reads health via `docker compose ps` /
  `docker compose config --services` (healthchecks already in the compose — don't
  reimplement probes) and pushes `panel` **only on change**; `Broadcast` replays the
  last panel per region to new connections.
- The docker-py package is not installed; all docker access is via `subprocess`.