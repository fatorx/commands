"""services.py — workers de push da Zona C.

InfraWorker: empurra a saúde da stack via `docker compose ps` (usa os healthchecks
que JÁ existem no compose; não reimplementa probes). Com a stack parada, lista os
serviços esperados (`docker compose config --services`) como "down". HealthWorker:
empurra o resumo de saúde validado (analyzer real ou dublê). Ambos só enviam
quando o estado muda (debounce por igualdade); `Broadcast` repassa o último panel.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from dataclasses import dataclass

from .analyzer import AnalyzerError, fetch_health_report
from .commands import STACK_DIR
from .schemas import HealthReport

log = logging.getLogger(__name__)

POLL_INTERVAL = float(os.environ.get("INFRA_POLL_SECONDS", "5"))
HEALTH_POLL_INTERVAL = float(os.environ.get("HEALTH_POLL_SECONDS", "10"))

# Rótulo amigável por nome de serviço (definido em docs/infra/DEFINITION-01.md).
ROTULOS = {
    "db": "PostgreSQL",
    "redis": "Redis",
    "queue": "RabbitMQ",
    "app": "API",
    "ws-server": "WebSocket",
    "client-server": "Client",
    "client": "Client",
}
# Ordem de exibição preferida nos semáforos (o resto vem depois, alfabético).
ORDEM = ["PostgreSQL", "Redis", "RabbitMQ", "API", "WebSocket", "Client"]


@dataclass(frozen=True)
class Semafaro:
    """Um sinal de saúde: rótulo + estado normalizado."""

    nome: str
    estado: str  # healthy | starting | unhealthy | down


def _rotulo(servico: str) -> str:
    return ROTULOS.get(servico, servico)


def _estado(container: dict) -> str:
    saude = (container.get("Health") or "").lower()
    if saude:
        return "healthy" if saude == "healthy" else ("starting" if saude == "starting" else "unhealthy")
    state = (container.get("State") or "").lower()
    return "healthy" if state == "running" else "down"


def _parse_ps(output: str) -> dict[str, Semafaro]:
    """docker compose ps --format json -> {serviço: Semafaro}."""
    mapa: dict[str, Semafaro] = {}
    for linha in output.splitlines():
        linha = linha.strip()
        if not linha:
            continue
        try:
            c = json.loads(linha)
        except json.JSONDecodeError:
            continue
        servico = c.get("Service", "?")
        mapa[servico] = Semafaro(_rotulo(servico), _estado(c))
    return mapa


def _parse_services(output: str) -> list[str]:
    """`docker compose config --services` -> lista de serviços esperados."""
    return [linha.strip() for linha in output.splitlines() if linha.strip()]


def _ordem(semafaro: Semafaro) -> int:
    try:
        return ORDEM.index(semafaro.nome)
    except ValueError:
        return len(ORDEM)


def _snapshot_sync(stack_dir: str) -> list[Semafaro] | None:
    """Snapshot da stack. None significa "leitura falhou" (não empurra nada)."""
    expected = _servicos_esperados_sync(stack_dir)
    ps = _run_ps_sync(stack_dir)
    if expected is None or ps is None:
        return None
    semafaros = [
        ps.get(servico, Semafaro(_rotulo(servico), "down"))
        for servico in expected
    ]
    semafaros.sort(key=_ordem)
    return semafaros


def _servicos_esperados_sync(stack_dir: str) -> list[str] | None:
    try:
        proc = subprocess.run(
            ["docker", "compose", "config", "--services"],
            cwd=stack_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return _parse_services(proc.stdout)


def _run_ps_sync(stack_dir: str) -> dict[str, Semafaro] | None:
    try:
        proc = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            cwd=stack_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return _parse_ps(proc.stdout)


def panel_infra(semafaros: list[Semafaro]) -> dict:
    """Mensagem `panel` da região infra (Zona C, glanceable)."""
    return {
        "type": "panel",
        "region": "infra",
        "data": {"semafaros": [{"nome": s.nome, "estado": s.estado} for s in semafaros]},
    }


class InfraWorker:
    """Empurra panel quando o snapshot muda (debounce por igualdade)."""

    def __init__(
        self,
        *,
        interval: float = POLL_INTERVAL,
        stack_dir: str = STACK_DIR,
        snapshot_fn=None,
    ) -> None:
        self.interval = interval
        self.stack_dir = stack_dir
        self._snapshot_fn = snapshot_fn or (lambda: _snapshot_sync(self.stack_dir))
        self._ultimo: list[Semafaro] | None = None

    async def run(self, broadcast) -> None:
        while True:
            try:
                atual = await asyncio.to_thread(self._snapshot_fn)
                if atual is not None and atual != self._ultimo:
                    self._ultimo = atual
                    await broadcast(panel_infra(atual))
            except Exception:
                # Um erro inesperado não pode matar a task (a telemetria
                # congelaria sem aviso): registra e tenta de novo no próximo ciclo.
                log.exception("InfraWorker: falha no ciclo; mantendo o último estado")
            await asyncio.sleep(self.interval)


def panel_saude(report: HealthReport) -> dict:
    """Mensagem `panel` da região health (Zona C): resumo glanceable + barras."""
    resumo = report.resumo
    cx = resumo.complexidade_max if resumo else None
    return {
        "type": "panel",
        "region": "health",
        "data": {
            "duplicacao_pct": resumo.duplicacao_pct if resumo else None,
            "alertas_arquitetura": resumo.alertas_arquitetura if resumo else 0,
            "complexidade_max": (
                {"modulo": cx.modulo, "score": cx.score, "nivel": cx.nivel} if cx else None
            ),
        },
    }


class HealthWorker:
    """Empurra o resumo de saúde validado (fake ou analyzer real), só em mudança."""

    def __init__(self, *, interval: float = HEALTH_POLL_INTERVAL, fetch_fn=None) -> None:
        self.interval = interval
        self._fetch_fn = fetch_fn or fetch_health_report
        self._ultimo: dict | None = None

    async def run(self, broadcast) -> None:
        while True:
            try:
                report = await asyncio.to_thread(self._fetch_fn)
                msg = panel_saude(report)
                if msg != self._ultimo:
                    self._ultimo = msg
                    await broadcast(msg)
            except AnalyzerError:
                pass  # analyzer fora do ar: mantém o último estado
            except Exception:
                log.exception("HealthWorker: falha no ciclo; mantendo o último estado")
            await asyncio.sleep(self.interval)
