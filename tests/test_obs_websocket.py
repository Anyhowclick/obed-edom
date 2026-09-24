from __future__ import annotations

import base64
import hashlib
import json
import socket
import threading
from typing import Any, Callable

import pytest
from websockets.sync.server import serve

from obed_edom.obs_websocket import (
    ObsAuthError,
    ObsRequestError,
    ObsWebsocket,
    ObsWebsocketError,
    ObsWebsocketTimeout,
    auth_response,
)


def _expected_auth(password: str, salt: str, challenge: str) -> str:
    # obs-websocket v5 protocol: base64(sha256(base64(sha256(password + salt)) + challenge)), written out independently.
    secret = base64.b64encode(hashlib.sha256(password.encode() + salt.encode()).digest())
    return base64.b64encode(hashlib.sha256(secret + challenge.encode()).digest()).decode()


class FakeObsWebsocket:
    """A loopback obs-websocket v5 stand-in: Hello (with auth when a password is set),
    Identify, GetVersion and GetOutputStatus. `password` is read at each connection, the
    way OBS reads its own config, so callers can point it at a seeded config.json."""

    SALT, CHALLENGE = "c2FsdA==", "Y2hhbGxlbmdl"

    def __init__(self, password: Callable[[], str | None], *, version: str = "32.2.2", output_active: bool | None = True, send_hello: bool = True) -> None:
        self.password, self.version, self.output_active, self.send_hello = password, version, output_active, send_hello
        self.requests: list[tuple[str, Any]] = []
        self.identifies: list[dict[str, Any]] = []
        self.server = serve(self._handler, "127.0.0.1", 0, subprotocols=["obswebsocket.json"])
        self.port = int(self.server.socket.getsockname()[1])
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()

    def _handler(self, ws: Any) -> None:
        if not self.send_hello:
            for _ in ws:
                pass
            return
        password = self.password()
        hello: dict[str, Any] = {"obsWebSocketVersion": "5.6.3", "rpcVersion": 1}
        if password:
            hello["authentication"] = {"salt": self.SALT, "challenge": self.CHALLENGE}
        ws.send(json.dumps({"op": 0, "d": hello}))
        identify = json.loads(ws.recv())
        self.identifies.append(identify)
        if password and identify["d"].get("authentication") != _expected_auth(password, self.SALT, self.CHALLENGE):
            ws.close(4009, "Authentication failed.")
            return
        ws.send(json.dumps({"op": 2, "d": {"negotiatedRpcVersion": 1}}))
        for raw in ws:
            message = json.loads(raw)
            body = message["d"]
            request_type, data = body["requestType"], body.get("requestData")
            self.requests.append((request_type, data))
            ws.send(json.dumps({"op": 5, "d": {"eventType": "Noise", "eventIntent": 1}}))
            ws.send(json.dumps({"op": 7, "d": {"requestType": request_type, "requestId": "not-yours", "requestStatus": {"result": True, "code": 100}, "responseData": {"obsVersion": "decoy"}}}))
            if request_type == "GetVersion":
                status, response = {"result": True, "code": 100}, {"obsVersion": self.version, "obsWebSocketVersion": "5.6.3"}
            elif request_type == "GetOutputStatus" and self.output_active is not None:
                status, response = {"result": True, "code": 100}, {"outputActive": self.output_active, "outputReconnecting": False}
            elif request_type == "GetOutputStatus":
                status, response = {"result": False, "code": 600, "comment": "No output was found with the name `decklink_output`."}, None
            else:
                status, response = {"result": False, "code": 204, "comment": "Unknown request type."}, None
            reply: dict[str, Any] = {"requestType": request_type, "requestId": body["requestId"], "requestStatus": status}
            if response is not None:
                reply["responseData"] = response
            ws.send(json.dumps({"op": 7, "d": reply}))


@pytest.fixture
def fake_obs():
    servers: list[FakeObsWebsocket] = []

    def make(password: str | None = "pw", **kwargs: Any) -> FakeObsWebsocket:
        server = FakeObsWebsocket(lambda: password, **kwargs)
        servers.append(server)
        return server

    yield make
    for server in servers:
        server.close()


def test_auth_response_matches_the_v5_formula():
    assert auth_response("hunter2", "salt", "challenge") == _expected_auth("hunter2", "salt", "challenge")


def test_identify_with_auth_then_get_version(fake_obs):
    server = fake_obs("s3cret")
    with ObsWebsocket(server.port, "s3cret") as ws:
        assert ws.request("GetVersion")["obsVersion"] == "32.2.2"
    identify = server.identifies[0]
    assert identify["op"] == 1
    assert identify["d"]["rpcVersion"] == 1
    assert identify["d"]["eventSubscriptions"] == 0
    assert server.requests == [("GetVersion", None)]


def test_request_skips_events_and_other_request_ids(fake_obs):
    server = fake_obs("pw")
    with ObsWebsocket(server.port, "pw") as ws:
        assert ws.request("GetVersion")["obsVersion"] == "32.2.2"
        assert ws.request("GetOutputStatus", {"outputName": "decklink_output"})["outputActive"] is True
    assert server.requests[1] == ("GetOutputStatus", {"outputName": "decklink_output"})


def test_no_auth_server_needs_no_password(fake_obs):
    server = fake_obs(None)
    with ObsWebsocket(server.port, None) as ws:
        assert ws.request("GetVersion")["obsVersion"] == "32.2.2"
    assert "authentication" not in server.identifies[0]["d"]


def test_wrong_password_raises_auth_error(fake_obs):
    server = fake_obs("right")
    with pytest.raises(ObsAuthError):
        ObsWebsocket(server.port, "wrong").connect()


def test_missing_password_raises_auth_error(fake_obs):
    server = fake_obs("right")
    with pytest.raises(ObsAuthError):
        ObsWebsocket(server.port, None).connect()


def test_failed_request_status_raises_typed_error(fake_obs):
    server = fake_obs("pw", output_active=None)
    with ObsWebsocket(server.port, "pw") as ws:
        with pytest.raises(ObsRequestError) as info:
            ws.request("GetOutputStatus", {"outputName": "decklink_output"})
    assert info.value.code == 600
    assert info.value.request_type == "GetOutputStatus"


def test_silent_server_times_out(fake_obs):
    server = fake_obs("pw", send_hello=False)
    with pytest.raises(ObsWebsocketTimeout):
        ObsWebsocket(server.port, "pw", timeout=0.3).connect()


def test_closed_port_raises_websocket_error():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with pytest.raises(ObsWebsocketError):
        ObsWebsocket(port, "pw", timeout=0.5).connect()


def test_request_before_connect_raises():
    with pytest.raises(ObsWebsocketError):
        ObsWebsocket(1, "pw").request("GetVersion")


def test_errors_never_carry_the_password(fake_obs):
    server = fake_obs("right")
    password = "do-not-leak-this-password"
    with pytest.raises(ObsAuthError) as info:
        ObsWebsocket(server.port, password).connect()
    assert password not in str(info.value)
    assert password not in repr(info.value)
