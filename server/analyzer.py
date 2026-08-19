"""analyzer.py — adaptador fino para o Local Code Analyzer real.

Fronteira validada em server/schemas.py. Com ANALYZER_URL definido, busca o
/health-report real via HTTP e valida contra o modelo; sem a variável, usa o
dublê fake_analyzer (mesma validação). Divergência de formato vira erro claro —
nunca um "0 duplicações" mudo.
"""
from __future__ import annotations

import os

import httpx

from .schemas import HealthReport

ANALYZER_ENDPOINT = "/health-report"


class AnalyzerError(Exception):
    """Falha ao obter ou validar o relatório do analyzer."""


def fetch_health_report() -> HealthReport:
    """Relatório validado: do analyzer real (ANALYZER_URL) ou do dublê."""
    url = os.environ.get("ANALYZER_URL", "").rstrip("/")
    if url:
        return _fetch_real(url)
    return _fetch_fake()


def _fetch_real(base_url: str) -> HealthReport:
    try:
        resp = httpx.get(f"{base_url}{ANALYZER_ENDPOINT}", timeout=10)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise AnalyzerError(f"falha HTTP no analyzer ({base_url}): {exc}") from exc
    try:
        return HealthReport.model_validate(resp.json())
    except Exception as exc:
        raise AnalyzerError(f"relatório do analyzer não valida contra o contrato: {exc}") from exc


def _fetch_fake() -> HealthReport:
    from fake_analyzer import health_report

    try:
        return HealthReport.model_validate(health_report())
    except Exception as exc:  # pragma: no cover — o dublê é validado nos testes
        raise AnalyzerError(f"dublê fora do contrato: {exc}") from exc