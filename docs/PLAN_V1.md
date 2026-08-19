# v1 Implementation Plan — Multimodal Command Cockpit

## Starting point

This is **not** a greenfield build. Phase 0 already runs end to end: the
modality-agnostic spine (`IntentEnvelope`, `Registry`, `Dispatcher`), a scannable
high-contrast panel, switch scanning (step scanning with debounce and auditory
cues), local TTS, the destructive-confirmation flow, real commands (docker, tests,
code health), and an end-to-end test suite.

**v1 = evolve Phase 0 into the "cockpit"** described in the UI design doc, folding
in the corrections from design review. **Voice (Phase 2) and the LLM router
(Phase 3) are out of scope for v1**, deliberately. The goal of v1 is a solid,
switch-first visual cockpit with live telemetry and your real analyzer wired in —
good enough to start using day to day.

## Two design corrections folded in

1. **No microphone state machine in the header.** The design doc's ambient mic
   states (`Sleeping / Listening / Thinking / Speaking`) only make sense with
   continuous wake-word listening, which we dropped in favor of switch-gated
   push-to-talk. With no voice in v1, there are no `Sleeping/Listening` states to
   show. The header shows **context** (loaded workspace) + **connection state**,
   not mic states.

2. **Separate the ACTION surface from the TELEMETRY surface.** Scanning traverses
   `[data-cmd-id]` and must stay linear and lean — only the current context's
   actions (Zone B). Telemetry (Zone C: infra semaphores, git, code health) is
   glanceable, pushed by the backend, and **does not participate in scanning**.
   Letting telemetry cards into the scan set bloats the cursor exactly where
   accessibility matters most. Clean split: the `options` message drives the
   scannable set (Zone B); a new `panel` message updates the ambient widgets
   (Zone C). The existing `status` message is the minimal case of this.

## Ordering principle

Risk-ordered: reshape the skeleton early, integrate real data in the middle,
harden the scanner and audit accessibility at the end.

---

## Day 1 — Reshape the client into the cockpit + split the protocol

Restructure `client/index.html` and `client/styles.css` from the Phase 0 single
column into the rigid zone grid: Zone A (context + connection, **no mic FSM**),
Zone B (the scannable action column — the existing `options`), Zone C (telemetry
cards, non-interactive). Introduce a second server→client message type in
`server/core.py`: `{"type": "panel", "region": "infra|git|health", "data": {…}}`,
distinct from `options`. In `client/app.js`, route `panel` to the Zone C widgets
and keep `options` driving Zone B (and `Scanner.refresh()` only over Zone B). Stay
build-free and vanilla JS.

**Deliverable:** the cockpit renders; Zone B scans exactly as before; Zone C shows
cards from sample `panel` messages.

## Day 2 — Live infrastructure telemetry (the push loop)

Add a background task (the doc's "Infra Worker") in `server/services.py` /
`server/main.py`: it periodically inspects real service health (`docker` ps +
health, port checks) and pushes `panel` messages to the Zone C semaphores —
debounced, only on change. Wire the soft earcon on state transitions (green↔red),
as the doc asks ("in case the user isn't looking"). Container runtime is fixed to
**docker** (settled).

**Deliverable:** you start the services via the action and watch the semaphores go
yellow→green in real time, with a soft chime, driven by push (no client polling).

## Day 3 — Real analyzer integration + rich code-health render

Replace the `fake_analyzer.py` path with your **real Local Code Analyzer** — point
`ANALYZER_URL` at it and write a thin adapter mapping the real `/health-report`
output to the internal `item` / `panel` shapes, validated by a **Pydantic model at
the boundary** (`server/schemas.py`). Render the code-health cards in Zone C
(Card 3): complexity (thick bars, per the doc), architecture alerts, duplication %.
Note that code health appears on **both** surfaces, reusing the split: the
*glanceable summary* in Zone C (via `panel`) and the *scannable item list* in
Zone B (via `options`) when you drill in (`saude_codigo → item::N → detalhe_item`,
which already exists).

**Deliverable:** "Code health" shows the cockpit summary card from real data **and**
the scannable per-item drill-down.

## Day 4 — Harden the scanner: row-column scanning + dwell, eye-tracking friendliness

Upgrade `client/scanner.js` from linear step scanning to **row-column scanning**,
using the `group` field already carried in the protocol (Zone B actions are
grouped; scan the group first, then items within it). This is the highest-value
Phase 1 feature, and the cockpit's grouping makes it natural. Add **autoscan with
adjustable dwell** (config) — off by default (step scanning stays the default), but
available; keep the acceptance window / debounce. Eye-tracking friendliness:
confirm large targets and generous spacing, and that the *pointer* path is robust
(an eye-tracker emits dwell-clicks), requiring no precise click.

**Deliverable:** row-column works over the grouped actions; autoscan/dwell available
via config; targets validated for adaptive pointer / eye-tracker.

## Day 5 — Accessibility audit, audio polish, tests, packaging

Finalize Zone A (context + connection, no fake mic states; at most a "voice: off —
Phase 2" note). Accessibility pass: ARIA roles/labels on regions and cards,
`aria-live` on telemetry so screen readers announce changes, focus management on
options re-render, `prefers-reduced-motion` / `forced-colors` verified on the new
cockpit, a full keyboard-only run, contrast check. Audio: distinct earcons for
scan-move / select / success / failure, with the Phase 0 interruption policy so
cues don't collide. Tests: extend `tests/test_flow.py` to cover `panel` messages
and the real-analyzer adapter (with a double); a unit test for the health monitor.
Packaging: update `run.py` / README for the real analyzer config, and a "usable on
day one" boot.

**Deliverable:** a v1 you actually start using — switch-first cockpit, live
telemetry, real analyzer, hardened scanner, audited accessibility.

---

## What this plan needs from you

- **Docker** — settled (v1 fixes the runtime to docker).
- **The real `/health-report` output** — one real response body from the endpoint,
  so Day 3's adapter and the Pydantic model in `server/schemas.py` are built to
  spec rather than to the placeholder shape.
