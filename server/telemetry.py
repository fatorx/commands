"""telemetry.py — mensagens `panel` de amostra (Zona C, glanceable).

O `panel` é estritamente separado do `options`: nunca participa da varredura.
As regiões `infra` e `health` são empurradas pelos workers reais
(server/services.py) — este módulo só mantém a amostra estática de `git` até
existir uma fonte real.
"""
from __future__ import annotations


def sample_panels() -> list[dict]:
    """Amostra estática empurrada na conexão (fora infra/health, que são dos workers)."""
    return [
        {
            "type": "panel",
            "region": "git",
            "data": {"branch": "main", "alteracoes": 3},
        },
    ]