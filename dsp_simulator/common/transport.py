"""Small TCP + JSON Lines transport for local simulator processes."""

from __future__ import annotations

import queue
import socket
import socketserver
import threading
import time
from collections.abc import Callable
from typing import Any, Optional, Union

from .protocol import decode_message, encode_message

Message = dict[str, Any]
MessageResponse = Optional[Union[Message, list[Message]]]
MessageHandler = Callable[[Message, "Peer"], MessageResponse]


class Peer:
    def __init__(self, request: socket.socket):
        self._request = request
        self._lock = threading.Lock()

    def send(self, message: Message) -> bool:
        try:
            with self._lock:
                self._request.sendall(encode_message(message))
            return True
        except OSError:
            return False


class JsonLineServer:
    def __init__(self, host: str, port: int, on_message: MessageHandler, name: str = "server"):
        self.host = host
        self.port = port
        self.on_message = on_message
        self.name = name
        self._server: socketserver.ThreadingTCPServer | None = None
        self._thread: threading.Thread | None = None

    def start_background(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        owner = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                peer = Peer(self.request)
                for raw in self.rfile:
                    try:
                        message = decode_message(raw)
                        response = owner.on_message(message, peer)
                        if response is None:
                            continue
                        if isinstance(response, list):
                            for item in response:
                                peer.send(item)
                        else:
                            peer.send(response)
                    except Exception as exc:  # Keep simulation links alive during malformed traffic.
                        peer.send({"error": str(exc), "server": owner.name})

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._server = Server((self.host, self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, name=self.name, daemon=True)
        self._thread.start()

    def serve_forever(self) -> None:
        self.start_background()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


class JsonLineClient:
    def __init__(self, host: str, port: int, name: str = "client", reconnect_interval: float = 1.0):
        self.host = host
        self.port = port
        self.name = name
        self.reconnect_interval = reconnect_interval
        self._sock: socket.socket | None = None
        self._file = None
        self._send_lock = threading.Lock()
        self._messages: queue.Queue[Message] = queue.Queue()
        self._reader: threading.Thread | None = None
        self._last_connect_attempt = 0.0
        self._closed = False

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def connect(self, force: bool = False) -> bool:
        if self._closed:
            return False
        if self._sock:
            return True
        now = time.time()
        if not force and now - self._last_connect_attempt < self.reconnect_interval:
            return False
        self._last_connect_attempt = now
        try:
            sock = socket.create_connection((self.host, self.port), timeout=0.5)
            sock.settimeout(None)
            self._sock = sock
            self._file = sock.makefile("rb")
            self._reader = threading.Thread(target=self._read_loop, name=f"{self.name}-reader", daemon=True)
            self._reader.start()
            return True
        except OSError:
            self._sock = None
            self._file = None
            return False

    def _read_loop(self) -> None:
        try:
            while not self._closed and self._file:
                raw = self._file.readline()
                if not raw:
                    break
                self._messages.put(decode_message(raw))
        except OSError:
            pass
        finally:
            self._disconnect()

    def send(self, message: Message) -> bool:
        if not self.connect():
            return False
        try:
            with self._send_lock:
                assert self._sock is not None
                self._sock.sendall(encode_message(message))
            return True
        except OSError:
            self._disconnect()
            return False

    def drain(self) -> list[Message]:
        messages: list[Message] = []
        while True:
            try:
                messages.append(self._messages.get_nowait())
            except queue.Empty:
                break
        return messages

    def close(self) -> None:
        self._closed = True
        self._disconnect()

    def _disconnect(self) -> None:
        sock = self._sock
        self._sock = None
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self._file:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None
        if sock:
            try:
                sock.close()
            except OSError:
                pass


def send_message_once(host: str, port: int, message: Message, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(encode_message(message))
        return True
    except OSError:
        return False
