"""run.py — boot do cockpit.

Serve o client estático E o WebSocket num único porto (HTTP sem upgrade é
respondido com o arquivo; handshake `Upgrade: websocket` segue para o handler).

    PORT=8000 python3 run.py
"""
from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
from pathlib import Path

import websockets
from websockets.datastructures import Headers
from websockets.http11 import Response

from server.app import DEFAULT_WS_HOST, DEFAULT_WS_PORT, broadcast, connection_handler
from server.security import allowed_hosts_from_env, allowed_origins_from_env, check_request
from server.services import HealthWorker, InfraWorker

CLIENT_DIR = Path(__file__).parent / "client"

# Padrão seguro: só loopback. O cockpit controla o docker do host; expor em
# 0.0.0.0 é decisão explícita (HOST=0.0.0.0, como faz o Docker, que publica a
# porta só em 127.0.0.1).
HOST = os.environ.get("HOST", DEFAULT_WS_HOST)
ALLOWED_HOSTS = allowed_hosts_from_env()
ALLOWED_ORIGINS = allowed_origins_from_env()
PORT = int(os.environ.get("PORT", "8000"))
INFRA_POLL_SECONDS = int(os.environ.get("INFRA_POLL_SECONDS", "5"))
HEALTH_POLL_SECONDS = int(os.environ.get("HEALTH_POLL_SECONDS", "10"))


def _static_response(path: str) -> Response:
    """Resolve `path` dentro de client/ (sem escapar da raiz) e devolve o arquivo."""
    path = path.split("?", 1)[0].split("#", 1)[0]
    if path in ("", "/"):
        path = "/index.html"
    target = (CLIENT_DIR / Path(path.lstrip("/"))).resolve()
    try:
        target.relative_to(CLIENT_DIR.resolve())
    except ValueError:
        return Response(404, "Not Found", Headers(), b"fora da raiz")
    if not target.is_file():
        return Response(404, "Not Found", Headers(), b"nao encontrado")
    mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    headers = Headers()
    headers["Content-Type"] = mime
    return Response(200, "OK", headers, target.read_bytes())


async def process_request(connection, request) -> Response | None:
    """Host/Origin checados primeiro; HTTP puro -> estático; handshake WS -> handler."""
    motivo = check_request(
        request.headers.get("Host"),
        request.headers.get("Origin"),
        allowed_hosts=ALLOWED_HOSTS,
        allowed_origins=ALLOWED_ORIGINS,
    )
    if motivo:
        logging.getLogger(__name__).warning("requisição recusada: %s", motivo)
        return Response(403, "Forbidden", Headers(), b"forbidden")
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return None
    return _static_response(request.path)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(f"Cockpit em http://{HOST}:{PORT} (WebSocket no mesmo porto).")
    infra = InfraWorker(interval=INFRA_POLL_SECONDS)
    saude = HealthWorker(interval=HEALTH_POLL_SECONDS)
    print(
        f"Workers: Infra poll {INFRA_POLL_SECONDS}s "
        f"(stack {infra.stack_dir!r}), Saúde poll {HEALTH_POLL_SECONDS}s."
    )
    async with websockets.serve(connection_handler, HOST, PORT, process_request=process_request):
        task_infra = asyncio.create_task(infra.run(broadcast.send))
        task_saude = asyncio.create_task(saude.run(broadcast.send))
        try:
            await asyncio.Future()
        finally:
            task_infra.cancel()
            task_saude.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
