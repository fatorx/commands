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
Ações destrutivas pedem uma segunda confirmação, com o cursor começando em **Cancelar**.
Mensagens são lidas por TTS (`pt-BR`).

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

## Segurança

O cockpit executa `docker compose up/down` a pedido de quem fala com o WebSocket, então:

- **Escuta só em loopback** por padrão (`HOST=127.0.0.1`); no Docker a porta é publicada
  em `127.0.0.1:8000`.
- **Host e Origin são verificados** (`server/security.py`): o handshake exige
  `Origin == Host` (bloqueia páginas hostis abrindo `ws://localhost:8000`) e o `Host` deve
  estar em `ALLOWED_HOSTS` (bloqueia DNS rebinding). Clientes sem `Origin` (scripts,
  testes) passam. Para acessar por outro nome/IP, defina `HOST`, `ALLOWED_HOSTS` e, se
  houver proxy HTTPS, `ALLOWED_ORIGINS`.
- Não há autenticação de usuário: não exponha a porta a redes não confiáveis.

## Reconexão do cliente

Se o servidor cair, o cliente reconecta sozinho (backoff de 1 s até 10 s, com jitter; o
evento `online` do navegador pula a espera). A Zona A mostra o estado e a próxima
tentativa, as zonas B/C ficam esmaecidas com borda tracejada, e a queda/volta é
sinalizada por earcon e voz. Ações escolhidas **sem conexão não são enfileiradas** — o
cliente avisa e você repete após reconectar. Testes da lógica: `node --test
tests/client/conexao_test.js` (também rodado pelo pytest).

## O cockpit em Docker

`docker-compose.yml` é a **stack de demonstração** (o que o cockpit sobe/derruba). O
próprio cockpit roda com o manifest próprio:

```bash
docker compose -f docker-compose.cockpit.yml up -d --build
```

Cada manifest tem nome de projeto próprio (`cockpit-app` e `cockpit-demo`), então as
duas stacks sobem juntas sem disputar o serviço `db`.

A imagem traz o CLI do docker + plugin compose e o manifest monta
`/var/run/docker.sock`, para o cockpit controlar a stack pelo daemon do host.
Atenção: acesso ao socket equivale a root no host — não exponha a porta 8000 a
redes não confiáveis.

## Variáveis de ambiente

| Variável | Padrão | Uso |
|---|---|---|
| `PORT` | `8000` | porta do cockpit (HTTP + WS) |
| `HOST` | `127.0.0.1` | interface onde o cockpit escuta (o Docker define `0.0.0.0` dentro do container e publica só em `127.0.0.1`) |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1,::1` | hostnames aceitos no cabeçalho `Host` (`*` desliga a checagem) |
| `ALLOWED_ORIGINS` | — | origens extras aceitas no WebSocket (ex.: `https://cockpit.exemplo.com`) |
| `WS_HOST` / `WS_PORT` | `127.0.0.1` / `8765` | fallbacks de `HOST`/porta (ignorados se `HOST`/`PORT` setados em `run.py`) |
| `WORKSPACE` | `vertical-manager` | contexto exibido na Zona A |
| `STACK_DIR` | raiz do repo | diretório do compose controlado por `subir/derrubar/status_containers` |
| `INFRA_POLL_SECONDS` | `5` | intervalo de leitura do Infra Worker (push de semáforos) |
| `HEALTH_POLL_SECONDS` | `10` | intervalo de leitura do Health Worker (card de saúde do código) |
| `ANALYZER_URL` | — | URL do Local Code Analyzer real (Dia 8); a resposta precisa trazer todas as chaves do contrato (`server/schemas.py`), senão é rejeitada |
| `DATABASE_URL` | `postgresql+psycopg://cockpit:cockpit@localhost:5432/cockpit` | DSN do Postgres usado pelo Alembic |

## Testes

```bash
python3 -m pytest
python3 engine/schemas.py   # valida o contrato do /health-report
node --test tests/client/scanner_test.js   # só a varredura (também rodado pelo pytest)
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
- `server/security.py` — checagem de Host/Origin (CSWSH / DNS rebinding)
- `client/` — vanilla JS, sem build: `app.js`, `scanner.js`, `conexao.js` (reconexão), `styles.css`, `index.html`
- `engine/schemas.py` — modelo Pydantic (PROVISIONAL) da resposta do `/health-report`
- `fake_analyzer.py` — dublê do analyzer (contrato validado)
- `run.py` — boot: estáticos + WebSocket num porto só
