"""Roda os testes Node do cliente (client/conexao.js) dentro da suíte pytest.

O cliente é vanilla JS sem build; a lógica de reconexão é testada em Node com
socket/timers falsos (tests/client/conexao_test.js). Sem `node` no PATH, pula.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
TESTES_JS = Path(__file__).parent / "client" / "conexao_test.js"


@pytest.mark.skipif(NODE is None, reason="node não encontrado no PATH")
def test_conexao_js() -> None:
    proc = subprocess.run(
        [NODE, "--test", str(TESTES_JS)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
