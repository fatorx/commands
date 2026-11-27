"""Roda os testes Node da varredura (client/scanner.js) dentro da suíte pytest.

O cliente é vanilla JS sem build; o scanner é testado em Node com DOM mínimo e
relógio falso (tests/client/scanner_test.js). Sem `node` no PATH, pula.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
TESTES_JS = Path(__file__).parent / "client" / "scanner_test.js"


@pytest.mark.skipif(NODE is None, reason="node não encontrado no PATH")
def test_scanner_js() -> None:
    proc = subprocess.run(
        [NODE, "--test", str(TESTES_JS)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
