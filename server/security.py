"""security.py — verificação de Host/Origin das requisições HTTP e do handshake WS.

O cockpit executa `docker compose up/down` a pedido de quem fala com o WebSocket,
então qualquer página aberta no navegador do usuário NÃO pode conseguir conectar:

  - Cross-site WebSocket hijacking: o navegador envia `Origin` no handshake e deixa
    qualquer site abrir `ws://localhost:8000`. Exigimos Origin == Host (same-origin).
  - DNS rebinding: um domínio hostil resolve para 127.0.0.1; Origin e Host passam a
    coincidir. Por isso o próprio Host precisa estar numa lista de permitidos
    (padrão: só loopback).

Clientes que não são navegadores (scripts, testes) não enviam Origin e continuam
aceitos — a defesa aqui é contra navegadores, e o bind padrão em 127.0.0.1 (run.py)
cobre a exposição de rede.

Config (env):
  ALLOWED_HOSTS    hostnames aceitos no cabeçalho Host, separados por vírgula
                   (padrão: localhost,127.0.0.1,::1; `*` desliga a checagem).
  ALLOWED_ORIGINS  origens extras aceitas (ex.: https://cockpit.exemplo.com).
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit

DEFAULT_ALLOWED_HOSTS = ("localhost", "127.0.0.1", "::1")


def _csv(valor: str) -> tuple[str, ...]:
    return tuple(p.strip().lower() for p in valor.split(",") if p.strip())


def allowed_hosts_from_env() -> tuple[str, ...]:
    bruto = os.environ.get("ALLOWED_HOSTS", "")
    return _csv(bruto) or DEFAULT_ALLOWED_HOSTS


def allowed_origins_from_env() -> tuple[str, ...]:
    return tuple(o.rstrip("/") for o in _csv(os.environ.get("ALLOWED_ORIGINS", "")))


def _hostname(host_header: str) -> str | None:
    """Hostname do cabeçalho Host (sem porta; aceita IPv6 `[::1]:8000`)."""
    try:
        return urlsplit(f"//{host_header}").hostname
    except ValueError:
        return None


def check_request(
    host_header: str | None,
    origin_header: str | None,
    *,
    allowed_hosts: tuple[str, ...] | None = None,
    allowed_origins: tuple[str, ...] | None = None,
) -> str | None:
    """Devolve None se a requisição é aceita, ou o motivo da recusa."""
    hosts = DEFAULT_ALLOWED_HOSTS if allowed_hosts is None else allowed_hosts
    origens = () if allowed_origins is None else allowed_origins

    if "*" not in hosts:
        hostname = _hostname(host_header or "")
        if not hostname or hostname.lower() not in hosts:
            return f"Host não permitido: {host_header!r}"

    if origin_header is None:
        return None  # cliente não-navegador (navegadores sempre enviam Origin no WS)

    origem = origin_header.rstrip("/").lower()
    if origem in origens:
        return None
    try:
        netloc = urlsplit(origem).netloc
    except ValueError:
        netloc = ""
    if netloc and netloc == (host_header or "").lower():
        return None  # same-origin
    return f"Origin não permitida: {origin_header!r}"
