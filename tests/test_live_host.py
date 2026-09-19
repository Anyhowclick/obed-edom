from __future__ import annotations

import hashlib
import json
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
        self.clicks = 0
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
    def click_stage(self):
        self.clicks += 1
        self.revision += 1
        self.busy = self.busy_on_enter
    def evaluate(self, expression):
        if "__OBED_CONTINUITY_INFO__" in expression:
            return {"ready": False, "present": False, "info": {"installed": True}, "stage": None}
        if "__obedLive" in expression:
            return {"exportedSlideIndex": self.index, "sceneId": self.index, "buildIndex": None, "revision": self.revision, "canAdvance": self.can_advance, "canGoTo": not self.busy, "ready": not self.busy, "busy": self.busy}
        if ".hide()" in expression: self.visible = False; return None
        if ".show()" in expression: self.visible = True; return None
        return self.visible


class FakeServer:
    def __init__(self, *_, alpha=False, continuity_script=""):
        self.stopped = False; self.alpha = alpha; self.continuity_script = continuity_script
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
    with pytest.raises(live_host.PlayerCommandRejected, match="did not acknowledge digit/Enter key input"):
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


def test_pick_target_with_match_requires_exactly_one_match_not_a_silent_fallback(tmp_path):
    display = live_host.OutputDisplay(1, 0, 0, 1920, 1080, True)
    transport = live_host.ChromeCdp(Path("chrome"), tmp_path, display, attach_endpoint="http://127.0.0.1:9222", attach_match="obs")
    no_match = [{"type": "page", "id": "1", "url": "http://x/blank", "title": "blank", "webSocketDebuggerUrl": "ws://a"}]
    with pytest.raises(live_host.LiveHostError, match="did not select exactly one"):
        transport._pick_target(no_match)
    two_matches = [
        {"type": "page", "id": "1", "url": "http://x/obs-a", "title": "obs a", "webSocketDebuggerUrl": "ws://a"},
        {"type": "page", "id": "2", "url": "http://x/obs-b", "title": "obs b", "webSocketDebuggerUrl": "ws://b"},
    ]
    with pytest.raises(live_host.LiveHostError, match="did not select exactly one") as excinfo:
        transport._pick_target(two_matches)
    assert "1 http://x/obs-a" in str(excinfo.value)
    assert "2 http://x/obs-b" in str(excinfo.value)


def test_pick_target_without_match_never_falls_back_on_multiple_pages(tmp_path):
    display = live_host.OutputDisplay(1, 0, 0, 1920, 1080, True)
    transport = live_host.ChromeCdp(Path("chrome"), tmp_path, display, attach_endpoint="http://127.0.0.1:9222")
    pages = [
        {"type": "page", "id": "1", "url": "http://x/a", "title": "a", "webSocketDebuggerUrl": "ws://a"},
        {"type": "page", "id": "2", "url": "http://x/b", "title": "b", "webSocketDebuggerUrl": "ws://b"},
    ]
    with pytest.raises(live_host.LiveHostError, match="Ambiguous") as excinfo:
        transport._pick_target(pages)
    assert "1 http://x/a" in str(excinfo.value)
    assert "2 http://x/b" in str(excinfo.value)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://127.0.0.1:9222",
        "http://user:pass@127.0.0.1:9222",
        "http://127.0.0.1:9222/some/path",
        "http://127.0.0.1:9222/?x=1",
        "http://127.0.0.1:9222/#frag",
        "http://[::2]:9222",
        "http://0.0.0.0:9222",
    ],
)
def test_attach_endpoint_rejects_anything_but_a_bare_loopback_origin(endpoint, tmp_path, monkeypatch):
    monkeypatch.setenv("OBED_EDOM_OUTPUT_ROOT", str(tmp_path / "preview"))
    with pytest.raises(live_host.LiveHostError):
        live_host.LiveOutputHost(tmp_path, [], attach_endpoint=endpoint, transport_factory=FakeCdp, server_factory=FakeServer, resolver=resolver)


@pytest.mark.parametrize("endpoint", ["http://127.0.0.1:9222", "http://[::1]:9222", "http://localhost:9222"])
def test_attach_endpoint_accepts_bare_loopback_origins(endpoint, tmp_path, monkeypatch):
    monkeypatch.setenv("OBED_EDOM_OUTPUT_ROOT", str(tmp_path / "preview"))
    live_host.LiveOutputHost(tmp_path, [], attach_endpoint=endpoint, transport_factory=FakeCdp, server_factory=FakeServer, resolver=resolver)


def test_validate_target_ws_url_rejects_non_loopback_and_mismatched_port():
    endpoint = "http://127.0.0.1:9222"
    assert live_host._validate_target_ws_url("ws://127.0.0.1:9222/devtools/page/1", endpoint) == "ws://127.0.0.1:9222/devtools/page/1"
    with pytest.raises(live_host.LiveHostError, match="scheme"):
        live_host._validate_target_ws_url("http://127.0.0.1:9222/devtools/page/1", endpoint)
    with pytest.raises(live_host.LiveHostError, match="loopback"):
        live_host._validate_target_ws_url("ws://evil.example:9222/devtools/page/1", endpoint)
    with pytest.raises(live_host.LiveHostError, match="port"):
        live_host._validate_target_ws_url("ws://127.0.0.1:1234/devtools/page/1", endpoint)


def test_discovery_does_not_follow_redirects(tmp_path, monkeypatch):
    class FakeRedirectResponse:
        status = 302

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(live_host._DISCOVERY_OPENER, "open", lambda *a, **k: FakeRedirectResponse())
    display = live_host.OutputDisplay(1, 0, 0, 1920, 1080, True)
    transport = live_host.ChromeCdp(Path("chrome"), tmp_path, display, attach_endpoint="http://127.0.0.1:9222")
    with pytest.raises(live_host.LiveHostError, match="status 302"):
        transport._list_targets()


def test_chrome_cdp_call_does_not_require_a_process_in_attach_mode(tmp_path):
    display = live_host.OutputDisplay(1, 0, 0, 1920, 1080, True)
    transport = live_host.ChromeCdp(Path("chrome"), tmp_path, display, attach_endpoint="http://127.0.0.1:9222")
    ws = BlockingWs()
    ws.recv = lambda timeout=None: __import__("json").dumps({"id": 1, "result": {}})
    transport.ws = ws
    assert transport.proc is None
    assert transport.call("Test.method") == {}


class FakeBlankWs:
    def __init__(self, *, fail_navigate=False, confirmed_url="about:blank"):
        self.sent: list[dict] = []
        self.closed = False
        self.fail_navigate = fail_navigate
        self.confirmed_url = confirmed_url

    def send(self, data):
        self.sent.append(json.loads(data))

    def recv(self, timeout=None):
        message = self.sent[-1]
        if message["method"] == "Page.navigate":
            if self.fail_navigate:
                return json.dumps({"id": message["id"], "error": {"message": "navigate boom"}})
            return json.dumps({"id": message["id"], "result": {}})
        return json.dumps({"id": message["id"], "result": {"result": {"value": self.confirmed_url}}})

    def close(self):
        self.closed = True


def test_attach_stop_navigates_about_blank_via_a_fresh_socket_and_never_terminates_a_process(tmp_path, monkeypatch):
    display = live_host.OutputDisplay(1, 0, 0, 1920, 1080, True)
    transport = live_host.ChromeCdp(Path("chrome"), tmp_path, display, attach_endpoint="http://127.0.0.1:9222")
    transport._target_ws_url = "ws://127.0.0.1:9222/devtools/page/abc"
    ws = BlockingWs()
    transport.ws = ws
    blank_ws = FakeBlankWs()
    monkeypatch.setattr(live_host, "connect", lambda *a, **k: blank_ws)
    transport.stop()
    # The original socket is closed (unblocking a pending call) before the fresh
    # one is opened to confirm the blank; the process, which attach never owned,
    # is never touched.
    assert ws.close_calls == 1
    assert transport.ws is None
    assert transport.proc is None
    methods = [message["method"] for message in blank_ws.sent]
    assert methods == ["Page.navigate", "Runtime.evaluate"]
    assert blank_ws.sent[0]["params"]["url"] == "about:blank"
    assert blank_ws.closed
    assert transport._blanked


def test_attach_stop_raises_and_retries_only_the_blank_when_confirmation_fails(tmp_path, monkeypatch):
    display = live_host.OutputDisplay(1, 0, 0, 1920, 1080, True)
    transport = live_host.ChromeCdp(Path("chrome"), tmp_path, display, attach_endpoint="http://127.0.0.1:9222")
    transport._target_ws_url = "ws://127.0.0.1:9222/devtools/page/abc"
    ws = BlockingWs()
    transport.ws = ws
    failing = FakeBlankWs(confirmed_url="https://still-live.example/")
    monkeypatch.setattr(live_host, "connect", lambda *a, **k: failing)
    with pytest.raises(live_host.LiveHostError, match="did not fully stop"):
        transport.stop()
    assert ws.close_calls == 1
    assert transport.ws is None
    assert not transport._blanked
    succeeding = FakeBlankWs()
    monkeypatch.setattr(live_host, "connect", lambda *a, **k: succeeding)
    transport.stop()
    assert transport._blanked
    assert succeeding.closed


def test_call_uses_one_absolute_deadline_not_a_fresh_one_per_recv(tmp_path, monkeypatch):
    display = live_host.OutputDisplay(1, 0, 0, 1920, 1080, True)
    transport = live_host.ChromeCdp(Path("chrome"), tmp_path, display)

    class SlowEventsWs:
        def __init__(self):
            self.sends = 0

        def send(self, _data):
            self.sends += 1

        def recv(self, timeout=None):
            return json.dumps({"method": "Runtime.consoleAPICalled", "params": {"type": "log"}})

    transport.ws = SlowEventsWs()
    transport.proc = None
    clock = iter([0.0, 0.0, 5.0, 10.0, 14.9, 16.0, 20.0])
    monkeypatch.setattr(live_host.time, "monotonic", lambda: next(clock, 100.0))
    with pytest.raises(live_host.LiveHostError, match="did not answer"):
        transport.call("Test.method")


def test_call_skips_a_stale_reply_from_a_timed_out_earlier_request(tmp_path):
    display = live_host.OutputDisplay(1, 0, 0, 1920, 1080, True)
    transport = live_host.ChromeCdp(Path("chrome"), tmp_path, display)

    class StaleThenFreshWs:
        def __init__(self):
            self.replies = [
                json.dumps({"id": 1, "result": {"stale": True}}),
                json.dumps({"id": 2, "result": {"fresh": True}}),
            ]

        def send(self, _data):
            pass

        def recv(self, timeout=None):
            return self.replies.pop(0)

    transport.ws = StaleThenFreshWs()
    transport.proc = None
    transport._id = 1
    result = transport.call("Test.method")
    assert result == {"fresh": True}


def test_video_snapshot_uses_a_short_deadline_and_reports_timeout_without_raising(tmp_path):
    display = live_host.OutputDisplay(1, 0, 0, 1920, 1080, True)
    host_instance = object.__new__(live_host.LiveOutputHost)
    transport = live_host.ChromeCdp(Path("chrome"), tmp_path, display)
    seen_deadlines = []

    def fake_call(method, deadline_s=None, **params):
        seen_deadlines.append(deadline_s)
        raise live_host.LiveHostError("Program browser did not answer CDP Runtime.evaluate in time.")

    transport.call = fake_call
    assert host_instance._video_snapshot(transport) == "timeout"
    assert seen_deadlines == [1.5]


def test_session_logger_writes_jsonl_and_swallows_failures(tmp_path):
    path = tmp_path / "sub" / "log.jsonl"
    logger = live_host._SessionLogger(path)
    logger.log("start", mode="hdmi")
    logger.close()
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    record = __import__("json").loads(lines[0])
    assert record["kind"] == "start" and record["mode"] == "hdmi"
    broken = live_host._SessionLogger(path / "not-a-directory")
    broken.log("start")
    broken.close()


def slides_with_uuid():
    return [
        {"originalOrdinal": 1, "playerIndex": 0, "exportedUuid": "s1", "skipped": False},
        {"originalOrdinal": 2, "playerIndex": 1, "exportedUuid": "s2", "skipped": False},
    ]


def continuity_resolver(root: Path):
    def resolve(_root: Path, relative: str) -> Path:
        return root / relative
    return resolve


def _mp4_box(fourcc: bytes, payload: bytes = b"") -> bytes:
    return (8 + len(payload)).to_bytes(4, "big") + fourcc + payload


def _movie_bytes(fourcc: bytes) -> bytes:
    """A minimal synthetic ISO-BMFF file whose sole video track reports `fourcc`:
    see tests/test_live_codec.py for the box-tree format this builds."""
    hdlr = _mp4_box(b"hdlr", b"\x00" * 8 + b"vide" + b"\x00" * 12 + b"Handler\x00")
    entry = _mp4_box(fourcc, b"\x00" * 78)
    stsd = _mp4_box(b"stsd", b"\x00" * 4 + (1).to_bytes(4, "big") + entry)
    stbl = _mp4_box(b"stbl", stsd)
    minf = _mp4_box(b"minf", stbl)
    mdia = _mp4_box(b"mdia", hdlr + minf)
    trak = _mp4_box(b"trak", mdia)
    moov = _mp4_box(b"moov", trak)
    ftyp = _mp4_box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2avc1mp41")
    return ftyp + moov


def h264_movie_bytes() -> bytes:
    return _movie_bytes(b"avc1")


def hevc_movie_bytes() -> bytes:
    return _movie_bytes(b"hvc1")


def write_one_movie_export(
    root: Path, *, movie_bytes: bytes | None = None, extra_movie_bytes: bytes | None = None,
    movie_bytes_by_slide: dict[str, bytes] | None = None,
) -> None:
    assets_dir = root / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / "header.json").write_text(json.dumps({"slideWidth": 1920, "slideHeight": 1080, "showMode": 0, "slideList": ["s1", "s2"]}))
    assets = {"movie-asset": {"url": {"web": "assets/movie.mov"}}}
    movie_node = {
        "movie": {"asset": "movie-asset"},
        "baseLayer": {
            "initialState": {"position": {"pointX": 200.0, "pointY": 200.0}, "width": 100.0, "height": 100.0},
            "layers": [
                {
                    "isVideoLayer": True,
                    "initialState": {"position": {"pointX": 50.0, "pointY": 50.0}, "width": 100.0, "height": 100.0},
                }
            ],
        },
    }
    extra_movie_node = None
    if extra_movie_bytes is not None:
        assets["extra-movie-asset"] = {"url": {"web": "assets/extra-movie.mov"}}
        extra_movie_node = {
            "movie": {"asset": "extra-movie-asset"},
            "baseLayer": {
                "initialState": {"position": {"pointX": 600.0, "pointY": 600.0}, "width": 50.0, "height": 50.0},
                "layers": [
                    {
                        "isVideoLayer": True,
                        "initialState": {"position": {"pointX": 25.0, "pointY": 25.0}, "width": 50.0, "height": 50.0},
                    }
                ],
            },
        }
    # Like a real HTML export, each slide folder holds its own copy of the movie file;
    # `movie_bytes_by_slide` makes those copies differ.
    default_bytes = movie_bytes if movie_bytes is not None else h264_movie_bytes()
    for uuid in ("s1", "s2"):
        (assets_dir / uuid / "assets").mkdir(parents=True, exist_ok=True)
        per_slide = (movie_bytes_by_slide or {}).get(uuid, default_bytes)
        (assets_dir / uuid / "assets" / "movie.mov").write_bytes(per_slide)
    # The extra movie is unplanned: single-instance only on slide 2 (not slide 1), so
    # ContinuityPlan.to_runtime()'s movie table -- built from slide 1's footprints --
    # never includes it, even though codec_report must still enumerate it.
    if extra_movie_node is not None:
        (assets_dir / "s2" / "assets" / "extra-movie.mov").write_bytes(extra_movie_bytes)
    events_s1 = [movie_node, {"type": "transition", "name": "apple:magic-move"}]
    events_s2 = [movie_node] + ([extra_movie_node] if extra_movie_node is not None else [])
    (assets_dir / "s1" / "s1.json").write_text(json.dumps({"events": events_s1, "assets": assets}))
    (assets_dir / "s2" / "s2.json").write_text(json.dumps({"events": events_s2, "assets": assets}))
    (assets_dir / "s1" / "s1.jsonp").write_text("local_slide(" + json.dumps({"json": {"events": events_s1}}) + ")")
    (assets_dir / "s2" / "s2.jsonp").write_text("local_slide(" + json.dumps({"json": {"events": events_s2}}) + ")")


def host_with_continuity(
    tmp_path, monkeypatch, *, attach: bool = False, continuity: str = "auto", headless: bool = True,
    movie_bytes: bytes | None = None, extra_movie_bytes: bytes | None = None,
    movie_bytes_by_slide: dict[str, bytes] | None = None,
) -> live_host.LiveOutputHost:
    export_root = tmp_path / "export"
    write_one_movie_export(
        export_root, movie_bytes=movie_bytes, extra_movie_bytes=extra_movie_bytes,
        movie_bytes_by_slide=movie_bytes_by_slide,
    )
    (export_root / "assets" / "player").mkdir(parents=True, exist_ok=True)
    (export_root / "assets" / "player" / "main.js").write_bytes(player_bytes())
    (export_root / "index.html").write_text('<html><head></head><body><div id="stage"></div></body></html>')
    monkeypatch.setattr(live_runtime, "PLAYER_SHA256", hashlib.sha256(player_bytes()).hexdigest())
    monkeypatch.setattr(live_host, "choose_display", lambda *_a, **_k: live_host.OutputDisplay(1, 0, 0, 1920, 1080, True))
    # The fake CDP transport does not model authored scene counts; this fixture is
    # only exercising continuity resolution, not the build-renderer fallback check.
    monkeypatch.setattr(live_host.LiveOutputHost, "_authored_scene_count", lambda self: None)
    # The synthetic one-movie export is not a P2-measured plan; the allowlist itself is
    # covered in tests/test_live_continuity.py, so treat this plan as measured here.
    from obed_edom import live_continuity
    monkeypatch.setattr(live_continuity, "plan_signature", lambda _runtime: next(iter(live_continuity.QUALIFIED_PLAN_SHA256)))
    FakeCdp.instances.clear()
    kwargs = {"attach_endpoint": "http://127.0.0.1:9222"} if attach else {}
    return live_host.LiveOutputHost(
        export_root, slides_with_uuid(), headless=headless, transport_factory=FakeCdp,
        server_factory=FakeServer, resolver=continuity_resolver(export_root), continuity=continuity, **kwargs,
    )


def test_continuity_off_env_installs_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv(live_host.CONTINUITY_ENV, "off")
    output = host_with_continuity(tmp_path, monkeypatch)
    output.observe()
    assert output._continuity_mode == "off"
    assert output.output["continuity"]["mode"] == "off"
    assert output._server.continuity_script == ""
    assert not FakeCdp.instances[0].keys


def test_continuity_unsupported_from_derive(tmp_path, monkeypatch):
    output = host_with_continuity(tmp_path, monkeypatch)
    monkeypatch.setattr(live_host, "derive_plan", lambda *a, **k: live_host.Unsupported("bad export"))
    output.observe()
    assert output._continuity_mode == "unsupported"
    assert output.output["continuity"]["reason"] == "bad export"
    assert output._server.continuity_script == ""


def test_continuity_unsupported_from_to_runtime(tmp_path, monkeypatch):
    output = host_with_continuity(tmp_path, monkeypatch)

    class FakePlan:
        def to_runtime(self):
            return live_host.Unsupported("cannot translate")

    monkeypatch.setattr(live_host, "derive_plan", lambda *a, **k: FakePlan())
    output.observe()
    assert output._continuity_mode == "unsupported"
    assert output.output["continuity"]["reason"] == "cannot translate"
    assert output._server.continuity_script == ""


def stage_geometry(offset_width, offset_height, left, top, width, height):
    return {"offsetWidth": offset_width, "offsetHeight": offset_height, "rect": {"left": left, "top": top, "width": width, "height": height}}


def continuity_ready_evaluate(real_evaluate, stages):
    """A FakeCdp.evaluate replacement that reports the runtime ready and returns
    successive stage readings from `stages` for the continuity readback (the last
    value repeats once exhausted, simulating a stage that settles after N polls);
    everything else falls through to `real_evaluate`."""
    remaining = list(stages)

    def evaluate(self, expression):
        if "__OBED_CONTINUITY_INFO__" in expression:
            current = remaining.pop(0) if len(remaining) > 1 else remaining[0]
            return {"ready": True, "info": {"installed": True}, "stage": current}
        return real_evaluate(self, expression)

    return evaluate


def test_continuity_qualified_at_1to1(tmp_path, monkeypatch):
    output = host_with_continuity(tmp_path, monkeypatch)
    monkeypatch.setattr(FakeCdp, "evaluate", continuity_ready_evaluate(FakeCdp.evaluate, [stage_geometry(1920, 1080, 0, 0, 1920, 1080)]))
    output.observe()
    assert output._continuity_mode == "qualified"
    assert "reason" not in output.output["continuity"]
    assert output.output["continuity"]["scale"] == 1.0
    assert output._server.continuity_script != ""


def test_continuity_qualified_at_scaled_stage(tmp_path, monkeypatch):
    output = host_with_continuity(tmp_path, monkeypatch)
    monkeypatch.setattr(FakeCdp, "evaluate", continuity_ready_evaluate(FakeCdp.evaluate, [stage_geometry(1920, 1080, 0, 0, 2560, 1440)]))
    output.observe()
    assert output._continuity_mode == "qualified"
    assert output.output["continuity"]["scale"] == pytest.approx(1.3333, abs=1e-4)


def test_continuity_qualified_letterboxed(tmp_path, monkeypatch):
    output = host_with_continuity(tmp_path, monkeypatch)
    monkeypatch.setattr(FakeCdp, "evaluate", continuity_ready_evaluate(FakeCdp.evaluate, [stage_geometry(1920, 1080, 0, 50, 1600, 900)]))
    output.observe()
    assert output._continuity_mode == "qualified"
    assert output.output["continuity"]["scale"] == pytest.approx(1600 / 1920, abs=1e-4)


def test_continuity_stage_settles_after_a_few_polls(tmp_path, monkeypatch):
    output = host_with_continuity(tmp_path, monkeypatch)
    output.timeout_s = 2.0
    monkeypatch.setattr(
        FakeCdp, "evaluate",
        continuity_ready_evaluate(FakeCdp.evaluate, [None, None, stage_geometry(1920, 1080, 0, 0, 1920, 1080)]),
    )
    output.observe()
    assert output._continuity_mode == "qualified"


def test_continuity_stage_offset_size_mismatch_disables_runtime(tmp_path, monkeypatch):
    output = host_with_continuity(tmp_path, monkeypatch)
    output.timeout_s = .05
    real_evaluate = FakeCdp.evaluate
    disable_calls = []

    def evaluate(self, expression):
        if "disable" in expression:
            disable_calls.append(expression)
            return True
        if "__OBED_CONTINUITY_INFO__" in expression:
            return {"ready": True, "info": {"installed": True}, "stage": stage_geometry(1024, 768, 0, 0, 1024, 768)}
        return real_evaluate(self, expression)

    monkeypatch.setattr(FakeCdp, "evaluate", evaluate)
    output.observe()
    assert output._continuity_mode == "unsupported"
    assert output.output["continuity"]["reason"] == "stage is not the authored size"
    assert disable_calls


def test_continuity_non_uniform_scale_disables_runtime(tmp_path, monkeypatch):
    output = host_with_continuity(tmp_path, monkeypatch)
    output.timeout_s = .05
    real_evaluate = FakeCdp.evaluate
    disable_calls = []

    def evaluate(self, expression):
        if "disable" in expression:
            disable_calls.append(expression)
            return True
        if "__OBED_CONTINUITY_INFO__" in expression:
            return {"ready": True, "info": {"installed": True}, "stage": stage_geometry(1920, 1080, 0, 0, 2560, 1000)}
        return real_evaluate(self, expression)

    monkeypatch.setattr(FakeCdp, "evaluate", evaluate)
    output.observe()
    assert output._continuity_mode == "unsupported"
    assert output.output["continuity"]["reason"] == "stage scale is non-uniform"
    assert disable_calls


def test_continuity_stage_gate_deadline_expiry_disables_runtime(tmp_path, monkeypatch):
    output = host_with_continuity(tmp_path, monkeypatch)
    output.timeout_s = .12
    real_evaluate = FakeCdp.evaluate
    disable_calls = []

    def evaluate(self, expression):
        if "disable" in expression:
            disable_calls.append(expression)
            return True
        if "__OBED_CONTINUITY_INFO__" in expression:
            return {"ready": True, "info": {"installed": True}, "stage": None}
        return real_evaluate(self, expression)

    monkeypatch.setattr(FakeCdp, "evaluate", evaluate)
    output.observe()
    assert output._continuity_mode == "unsupported"
    assert output.output["continuity"]["reason"] == "stage is not the authored size"
    assert disable_calls


def test_continuity_disable_not_confirmed_raises(tmp_path, monkeypatch):
    output = host_with_continuity(tmp_path, monkeypatch)
    output.timeout_s = .05
    real_evaluate = FakeCdp.evaluate

    def evaluate(self, expression):
        if "disable" in expression:
            return False
        if "__OBED_CONTINUITY_INFO__" in expression:
            return {"ready": True, "info": {"installed": True}, "stage": None}
        return real_evaluate(self, expression)

    monkeypatch.setattr(FakeCdp, "evaluate", evaluate)
    with pytest.raises(live_host.LiveHostError, match="could not be confirmed disabled"):
        output.observe()


def test_continuity_runtime_never_present_is_immediate_no_polling_no_disable(tmp_path, monkeypatch):
    output = host_with_continuity(tmp_path, monkeypatch)
    output.timeout_s = 5.0  # would hang for seconds if the gate incorrectly polled this case
    real_evaluate = FakeCdp.evaluate
    calls, disable_calls = [], []

    def evaluate(self, expression):
        if "disable" in expression:
            disable_calls.append(expression)
            return True
        if "__OBED_CONTINUITY_INFO__" in expression:
            calls.append(expression)
            return {"ready": False, "present": False, "info": {"installed": True}, "stage": None}
        return real_evaluate(self, expression)

    monkeypatch.setattr(FakeCdp, "evaluate", evaluate)
    start = time.monotonic()
    output.observe()
    elapsed = time.monotonic() - start
    assert output._continuity_mode == "unsupported"
    assert output.output["continuity"]["reason"] == "runtime failed to install"
    assert len(calls) == 1
    assert disable_calls == []
    assert elapsed < 1.0


def test_continuity_partial_install_never_ready_disables_runtime(tmp_path, monkeypatch):
    output = host_with_continuity(tmp_path, monkeypatch)
    output.timeout_s = 5.0  # would hang for seconds if the gate incorrectly polled this case
    real_evaluate = FakeCdp.evaluate
    calls, disable_calls = [], []

    def evaluate(self, expression):
        if "disable" in expression:
            disable_calls.append(expression)
            return True
        if "__OBED_CONTINUITY_INFO__" in expression:
            calls.append(expression)
            return {"ready": False, "present": True, "info": {"installed": True}, "stage": None}
        return real_evaluate(self, expression)

    monkeypatch.setattr(FakeCdp, "evaluate", evaluate)
    start = time.monotonic()
    output.observe()
    elapsed = time.monotonic() - start
    assert output._continuity_mode == "unsupported"
    assert output.output["continuity"]["reason"] == "runtime failed to install"
    assert len(calls) == 1
    assert len(disable_calls) == 1
    assert elapsed < 1.0


def test_continuity_partial_install_disable_unconfirmed_raises(tmp_path, monkeypatch):
    output = host_with_continuity(tmp_path, monkeypatch)
    output.timeout_s = 5.0
    real_evaluate = FakeCdp.evaluate

    def evaluate(self, expression):
        if "disable" in expression:
            return False
        if "__OBED_CONTINUITY_INFO__" in expression:
            return {"ready": False, "present": True, "info": {"installed": True}, "stage": None}
        return real_evaluate(self, expression)

    monkeypatch.setattr(FakeCdp, "evaluate", evaluate)
    with pytest.raises(live_host.LiveHostError, match="could not be confirmed disabled"):
        output.observe()


def test_continuity_go_to_clears_runtime_only_when_qualified(tmp_path, monkeypatch):
    output = host_with_continuity(tmp_path, monkeypatch)
    real_evaluate = continuity_ready_evaluate(FakeCdp.evaluate, [stage_geometry(1920, 1080, 0, 0, 1920, 1080)])
    calls = []

    def evaluate(self, expression):
        if "clear" in expression:
            calls.append(expression)
            return None
        return real_evaluate(self, expression)

    monkeypatch.setattr(FakeCdp, "evaluate", evaluate)
    output.observe()
    assert output._continuity_mode == "qualified"
    output.execute("goTo", 2)
    assert len(calls) == 1
    assert FakeCdp.instances[0].keys[-3:] == ["clear-noop", "2", "Enter"] or FakeCdp.instances[0].keys == ["2", "Enter"]


def test_continuity_go_to_never_clears_when_not_qualified(tmp_path, monkeypatch):
    output = host_with_continuity(tmp_path, monkeypatch)
    output.observe()
    assert output._continuity_mode == "unsupported"
    calls = []
    real_evaluate = FakeCdp.evaluate

    def evaluate(self, expression):
        if "clear" in expression:
            calls.append(expression)
        return real_evaluate(self, expression)

    monkeypatch.setattr(FakeCdp, "evaluate", evaluate)
    output.execute("goTo", 2)
    assert calls == []


def test_continuity_transparent_background_only_in_attach_mode(tmp_path, monkeypatch):
    hdmi = host_with_continuity(tmp_path, monkeypatch, attach=False)
    hdmi.observe()
    assert hdmi._continuity_runtime_plan is not None
    assert not hdmi._continuity_runtime_plan.get("transparentBackground")

    monkeypatch.setenv("OBED_EDOM_OUTPUT_ROOT", str(tmp_path / "preview"))
    attach = host_with_continuity(tmp_path, monkeypatch, attach=True)
    attach.observe()
    assert attach._continuity_runtime_plan is not None
    assert attach._continuity_runtime_plan["transparentBackground"] is True


def test_continuity_scripts_injection_order_and_safe_json_embedding(tmp_path):
    (tmp_path / "index.html").write_text('<html><head></head><body><div id="stage"></div></body></html>')
    plan = {"movies": {"movie1": {"assetKeys": ["</script><script>alert(1)</script>"], "footprint": {"x": 0, "y": 0, "w": 1, "h": 1}}}, "boundaries": []}
    script = live_host._continuity_scripts(plan, {"width": 1920, "height": 1080})
    assert "</script><script>alert(1)" not in script
    server = live_host._AssetServer(tmp_path, b"", resolver=resolver_for(tmp_path), continuity_script=script)
    document = server._program_html().decode()
    body = document[document.index("<body"):]
    assert (
        body.index('id="obed-output-black"')
        < body.index('id="obed-continuity-plan"')
        < body.index('id="obed-continuity-core"')
        < body.index('id="obed-output-fit"')
        < body.index('id="stage"')
    )
    # A naive close of the script tag inside the embedded plan would truncate the
    # document before the core/fit scripts; both must still be present intact.
    assert document.count('id="obed-continuity-core"') == 1
    assert document.count('id="obed-output-fit"') == 1


def test_nothing_continuity_related_injected_when_off(tmp_path, monkeypatch):
    monkeypatch.setenv(live_host.CONTINUITY_ENV, "off")
    output = host_with_continuity(tmp_path, monkeypatch)
    output.observe()
    document = output._server.continuity_script
    assert document == ""


def test_continuity_output_shape(tmp_path, monkeypatch):
    output = host_with_continuity(tmp_path, monkeypatch)
    output.observe()
    continuity = output.output["continuity"]
    assert set(continuity) <= {"mode", "reason", "version", "sha256", "scale"}
    assert continuity["mode"] == "unsupported"
    assert continuity["version"] == live_host.CONTINUITY_VERSION
    assert isinstance(continuity["sha256"], str) and len(continuity["sha256"]) == 64


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


@pytest.mark.parametrize("mode", ["key", "click"])
def test_advance_mode_is_resolved_once_at_start_and_logged(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("OBED_EDOM_OUTPUT_ROOT", str(tmp_path / "preview"))
    output = host(tmp_path, monkeypatch)
    monkeypatch.setenv(live_host.ADVANCE_ENV, mode)
    output.start()
    monkeypatch.setenv(live_host.ADVANCE_ENV, "key" if mode == "click" else "click")
    observed = output.execute("advance")
    fake = FakeCdp.instances[0]
    assert observed.revision == 1
    assert fake.clicks == (1 if mode == "click" else 0)
    assert fake.keys == ([] if mode == "click" else [" "])
    output.stop()
    records = [json.loads(line) for line in output._log_path.read_text().splitlines()]
    assert next(record for record in records if record["kind"] == "start")["advanceMode"] == mode


def test_invalid_advance_mode_refuses_before_starting_resources(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)
    monkeypatch.setenv(live_host.ADVANCE_ENV, "tap")
    with pytest.raises(live_host.LiveHostError, match="must be key or click"):
        output.start()
    assert not FakeCdp.instances
    assert output._server is None


def test_click_mode_go_to_still_uses_keys_and_refuses_missing_ack(tmp_path, monkeypatch):
    monkeypatch.setenv(live_host.ADVANCE_ENV, "click")
    output = host(tmp_path, monkeypatch)
    output.start()
    fake = FakeCdp.instances[0]
    fake.revision_on_enter = False
    output.timeout_s = .01
    with pytest.raises(live_host.PlayerCommandRejected, match="Click advance cannot select a slide"):
        output.execute("goTo", 2)
    assert fake.keys == ["2", "Enter"]
    assert fake.clicks == 0


def test_click_stage_dispatches_press_and_release_at_measured_centre(tmp_path, monkeypatch):
    transport = live_host.ChromeCdp(Path("chrome"), tmp_path, None)
    expressions, calls = [], []
    def evaluate(expression):
        expressions.append(expression)
        return [812.5, 406.25]
    monkeypatch.setattr(transport, "evaluate", evaluate)
    monkeypatch.setattr(transport, "call", lambda method, **params: calls.append((method, params)))
    transport.click_stage()
    assert "getElementById('stage')" in expressions[0]
    assert "getBoundingClientRect" in expressions[0]
    assert calls == [
        ("Input.dispatchMouseEvent", {"type": kind, "x": 812.5, "y": 406.25, "button": "left", "clickCount": 1})
        for kind in ("mousePressed", "mouseReleased")
    ]


@pytest.mark.parametrize("point", [None, [], [1], [True, 2], [float("nan"), 2], [1, float("inf")]])
def test_click_stage_refuses_missing_or_invalid_geometry(tmp_path, monkeypatch, point):
    transport = live_host.ChromeCdp(Path("chrome"), tmp_path, None)
    monkeypatch.setattr(transport, "evaluate", lambda _: point)
    with pytest.raises(live_host.PlayerCommandRejected, match="no usable centre"):
        transport.click_stage()


@pytest.mark.parametrize("readback", [None, {}, {"ready": False, "present": False, "info": {"installed": True}, "stage": None}])
def test_continuity_runtime_failure_is_distinct_from_stage_gate_failure(tmp_path, monkeypatch, readback):
    output = host_with_continuity(tmp_path, monkeypatch)
    real_evaluate = FakeCdp.evaluate
    def evaluate(self, expression):
        if "__OBED_CONTINUITY_INFO__" in expression:
            assert ".ready" in expression
            return readback
        return real_evaluate(self, expression)
    monkeypatch.setattr(FakeCdp, "evaluate", evaluate)
    output.start()
    assert output.output["continuity"]["mode"] == "unsupported"
    assert output.output["continuity"]["reason"] == "runtime failed to install"


def test_pick_target_does_not_match_across_url_title_boundary(tmp_path):
    transport = live_host.ChromeCdp(Path("chrome"), tmp_path, None, attach_match="programsource")
    pages = [{"type": "page", "url": "http://localhost/program", "title": "source", "webSocketDebuggerUrl": "ws://localhost"}]
    with pytest.raises(live_host.LiveHostError, match="did not select exactly one"):
        transport._pick_target(pages)


def test_logger_full_queue_close_drains_and_never_closes_a_busy_writer(tmp_path, monkeypatch):
    writing, release = threading.Event(), threading.Event()
    class SlowFile:
        def __init__(self): self.closed = False; self.lines = []
        def write(self, line):
            writing.set()
            assert release.wait(3)
            assert not self.closed
            self.lines.append(line)
        def flush(self): pass
        def close(self): self.closed = True
    file = SlowFile()
    monkeypatch.setattr(Path, "open", lambda *_a, **_k: file)
    monkeypatch.setattr(live_host._SessionLogger, "_QUEUE_MAXSIZE", 1)
    logger = live_host._SessionLogger(tmp_path / "slow.jsonl")
    logger.log("first")
    assert writing.wait(1)
    logger.log("second")
    logger.log("dropped")
    assert logger.dropped == 1
    writer = logger._writer
    real_join = writer.join
    monkeypatch.setattr(writer, "join", lambda timeout=None: real_join(timeout=.01))
    try:
        logger.close()
        assert not file.closed
        logger.log("after-close")
    finally:
        release.set()
        real_join(timeout=1)
    assert not writer.is_alive()
    assert file.closed
    assert [json.loads(line)["kind"] for line in file.lines] == ["first", "second"]


@pytest.mark.parametrize("mode", ["off", "unsupported"])
@pytest.mark.parametrize("alpha,expected_sha", [
    (False, "214fe86209b3b88fa2ff129674f108b5b99d2023bf061321b98f7c9bbdea5a99"),
    (True, "747ae7b38e5c724cad51f1b4be9c5893e7cebdd556435c5a72671bf05b83cafc"),
])
def test_continuity_inactive_html_is_byte_identical_to_pre_i2(tmp_path, monkeypatch, mode, alpha, expected_sha):
    # Hashes generated from _AssetServer._program_html at 1ff9f89 (before I2),
    # using this fixture's exact index.html; include blank lines in the contract.
    if mode == "off":
        monkeypatch.setenv(live_host.CONTINUITY_ENV, "off")
    else:
        monkeypatch.setattr(live_host, "derive_plan", lambda *_a, **_k: live_host.Unsupported("unsupported fixture"))
    output = host_with_continuity(tmp_path, monkeypatch, attach=alpha)
    output.start()
    assert output._continuity_mode == mode
    server = live_host._AssetServer(output.export_root, b"", resolver=output.resolver, alpha=alpha, continuity_script=output._server.continuity_script)
    assert hashlib.sha256(server._program_html()).hexdigest() == expected_sha


@pytest.mark.parametrize("endpoint", ["http://127.0.0.1:wrong", "http://127.0.0.1:65536", "http://[::1"])
def test_attach_endpoint_rejects_invalid_ports_and_brackets_with_host_error(endpoint):
    with pytest.raises(live_host.LiveHostError, match="valid http loopback"):
        live_host._validate_loopback_endpoint(endpoint)


@pytest.mark.parametrize("url", ["ws://user@127.0.0.1:9222/page", "ws://127.0.0.1:9222/page#fragment", "ws://127.0.0.1:bad/page"])
def test_target_websocket_rejects_credentials_fragments_and_invalid_ports(url):
    with pytest.raises(live_host.LiveHostError):
        live_host._validate_target_ws_url(url, "http://127.0.0.1:9222")


def test_failed_attach_discovery_can_be_stopped_without_an_unowned_target(tmp_path, monkeypatch):
    transport = live_host.ChromeCdp(Path("chrome"), tmp_path, None, attach_endpoint="http://127.0.0.1:9222")
    monkeypatch.setattr(transport, "_list_targets", lambda: [])
    with pytest.raises(live_host.LiveHostError, match="Ambiguous"):
        transport.start()
    transport.stop()
    transport.stop()
    assert transport._blanked


def test_continuity_session_opt_out_installs_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv(live_host.CONTINUITY_ENV, raising=False)
    output = host_with_continuity(tmp_path, monkeypatch, continuity="off")
    output.observe()
    assert output.output["continuity"]["mode"] == "off"
    assert output._server.continuity_script == ""


def test_continuity_auto_cannot_override_environment_opt_out(tmp_path, monkeypatch):
    monkeypatch.setenv(live_host.CONTINUITY_ENV, "off")
    output = host_with_continuity(tmp_path, monkeypatch, continuity="auto")
    output.observe()
    assert output.output["continuity"]["mode"] == "off"
    assert output._server.continuity_script == ""


def test_attach_stop_restores_the_blank_url_the_target_had_so_a_match_string_still_works(tmp_path, monkeypatch):
    # Found against real OBS 32.2.2: the browser source was `about:blank#program` and the
    # operator matched on that; blanking to bare `about:blank` made the NEXT session's
    # OBED_LIVE_ATTACH_MATCH select nothing. A non-blank original URL still blanks to about:blank.
    display = live_host.OutputDisplay(1, 0, 0, 1920, 1080, True)
    for original, expected in (("about:blank#program", "about:blank#program"), ("https://example.invalid/x", "about:blank")):
        transport = live_host.ChromeCdp(
            Path("chrome"), tmp_path, display, attach_endpoint="http://127.0.0.1:9222", attach_match="program" if "#" in original else None,
        )
        target = {"type": "page", "id": "abc", "url": original, "title": original, "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/abc"}
        monkeypatch.setattr(transport, "_list_targets", lambda target=target: [target])
        attach_ws = BlockingWs()
        blank_ws = FakeBlankWs(confirmed_url=expected)
        sockets = iter([attach_ws, blank_ws])
        monkeypatch.setattr(live_host, "connect", lambda *a, **k: next(sockets))
        monkeypatch.setattr(transport, "call", lambda *a, **k: {})
        transport.start()
        transport.stop()
        assert blank_ws.sent[0]["params"]["url"] == expected
        assert transport._blanked


# --- I5 codec report -------------------------------------------------------------------------


def test_codecs_output_present_even_when_continuity_off(tmp_path, monkeypatch):
    monkeypatch.setenv(live_host.CONTINUITY_ENV, "off")
    output = host_with_continuity(tmp_path, monkeypatch, extra_movie_bytes=hevc_movie_bytes())
    output.observe()
    assert output.output["continuity"]["mode"] == "off"
    assets = {entry["asset"] for entry in output.output["codecs"]}
    assert assets == {"movie.mov", "extra-movie.mov"}
    assert output.output["codecWarnings"] == ["extra-movie.mov (hvc1) may not play in this output"]


def test_h264_movie_qualifies_with_no_codec_warning(tmp_path, monkeypatch):
    output = host_with_continuity(tmp_path, monkeypatch)
    monkeypatch.setattr(FakeCdp, "evaluate", continuity_ready_evaluate(FakeCdp.evaluate, [stage_geometry(1920, 1080, 0, 0, 1920, 1080)]))
    output.observe()
    assert output._continuity_mode == "qualified"
    assert output.output["codecWarnings"] == []
    # both slide folders hold their own copy of the movie, and both are probed.
    assert output.output["codecs"] == [{"asset": "movie.mov", "codec": "avc1", "family": "h264", "files": 2}]


def test_unplanned_hevc_movie_does_not_block_continuity_but_warns(tmp_path, monkeypatch):
    # The extra movie only appears (single-instance) on slide 2, so it never enters the
    # runtime's movie table; the planned movie is still plain h264, so continuity must
    # still qualify. The unplanned movie's HEVC still shows up as an advisory warning.
    output = host_with_continuity(tmp_path, monkeypatch, extra_movie_bytes=hevc_movie_bytes())
    monkeypatch.setattr(FakeCdp, "evaluate", continuity_ready_evaluate(FakeCdp.evaluate, [stage_geometry(1920, 1080, 0, 0, 1920, 1080)]))
    output.observe()
    assert output._continuity_mode == "qualified"
    assert output.output["codecWarnings"] == ["extra-movie.mov (hvc1) may not play in this output"]


def test_planned_hevc_headless_launch_is_unsupported_with_no_continuity_script(tmp_path, monkeypatch):
    output = host_with_continuity(tmp_path, monkeypatch, movie_bytes=hevc_movie_bytes())
    output.observe()
    assert output._continuity_mode == "unsupported"
    assert output.output["continuity"]["reason"] == "movie codec is not playable in this output: movie.mov (hvc1)"
    assert output._server.continuity_script == ""


def test_planned_hevc_headful_launch_still_qualifies_statically(tmp_path, monkeypatch):
    output = host_with_continuity(tmp_path, monkeypatch, headless=False, movie_bytes=hevc_movie_bytes())
    output._codec_report, output._codec_warnings = output._resolve_codecs()
    mode, reason, runtime = output._resolve_continuity_static()
    assert mode == "pending"
    assert reason is None
    assert runtime is not None


def test_planned_hevc_attach_mode_is_unsupported(tmp_path, monkeypatch):
    monkeypatch.setenv("OBED_EDOM_OUTPUT_ROOT", str(tmp_path / "preview"))
    output = host_with_continuity(tmp_path, monkeypatch, attach=True, movie_bytes=hevc_movie_bytes())
    output.observe()
    assert output._continuity_mode == "unsupported"
    assert output.output["continuity"]["reason"] == "movie codec is not playable in this output: movie.mov (hvc1)"


def test_unreadable_planned_movie_is_unsupported(tmp_path, monkeypatch):
    output = host_with_continuity(tmp_path, monkeypatch, movie_bytes=b"not a real movie file, just garbage bytes here")
    output.observe()
    assert output._continuity_mode == "unsupported"
    assert output.output["continuity"]["reason"] == "movie codec is not playable in this output: movie.mov (unreadable)"


def test_planned_movie_whose_slide_copies_disagree_is_unsupported_even_headful(tmp_path, monkeypatch):
    # Slide 1's copy is H.264 and slide 2's is HEVC under the same logical key, so the key
    # cannot be called playable: headful launch, where plain HEVC would qualify, must not.
    output = host_with_continuity(
        tmp_path, monkeypatch, headless=False, movie_bytes_by_slide={"s2": hevc_movie_bytes()},
    )
    output._codec_report, output._codec_warnings = output._resolve_codecs()
    assert output._codec_report == [
        {"asset": "movie.mov", "codec": None, "family": "other", "files": 2, "mixed": True},
    ]
    assert output._codec_warnings == ["movie.mov (mixed codecs) may not play in this output"]
    mode, reason, runtime = output._resolve_continuity_static()
    assert mode == "unsupported"
    assert reason == "movie codec is not playable in this output: movie.mov (mixed codecs)"
    assert runtime is None


def test_planned_movie_with_one_unreadable_slide_copy_is_unsupported(tmp_path, monkeypatch):
    output = host_with_continuity(
        tmp_path, monkeypatch, movie_bytes_by_slide={"s2": b"not a real movie file, just garbage"},
    )
    output.observe()
    assert output._continuity_mode == "unsupported"
    assert output.output["continuity"]["reason"] == "movie codec is not playable in this output: movie.mov (unreadable)"
    assert output._server.continuity_script == ""


def test_codecs_recorded_in_session_log(tmp_path, monkeypatch):
    output = host_with_continuity(tmp_path, monkeypatch, extra_movie_bytes=hevc_movie_bytes())
    output.start()
    records = [json.loads(line) for line in output._log_path.read_text().splitlines()]
    codecs_record = next(record for record in records if record["kind"] == "codecs")
    assets = {entry["asset"] for entry in codecs_record["report"]}
    assert assets == {"movie.mov", "extra-movie.mov"}
    assert codecs_record["warnings"] == ["extra-movie.mov (hvc1) may not play in this output"]
