"""commands.py — catálogo de comandos do cockpit.

Dia 3: comandos reais. `subir/derrubar/status_containers` chamam `docker compose`
no diretório da stack (STACK_DIR, padrão: a raiz deste repo, que traz o compose
de demonstração); `testes` roda a própria suíte pytest; a saúde do código vem do
fake_analyzer (dublê do contrato — o Dia 8 troca a fonte pelo analyzer real).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .analyzer import fetch_health_report
from .core import Command, IntentEnvelope, OptionsItem, OptionsResponse, Registry, ResultResponse
from .schemas import HealthReport

ROOT_TITLE = "Pilotar ambiente"
COCKPIT_DIR = Path(__file__).resolve().parent.parent
STACK_DIR = os.environ.get("STACK_DIR", str(COCKPIT_DIR))


def _relatorio() -> HealthReport:
    """Relatório de saúde do código, validado na fronteira (server/schemas.py)."""
    return fetch_health_report()


def _achados() -> list[dict]:
    """Achados achatados (duplicações + pendências + complexidade) com tipo."""
    report = _relatorio()
    achados: list[dict] = []
    for tipo, achados_lista in (
        ("duplicação", report.duplicacoes),
        ("pendência", report.pendencias),
        ("complexidade", report.complexidade),
    ):
        for achado in achados_lista:
            achados.append(
                {
                    "titulo": achado.titulo,
                    "tipo": tipo,
                    "detalhe": achado.detalhe,
                    "detalhe_fala": achado.detalhe_fala,
                    "arquivo": achado.arquivo,
                    "severidade": achado.severidade,
                }
            )
    return achados


async def _run_compose(*args: str) -> tuple[int, str]:
    """Executa `docker compose <args>` na stack; nunca levanta exceção."""
    return await asyncio.to_thread(_run_compose_sync, *args)


def _run_compose_sync(*args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["docker", "compose", *args],
            cwd=STACK_DIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except FileNotFoundError:
        return 127, "docker não encontrado no PATH"
    except subprocess.TimeoutExpired:
        return 124, "tempo esgotado ao chamar docker"


async def _executar_suite() -> tuple[int, str]:
    """Roda a suíte pytest do cockpit; nunca levanta exceção."""
    return await asyncio.to_thread(_executar_suite_sync)


def _executar_suite_sync() -> tuple[int, str]:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=COCKPIT_DIR,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except FileNotFoundError:
        return 127, "interpretador Python não encontrado"
    except subprocess.TimeoutExpired:
        return 124, "tempo esgotado na suíte de testes"


async def _testes(envelope: IntentEnvelope, registry: Registry) -> ResultResponse:
    code, output = await _executar_suite()
    if code == 0:
        m = re.search(r"(\d+) passed", output)
        n = m.group(1) if m else "0"
        return ResultResponse(
            "Testes",
            f"{n} testes passaram.",
            f"{n} testes passaram.",
            ok=True,
        )
    return ResultResponse(
        "Testes",
        f"Falha (código {code}). {output[-400:]}",
        "Suíte de testes com falhas.",
        ok=False,
    )


async def _saude_codigo(envelope: IntentEnvelope, registry: Registry) -> OptionsResponse:
    items = [
        OptionsItem(
            f"item::{i}",
            achado["titulo"],
            group="Achados",
            detalhe=achado.get("detalhe"),
            detalhe_fala=achado.get("detalhe_fala", achado["titulo"]),
        )
        for i, achado in enumerate(_achados())
    ]
    items.append(OptionsItem("voltar", "Voltar"))
    return OptionsResponse("Saúde do código", items)


def _achado_de(envelope: IntentEnvelope) -> dict:
    _, _, n = envelope.intent.rpartition("::")
    return _achados()[int(n)]


def _numero(envelope: IntentEnvelope) -> str:
    return envelope.intent.rpartition("::")[2]


async def _item(envelope: IntentEnvelope, registry: Registry) -> OptionsResponse:
    achado = _achado_de(envelope)
    return OptionsResponse(
        achado["titulo"],
        [
            OptionsItem(
                f"detalhe_item::{_numero(envelope)}",
                "Ver detalhe",
                group="Ações",
                detalhe_fala=f"Ver detalhe de {achado['titulo']}",
            ),
            OptionsItem("voltar", "Voltar"),
        ],
    )


async def _detalhe_item(envelope: IntentEnvelope, registry: Registry) -> ResultResponse:
    achado = _achado_de(envelope)
    return ResultResponse(
        "Detalhe",
        achado.get("detalhe", achado["titulo"]),
        achado.get("detalhe_fala", achado["titulo"]),
    )


async def _containers(envelope: IntentEnvelope, registry: Registry) -> OptionsResponse:
    return OptionsResponse(
        "Containers",
        [
            OptionsItem("status_containers", "Status dos containers", group="Infra"),
            OptionsItem("subir_containers", "Subir containers", group="Infra"),
            OptionsItem("derrubar_containers", "Derrubar containers", group="Infra", destructive=True),
            OptionsItem("voltar", "Voltar"),
        ],
    )


def _resumo_ps(output: str) -> str:
    """Reduz a saída de `docker compose ps --format json` a linhas curtas."""
    resumo = []
    for linha in output.splitlines():
        linha = linha.strip()
        if not linha:
            continue
        try:
            c = json.loads(linha)
        except json.JSONDecodeError:
            continue
        nome = c.get("Service", "?")
        saude = c.get("Health") or c.get("State") or "?"
        resumo.append(f"{nome}: {saude}")
    return "; ".join(resumo) or "sem serviços na stack"


async def _status_containers(envelope: IntentEnvelope, registry: Registry) -> ResultResponse:
    code, output = await _run_compose("ps", "--format", "json")
    if code != 0:
        return ResultResponse(
            "Status dos containers",
            f"Falha ao ler a stack (código {code}). {output[-200:]}",
            "Falha ao ler o status dos containers.",
            ok=False,
        )
    resumo = _resumo_ps(output)
    return ResultResponse("Status dos containers", resumo, resumo, ok=True)


async def _subir_containers(envelope: IntentEnvelope, registry: Registry) -> ResultResponse:
    code, output = await _run_compose("up", "-d")
    if code != 0:
        return ResultResponse(
            "Subir containers",
            f"Falha (código {code}). {output[-300:]}",
            "Falha ao subir a stack.",
            ok=False,
        )
    return ResultResponse("Subir containers", "Stack iniciada.", "Stack iniciada.", ok=True)


async def _derrubar_containers(envelope: IntentEnvelope, registry: Registry) -> ResultResponse:
    code, output = await _run_compose("down")
    if code != 0:
        return ResultResponse(
            "Derrubar containers",
            f"Falha (código {code}). {output[-300:]}",
            "Falha ao derrubar a stack.",
            ok=False,
        )
    return ResultResponse("Derrubar containers", "Stack derrubada.", "Stack derrubada.", ok=True)


def build_registry() -> Registry:
    registry = Registry()
    registry.register(Command("testes", "Executar testes", _testes, group="Ações"))
    registry.register(Command("saude_codigo", "Saúde do código", _saude_codigo, group="Inspeções"))
    registry.register(Command("containers", "Containers", _containers, group="Infra"))
    registry.register(Command("subir_containers", "Subir containers", _subir_containers, group="Infra"))
    registry.register(
        Command("derrubar_containers", "Derrubar containers", _derrubar_containers, group="Infra", destructive=True)
    )
    registry.register(Command("status_containers", "Status dos containers", _status_containers, group="Infra"))
    for i in range(len(_achados())):
        registry.register(Command(f"item::{i}", f"Achado {i}", _item, group="Achados"))
        registry.register(Command(f"detalhe_item::{i}", "Ver detalhe", _detalhe_item, group="Ações"))
    return registry


def root_options() -> OptionsResponse:
    """Opções da raiz: o conjunto varrível inicial (Zona B)."""
    return OptionsResponse(
        ROOT_TITLE,
        [
            OptionsItem("testes", "Executar testes", group="Ações"),
            OptionsItem("saude_codigo", "Saúde do código", group="Inspeções"),
            OptionsItem("containers", "Containers", group="Infra"),
        ],
    )
