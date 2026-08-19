"""run.py — boot do cockpit.

Serve o client estático E o WebSocket num único porto (HTTP sem upgrade é
respondido com o arquivo; handshake `Upgrade: websocket` segue para o handler).

    PORT=8000 python3 run.py
"""
from __future__ import annotations

import asyncio
import mimetypes
import os
from pathlib import Path

import websockets
from websockets.http import Headers
from websockets.http11 import Response

from server.app import DEFAULT_WS_HOST, DEFAULT_WS_PORT, broadcast, connection_handler
from server.services import HealthWorker, InfraWorker

CLIENT_DIR = Path(__file__).parent / "client"

HOST = os.environ.get("HOST", DEFAULT_WS_HOST)
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
    """Requisição HTTP pura -> arquivo estático; handshake WS -> segue o handler."""
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return None
    return _static_response(request.path)


async def main() -> None:
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
