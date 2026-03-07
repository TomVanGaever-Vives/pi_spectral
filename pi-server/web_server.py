"""
web_server.py — lightweight FastAPI server for phone-based function-gen controls.

Serves a mobile-friendly HTML page on port 8080 and relays commands to the ESP32
via a shared queue that main.py drains each frame.

Usage (started automatically by main.py):
    from web_server import WebServer
    ws = WebServer(cmd_queue)
    ws.start()              # runs uvicorn in a daemon thread
    ...
    cmds = ws.drain()       # call each frame in the main loop
    ws.stop()
"""

import asyncio
import json
import logging
import os
import queue
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

STATIC_DIR = Path(__file__).parent / "static"


def _create_app(cmd_queue: queue.Queue) -> FastAPI:
    app = FastAPI(title="Spectral Controls")

    # ── WebSocket endpoint ────────────────────────────────────────────────────
    clients: list[WebSocket] = []

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        clients.append(ws)
        logging.info("WS client connected (%d total)", len(clients))
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") == "command" and "command" in msg:
                    cmd = msg["command"].strip()
                    if cmd:
                        try:
                            cmd_queue.put_nowait(cmd)
                        except queue.Full:
                            pass
        except WebSocketDisconnect:
            pass
        except Exception:
            logging.error("WS handler error:\n%s", __import__("traceback").format_exc())
        finally:
            if ws in clients:
                clients.remove(ws)
            logging.info("WS client disconnected (%d remaining)", len(clients))

    # ── Serve static files ────────────────────────────────────────────────────
    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app


class WebServer:
    """Thin wrapper: runs FastAPI/uvicorn in a daemon thread."""

    def __init__(self, port: int = 8080):
        self._port = port
        self._cmd_queue: queue.Queue = queue.Queue(maxsize=200)
        self._app = _create_app(self._cmd_queue)
        self._thread: threading.Thread | None = None
        self._server: uvicorn.Server | None = None

    def start(self) -> None:
        cfg = uvicorn.Config(
            self._app,
            host="0.0.0.0",
            port=self._port,
            log_level="warning",
        )
        self._server = uvicorn.Server(cfg)
        self._thread = threading.Thread(
            target=self._server.run, daemon=True, name="web-server",
        )
        self._thread.start()
        logging.info("Web controls server started on http://0.0.0.0:%d", self._port)

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True

    def drain(self) -> list[str]:
        """Return all pending commands from the web UI (non-blocking)."""
        cmds: list[str] = []
        while True:
            try:
                cmds.append(self._cmd_queue.get_nowait())
            except queue.Empty:
                break
        return cmds
