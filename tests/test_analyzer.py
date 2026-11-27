"""test_analyzer.py — adaptador da fronteira do analyzer.

Sem ANALYZER_URL usa o dublê; com URL usa HTTP real validado contra o modelo.
Uma resposta fora do contrato deve falhar alto — nunca virar "0 duplicações".
"""
from __future__ import annotations

import httpx
import pytest

from server.analyzer import AnalyzerError, fetch_health_report
from server.app import Session
from server.commands import build_registry
from server.core import IntentEnvelope
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


def _responder(monkeypatch, corpo) -> None:
    """Faz o analyzer "real" (ANALYZER_URL) devolver `corpo`."""

    class FakeResp:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return corpo

    monkeypatch.setenv("ANALYZER_URL", "http://analyzer:9000")
    monkeypatch.setattr("server.analyzer.httpx.get", lambda url, timeout: FakeResp())


def _sem(chave: str) -> dict:
    return {k: v for k, v in EXEMPLO_RESPOSTA.items() if k != chave}


def _com_resumo(resumo) -> dict:
    return {**EXEMPLO_RESPOSTA, "resumo": resumo}


@pytest.mark.parametrize(
    "corpo",
    [
        pytest.param({}, id="vazio"),
        pytest.param([], id="lista"),
        pytest.param({"duplications": [], "summary": {}}, id="outro-idioma"),
        pytest.param(_sem("duplicacoes"), id="sem-duplicacoes"),
        pytest.param(_sem("pendencias"), id="sem-pendencias"),
        pytest.param(_sem("complexidade"), id="sem-complexidade"),
        pytest.param(_sem("resumo"), id="sem-resumo"),
        pytest.param(_com_resumo({}), id="resumo-vazio"),
        pytest.param(
            _com_resumo({"duplication_pct": 40, "max_complexity": None, "alerts": 3}),
            id="resumo-renomeado",
        ),
    ],
)
def test_formato_errado_nao_vira_relatorio_vazio(monkeypatch, corpo) -> None:
    _responder(monkeypatch, corpo)
    with pytest.raises(AnalyzerError, match="não valida"):
        fetch_health_report()


def test_relatorio_sem_achados_e_valido_quando_explicito(monkeypatch) -> None:
    # "Nada encontrado" é válido — desde que o analyzer diga isso com as chaves.
    _responder(monkeypatch, {"duplicacoes": [], "pendencias": [], "complexidade": [], "resumo": None})
    report = fetch_health_report()
    assert report.duplicacoes == []
    assert report.resumo is None


def test_valores_nulos_no_resumo_sao_aceitos(monkeypatch) -> None:
    _responder(
        monkeypatch,
        _com_resumo({"duplicacao_pct": None, "complexidade_max": None, "alertas_arquitetura": 0}),
    )
    assert fetch_health_report().resumo.duplicacao_pct is None


def test_campos_extras_sao_tolerados(monkeypatch) -> None:
    _responder(monkeypatch, {**EXEMPLO_RESPOSTA, "gerado_em": "2026-01-01"})
    assert fetch_health_report().duplicacoes


async def test_comando_saude_codigo_avisa_formato_errado(monkeypatch) -> None:
    _responder(monkeypatch, {"duplications": []})
    msgs = await Session(build_registry()).handle(IntentEnvelope("saude_codigo"))
    assert msgs[0]["type"] == "result"
    assert msgs[0]["ok"] is False
    assert "não valida" in msgs[0]["detalhe"]


def test_engine_schemas_reexporta_a_fronteira() -> None:
    from engine.schemas import EXEMPLO_RESPOSTA as EXEMPLO_ENGINE
    from engine.schemas import HealthReport as HealthReportEngine

    assert EXEMPLO_ENGINE is EXEMPLO_RESPOSTA
    assert HealthReportEngine.model_validate(EXEMPLO_RESPOSTA).duplicacoes