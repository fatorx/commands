# v1 Execution Plan — 10 Days

## Purpose and relationship to `docs/PLAN_V1.md`

This is an execution breakdown of `docs/PLAN_V1.md` (the authoritative roadmap) into ten
working days. It does not change any settled design decision from PLAN_V1; it only adds
detail and re-baselines the starting point.

**Infra targets are concrete:** `docs/infra/DEFINITION-01.md` documents the real backend
stack the cockpit controls (`commands-stack` — FastAPI API + WebSocket + 5 workers over
PostgreSQL / Redis / RabbitMQ, Nginx client, Playwright tester). That document is the
source of truth for the service names, ports, healthchecks, and semaphore signals used in
Days 3 and 6–7.

**One deviation, forced by repo reality:** PLAN_V1 assumes Phase 0 (spine, scannable
panel, switch scanning, TTS, destructive confirmation, real commands, e2e tests) already
runs end to end. **That code does not exist in this repository** — only `docs/PLAN_V1.md`
and `engine/schemas.py` are present. Days 1–3 therefore rebuild the Phase 0 baseline
before the PLAN_V1 work begins. Wherever possible, the rebuild targets the **final cockpit
shape** (zone grid, `options`/`panel` split) to avoid throwaway work.

## Settled constraints (carried over from PLAN_V1)

- Zone split: ACTION surface (Zone B, scannable, driven by `options`) is strictly separate
  from TELEMETRY surface (Zone C, glanceable, pushed by `panel`). Telemetry never
  participates in scanning.
- No mic state machine in the header; voice (Phase 2) and the LLM router (Phase 3) are out
  of scope for v1.
- Runtime fixed to Docker. Client is vanilla JS, build-free (no bundler, no framework).
- Language convention: plan docs in English; code comments, user-facing strings, and domain
  field names in pt-BR (`titulo`, `detalhe_fala`, `saude_codigo`, …).

## Ordering principle

Risk-ordered, per PLAN_V1: rebuild the skeleton early (Days 1–4), integrate real data in
the middle (Days 5–8), harden the scanner and audit accessibility at the end (Days 9–10).

---

## Block 0 — Rebuild the missing Phase 0 baseline

### Day 1 — Spine + server core

**Goal:** the modality-agnostic spine and the server protocol stand on their own, testable
without a client.

- `server/core.py`: `IntentEnvelope`, `Registry`, `Dispatcher` — the spine that maps an
  intent (e.g. `saude_codigo`, `testes`, `subir_containers`, `derrubar_containers`) to a
  command.
- Server→client messages so far: `status` (context + connection) and `options` (scannable
  action set for the current context, with `group` on grouped actions).
- `run.py`: minimal boot that serves the static client and the WebSocket/socket server.
- `tests/test_flow.py`: first end-to-end test — intent in, `options`/`status` out, real
  commands wired to doubles.

**Accept:** running `python3 run.py` serves the app; `tests/test_flow.py` passes; the spine
is exercised without a browser.

### Day 2 — Client + switch scanning

**Goal:** the Phase 0 client actually usable by switch.

- `client/index.html`, `client/styles.css`: high-contrast UI. **Build it directly in the
  zone grid** (Zone A context+connection, Zone B scannable actions, Zone C telemetry
  placeholder) so Day 3–4 are refinement, not rework. No mic states.
- `client/app.js`: connects to the server, renders `options` into Zone B, routes messages.
- `client/scanner.js`: linear step scanning with debounce + acceptance window, auditory cues
  on move/select, local TTS for `detalhe_fala`.
- Destructive-confirmation flow for commands that need it (second confirm before running).

**Accept:** switch can move over Zone B actions, select, confirm a destructive command, and
hear/see feedback end to end.

### Day 3 — Commands, telemetry placeholder, packaging

**Goal:** Phase 0 completeness so the cockpit work starts from a green baseline.

- Real commands wired to the spine:
  - `subir_containers` / `derrubar_containers`: `docker compose up -d` / `docker compose
    down` against the **`commands-stack`** compose (per `docs/infra/DEFINITION-01.md`), the
    workspace behind `Workspace: commands`. This stack is **separate** from the
    Local Code Analyzer that feeds `saude_codigo`.
  - tests, code health (the `saude_codigo` drill: `saude_codigo → item::N → detalhe_item`).
- `fake_analyzer.py`: returns the `EXEMPLO_RESPOSTA` shape from `engine/schemas.py` so the
  drill-down has data today (the double gets richer, still inside the contract).
- Docker runtime: compose/manifest so the cockpit server itself runs in Docker.
- README: boot instructions.
- `tests/test_flow.py` green across the command set.

**Accept:** the whole Phase 0 loop runs end to end (browser or double), and `python3
engine/schemas.py` still validates the contract fixture.

---

## Block 1 — Reshape into the cockpit + split the protocol (PLAN_V1 Day 1)

### Day 4 — Finalize the zone grid + scope the scanner

**Goal:** the cockpit renders as a rigid grid and Zone B scans exactly as before.

- Lock Zone A (context + connection only), Zone B (scannable action column), Zone C
  (telemetry cards, non-interactive) in `client/index.html` / `styles.css`.
- Ensure `Scanner.refresh()` runs **only over Zone B** (`[data-cmd-id]` stays the scan set).
- Confirm scan targets are large and well-spaced (anticipates the adaptive pointer path).

**Accept:** grid renders; scanning behavior is unchanged from Day 2; Zone C is visibly a
separate, non-focusable surface.

### Day 5 — Protocol split: introduce `panel`

**Goal:** the `options`/`panel` split exists in protocol and client.

- New server→client message in `server/core.py`: `{"type": "panel", "region": "infra|git|health", "data": {…}}`, distinct from `options`. `status` remains the minimal case.
- `client/app.js` routes `panel` to Zone C widgets; `options` keeps driving Zone B.
- Zone C renders cards from sample `panel` messages (static fixture) with ARIA labels.

**Accept:** with sample data, Zone C shows glanceable cards; nothing telemetry-related is in
the scan set.

---

## Block 2 — Live infrastructure telemetry (PLAN_V1 Day 2)

### Day 6 — Infra Worker: the push loop

**Goal:** real infra data pushes to Zone C without client polling.

- Background task (the doc's "Infra Worker") in `server/services.py` / `server/main.py`.
- **Read container health directly** from the `commands-stack` (`docker compose ps` /
  `docker inspect` health status) instead of re-implementing probes — the healthchecks
  already exist in that compose. The worker adds debounced push of `panel` messages to the
  Zone C semaphores — only on change.
- One semaphore per signal (per `docs/infra/DEFINITION-01.md`):

  | Semaphore | Green when |
  |---|---|
  | PostgreSQL | `pg_isready` / TCP 5432 |
  | Redis | `redis-cli ping` / TCP 6379 |
  | RabbitMQ | `rabbitmq-diagnostics check_running` / mgmt 15673 |
  | FastAPI API | `GET /health` on 8006 (2xx) |
  | WebSocket | `GET /health` on 8007 (2xx) |
  | Client (Nginx) | `GET /` on 8080 (2xx) |

  The five app workers have no ports/healthchecks — monitor them by container running
  state if needed.
- **Wiring decision required (see "What this plan needs from you"):** if the cockpit runs
  on the **host**, probe the external ports above (8006/8007/5432/6379/5673/15673/8080);
  if it runs **inside** `commands-network`, use service names and internal ports
  (`app:8000`, `ws-server:8000`, `db:5432`, `redis:6379`, `queue:5672`) — the same names
  the Playwright `tester` uses.

**Accept:** start a service via `subir_containers`; the semaphores flip yellow→green in
dependency order (infra → app/ws → workers, driven by the stack's `depends_on:
service_healthy`), pushed in real time, no polling from the client.

### Day 7 — Earcons, transitions, polish

**Goal:** state changes are heard, not just seen.

- Soft earcon on state transitions (green↔red), per "in case the user isn't looking".
- Semaphore render polish (colors, labels, region grouping); `panel` region updates merge
  into the right card without re-rendering the scan set.

**Accept:** transitions are audible and the card updates are surgical (no full-client
re-render).

---

## Block 3 — Real analyzer integration + code health (PLAN_V1 Day 3)

### Day 8 — Adapter + validated boundary

**Goal:** real data instead of the double.

- Point `ANALYZER_URL` at the real Local Code Analyzer (a **separate** FastAPI/PostgreSQL
  service, not part of `commands-stack`; its `/health-report` shape still needs to be
  captured).
- Thin adapter mapping the real `/health-report` output to internal `item` / `panel` shapes.
- **Reconcile `engine/schemas.py` against the real output and place the validated boundary
  model at `server/schemas.py`** (PLAN_V1's intended home). Update `engine/schemas.py` or
  fold it in — don't duplicate. This is where format divergence stops being a silent
  "0 duplications".

**Accept:** `/health-report` is fetched, validated by the Pydantic model, and surfaces as
typed data; a malformed response raises a clear validation error instead of silently
emptying.

### Day 9 — Code-health render on both surfaces

**Goal:** health appears glanceable *and* scannable, reusing the split.

- Zone C summary card (Card 3): complexity with thick bars (per the doc), architecture
  alerts, duplication %, via `panel`.
- Zone B drill-down via `options`: `saude_codigo → item::N → detalhe_item` already exists;
  ensure it feeds from the real analyzer.

**Accept:** "Code health" shows the cockpit summary card from real data and the scannable
per-item drill-down.

---

## Block 4 — Harden the scanner + accessibility (PLAN_V1 Days 4–5)

### Day 10 — Row-column scanning, dwell, a11y audit, tests, packaging

**Goal:** the v1 you actually start using.

- Row-column scanning in `client/scanner.js`: scan the `group` first, then items within it
  (groups already ride in the protocol). This is the highest-value scanner feature.
- Autoscan with adjustable dwell via config — **off by default** (step scanning stays
  default); keep the acceptance window / debounce. Pointer path robust for eye-tracker
  dwell-clicks (no precise click needed).
- Accessibility pass: ARIA roles/labels on regions and cards, `aria-live` on telemetry,
  focus management on `options` re-render, `prefers-reduced-motion` / `forced-colors`,
  full keyboard-only run, contrast check.
- Audio polish: distinct earcons for scan-move / select / success / failure, with the
  Phase 0 interruption policy (cues don't collide).
- Tests: extend `tests/test_flow.py` to cover `panel` messages and the real-analyzer
  adapter (with a double); add a unit test for the health monitor.
- Packaging: update `run.py` / README for the real analyzer config; "usable on day one" boot.

**Accept:** row-column scanning works over grouped actions; autoscan/dwell is configurable;
the cockpit passes the a11y checklist; the extended test suite is green; a fresh boot from
the README gives a working cockpit with live telemetry and real analyzer data.

---

## What this plan needs from you

- **Where the cockpit runs vs. `commands-stack`** — host or inside `commands-network`?
  This decides whether the Infra Worker probes external ports or service names/internal
  ports (flagged on Day 6).
- **The real `/health-report` response body** — one paste so Day 8's adapter and
  `server/schemas.py` are built to spec, not to the placeholder shape (this unblocks the
  PROVISIONAL markers in `engine/schemas.py`).
- **Transport for the client↔server link** if not already settled (the current protocol
  assumes one push channel for both `options` and `panel`).
