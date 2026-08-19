"""schemas.py — re-exporta o modelo da fronteira (fonte única: server/schemas.py).

O modelo foi reconciliado para server/schemas.py (a morada prevista pelo PLAN_V1,
Dia 3). Este arquivo continua existindo por compatibilidade e como alvo de
verificação: `python3 engine/schemas.py` segue validando o exemplo.
"""
from __future__ import annotations

import sys
from pathlib import Path

# roda direto: `python3 engine/schemas.py` (alvo de verificação do AGENTS.md)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.schemas import *  # noqa: F401,F403  (re-export do contrato)
from server.schemas import EXEMPLO_RESPOSTA, HealthReport

if __name__ == "__main__":
    report = HealthReport.model_validate(EXEMPLO_RESPOSTA)
    print(
        "OK — exemplo válido:",
        f"{len(report.duplicacoes)} duplicações,",
        f"{len(report.pendencias)} pendências,",
        f"{len(report.complexidade)} de complexidade;",
        "resumo:", report.resumo.model_dump() if report.resumo else None,
    )