"""app.py — enlace WebSocket e sessão por conexão.

Camada fina de I/O sobre a espinha (server/core.py): parseia a mensagem em
IntentEnvelope, delega ao Session (pilha de navegação + despacho) e devolve as
mensagens do protocolo.
"""
from __future__ import annotations

import json
import os

from .commands import build_registry, root_options
from .core import Dispatcher, IntentEnvelope, OptionsResponse
from .telemetry import sample_panels

DEFAULT_WS_HOST = os.environ.get("WS_HOST", "127.0.0.1")  # loopback por padrão (segurança)
DEFAULT_WS_PORT = int(os.environ.get("WS_PORT", "8765"))
WORKSPACE = os.environ.get("WORKSPACE", "vertical-manager")


class Broadcast:
    """Reúne as conexões ativas; envia para todas, descartando as que fecharam.

    Retém o último `panel` por região para novos clientes receberem o estado
    atual ao conectar (o worker só empurra quando muda — sem replay, quem chega
    depois não vê nada até a próxima transição).
    """

    def __init__(self) -> None:
        self._clientes: set = set()
        self._ultimos: dict[str, dict] = {}

    def registra(self, ws) -> None:
        self._clientes.add(ws)

    def remove(self, ws) -> None:
        self._clientes.discard(ws)

    def current(self) -> list[dict]:
        """Estado atual (um panel por região) para repassar em novas conexões."""
        return list(self._ultimos.values())

    async def send(self, message: dict) -> None:
        if message.get("type") == "panel":
            self._ultimos[message.get("region", "")] = message
        payload = json.dumps(message)
        for ws in list(self._clientes):
            try:
                await ws.send(payload)
            except Exception:
                self._clientes.discard(ws)


broadcast = Broadcast()


class Session:
    """Estado de navegação de uma conexão: pilha de options + despacho."""

    def __init__(self, registry) -> None:
        self.dispatcher = Dispatcher(registry)
        self.stack: list[OptionsResponse] = [root_options()]

    @property
    def current(self) -> OptionsResponse:
        return self.stack[-1]

    def initial_messages(self) -> list[dict]:
        """status (Zona A) + options da raiz (Zona B), na ordem de chegada."""
        return [
            {"type": "status", "context": {"workspace": WORKSPACE}, "connection": "connected"},
            self.current.to_message(),
        ]

    async def handle(self, envelope: IntentEnvelope) -> list[dict]:
        """Um intent entra, mensagens do protocolo saem."""
        if envelope.intent == "voltar":
            if len(self.stack) > 1:
                self.stack.pop()
            return [self.current.to_message()]
        response = await self.dispatcher.dispatch(envelope)
        if isinstance(response, OptionsResponse):
            self.stack.append(response)
        return [response.to_message()]


async def connection_handler(websocket) -> None:
    broadcast.registra(websocket)
    session = Session(build_registry())
    try:
        for message in session.initial_messages() + sample_panels() + broadcast.current():
            await websocket.send(json.dumps(message))
        async for raw in websocket:
            try:
                envelope = IntentEnvelope.from_message(json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                continue
            for message in await session.handle(envelope):
                await websocket.send(json.dumps(message))
    finally:
        broadcast.remove(websocket)
