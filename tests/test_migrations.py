"""test_migrations.py — grafo de migrations consistente, sem tocar em banco.

Valida a infraestrutura Alembic (config + script location) e que a cabeça
atual é a migration marcadora 0001_infra_base (que não altera schema).
"""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parent.parent
HEAD_REVISION = "0001_infra_base"


def _script() -> ScriptDirectory:
    cfg = Config(str(ROOT / "alembic.ini"))
    return ScriptDirectory.from_config(cfg)


def test_config_aponta_para_o_diretorio_de_migrations() -> None:
    script = _script()
    assert script.dir == str(ROOT / "migrations")


def test_grafo_tem_uma_cabeca_marcadora() -> None:
    script = _script()
    heads = script.get_heads()
    assert heads == [HEAD_REVISION]

    head = script.get_revision(HEAD_REVISION)
    assert head is not None
    assert head.down_revision is None
    assert head.branch_labels in (None, set())


def test_marcadora_nao_altera_schema() -> None:
    script = _script()
    path = script.get_revision(HEAD_REVISION).path
    source = Path(path).read_text(encoding="utf-8")
    assert "op." not in source
    assert "def upgrade" in source
    assert "def downgrade" in source