"""fake_analyzer.py — dublê do Local Code Analyzer.

Devolve o EXEMPLO_RESPOSTA de engine/schemas.py (o contrato validado), para a
árvore saude_codigo ter dados hoje. O Dia 8 troca esta fonte pelo analyzer real
via ANALYZER_URL — este arquivo continua servindo de dublê nos testes.
"""
from __future__ import annotations

from engine.schemas import EXEMPLO_RESPOSTA


def health_report() -> dict:
    """Resposta bruta do /health-report tal como o analyzer entregaria."""
    return EXEMPLO_RESPOSTA
