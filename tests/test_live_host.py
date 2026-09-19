from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path

import pytest

from obed_edom import html_preview, live_host, live_runtime


class FakeCdp:
    instances: list["FakeCdp"] = []

    def __init__(self, chrome, profile, display, *, headless=False, attach_endpoint=None, attach_match=None, logger=None, log_path=None):
        self.chrome, self.profile, self.display, self.headless = chrome, profile, display, headless
        self.attach_endpoint, self.attach_match, self.logger, self.log_path = attach_endpoint, attach_match, logger, log_path
        self.started = False
        self.stopped = False
        self.visible = False
        self.index = 0
        self.keys: list[str] = []
        self.busy = False
        self.revision = 0
        self.revision_on_enter = True
        self.busy_on_enter = False
        self.can_advance = True
        self.__class__.instances.append(self)

    def start(self): self.started = True
    def goto(self, url): self.url = url
    def stop(self): self.stopped = True
    def key(self, key, code, vk):
        self.keys.append(key)
        if key == " ":
            self.revision += 1
            self.busy = self.busy_on_enter
        if key == "Enter":
            self.index = int("".join(x for x in self.keys if x.isdigit())) - 1
            if self.revision_on_enter:
                self.revision += 1
            self.busy = self.busy_on_enter
    def evaluate(self, expression):
        if "__obedLive" in expression:
            return {"exportedSlideIndex": self.index, "sceneId": self.index, "buildIndex": None, "revision": self.revision, "canAdvance": self.can_advance, "canGoTo": not self.busy, "ready": not self.busy, "busy": self.busy}
        if ".hide()" in expression: self.visible = False; return None
        if ".show()" in expression: self.visible = True; return None
        return self.visible


class FakeServer:
    def __init__(self, *_, alpha=False): self.stopped = False; self.alpha = alpha
    def start(self): return "http://program.test/program.html"
    def stop(self): self.stopped = True


def player_bytes() -> bytes:
    return b"before;" + live_runtime._ANCHOR + b";after"


def resolver(root: Path, relative: str) -> Path:
    if relative == "assets/player/main.js": return root / "main.js"
    if relative == "assets/header.json": return root / "header.json"
    raise AssertionError(relative)


def host(tmp_path, monkeypatch) -> live_host.LiveOutputHost:
    (tmp_path / "main.js").write_bytes(player_bytes())
    (tmp_path / "header.json").write_text('{"slideWidth":1920,"slideHeight":1080,"showMode":0}')
    monkeypatch.setattr(live_runtime, "PLAYER_SHA256", hashlib.sha256(player_bytes()).hexdigest())
    monkeypatch.setattr(live_host, "choose_display", lambda *_args, **_kwargs: live_host.OutputDisplay(9, 10, 20, 2560, 1440))
    FakeCdp.instances.clear()
    return live_host.LiveOutputHost(tmp_path, [{"originalOrdinal": 1, "playerIndex": 0, "skipped": False}, {"originalOrdinal": 2, "playerIndex": 1, "skipped": False}, {"originalOrdinal": 3, "skipped": True}], headless=True, transport_factory=FakeCdp, server_factory=FakeServer, resolver=resolver)


def test_output_geometry_is_detected_before_lazy_start(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch).output
    assert output["displayId"] == 9
    assert output["viewport"] == {"width": 2560, "height": 1440}
    assert output["canvas"] == {"width": 1920, "height": 1080}
    assert output["aspect"] == "16:9"
    assert not FakeCdp.instances


def test_observe_starts_one_hidden_owner_and_maps_player_index(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)
    observed = output.observe()
    assert observed.original_slide == 1
    assert not observed.output_visible
    assert len(FakeCdp.instances) == 1
    assert FakeCdp.instances[0].headless


def test_go_to_uses_original_to_player_map_and_enter(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)
    output.observe()
    observed = output.execute("goTo", 2)
    assert observed.original_slide == 2
    assert FakeCdp.instances[0].keys == ["2", "Enter"]
    with pytest.raises(live_host.PlayerCommandRejected, match="unavailable or skipped"):
        output.execute("goTo", 3)


def test_same_slide_go_to_requires_a_new_runtime_observation(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)
    output.observe()
    FakeCdp.instances[0].revision_on_enter = False
    output.timeout_s = 0.05
    with pytest.raises(live_host.LiveHostError, match="did not acknowledge"):
        output.execute("goTo", 1)


def test_advance_acknowledges_a_busy_authored_scene_without_waiting_for_settlement(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)
    output.observe()
    FakeCdp.instances[0].busy_on_enter = True
    observed = output.execute("advance")
    assert observed.busy


def test_capabilities_reflect_observed_end_state(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)
    output.observe()
    FakeCdp.instances[0].can_advance = False
    output.observe()
    capability = output.capabilities()["advance"]
    assert not capability["supported"]
    assert capability["reason"] == "Player has no next manual action."


def test_refuses_player_with_fewer_scenes_than_authored(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)
    output.observe()
    output._expected_scene_count = 3
    with pytest.raises(live_host.LiveHostError, match="fell back"):
        output.observe()


def test_stop_only_stops_owned_resources_and_refuses_restart(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)
    output.observe()
    fake = FakeCdp.instances[0]
    output.stop()
    assert fake.stopped
    with pytest.raises(live_host.LiveHostError, match="stopped"):
        output.observe()


class FakeProc:
    def __init__(self):
        self.terminate_calls = 0
        self._terminated = False

    def poll(self): return 0 if self._terminated else None
    def terminate(self):
        self.terminate_calls += 1
        self._terminated = True
    def wait(self, timeout=None): return 0


class BlockingWs:
    def __init__(self):
        self.send_started = threading.Event()
        self.closed = threading.Event()
        self.close_calls = 0

    def send(self, _data): self.send_started.set()
    def recv(self, timeout=None):
        if self.closed.wait(timeout=timeout): raise ConnectionError("closed")
        raise TimeoutError
    def close(self):
        self.close_calls += 1
        self.closed.set()


def test_chrome_cdp_stop_unblocks_a_pending_call_without_waiting_on_the_call_lock(tmp_path):
    display = live_host.OutputDisplay(1, 0, 0, 1920, 1080, True)
    transport = live_host.ChromeCdp(Path("chrome"), tmp_path, display)
    ws, proc = BlockingWs(), FakeProc()
    transport.ws, transport.proc = ws, proc
    errors: list[Exception] = []

    def blocked_call():
        try: transport.call("Test.method")
        except live_host.LiveHostError as exc: errors.append(exc)

    thread = threading.Thread(target=blocked_call)
    thread.start()
    assert ws.send_started.wait(2)
    start = time.monotonic()
    transport.stop()
    elapsed = time.monotonic() - start
    thread.join(2)
    assert not thread.is_alive()
    assert elapsed < 1
    assert errors and "CDP connection failed" in str(errors[0])
    assert ws.close_calls == 1
    assert proc.terminate_calls == 1
    transport.stop()
    assert ws.close_calls == 1
    assert proc.terminate_calls == 1


def test_chrome_cdp_stop_releases_resources_exactly_once_under_concurrent_calls(tmp_path):
    display = live_host.OutputDisplay(1, 0, 0, 1920, 1080, True)
    transport = live_host.ChromeCdp(Path("chrome"), tmp_path, display)
    ws, proc = BlockingWs(), FakeProc()
    transport.ws, transport.proc = ws, proc
    threads = [threading.Thread(target=transport.stop) for _ in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(2)
    assert ws.close_calls == 1
    assert proc.terminate_calls == 1


class FakeHttpdShutdownFlaky:
    def __init__(self):
        self.shutdown_calls = 0
        self.close_calls = 0
        self.fail_shutdown = True

    def shutdown(self):
        self.shutdown_calls += 1
        if self.fail_shutdown:
            self.fail_shutdown = False
            raise RuntimeError("shutdown boom")

    def server_close(self):
        self.close_calls += 1


def test_asset_server_stop_attempts_server_close_even_when_shutdown_raises(tmp_path):
    server = live_host._AssetServer(tmp_path, b"")
    httpd = FakeHttpdShutdownFlaky()
    server.httpd = httpd
    server.thread = None

    with pytest.raises(live_host.LiveHostError, match="did not fully stop"):
        server.stop()
    assert httpd.shutdown_calls == 1
    assert httpd.close_calls == 1
    assert server.httpd is httpd

    server.stop()
    assert httpd.shutdown_calls == 2
    assert httpd.close_calls == 2
    assert server.httpd is None

    server.stop()
    assert httpd.shutdown_calls == 2
    assert httpd.close_calls == 2


def test_live_output_host_stop_is_a_prompt_no_op_when_called_again(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)
    output.observe()
    output.stop()
    assert FakeCdp.instances[0].stopped
    output.stop()
    assert FakeCdp.instances[0].stopped


def test_live_output_host_stop_blocks_a_concurrent_stop_until_teardown_completes(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)
    output.observe()
    fake = FakeCdp.instances[0]
    stop_calls = []
    entered = threading.Event()
    release = threading.Event()

    def slow_stop():
        stop_calls.append(1)
        entered.set()
        release.wait()
        fake.stopped = True

    fake.stop = slow_stop
    first = threading.Thread(target=output.stop)
    first.start()
    second = threading.Thread(target=output.stop)
    try:
        assert entered.wait(2)
        second.start()
        assert second.is_alive()
        assert not second.join(timeout=0.2)
        assert second.is_alive()
    finally:
        release.set()
        first.join(5)
        second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert stop_calls == [1]
    assert fake.stopped


def test_chrome_cdp_stop_raises_when_ws_close_fails_but_still_terminates_process(tmp_path):
    display = live_host.OutputDisplay(1, 0, 0, 1920, 1080, True)
    transport = live_host.ChromeCdp(Path("chrome"), tmp_path, display)
    ws, proc = BlockingWs(), FakeProc()
    ws.close = lambda: (_ for _ in ()).throw(RuntimeError("socket gone"))
    transport.ws, transport.proc = ws, proc
    with pytest.raises(live_host.LiveHostError, match="did not fully stop"):
        transport.stop()
    assert proc.terminate_calls == 1
    assert transport.proc is None
    assert transport.ws is ws
    assert transport._stopped


def test_chrome_cdp_stop_retries_only_the_resource_still_held(tmp_path):
    display = live_host.OutputDisplay(1, 0, 0, 1920, 1080, True)
    transport = live_host.ChromeCdp(Path("chrome"), tmp_path, display)
    ws, proc = BlockingWs(), FakeProc()
    failing = [True]

    def flaky_close():
        ws.close_calls += 1
        if failing[0]: raise RuntimeError("socket gone")
        ws.closed.set()

    ws.close = flaky_close
    transport.ws, transport.proc = ws, proc
    with pytest.raises(live_host.LiveHostError):
        transport.stop()
    assert proc.terminate_calls == 1
    assert transport.ws is ws
    failing[0] = False
    transport.stop()
    assert transport.ws is None
    assert ws.close_calls == 2
    assert proc.terminate_calls == 1
    transport.stop()
    assert ws.close_calls == 2


def test_live_output_host_stop_raises_when_a_step_fails_but_attempts_every_step(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)
    output.observe()
    fake = FakeCdp.instances[0]
    fake.stop = lambda: (_ for _ in ()).throw(RuntimeError("transport wedged"))
    server = output._server
    profile = output._profile
    with pytest.raises(live_host.LiveHostError, match="did not fully stop"):
        output.stop()
    assert output._transport is not None
    assert output._server is None
    assert server.stopped
    assert output._profile is None
    assert not profile.exists()
    fake.stop = lambda: None
    output.stop()
    assert output._transport is None


def test_live_output_host_start_failure_preserves_original_error_when_cleanup_also_fails(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)

    class ExplodingServer(FakeServer):
        def start(self): raise RuntimeError("asset server boom")
        def stop(self): raise RuntimeError("cleanup also failed")

    output.server_factory = ExplodingServer
    with pytest.raises(RuntimeError, match="asset server boom"):
        output.start()


def test_chrome_cdp_start_failure_preserves_original_error_when_stop_also_fails(monkeypatch, tmp_path):
    display = live_host.OutputDisplay(1, 0, 0, 1920, 1080, True)
    transport = live_host.ChromeCdp(Path("chrome"), tmp_path, display, headless=True)
    monkeypatch.setattr(live_host.subprocess, "Popen", lambda *a, **k: FakeProc())
    clock = iter([0.0, 100.0])
    monkeypatch.setattr(live_host.time, "monotonic", lambda: next(clock, 100.0))
    monkeypatch.setattr(live_host.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("no chrome")))
    monkeypatch.setattr(transport, "stop", lambda: (_ for _ in ()).throw(RuntimeError("stop boom")))
    with pytest.raises(live_host.LiveHostError, match="did not start"):
        transport.start()


def test_choose_display_prefers_external_and_validates_requested_id():
    primary = live_host.OutputDisplay(1, 0, 0, 1512, 982, True)
    external = live_host.OutputDisplay(2, 1512, 0, 1920, 1080)
    assert live_host.choose_display(None, [primary, external]) == external
    assert live_host.choose_display(1, [primary, external]) == primary
    with pytest.raises(live_host.LiveHostError, match="unavailable"):
        live_host.choose_display(99, [primary, external])


def test_safe_export_file_rejects_traversal_and_symlink(tmp_path, monkeypatch):
    preview = tmp_path / "preview"; root = preview / "cache" / "html"; root.mkdir(parents=True)
    (root / "index.html").write_text("ok")
    monkeypatch.setattr(html_preview, "preview_root", lambda: preview)
    assert html_preview.safe_export_file(root, "index.html") == root / "index.html"
    with pytest.raises(html_preview.PreviewError): html_preview.safe_export_file(root, "../index.html")
    (root / "out").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(html_preview.PreviewError): html_preview.safe_export_file(root, "out/x")


def test_program_html_injects_overlay_first_and_fit_once(tmp_path):
    (tmp_path / "index.html").write_text("<html><head></head><body><div id=\"stage\"></div></body></html>")
    server = live_host._AssetServer(tmp_path, b"", resolver=resolver_for(tmp_path))
    document = server._program_html().decode()
    body = document[document.index("<body"):]
    assert body.index('id="obed-output-black"') < body.index('id="stage"')
    assert document.count('id="obed-output-fit"') == 1


def test_program_html_requires_head_and_body(tmp_path):
    (tmp_path / "index.html").write_text("<div>no head or body</div>")
    server = live_host._AssetServer(tmp_path, b"", resolver=resolver_for(tmp_path))
    with pytest.raises(live_host.LiveHostError, match="head and body"):
        server._program_html()


def resolver_for(root: Path):
    def resolve(_root: Path, relative: str) -> Path:
        return root / relative
    return resolve


class RecordingHandler:
    def __init__(self, fail_after_headers: bool):
        self.fail_after_headers = fail_after_headers
        self.headers = {}
        self.status = None
        self.error = None
        self.sent_headers = False

    def send_response(self, status):
        self.status = status

    def send_header(self, *_args):
        pass

    def end_headers(self):
        self.sent_headers = True

    def send_error(self, status):
        self.error = status

    class _Wfile:
        def __init__(self, outer):
            self.outer = outer

        def write(self, _chunk):
            if self.outer.fail_after_headers:
                raise OSError("socket gone")

    @property
    def wfile(self):
        return self._Wfile(self)


def test_send_file_ends_response_silently_after_headers_are_sent(tmp_path):
    path = tmp_path / "movie.mp4"
    path.write_bytes(b"data")
    handler = RecordingHandler(fail_after_headers=True)
    assert live_host._AssetServer._send_file(handler, path) is True
    assert handler.sent_headers
    assert handler.error is None


def test_send_file_error_before_headers_propagates_for_a_404(tmp_path):
    handler = RecordingHandler(fail_after_headers=False)
    with pytest.raises(OSError):
        live_host._AssetServer._send_file(handler, tmp_path / "missing.mp4")
    assert not handler.sent_headers


def test_send_bytes_ends_response_silently_when_write_fails_after_headers():
    handler = RecordingHandler(fail_after_headers=True)
    assert live_host._AssetServer._send_bytes(handler, b"data", "text/html") is True
    assert handler.sent_headers
    assert handler.error is None


def test_key_events_omit_native_key_code(tmp_path):
    # A Windows VK sent as nativeVirtualKeyCode makes macOS Chrome redispatch the
    # key through AppKit key-equivalent routing; the browser UI thread then stalls
    # and every later CDP call times out (reproduced headless, 2026-09-19).
    display = live_host.OutputDisplay(1, 0, 0, 1920, 1080, True)
    transport = live_host.ChromeCdp(Path("chrome"), tmp_path, display)
    calls = []
    transport.call = lambda method, **params: calls.append((method, params)) or {}
    transport.key(" ", "Space", 32)
    assert [params["type"] for _, params in calls] == ["keyDown", "keyUp"]
    for method, params in calls:
        assert method == "Input.dispatchKeyEvent"
        assert params["windowsVirtualKeyCode"] == 32
        assert "nativeVirtualKeyCode" not in params


def test_attach_mode_reads_env_skips_display_choice_and_reports_fill_key_output(tmp_path, monkeypatch):
    monkeypatch.setenv("OBED_LIVE_ATTACH", "http://127.0.0.1:9222")
    monkeypatch.setenv("OBED_EDOM_OUTPUT_ROOT", str(tmp_path / "preview"))
    (tmp_path / "main.js").write_bytes(player_bytes())
    (tmp_path / "header.json").write_text('{"slideWidth":1920,"slideHeight":1080,"showMode":0}')
    monkeypatch.setattr(live_runtime, "PLAYER_SHA256", hashlib.sha256(player_bytes()).hexdigest())
    output = live_host.LiveOutputHost(tmp_path, [], transport_factory=FakeCdp, server_factory=FakeServer, resolver=resolver)
    assert output.display is None
    result = output.output
    assert result["transport"] == "fill-key"
    assert result["alpha"] is True
    assert result["bridge"] == "obs-cdp"
    assert "displayId" not in result and "bounds" not in result


def test_attach_endpoint_must_be_loopback(tmp_path, monkeypatch):
    monkeypatch.setenv("OBED_EDOM_OUTPUT_ROOT", str(tmp_path / "preview"))
    with pytest.raises(live_host.LiveHostError, match="loopback"):
        live_host.LiveOutputHost(tmp_path, [], attach_endpoint="http://example.com:9222", transport_factory=FakeCdp, server_factory=FakeServer, resolver=resolver)


def test_attach_host_navigates_and_settles_without_a_display(tmp_path, monkeypatch):
    monkeypatch.setenv("OBED_EDOM_OUTPUT_ROOT", str(tmp_path / "preview"))
    output = host(tmp_path, monkeypatch)
    output._attach_endpoint = "http://127.0.0.1:9222"
    output.display = None
    observed = output.observe()
    assert observed.output["transport"] == "fill-key"
    assert FakeCdp.instances[0].display is None


def test_program_html_alpha_mode_hides_via_opacity_not_a_black_div(tmp_path):
    (tmp_path / "index.html").write_text('<html><head></head><body><div id="body"></div></body></html>')
    server = live_host._AssetServer(tmp_path, b"", resolver=resolver_for(tmp_path), alpha=True)
    document = server._program_html().decode()
    assert 'id="obed-output-black"' not in document
    assert "background:transparent!important" in document
    assert "#body{opacity:0}" in document


def test_pick_target_prefers_match_then_requires_a_single_page(tmp_path):
    display = live_host.OutputDisplay(1, 0, 0, 1920, 1080, True)
    transport = live_host.ChromeCdp(Path("chrome"), tmp_path, display, attach_endpoint="http://127.0.0.1:9222", attach_match="program")
    pages = [{"type": "page", "url": "http://x/blank", "title": "blank", "webSocketDebuggerUrl": "ws://a"},
             {"type": "page", "url": "http://x/program.html", "title": "program", "webSocketDebuggerUrl": "ws://b"}]
    assert transport._pick_target(pages)["webSocketDebuggerUrl"] == "ws://b"
    transport.attach_match = None
    with pytest.raises(live_host.LiveHostError, match="Ambiguous"):
        transport._pick_target(pages)
    assert transport._pick_target(pages[:1])["webSocketDebuggerUrl"] == "ws://a"


def test_chrome_cdp_call_does_not_require_a_process_in_attach_mode(tmp_path):
    display = live_host.OutputDisplay(1, 0, 0, 1920, 1080, True)
    transport = live_host.ChromeCdp(Path("chrome"), tmp_path, display, attach_endpoint="http://127.0.0.1:9222")
    ws = BlockingWs()
    ws.recv = lambda timeout=None: __import__("json").dumps({"id": 1, "result": {}})
    transport.ws = ws
    assert transport.proc is None
    assert transport.call("Test.method") == {}


def test_attach_stop_navigates_about_blank_and_never_terminates_a_process(tmp_path):
    display = live_host.OutputDisplay(1, 0, 0, 1920, 1080, True)
    transport = live_host.ChromeCdp(Path("chrome"), tmp_path, display, attach_endpoint="http://127.0.0.1:9222")
    calls = []
    transport.call = lambda method, **params: calls.append((method, params)) or {}
    ws = BlockingWs()
    transport.ws = ws
    transport.stop()
    assert calls == [("Page.navigate", {"url": "about:blank"})]
    assert ws.close_calls == 1
    assert transport.proc is None


def test_session_logger_writes_jsonl_and_swallows_failures(tmp_path):
    path = tmp_path / "sub" / "log.jsonl"
    logger = live_host._SessionLogger(path)
    logger.log("start", mode="hdmi")
    logger.close()
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    record = __import__("json").loads(lines[0])
    assert record["kind"] == "start" and record["mode"] == "hdmi"
    broken = live_host._SessionLogger(tmp_path / "nonexistent" / "dir" / "x")
    broken._file = None
    broken.log("start")
    broken.close()


def test_observe_logs_only_on_change(tmp_path, monkeypatch):
    monkeypatch.setenv("OBED_EDOM_OUTPUT_ROOT", str(tmp_path / "preview"))
    output = host(tmp_path, monkeypatch)
    output.observe()
    logger = output._logger
    seen = []
    logger.log = lambda kind, **fields: seen.append((kind, fields))
    output.observe()
    observation_logs = [entry for entry in seen if entry[0] == "observation"]
    assert observation_logs == []
    output.execute("goTo", 2)
    observation_logs = [entry for entry in seen if entry[0] == "observation"]
    assert len(observation_logs) == 1
