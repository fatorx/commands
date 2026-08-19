# Cockpit — Multimodal Command Cockpit

Controlador switch-first de ambiente de desenvolvimento: varredura por passos sobre
ações, telemetria glanceable, TTS e fluxo de confirmação destrutiva. **v1** em
implementação — veja `docs/PLAN_V1.md` (roadmap), `docs/plans/PLAN_V1_EXEC_10D.md`
(plano de 10 dias) e `docs/infra/DEFINITION-01.md` (a stack real controlada).

## Rodar

Requer Python 3.10+ e Docker (para os comandos de containers).

```bash
poetry install
python3 run.py            # http://localhost:8000 (WebSocket no mesmo porto)
```

Use **espaço/Enter** para selecionar na varredura (ou clique), setas para mover o cursor.
Ações destrutivas pedem uma segunda confirmação. Mensagens são lidas por TTS (`pt-BR`).

## Varredura (modos)

- **Passo** (padrão): cada toque no switch (ou espaço) avança um item; **segurar** o
  switch pela janela de aceite (padrão 700 ms) seleciona — ideal para switch/ponteiro
  adaptativo.
- **Autoscan**: a varredura avança sozinha a cada `dwell`; um toque seleciona.

Ações agrupadas usam varredura **linha-coluna**: o cursor percorre os grupos primeiro;
selecionar um grupo entra nos itens dele (um item "↑ Grupos" volta). Config via query:

```bash
# autoscan com dwell de 700 ms e aceite de 600 ms:
python3 run.py   # depois abra http://localhost:8000/?modo=autoscan&dwell=700&aceite=600
```

## Comandos

| Intent | Efeito |
|---|---|
| `testes` | roda a suíte pytest do cockpit |
| `saude_codigo` → `item::N` → `detalhe_item` | drill-down de saúde do código |
| `subir_containers` / `derrubar_containers` | `docker compose up -d` / `down` na stack |
| `status_containers` | `docker compose ps` resumido |

A stack de containers controlada é o `docker-compose.yml` (demo, com semáforos de
verdade: postgres/redis/nginx/busybox com healthchecks). Para apontar à stack real,
defina `STACK_DIR=<diretório do commands-stack>` — os comandos passam a executar o
compose daquele projeto (`docs/infra/DEFINITION-01.md`).

## O cockpit em Docker

`docker-compose.yml` é a **stack de demonstração** (o que o cockpit sobe/derruba). O
próprio cockpit roda com o manifest próprio:

```bash
docker compose -f docker-compose.cockpit.yml up -d --build
```

## Variáveis de ambiente

| Variável | Padrão | Uso |
|---|---|---|
| `PORT` | `8000` | porta do cockpit (HTTP + WS) |
| `WS_HOST` / `WS_PORT` | `0.0.0.0` / `8765` | host/porta do WebSocket (ignorado se `PORT` setado em `run.py`) |
| `WORKSPACE` | `vertical-manager` | contexto exibido na Zona A |
| `STACK_DIR` | raiz do repo | diretório do compose controlado por `subir/derrubar/status_containers` |
| `INFRA_POLL_SECONDS` | `5` | intervalo de leitura do Infra Worker (push de semáforos) |
| `ANALYZER_URL` | — | URL do Local Code Analyzer real (Dia 8) |
| `DATABASE_URL` | `postgresql+psycopg://cockpit:cockpit@localhost:5432/cockpit` | DSN do Postgres usado pelo Alembic |

## Testes

```bash
python3 -m pytest
python3 engine/schemas.py   # valida o contrato do /health-report
```

## Migrations (Alembic + PostgreSQL)

O cockpit tem a infraestrutura de migrations Alembic pronta (PostgreSQL via
psycopg). A primeira migration é apenas **marcadora** (`0001_infra_base`) — o
domínio ainda não tem tabelas.

```bash
export DATABASE_URL="postgresql+psycopg://cockpit:cockpit@localhost:5432/cockpit"
alembic upgrade head        # aplica as migrations
alembic downgrade base      # desfaz até a base
alembic revision -m "nome"  # nova migration
```

`DATABASE_URL` é lido de ambiente; sem a variável, usa o padrão
`postgresql+psycopg://cockpit:cockpit@localhost:5432/cockpit`. No Docker, o
`docker-compose.cockpit.yml` sobe um `db` (postgres:15-alpine) e injeta o
`DATABASE_URL` no cockpit:

```bash
docker compose -f docker-compose.cockpit.yml exec cockpit alembic upgrade head
```

## Estrutura

- `server/core.py` — espinha: `IntentEnvelope`, `Registry`, `Dispatcher` + modelos do protocolo
- `server/commands.py` — catálogo de comandos (docker, testes, saude_codigo)
- `server/app.py` — sessão por conexão WebSocket (pilha de navegação)
- `client/` — vanilla JS, sem build: `app.js`, `scanner.js`, `styles.css`, `index.html`
- `engine/schemas.py` — modelo Pydantic (PROVISIONAL) da resposta do `/health-report`
- `fake_analyzer.py` — dublê do analyzer (contrato validado)
- `run.py` — boot: estáticos + WebSocket num porto só
