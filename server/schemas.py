"""schemas.py — modelo tipado da resposta do /health-report (a fronteira do analisador).

Morada do modelo validado no boundary, conforme o PLAN_V1 (Dia 3): o adaptador em
server/analyzer.py valida a resposta REAL aqui. `engine/schemas.py` apenas
re-exporta este módulo (reconciliado — não duplicado).

PROVISIONAL. O modelo reflete a forma ASSUMIDA hoje — a mesma que o fake_analyzer
devolve e que o saude_codigo consome. Quando você colar a saída REAL do seu Local
Code Analyzer, reconciliamos aqui os nomes de campo e a estrutura. É exatamente
neste ponto que a validação passa a pegar divergência de formato, em vez de virar
um "0 duplicações" mudo (hoje o saude_codigo faz data.get("duplicacoes", []), então
uma chave com outro nome no analisador real viraria lista vazia, silenciosa).

Duas superfícies consomem este relatório, e cada uma puxa campos diferentes:
  - Zona B (lista varrível): a lista plana de achados (Finding) -> item::N -> detalhe.
  - Zona C (cards glanceable do cockpit): os agregados (HealthSummary).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class Finding(BaseModel):
    """Um achado individual, endereçável na lista varrível (Zona B)."""

    titulo: str                      # rótulo curto exibido no botão
    tipo: str                        # categoria: "duplicação", "pendência", ...
    detalhe: str                     # texto do drill-down (exibido na tela)
    detalhe_fala: str                # versão falada do detalhe (TTS)
    # --- opcionais, provisionais: prováveis no analisador real ---
    arquivo: str | None = None       # ex.: "auth.py:37" (para navegação futura)
    severidade: str | None = None    # ex.: "alta" | "média" | "baixa"


class ComplexidadeMax(BaseModel):
    """O pior ponto de complexidade — manchete do card de arquitetura (Zona C)."""

    modulo: str                      # ex.: "pathfinding.py"
    score: int                       # ex.: 18
    nivel: str                       # ex.: "Muito Alta"


class HealthSummary(BaseModel):
    """Agregados glanceable para os cards do cockpit (Zona C).

    PROVISIONAL: confirme se o analisador já entrega isto pronto, ou se o adaptador
    do Dia 3 precisa DERIVAR estes valores percorrendo a lista de achados.
    """

    duplicacao_pct: float | None = None            # ex.: 5.0 -> "Duplicação 5% (Aprovado)"
    complexidade_max: ComplexidadeMax | None = None
    alertas_arquitetura: int = 0                    # ex.: 2 -> "2 rotas sem anotação de auth"


class HealthReport(BaseModel):
    """Resposta completa do /health-report.

    REAL-ATUAL (o que o fake_analyzer já devolve e o saude_codigo já lê):
        as listas `duplicacoes` e `pendencias`.
    PROVISIONAL-PARA-O-COCKPIT (a confirmar contra a saída real do analisador):
        `complexidade` e `resumo`, que a Zona C do cockpit v1 precisa.
    """

    # real-atual
    duplicacoes: list[Finding] = Field(default_factory=list)
    pendencias: list[Finding] = Field(default_factory=list)
    # provisional-para-o-cockpit
    complexidade: list[Finding] = Field(default_factory=list)
    resumo: HealthSummary | None = None


# Exemplo que valida contra o modelo. Duplo papel: documenta a forma esperada e
# serve de fixture. Quando ligarmos o cockpit, o fake_analyzer.py pode passar a
# devolver algo assim (é o dublê ficando mais rico, ainda dentro do contrato).
EXEMPLO_RESPOSTA = {
    "duplicacoes": [
        {
            "titulo": "Bloco duplicado em auth.py e login.py",
            "tipo": "duplicação",
            "detalhe": "37 linhas idênticas de validação de token aparecem nos dois módulos.",
            "detalhe_fala": "Trinta e sete linhas de validação de token duplicadas entre auth e login.",
            "arquivo": "auth.py:37",
            "severidade": "média",
        },
    ],
    "pendencias": [
        {
            "titulo": "Feature: exportar relatório em CSV",
            "tipo": "pendência",
            "detalhe": "O endpoint /export está planejado, mas ainda não implementado.",
            "detalhe_fala": "Falta implementar a exportação de relatório em C S V.",
        },
    ],
    "complexidade": [
        {
            "titulo": "pathfinding.py — complexidade 18 (Muito Alta)",
            "tipo": "complexidade",
            "detalhe": "A função find_route concentra complexidade ciclomática 18.",
            "detalhe_fala": "O módulo pathfinding tem complexidade dezoito, muito alta.",
            "arquivo": "pathfinding.py",
            "severidade": "alta",
        },
    ],
    "resumo": {
        "duplicacao_pct": 5.0,
        "complexidade_max": {"modulo": "pathfinding.py", "score": 18, "nivel": "Muito Alta"},
        "alertas_arquitetura": 2,
    },
}


if __name__ == "__main__":
    # Valida o exemplo contra o modelo.
    report = HealthReport.model_validate(EXEMPLO_RESPOSTA)
    print(
        "OK — exemplo válido:",
        f"{len(report.duplicacoes)} duplicações,",
        f"{len(report.pendencias)} pendências,",
        f"{len(report.complexidade)} de complexidade;",
        "resumo:", report.resumo.model_dump() if report.resumo else None,
    )