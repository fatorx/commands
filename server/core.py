"""core.py — espinha modalidade-agnóstica do cockpit.

O cliente nunca chama funções Python: troca mensagens JSON com o servidor.

  - servidor -> cliente: status | options | result  (panel entra no Dia 5)
  - cliente -> servidor: {"type": "intent", "intent": "...", "params": {...}}

Este módulo tem só lógica pura (sem I/O): modelos do protocolo, `Registry`
(catálogo de comandos) e `Dispatcher` (rota IntentEnvelope -> handler).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable


@dataclass
class IntentEnvelope:
    """Envelope de intenção vinda do cliente (ou de um teste)."""

    intent: str
    params: dict = field(default_factory=dict)

    @classmethod
    def from_message(cls, msg: dict) -> "IntentEnvelope":
        return cls(
            intent=str(msg.get("intent", "")),
            params=dict(msg.get("params") or {}),
        )


@dataclass
class OptionsItem:
    """Um item varrível da Zona B (superfície de ação, regida pelo options)."""

    cmd_id: str
    titulo: str
    group: str | None = None
    destructive: bool = False
    detalhe: str | None = None
    detalhe_fala: str | None = None

    def to_dict(self) -> dict:
        return {
            "cmd_id": self.cmd_id,
            "titulo": self.titulo,
            "group": self.group,
            "destructive": self.destructive,
            "detalhe": self.detalhe,
            "detalhe_fala": self.detalhe_fala,
        }


@dataclass
class OptionsResponse:
    """Conjunto varrível novo: resposta de um drill-down (navegação)."""

    title: str
    items: list[OptionsItem]

    def to_message(self) -> dict:
        return {
            "type": "options",
            "title": self.title,
            "items": [item.to_dict() for item in self.items],
        }


@dataclass
class ResultResponse:
    """Resultado de uma ação (efeito colateral) ou de um erro."""

    titulo: str
    detalhe: str
    detalhe_fala: str
    ok: bool = True

    def to_message(self) -> dict:
        return {
            "type": "result",
            "ok": self.ok,
            "titulo": self.titulo,
            "detalhe": self.detalhe,
            "detalhe_fala": self.detalhe_fala,
        }


Handler = Callable[[IntentEnvelope, "Registry"], Awaitable[OptionsResponse | ResultResponse]]


@dataclass
class Command:
    """Entrada do catálogo de comandos."""

    intent: str
    titulo: str
    handler: Handler
    group: str | None = None
    destructive: bool = False
    detalhe: str | None = None
    detalhe_fala: str | None = None


class Registry:
    """Catálogo de comandos por intent."""

    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}

    def register(self, command: Command) -> None:
        if command.intent in self._commands:
            raise ValueError(f"comando duplicado: {command.intent}")
        self._commands[command.intent] = command

    def get(self, intent: str) -> Command | None:
        return self._commands.get(intent)


class Dispatcher:
    """Roteia IntentEnvelope até o handler registrado, nunca quebra o enlace."""

    def __init__(self, registry: Registry) -> None:
        self.registry = registry

    async def dispatch(self, envelope: IntentEnvelope) -> OptionsResponse | ResultResponse:
        command = self.registry.get(envelope.intent)
        if command is None:
            return ResultResponse(
                "Comando desconhecido",
                f"Não existe comando '{envelope.intent}'.",
                f"Comando {envelope.intent} desconhecido.",
                ok=False,
            )
        try:
            return await command.handler(envelope, self.registry)
        except Exception as exc:  # handler com bug não pode derrubar a sessão
            return ResultResponse(
                "Falha ao executar",
                f"{envelope.intent}: {exc}",
                f"Falha ao executar {envelope.intent}.",
                ok=False,
            )
