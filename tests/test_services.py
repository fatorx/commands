"""test_services.py — Infra Worker: parsing, snapshot e debounce.

O worker lê o compose real (healthchecks já definidos) — aqui testamos a
normalização de estado, os rótulos e a política "só envia quando muda".
"""
from __future__ import annotations

import asyncio

import pytest

from server.analyzer import AnalyzerError
from server.schemas import EXEMPLO_RESPOSTA, HealthReport
from server.services import (
    HealthWorker,
    InfraWorker,
    Semafaro,
    _estado,
    _parse_ps,
    _snapshot_sync,
    panel_infra,
    panel_saude,
)


def test_estado_normaliza_saude() -> None:
    assert _estado({"Health": "healthy", "State": "running"}) == "healthy"
    assert _estado({"Health": "starting"}) == "starting"
    assert _estado({"Health": "unhealthy"}) == "unhealthy"
    assert _estado({"Health": "", "State": "running"}) == "healthy"
    assert _estado({"Health": "", "State": "exited"}) == "down"


def test_parse_ps_rotula_servicos() -> None:
    saida = (
        '{"Service":"db","Health":"healthy"}\n'
        '{"Service":"redis","Health":"starting"}\n'
        '{"Service":"queue","Health":"unhealthy"}\n'
        '{"Service":"worker","State":"running"}\n'
    )
    mapa = _parse_ps(saida)
    assert mapa["db"] == Semafaro("PostgreSQL", "healthy")
    assert mapa["redis"] == Semafaro("Redis", "starting")
    assert mapa["queue"] == Semafaro("RabbitMQ", "unhealthy")
    assert mapa["worker"] == Semafaro("worker", "healthy")
    assert "lixo" not in mapa  # linhas não-JSON são ignoradas


def test_snapshot_marca_esperados_como_down(monkeypatch) -> None:
    monkeypatch.setattr(
        "server.services._servicos_esperados_sync",
        lambda stack_dir: ["db", "redis", "queue", "app"],
    )
    monkeypatch.setattr(
        "server.services._run_ps_sync",
        lambda stack_dir: {"db": Semafaro("PostgreSQL", "healthy"), "app": Semafaro("API", "starting")},
    )
    snap = _snapshot_sync("/stack")
    assert snap == [
        Semafaro("PostgreSQL", "healthy"),
        Semafaro("Redis", "down"),
        Semafaro("RabbitMQ", "down"),
        Semafaro("API", "starting"),
    ]


def test_snapshot_falha_devolve_none(monkeypatch) -> None:
    monkeypatch.setattr("server.services._servicos_esperados_sync", lambda stack_dir: None)
    assert _snapshot_sync("/stack") is None


def test_panel_infra_shape() -> None:
    msg = panel_infra([Semafaro("PostgreSQL", "healthy"), Semafaro("RabbitMQ", "down")])
    assert msg["type"] == "panel"
    assert msg["region"] == "infra"
    assert msg["data"]["semafaros"][0] == {"nome": "PostgreSQL", "estado": "healthy"}


async def test_infra_worker_debounce() -> None:
    seq = [
        [Semafaro("PostgreSQL", "healthy")],
        [Semafaro("PostgreSQL", "healthy")],
        [Semafaro("PostgreSQL", "starting")],
        [Semafaro("PostgreSQL", "starting")],
        [Semafaro("PostgreSQL", "starting")],
    ]
    i = 0

    def snapshot():
        nonlocal i
        v = seq[min(i, len(seq) - 1)]
        i += 1
        return v

    empurrados = []

    async def broadcast(msg):
        empurrados.append(msg)

    worker = InfraWorker(interval=0.01, stack_dir="/stack", snapshot_fn=snapshot)
    task = asyncio.create_task(worker.run(broadcast))
    await asyncio.sleep(0.06)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # empurra na largada + só quando muda (healthy->starting); não repete igual.
    assert [m["data"]["semafaros"][0]["estado"] for m in empurrados] == ["healthy", "starting"]


async def test_infra_worker_ignora_falha_e_mantem_ultimo() -> None:
    estados = [None, [Semafaro("PostgreSQL", "healthy")]]
    i = 0

    def snapshot():
        nonlocal i
        v = estados[min(i, len(estados) - 1)]
        i += 1
        return v

    empurrados = []

    async def broadcast(msg):
        empurrados.append(msg)

    worker = InfraWorker(interval=0.01, stack_dir="/stack", snapshot_fn=snapshot)
    task = asyncio.create_task(worker.run(broadcast))
    await asyncio.sleep(0.04)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # a falha (None) não derruba nem empurra; o healthy empurra uma vez.
    assert len(empurrados) == 1
    assert empurrados[0]["data"]["semafaros"][0]["estado"] == "healthy"


async def test_infra_worker_sobrevive_a_excecao_inesperada(caplog) -> None:
    # Item 7: exceção qualquer (não só falha "esperada") não mata a task.
    chamadas = 0

    def snapshot():
        nonlocal chamadas
        chamadas += 1
        if chamadas == 1:
            raise RuntimeError("docker travou")
        return [Semafaro("PostgreSQL", "healthy")]

    empurrados = []

    async def broadcast(msg):
        empurrados.append(msg)

    worker = InfraWorker(interval=0.01, stack_dir="/stack", snapshot_fn=snapshot)
    task = asyncio.create_task(worker.run(broadcast))
    await asyncio.sleep(0.05)
    assert not task.done()  # continua viva
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(empurrados) == 1
    assert "InfraWorker" in caplog.text


async def test_infra_worker_sobrevive_a_falha_no_broadcast() -> None:
    envios = 0

    async def broadcast(msg):
        nonlocal envios
        envios += 1
        raise RuntimeError("falha ao enviar")

    seq = iter([[Semafaro("A", "healthy")], [Semafaro("A", "down")]] + [[Semafaro("A", "down")]] * 50)
    worker = InfraWorker(interval=0.01, stack_dir="/stack", snapshot_fn=lambda: next(seq))
    task = asyncio.create_task(worker.run(broadcast))
    await asyncio.sleep(0.05)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert envios >= 1


async def test_health_worker_sobrevive_a_excecao_inesperada(caplog) -> None:
    chamadas = 0

    def fetch():
        nonlocal chamadas
        chamadas += 1
        if chamadas == 1:
            raise ValueError("resposta bizarra")
        return HealthReport.model_validate(EXEMPLO_RESPOSTA)

    empurrados = []

    async def broadcast(msg):
        empurrados.append(msg)

    worker = HealthWorker(interval=0.01, fetch_fn=fetch)
    task = asyncio.create_task(worker.run(broadcast))
    await asyncio.sleep(0.05)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(empurrados) == 1
    assert "HealthWorker" in caplog.text


def test_panel_saude_shape() -> None:
    from server.schemas import HealthReport

    msg = panel_saude(HealthReport.model_validate(EXEMPLO_RESPOSTA))
    assert msg["type"] == "panel"
    assert msg["region"] == "health"
    assert msg["data"]["duplicacao_pct"] == 5.0
    assert msg["data"]["alertas_arquitetura"] == 2
    assert msg["data"]["complexidade_max"]["modulo"] == "pathfinding.py"


def test_panel_saude_sem_resumo() -> None:
    # Sem resumo não há número a mostrar: tudo nulo, nunca um zero inventado.
    msg = panel_saude(
        HealthReport(duplicacoes=[], pendencias=[], complexidade=[], resumo=None)
    )
    assert msg["data"]["duplicacao_pct"] is None
    assert msg["data"]["alertas_arquitetura"] is None
    assert msg["data"]["complexidade_max"] is None


async def test_health_worker_registra_analyzer_rejeitado_uma_vez(caplog) -> None:
    def fetch():
        raise AnalyzerError("relatório do analyzer não valida contra o contrato")

    empurrados = []

    async def broadcast(msg):
        empurrados.append(msg)

    worker = HealthWorker(interval=0.01, fetch_fn=fetch)
    task = asyncio.create_task(worker.run(broadcast))
    await asyncio.sleep(0.05)  # vários ciclos com o mesmo erro
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert empurrados == []
    avisos = [r for r in caplog.records if "não valida" in r.getMessage()]
    assert len(avisos) == 1


async def test_health_worker_debounce_e_tolera_analyzer_fora() -> None:
    seq = [EXEMPLO_RESPOSTA, EXEMPLO_RESPOSTA]
    i = 0

    def fetch():
        nonlocal i
        if i < len(seq):
            v = seq[i]
            i += 1
            return HealthReport.model_validate(v)
        return HealthReport.model_validate(seq[-1])

    empurrados = []

    async def broadcast(msg):
        empurrados.append(msg)

    worker = HealthWorker(interval=0.01, fetch_fn=fetch)
    task = asyncio.create_task(worker.run(broadcast))
    await asyncio.sleep(0.04)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(empurrados) == 1  # mesmo relatório não é reenviado

    def fetch_quebra():
        raise AnalyzerError("analyzer fora do ar")

    empurrados.clear()
    worker2 = HealthWorker(interval=0.01, fetch_fn=fetch_quebra)
    task2 = asyncio.create_task(worker2.run(broadcast))
    await asyncio.sleep(0.04)
    task2.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task2
    assert empurrados == []  # erro não derruba nem empurra nada
