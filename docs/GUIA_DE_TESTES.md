# Guia de testes do Cockpit

Este guia reúne **todas as maneiras verificadas** de testar o repositório —
localmente, via Docker, pela suíte automatizada e pela interface real — com os
comandos passo a passo e o que esperar nos logs em cada etapa. Todos os
comandos abaixo foram executados neste ambiente antes de documentados (Poetry
2.4.1 / Python 3.10 / Docker 27.5.1 / Compose v2.35.1) e os achados da seção
final (["Pendências e riscos encontrados"](#pendências-e-riscos-encontrados))
são resultado direto dessa execução, não suposição.

## Visão geral do que existe para testar

- **Suíte pytest** (`tests/`): 80 testes — fluxo do protocolo (`test_flow.py`),
  workers de infra/saúde (`test_services.py`), adapter do analyzer
  (`test_analyzer.py`), Host/Origin (`test_security.py`), estrutura das migrations
  Alembic (`test_migrations.py`, sem tocar em banco real) e dois que rodam os testes
  Node do cliente (`tests/client/`: reconexão e varredura).
- **Validação de contrato**: `engine/schemas.py` roda um exemplo fixo contra o
  modelo Pydantic do `/health-report`.
- **Duas stacks Docker distintas** (não confundir):
  - `docker-compose.cockpit.yml` — o **próprio cockpit** (serviço `cockpit` +
    seu Postgres `db`), o que você roda para testar a aplicação em container.
  - `docker-compose.yml` — a **stack de demonstração** que o cockpit
    sobe/derruba pelos comandos `subir_containers` / `derrubar_containers` /
    `status_containers` (postgres/redis/nginx/busybox com healthchecks — só
    para exercitar os semáforos da Zona C, não é a aplicação em si).
- **A interface real**: WebSocket + client vanilla JS servidos no mesmo porto
  (`run.py`), navegável por teclado (varredura por passo) ou mouse.

---

## Pré-requisitos

```bash
python3 --version   # 3.10+
poetry --version
docker --version
docker compose version
```

```bash
poetry install
```

---

## Modo A — Local, sem Docker (ciclo mais rápido para iterar)

Ideal para desenvolvimento: reinício instantâneo, sem build de imagem.

```bash
# 1. suíte de testes
poetry run pytest -q
# esperado: "80 passed in ~2s"

# 2. contrato do /health-report (fake_analyzer, sem ANALYZER_URL)
poetry run python3 engine/schemas.py
# esperado: "OK — exemplo válido: 1 duplicações, 1 pendências, 1 de complexidade; ..."

# 3. sobe o servidor (HTTP + WebSocket no mesmo porto)
poetry run python3 run.py
```

Log esperado ao subir:

```
Cockpit em http://127.0.0.1:8000 (WebSocket no mesmo porto).
Workers: Infra poll 5s ...
```

Abra `http://localhost:8000/` no navegador. Setas movem o cursor,
espaço/Enter seleciona; segurar o switch pela janela de aceite (padrão 700 ms)
também seleciona. Para testar os modos de varredura:

```
http://localhost:8000/?modo=autoscan&dwell=700&aceite=600
```

Pela própria UI dá para exercitar os três grupos de comando (`Ações` → 
`Executar testes`, `Inspeções` → `Saúde do código` → drill-down por item,
`Infra` → `Containers` → subir/status/derrubar). **Não** rode o comando
`testes` pela UI dentro de um processo que já está sob pytest — ele dispara
`pytest` via subprocess e recursaria (por isso o teste e2e usa `saude_codigo`
para exercitar o fluxo, não `testes`).

Para derrubar: `Ctrl+C` no terminal do `run.py`.

---

## Modo B — Docker: o cockpit em container

Este é o "aplicação real, mas empacotada": builda a imagem do `Dockerfile` e
sobe o cockpit + seu Postgres via `docker-compose.cockpit.yml`.

```bash
# 1. build + subida (Postgres primeiro, cockpit só depois do healthcheck)
docker compose -f docker-compose.cockpit.yml up -d --build
```

Saída esperada (resumida): build da imagem, depois

```
Container cockpit-app-db-1  Starting
Container cockpit-app-db-1  Started
Container cockpit-app-db-1  Waiting
Container cockpit-app-db-1  Healthy
Container cockpit-app-cockpit-1  Starting
Container cockpit-app-cockpit-1  Started
```

```bash
# 2. acompanhar a evolução em tempo real
docker compose -f docker-compose.cockpit.yml ps
docker compose -f docker-compose.cockpit.yml logs -f cockpit
docker compose -f docker-compose.cockpit.yml logs -f db
```

```bash
# 3. confirmar que está respondendo
curl -i http://localhost:8000/
```

```bash
# 4. aplicar as migrations Alembic dentro do container
docker compose -f docker-compose.cockpit.yml exec cockpit alembic upgrade head
docker compose -f docker-compose.cockpit.yml exec cockpit alembic current
# esperado: "0001_infra_base (head)"
```

```bash
# 5. rodar a suíte pytest dentro do próprio container (opcional, valida a imagem)
docker compose -f docker-compose.cockpit.yml exec cockpit python3 -m pytest -q
# esperado: "78 passed, 2 skipped" (a imagem não tem node; os testes do cliente pulam)
```

```bash
# 6. derrubar
docker compose -f docker-compose.cockpit.yml down
# some volumes: para descartar também os dados do Postgres de teste:
docker compose -f docker-compose.cockpit.yml down -v
```

---

## Modo C — Docker: a stack de demonstração controlada pelo cockpit

Serve para ver os semáforos da Zona C (Infra Worker) mudarem de estado ao
vivo. Pode ser acionada de duas formas:

**C.1 — pela própria UI do cockpit** (rodando via Modo A ou B): grupo
`Infra` → `Containers` → `Subir containers` / `Status dos containers` /
`Derrubar containers` (esta última pede confirmação, é destrutiva).

**C.2 — direto pelo Docker, para depurar sem depender da UI:**

```bash
docker compose -f docker-compose.yml up -d
docker compose -f docker-compose.yml ps
docker compose -f docker-compose.yml logs -f
```

Serviços e o que esperar: `db` (Postgres, healthy via `pg_isready`), `redis`
(healthy via `redis-cli ping`), `client` (nginx, healthy via `wget`), `app`
(busybox, imprime `cockpit-demo no ar` e dorme — depende de `db`+`redis`
saudáveis primeiro).

```bash
docker compose -f docker-compose.yml down
```

Os Modos B e C podem rodar juntos: cada manifesto define o próprio nome de
projeto (`cockpit-app` e `cockpit-demo`).

Para apontar os comandos `subir/derrubar/status_containers` para a stack real
do `commands-stack` (não a demo), defina `STACK_DIR` no ambiente do cockpit
(`docs/infra/DEFINITION-01.md` documenta essa stack — API/WS/workers FastAPI,
Postgres, Redis, RabbitMQ, Nginx, tester Playwright). Isso **não foi testado
neste guia** (veja pendência 2).

---

## Modo D — Migrations isoladas (sem subir o cockpit inteiro)

Útil para iterar em uma migration nova sem builder o container:

```bash
export DATABASE_URL="postgresql+psycopg://cockpit:cockpit@localhost:5432/cockpit"
# requer um Postgres acessível nesse DSN — o do Modo B expõe só a rede interna
# do compose, então para rodar do host suba um Postgres avulso ou publique a
# porta 5432 em docker-compose.cockpit.yml antes de tentar isto de fora do container.
alembic upgrade head
alembic downgrade base
alembic revision -m "nome_da_migration"
```

Dentro do container (mais simples, DSN já injetado):

```bash
docker compose -f docker-compose.cockpit.yml exec cockpit alembic upgrade head
```

---

## Modo E — Testando o protocolo WebSocket diretamente (sem UI)

Para depurar o protocolo (`status` / `options` / `result` / `panel`) sem
depender do client vanilla JS, use qualquer cliente WS. Exemplo com
`websocat` (instalar via `cargo install websocat` ou pacote da distro):

```bash
websocat ws://localhost:8000/
# envie um intent manualmente:
{"type":"intent","intent":"saude_codigo","params":{}}
```

Ou com Python (não precisa de dependência nova, `websockets` já é dependência
do projeto):

```bash
poetry run python3 - <<'EOF'
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://localhost:8000/") as ws:
        print(await ws.recv())  # status inicial
        print(await ws.recv())  # options iniciais
        await ws.send(json.dumps({"type": "intent", "intent": "saude_codigo", "params": {}}))
        print(await ws.recv())

asyncio.run(main())
EOF
```

---

## Acompanhando logs e a evolução da plataforma

```bash
docker compose -f docker-compose.cockpit.yml logs -f          # tudo
docker compose -f docker-compose.cockpit.yml logs -f cockpit   # só a app
docker compose -f docker-compose.cockpit.yml ps                # snapshot de saúde
watch -n 2 'docker compose -f docker-compose.cockpit.yml ps'   # snapshot ao vivo
docker stats cockpit-app-cockpit-1 cockpit-app-db-1            # CPU/memória
```

Para ver o Infra Worker reagindo em tempo real: deixe o cockpit no ar (Modo
B), suba a stack de demonstração (Modo C) e acompanhe `panel` mudar de
vermelho/amarelo para verde — pela UI (Zona C) ou inspecionando as mensagens
WS cruas (Modo E).

---

## Pendências e riscos encontrados

Verificados nesta sessão ao rodar os comandos acima — não são hipóteses:

1. **Sem CI configurado.** Não há `.github/workflows` nem outro pipeline no
   repo — a suíte só roda quando alguém lembra de rodar `pytest` (ou
   `alembic`/build de imagem) manualmente. Vale considerar um workflow mínimo
   (pytest + `docker build`) antes do v1 "usável no dia a dia" mencionado em
   `docs/PLAN_V1.md`.

2. **`STACK_DIR` apontando para a stack real (`commands-stack`) não foi
   testado neste guia** — só a stack de demonstração (`docker-compose.yml`)
   foi validada. Antes de usar em produção/dia a dia, validar
   `subir_containers`/`status_containers`/`derrubar_containers` com
   `STACK_DIR=<caminho do commands-stack>` de fato apontando para o projeto
   descrito em `docs/infra/DEFINITION-01.md`.

3. **`ANALYZER_URL` real ainda não integrado.** Todo o fluxo `saude_codigo`
   testado aqui usa `fake_analyzer.py` (dublê). O adapter real
   (`server/analyzer.py` contra um `/health-report` de verdade) é trabalho do
   "Dia 3" do `docs/PLAN_V1.md` e não foi exercitado neste guia.

4. **Testes de migration são só estruturais.** `tests/test_migrations.py`
   valida o grafo Alembic (config, head, que a marcadora não toca em schema)
   mas **não roda `upgrade`/`downgrade` contra um banco real** dentro da
   suíte automatizada — isso só foi confirmado manualmente no Modo B (passo
   4) desta sessão. Se migrations de domínio forem adicionadas depois da
   `0001_infra_base`, vale um teste de integração que suba um Postgres
   (`testcontainers` ou serviço no CI) e rode `upgrade head` de verdade.

5. **Cliente testado só em parte.** `tests/client/` cobre a reconexão e a
   varredura em Node; a renderização (`client/app.js`), o áudio, o TTS e o uso
   com switch físico continuam sendo conferidos à mão (Modo A ou B + navegador).

6. **Imagens não pinadas em `docker-compose.yml`.** `redis:alpine` e
   (na stack real) `nginx:alpine` usam tag flutuante — um `docker compose
   pull` pode trazer uma versão nova sem aviso. Pin recomendado:
   `redis:7-alpine` etc., para telemetria reproduzível.
