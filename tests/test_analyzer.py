"""test_analyzer.py — adaptador da fronteira do analyzer.

Sem ANALYZER_URL usa o dublê; com URL usa HTTP real validado contra o modelo.
Uma resposta fora do contrato deve falhar alto — nunca virar "0 duplicações".
"""
from __future__ import annotations

import httpx
import pytest

from server.analyzer import AnalyzerError, fetch_health_report
from server.schemas import EXEMPLO_RESPOSTA


def test_sem_url_usa_o_duble(monkeypatch) -> None:
    monkeypatch.delenv("ANALYZER_URL", raising=False)
    report = fetch_health_report()
    assert len(report.duplicacoes) >= 1
    assert report.resumo is not None


def test_com_url_valida_resposta_real(monkeypatch) -> None:
    monkeypatch.setenv("ANALYZER_URL", "http://analyzer:9000")

    class FakeResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return EXEMPLO_RESPOSTA

    def fake_get(url: str, timeout: int) -> FakeResp:
        assert url == "http://analyzer:9000/health-report"
        return FakeResp()

    monkeypatch.setattr("server.analyzer.httpx.get", fake_get)
    report = fetch_health_report()
    assert report.complexidade[0].titulo
    assert report.resumo.alertas_arquitetura == 2


def test_com_url_resposta_fora_do_contrato_falha(monkeypatch) -> None:
    monkeypatch.setenv("ANALYZER_URL", "http://analyzer:9000")

    class FakeResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            # formato divergente: campo de outro nome + resumo inválido
            return {"duplicacoes": [], "resumo": {"duplicacao_pct": "muito"} }

    monkeypatch.setattr("server.analyzer.httpx.get", lambda url, timeout: FakeResp())
    with pytest.raises(AnalyzerError, match="não valida"):
        fetch_health_report()


def test_com_url_falha_http(monkeypatch) -> None:
    monkeypatch.setenv("ANALYZER_URL", "http://analyzer:9000")

    def boom(url: str, timeout: int):
        raise httpx.ConnectError("conexão recusada")

    monkeypatch.setattr("server.analyzer.httpx.get", boom)
    with pytest.raises(AnalyzerError, match="falha HTTP"):
        fetch_health_report()


def test_engine_schemas_reexporta_a_fronteira() -> None:
    from engine.schemas import EXEMPLO_RESPOSTA as EXEMPLO_ENGINE
    from engine.schemas import HealthReport as HealthReportEngine

    assert EXEMPLO_ENGINE is EXEMPLO_RESPOSTA
    assert HealthReportEngine.model_validate(EXEMPLO_RESPOSTA).duplicacoes