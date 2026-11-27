"""test_security.py — Host/Origin: o cockpit controla o docker, então páginas
hostis no navegador do usuário não podem abrir o WebSocket (CSWSH / DNS rebinding).
"""
from __future__ import annotations

import asyncio
import json

import pytest
import websockets
from websockets.exceptions import InvalidStatus

import run
from server.security import (
    DEFAULT_ALLOWED_HOSTS,
    allowed_hosts_from_env,
    allowed_origins_from_env,
    check_request,
)


# ---- lógica pura ----


@pytest.mark.parametrize(
    "host, origin",
    [
        ("localhost:8000", "http://localhost:8000"),
        ("127.0.0.1:8000", "http://127.0.0.1:8000"),
        ("[::1]:8000", "http://[::1]:8000"),
        ("localhost", "http://localhost"),
        ("localhost:8000", None),  # não-navegador: sem Origin
    ],
)
def test_aceita_loopback_same_origin(host, origin) -> None:
    assert check_request(host, origin) is None


@pytest.mark.parametrize(
    "host, origin",
    [
        ("localhost:8000", "https://evil.example"),            # CSWSH clássico
        ("localhost:8000", "http://localhost:3000"),           # outra porta local
        ("localhost:8000", "null"),                            # iframe sandbox / file://
        ("localhost:8000", "http://localhost:8000.evil.com"),  # sufixo enganoso
        ("evil.example:8000", "http://evil.example:8000"),     # DNS rebinding
        ("evil.example", None),                                # rebinding sem Origin
        (None, None),                                          # sem Host
        ("", None),
    ],
)
def test_recusa_origem_e_host_hostis(host, origin) -> None:
    assert check_request(host, origin) is not None


def test_origens_extras_explicitas() -> None:
    kw = dict(allowed_hosts=("cockpit.exemplo.com",), allowed_origins=("https://cockpit.exemplo.com",))
    assert check_request("cockpit.exemplo.com", "https://cockpit.exemplo.com/", **kw) is None
    assert check_request("cockpit.exemplo.com", "https://outro.com", **kw) is not None


def test_hosts_curinga_desliga_checagem_de_host() -> None:
    assert check_request("qualquer.coisa:1", None, allowed_hosts=("*",)) is None
    # ...mas Origin cruzada continua recusada.
    assert check_request("qualquer.coisa:1", "https://evil.example", allowed_hosts=("*",)) is not None


def test_env(monkeypatch) -> None:
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    assert allowed_hosts_from_env() == DEFAULT_ALLOWED_HOSTS
    assert allowed_origins_from_env() == ()
    monkeypatch.setenv("ALLOWED_HOSTS", "Cockpit.Local, 10.0.0.5")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://cockpit.local/")
    assert allowed_hosts_from_env() == ("cockpit.local", "10.0.0.5")
    assert allowed_origins_from_env() == ("https://cockpit.local",)


def test_bind_padrao_e_loopback() -> None:
    from server.app import DEFAULT_WS_HOST

    assert DEFAULT_WS_HOST == "127.0.0.1"


# ---- integração: o servidor real do run.py ----


@pytest.fixture()
async def servidor():
    server = await websockets.serve(
        run.connection_handler, "127.0.0.1", 0, process_request=run.process_request
    )
    try:
        yield server.sockets[0].getsockname()[1]
    finally:
        server.close()
        await server.wait_closed()


async def _http_get(port: int, host_header: str) -> int:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"GET / HTTP/1.1\r\nHost: {host_header}\r\nConnection: close\r\n\r\n".encode())
    await writer.drain()
    status = (await reader.readline()).decode()
    writer.close()
    return int(status.split()[1])


async def test_ws_same_origin_conecta(servidor) -> None:
    async with websockets.connect(
        f"ws://127.0.0.1:{servidor}/", origin=f"http://127.0.0.1:{servidor}"
    ) as ws:
        assert json.loads(await ws.recv())["type"] == "status"


async def test_ws_sem_origin_conecta(servidor) -> None:
    async with websockets.connect(f"ws://127.0.0.1:{servidor}/") as ws:
        assert json.loads(await ws.recv())["type"] == "status"


async def test_ws_origin_hostil_recebe_403(servidor) -> None:
    with pytest.raises(InvalidStatus) as exc:
        async with websockets.connect(f"ws://127.0.0.1:{servidor}/", origin="https://evil.example"):
            pass
    assert exc.value.response.status_code == 403


async def test_http_host_hostil_recebe_403_e_loopback_200(servidor) -> None:
    assert await _http_get(servidor, "evil.example") == 403
    assert await _http_get(servidor, f"127.0.0.1:{servidor}") == 200
