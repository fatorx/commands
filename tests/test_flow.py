"""test_flow.py — fluxo de ponta a ponta da espinha (sem navegador).

Cobre o aceite do Dia 1: intent entra, status/options/result saem; comandos
reais em dublê; o spine é exercitado sem browser (incluindo via WebSocket).
"""
from __future__ import annotations

import json

import pytest
import websockets

from server.app import Session, connection_handler
from server.commands import build_registry
from server.core import IntentEnvelope

ROOT_IDS = ["testes", "saude_codigo", "containers"]


@pytest.fixture()
def session() -> Session:
    return Session(build_registry())


async def test_fluxo_raiz(session: Session) -> None:
    status, options = session.initial_messages()
    assert status["type"] == "status"
    assert status["connection"] == "connected"
    assert status["context"]["workspace"] == "vertical-manager"
    assert options["type"] == "options"
    assert [i["cmd_id"] for i in options["items"]] == ROOT_IDS
    assert options["items"][0]["group"] == "Ações"


async def test_drill_saude_codigo(session: Session) -> None:
    msgs = await session.handle(IntentEnvelope("saude_codigo"))
    assert msgs[0]["type"] == "options"
    assert msgs[0]["items"][0]["cmd_id"] == "item::0"
    assert msgs[0]["items"][0]["group"] == "Achados"

    msgs = await session.handle(IntentEnvelope("item::0"))
    assert msgs[0]["items"][0]["cmd_id"] == "detalhe_item::0"

    msgs = await session.handle(IntentEnvelope("detalhe_item::0"))
    assert msgs[0]["type"] == "result"
    assert msgs[0]["ok"] is True
    assert msgs[0]["detalhe_fala"]


async def test_voltar_retorna_a_raiz(session: Session) -> None:
    await session.handle(IntentEnvelope("saude_codigo"))
    msgs = await session.handle(IntentEnvelope("voltar"))
    assert msgs[0]["type"] == "options"
    assert [i["cmd_id"] for i in msgs[0]["items"]] == ROOT_IDS


async def test_destrutivo_marcado() -> None:
    registry = build_registry()
    assert registry.get("derrubar_containers").destructive is True
    assert registry.get("testes").destructive is False


async def test_intent_desconhecida(session: Session) -> None:
    msgs = await session.handle(IntentEnvelope("nao_existe"))
    assert msgs[0]["type"] == "result"
    assert msgs[0]["ok"] is False
    assert "nao_existe" in msgs[0]["detalhe"]


async def test_handler_com_excecao_nao_derruba(session: Session) -> None:
    msgs = await session.handle(IntentEnvelope("item::999"))
    assert msgs[0]["type"] == "result"
    assert msgs[0]["ok"] is False


async def test_subir_containers_chama_compose(session: Session, monkeypatch) -> None:
    chamadas = []

    async def fake(*args: str) -> tuple[int, str]:
        chamadas.append(args)
        return 0, "container created"

    monkeypatch.setattr("server.commands._run_compose", fake)
    msgs = await session.handle(IntentEnvelope("subir_containers"))
    assert chamadas == [("up", "-d")]
    assert msgs[0]["type"] == "result"
    assert msgs[0]["ok"] is True


async def test_derrubar_containers_chama_compose(session: Session, monkeypatch) -> None:
    chamadas = []

    async def fake(*args: str) -> tuple[int, str]:
        chamadas.append(args)
        return 0, "container removed"

    monkeypatch.setattr("server.commands._run_compose", fake)
    msgs = await session.handle(IntentEnvelope("derrubar_containers"))
    assert chamadas == [("down",)]
    assert msgs[0]["ok"] is True


async def test_status_containers_resume(session: Session, monkeypatch) -> None:
    async def fake(*args: str) -> tuple[int, str]:
        return 0, '{"Service":"db","Health":"healthy"}\n{"Service":"redis","Health":"starting"}\n'

    monkeypatch.setattr("server.commands._run_compose", fake)
    msgs = await session.handle(IntentEnvelope("status_containers"))
    assert msgs[0]["ok"] is True
    assert "db: healthy" in msgs[0]["detalhe"]
    assert "redis: starting" in msgs[0]["detalhe"]


async def test_container_sem_docker(session: Session, monkeypatch) -> None:
    async def fake(*args: str) -> tuple[int, str]:
        return 127, "docker não encontrado no PATH"

    monkeypatch.setattr("server.commands._run_compose", fake)
    msgs = await session.handle(IntentEnvelope("status_containers"))
    assert msgs[0]["ok"] is False


async def test_testes_verde(session: Session, monkeypatch) -> None:
    async def fake() -> tuple[int, str]:
        return 0, "7 passed in 0.2s"

    monkeypatch.setattr("server.commands._executar_suite", fake)
    msgs = await session.handle(IntentEnvelope("testes"))
    assert msgs[0]["ok"] is True
    assert "7 testes passaram" in msgs[0]["detalhe"]


async def test_testes_falha(session: Session, monkeypatch) -> None:
    async def fake() -> tuple[int, str]:
        return 1, "1 failed"

    monkeypatch.setattr("server.commands._executar_suite", fake)
    msgs = await session.handle(IntentEnvelope("testes"))
    assert msgs[0]["ok"] is False


def test_fake_analyzer_obedece_ao_contrato() -> None:
    from engine.schemas import HealthReport
    from fake_analyzer import health_report

    report = HealthReport.model_validate(health_report())
    assert len(report.duplicacoes) >= 1


async def test_e2e_websocket() -> None:
    server = await websockets.serve(connection_handler, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
            status = json.loads(await ws.recv())
            assert status["type"] == "status"
            options = json.loads(await ws.recv())
            assert options["type"] == "options"
            assert [i["cmd_id"] for i in options["items"]] == ROOT_IDS
            regioes = [json.loads(await ws.recv())["region"] for _ in range(1)]
            assert regioes == ["git"]
            await ws.send(json.dumps({"type": "intent", "intent": "saude_codigo"}))
            reply = json.loads(await ws.recv())
            assert reply["type"] == "options"
    finally:
        server.close()
        await server.wait_closed()


def test_panel_amostras_validas() -> None:
    from server.telemetry import sample_panels

    for msg in sample_panels():
        assert msg["type"] == "panel"
        assert msg["region"] in ("git",)
        assert "data" in msg
