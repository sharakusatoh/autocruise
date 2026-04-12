from __future__ import annotations

import hashlib
import json
import socket
import threading
from pathlib import Path
from typing import Callable


def _port_for_root(root: Path) -> int:
    digest = hashlib.sha1(str(root).encode("utf-8")).digest()
    return 39000 + (int.from_bytes(digest[:2], "big") % 1000)


class LocalCommandServer:
    def __init__(self, root: Path, on_message: Callable[[dict], None]) -> None:
        self.root = root
        self.on_message = on_message
        self.port = _port_for_root(root)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._socket: socket.socket | None = None

    def start(self) -> bool:
        if self._thread is not None:
            return True
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", self.port))
            sock.listen(5)
            sock.settimeout(0.25)
        except OSError:
            sock.close()
            return False
        self._socket = sock
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return True

    def close(self) -> None:
        self._stop.set()
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass

    def _serve(self) -> None:
        while not self._stop.is_set():
            if self._socket is None:
                return
            try:
                conn, _addr = self._socket.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with conn:
                conn.settimeout(1.0)
                try:
                    payload = conn.recv(4096)
                    if not payload:
                        continue
                    message = json.loads(payload.decode("utf-8"))
                    self.on_message(message)
                    conn.sendall(b"ok")
                except Exception:  # noqa: BLE001
                    try:
                        conn.sendall(b"error")
                    except OSError:
                        pass


def send_command(root: Path, payload: dict) -> bool:
    port = _port_for_root(root)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0) as sock:
            sock.sendall(json.dumps(payload).encode("utf-8"))
            response = sock.recv(16)
            return response == b"ok"
    except OSError:
        return False
