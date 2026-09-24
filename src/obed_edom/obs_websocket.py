"""Minimal synchronous obs-websocket v5 client (loopback only).

Product code sends read-only requests (`GetVersion`, `GetOutputStatus`); the
qualification harness alone may send state-changing ones.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import time
from typing import Any

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

_OP_HELLO, _OP_IDENTIFY, _OP_IDENTIFIED, _OP_REQUEST, _OP_RESPONSE = 0, 1, 2, 6, 7
_AUTH_FAILED_CLOSE_CODE = 4009
_MAX_MESSAGE_BYTES = 4 * 1024 * 1024


class ObsWebsocketError(RuntimeError):
    """obs-websocket could not be reached or answered unexpectedly."""


class ObsWebsocketTimeout(ObsWebsocketError):
    """obs-websocket did not answer in time."""


class ObsAuthError(ObsWebsocketError):
    """obs-websocket rejected the password."""


class ObsRequestError(ObsWebsocketError):
    """obs-websocket answered a request with a failed status."""

    def __init__(self, request_type: str, code: int | None, comment: str | None) -> None:
        super().__init__(f"{request_type} failed (code {code}): {comment or 'no comment'}")
        self.request_type, self.code, self.comment = request_type, code, comment


def auth_response(password: str, salt: str, challenge: str) -> str:
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


class ObsWebsocket:
    """One authenticated connection to `ws://127.0.0.1:<port>`; use as a context manager."""

    def __init__(self, port: int, password: str | None, *, timeout: float = 3.0) -> None:
        self.port, self.timeout = int(port), timeout
        self._password = password
        self._ws: Any = None
        self._stack = contextlib.ExitStack()
        self._next_id = 0

    def __enter__(self) -> "ObsWebsocket":
        self.connect()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def connect(self) -> None:
        deadline = time.monotonic() + self.timeout
        try:
            self._ws = self._stack.enter_context(connect(f"ws://127.0.0.1:{self.port}", subprotocols=["obswebsocket.json"], open_timeout=self.timeout, max_size=_MAX_MESSAGE_BYTES))
        except TimeoutError as exc:
            raise ObsWebsocketTimeout("obs-websocket did not accept the connection in time.") from exc
        except Exception as exc:
            raise ObsWebsocketError(f"Could not connect to obs-websocket: {type(exc).__name__}") from exc
        try:
            hello = self._recv_op(_OP_HELLO, deadline)
            identify: dict[str, Any] = {"rpcVersion": 1, "eventSubscriptions": 0}
            auth = hello.get("authentication")
            if auth:
                if not self._password:
                    raise ObsAuthError("obs-websocket requires a password.")
                identify["authentication"] = auth_response(self._password, auth["salt"], auth["challenge"])
            self._send(_OP_IDENTIFY, identify)
            self._recv_op(_OP_IDENTIFIED, deadline)
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        self._ws = None
        try: self._stack.close()
        except Exception: pass

    def request(self, request_type: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._ws is None:
            raise ObsWebsocketError("obs-websocket is not connected.")
        deadline = time.monotonic() + self.timeout
        self._next_id += 1
        request_id = str(self._next_id)
        payload: dict[str, Any] = {"requestType": request_type, "requestId": request_id}
        if data:
            payload["requestData"] = data
        self._send(_OP_REQUEST, payload)
        while True:
            message = self._recv(deadline)
            if message.get("op") != _OP_RESPONSE:
                continue
            body = message.get("d") or {}
            if body.get("requestId") != request_id:
                continue
            status = body.get("requestStatus") or {}
            if not status.get("result"):
                raise ObsRequestError(request_type, status.get("code"), status.get("comment"))
            return body.get("responseData") or {}

    def _send(self, op: int, data: dict[str, Any]) -> None:
        try:
            self._ws.send(json.dumps({"op": op, "d": data}))
        except Exception as exc:
            raise ObsWebsocketError(f"obs-websocket send failed: {type(exc).__name__}") from exc

    def _recv(self, deadline: float) -> dict[str, Any]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ObsWebsocketTimeout("obs-websocket did not answer in time.")
        try:
            raw = self._ws.recv(timeout=remaining)
        except TimeoutError as exc:
            raise ObsWebsocketTimeout("obs-websocket did not answer in time.") from exc
        except ConnectionClosed as exc:
            code = exc.rcvd.code if exc.rcvd is not None else None
            if code == _AUTH_FAILED_CLOSE_CODE:
                raise ObsAuthError("obs-websocket rejected the password.") from exc
            raise ObsWebsocketError(f"obs-websocket closed the connection (code {code}).") from exc
        except Exception as exc:
            raise ObsWebsocketError(f"obs-websocket receive failed: {type(exc).__name__}") from exc
        try:
            message = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise ObsWebsocketError("obs-websocket sent a malformed message.") from exc
        if not isinstance(message, dict):
            raise ObsWebsocketError("obs-websocket sent a malformed message.")
        return message

    def _recv_op(self, op: int, deadline: float) -> dict[str, Any]:
        message = self._recv(deadline)
        if message.get("op") != op:
            raise ObsWebsocketError(f"obs-websocket sent op {message.get('op')!r}, expected {op}.")
        return message.get("d") or {}
