from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from obed_edom import html_preview, live_gl_replay_js, live_host, live_runtime


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
        self.auto_play_run_length: int | None = None
        self.auto_play_run_kinds: list | None = None
        self.runtime_version = 2
        self.space_rejects: bool = False
        self.slide_number_showing = False
        self.__class__.instances.append(self)

    def start(self): self.started = True
    def goto(self, url): self.url = url
    def stop(self): self.stopped = True
    def key(self, key, code, vk):
        if key == " " and self.space_rejects:
            raise live_host.PlayerCommandRejected("Player is busy.")
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
        if self.space_rejects:
            raise live_host.PlayerCommandRejected("Player is busy.")
        self.clicks += 1
        self.revision += 1
        self.busy = self.busy_on_enter
    def evaluate(self, expression):
        if "__OBED_CONTINUITY_INFO__" in expression:
            return {"ready": False, "present": False, "info": {"installed": True}, "stage": None}
        if "__obedLive" in expression:
            return {
                "exportedSlideIndex": self.index, "sceneId": self.index, "buildIndex": None, "revision": self.revision,
                "canAdvance": self.can_advance, "canGoTo": not self.busy, "ready": not self.busy, "busy": self.busy,
                "autoPlayRunLength": self.auto_play_run_length, "autoPlayRunKinds": self.auto_play_run_kinds,
                "runtimeVersion": self.runtime_version, "slideNumberShowing": self.slide_number_showing,
            }
        if ".hide()" in expression: self.visible = False; return None
        if ".show()" in expression: self.visible = True; return None
        return self.visible


class FakeServer:
    def __init__(self, _root=None, patched_player=b"", *_, alpha=False, continuity_script=""):
        self.stopped = False; self.alpha = alpha; self.continuity_script = continuity_script; self.patched_player = patched_player
    def start(self): return "http://program.test/program.html"
    def stop(self): self.stopped = True


def player_bytes() -> bytes:
    mm_anchors = b";".join(before for before, _after in live_runtime._MM_OPACITY_REPLACEMENTS)
    return b"before;" + live_runtime._ANCHOR + b";" + mm_anchors + b";after"


def resolver(root: Path, relative: str) -> Path:
    if relative == "assets/player/main.js": return root / "main.js"
    if relative == "assets/header.json": return root / "header.json"
    raise AssertionError(relative)


def host(tmp_path, monkeypatch, **kwargs: Any) -> live_host.LiveOutputHost:
    (tmp_path / "main.js").write_bytes(player_bytes())
    (tmp_path / "header.json").write_text('{"slideWidth":1920,"slideHeight":1080,"showMode":0}')
    monkeypatch.setattr(live_runtime, "PLAYER_SHA256", hashlib.sha256(player_bytes()).hexdigest())
    monkeypatch.setattr(live_host, "choose_display", lambda *_args, **_kwargs: live_host.OutputDisplay(9, 10, 20, 2560, 1440))
    monkeypatch.delenv(live_host.MM_OPACITY_ENV, raising=False)
    FakeCdp.instances.clear()
    return live_host.LiveOutputHost(tmp_path, [{"originalOrdinal": 1, "playerIndex": 0, "skipped": False}, {"originalOrdinal": 2, "playerIndex": 1, "skipped": False}, {"originalOrdinal": 3, "skipped": True}], headless=True, transport_factory=FakeCdp, server_factory=FakeServer, resolver=resolver, **kwargs)


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


@pytest.mark.parametrize("alpha", [False, True])
def test_program_html_overlay_hides_slide_number_control(tmp_path, alpha):
    (tmp_path / "index.html").write_text('<html><head></head><body><div id="stage"></div></body></html>')
    server = live_host._AssetServer(tmp_path, b"", resolver=resolver_for(tmp_path), alpha=alpha)
    document = server._program_html().decode()
    overlay = document[document.index('id="obed-output-overlay"') : document.index("</style>")]
    rule = re.search(r"([^{}]*)\{display:none!important\}", overlay)
    assert rule and "#slideNumberControl" in rule.group(1).split(",")


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


def test_pick_target_matches_an_exact_target_id_whatever_the_page_url(tmp_path):
    transport = live_host.ChromeCdp(Path("chrome"), tmp_path, None, attach_endpoint="http://127.0.0.1:9222", attach_match="ABC123")
    pages = [
        {"type": "page", "id": "ABC123", "url": "http://127.0.0.1:5000/program.html", "title": "program", "webSocketDebuggerUrl": "ws://a"},
        {"type": "page", "id": "DEF456", "url": "about:blank", "title": "", "webSocketDebuggerUrl": "ws://b"},
    ]
    assert transport._pick_target(pages)["webSocketDebuggerUrl"] == "ws://a"
    transport.attach_match = "ABC12"
    with pytest.raises(live_host.LiveHostError, match="did not select exactly one"):
        transport._pick_target(pages)


def test_pick_target_url_substring_match_still_works_beside_id_match(tmp_path):
    transport = live_host.ChromeCdp(Path("chrome"), tmp_path, None, attach_endpoint="http://127.0.0.1:9222", attach_match="#obed-ak")
    pages = [
        {"type": "page", "id": "1", "url": "about:blank#obed-ak", "title": "", "webSocketDebuggerUrl": "ws://a"},
        {"type": "page", "id": "2", "url": "about:blank", "title": "", "webSocketDebuggerUrl": "ws://b"},
    ]
    assert transport._pick_target(pages)["webSocketDebuggerUrl"] == "ws://a"


def test_pick_target_id_match_is_ambiguous_when_another_page_also_matches_by_url(tmp_path):
    transport = live_host.ChromeCdp(Path("chrome"), tmp_path, None, attach_endpoint="http://127.0.0.1:9222", attach_match="ABC123")
    pages = [
        {"type": "page", "id": "ABC123", "url": "about:blank", "title": "", "webSocketDebuggerUrl": "ws://a"},
        {"type": "page", "id": "2", "url": "http://x/ABC123", "title": "", "webSocketDebuggerUrl": "ws://b"},
    ]
    with pytest.raises(live_host.LiveHostError, match="did not select exactly one"):
        transport._pick_target(pages)


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


def _draw_slot(object_id: str | None, x: float, y: float, w: float, h: float) -> dict[str, Any]:
    """One slide draw slot, as the real export encodes it: a wrapper layer holding a single
    object whose `initialState` carries the slide-space centre and size."""
    child: dict[str, Any] = {"initialState": {"position": {"pointX": x, "pointY": y}, "width": w, "height": h}}
    if object_id is not None:
        child["objectID"] = object_id
    return {"layers": [child]}


def write_one_movie_export(
    root: Path, *, movie_bytes: bytes | None = None, extra_movie_bytes: bytes | None = None,
    movie_bytes_by_slide: dict[str, bytes] | None = None,
    artwork_above_on_s2: bool = False, masked: bool = False,
) -> None:
    assets_dir = root / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / "header.json").write_text(json.dumps({"slideWidth": 1920, "slideHeight": 1080, "showMode": 0, "slideList": ["s1", "s2"]}))
    assets = {"movie-asset": {"url": {"web": "assets/movie.mov"}}}
    movie_state: dict[str, Any] = {"position": {"pointX": 200.0, "pointY": 200.0}, "width": 100.0, "height": 100.0}
    if masked:
        movie_state["masksToBounds"] = True
    movie_node = {
        "objectID": "movie-object",
        "movie": {"asset": "movie-asset"},
        "baseLayer": {
            "initialState": movie_state,
            "layers": [
                {
                    "isVideoLayer": True,
                    "initialState": {"position": {"pointX": 50.0, "pointY": 50.0}, "width": 100.0, "height": 100.0},
                }
            ],
        },
    }
    movie_slot = _draw_slot("movie-object", 200.0, 200.0, 100.0, 100.0)
    extra_movie_node = None
    extra_slot = None
    if extra_movie_bytes is not None:
        assets["extra-movie-asset"] = {"url": {"web": "assets/extra-movie.mov"}}
        extra_movie_node = {
            "objectID": "extra-movie-object",
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
        extra_slot = _draw_slot("extra-movie-object", 600.0, 600.0, 50.0, 50.0)
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
    background = _draw_slot(None, 960.0, 540.0, 1920.0, 1080.0)
    slots_s2 = [background] + ([extra_slot] if extra_slot is not None else []) + [movie_slot]
    if artwork_above_on_s2:
        slots_s2.append(_draw_slot(None, 200.0, 200.0, 80.0, 80.0))
    events_s1 = [{
        "baseLayer": {"layers": [background, movie_slot]},
        "effects": [movie_node, {"type": "transition", "name": "apple:magic-move"}],
    }]
    events_s2 = [{
        "baseLayer": {"layers": slots_s2},
        "effects": [movie_node] + ([extra_movie_node] if extra_movie_node is not None else []),
    }]
    (assets_dir / "s1" / "s1.json").write_text(json.dumps({"events": events_s1, "assets": assets}))
    (assets_dir / "s2" / "s2.json").write_text(json.dumps({"events": events_s2, "assets": assets}))
    (assets_dir / "s1" / "s1.jsonp").write_text("local_slide(" + json.dumps({"json": {"events": events_s1}}) + ")")
    (assets_dir / "s2" / "s2.jsonp").write_text("local_slide(" + json.dumps({"json": {"events": events_s2}}) + ")")


def host_with_continuity(
    tmp_path, monkeypatch, *, attach: bool = False, continuity: str = "auto", headless: bool = True,
    movie_bytes: bytes | None = None, extra_movie_bytes: bytes | None = None,
    movie_bytes_by_slide: dict[str, bytes] | None = None,
    artwork_above_on_s2: bool = False, masked: bool = False, gl_replay: str | None = None, **host_kwargs: Any,
) -> live_host.LiveOutputHost:
    export_root = tmp_path / "export"
    write_one_movie_export(
        export_root, movie_bytes=movie_bytes, extra_movie_bytes=extra_movie_bytes,
        movie_bytes_by_slide=movie_bytes_by_slide,
        artwork_above_on_s2=artwork_above_on_s2, masked=masked,
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
    monkeypatch.delenv("OBED_LIVE_GL_REPLAY", raising=False)
    monkeypatch.delenv(live_host.MM_OPACITY_ENV, raising=False)
    FakeCdp.instances.clear()
    kwargs: dict[str, Any] = {"attach_endpoint": "http://127.0.0.1:9222"} if attach else {}
    if gl_replay is not None:
        kwargs["gl_replay"] = gl_replay
    return live_host.LiveOutputHost(
        export_root, slides_with_uuid(), headless=headless, transport_factory=FakeCdp,
        server_factory=FakeServer, resolver=continuity_resolver(export_root), continuity=continuity, **kwargs, **host_kwargs,
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


def test_artwork_above_the_movie_retires_that_boundary_without_losing_continuity(tmp_path, monkeypatch):
    """Later-authored artwork on the destination slide declines ONE cut: the session still
    installs continuity (mode pending, then qualified), the runtime plan retires the movie at
    that scene, and the snapshot names the boundary in operator slide numbers."""
    output = host_with_continuity(tmp_path, monkeypatch, artwork_above_on_s2=True)
    monkeypatch.setattr(FakeCdp, "evaluate", continuity_ready_evaluate(FakeCdp.evaluate, [stage_geometry(1920, 1080, 0, 0, 1920, 1080)]))
    output.observe()
    assert output._continuity_mode == "qualified"
    assert output._server.continuity_script != ""
    retires = [b for b in output._continuity_runtime_plan["boundaries"] if b["action"] == "retire"]
    assert len(retires) == 1
    assert retires[0]["movieKey"] == "movie1"
    not_carried = output.output["continuity"]["notCarried"]
    assert len(not_carried) == 1
    entry = not_carried[0]
    assert entry["fromSlide"] == 1
    assert entry["toSlide"] == 2
    assert entry["asset"] == "movie.mov"
    assert "later-authored artwork overlaps" in entry["reason"]


def test_continuity_without_refusals_reports_no_not_carried(tmp_path, monkeypatch):
    output = host_with_continuity(tmp_path, monkeypatch)
    monkeypatch.setattr(FakeCdp, "evaluate", continuity_ready_evaluate(FakeCdp.evaluate, [stage_geometry(1920, 1080, 0, 0, 1920, 1080)]))
    output.observe()
    assert output._continuity_mode == "qualified"
    assert "notCarried" not in output.output["continuity"]


def test_possibly_masked_movie_is_unsupported_with_no_continuity_script(tmp_path, monkeypatch):
    output = host_with_continuity(tmp_path, monkeypatch, masked=True)
    output.observe()
    assert output._continuity_mode == "unsupported"
    assert "possible mask" in output.output["continuity"]["reason"]
    assert "masksToBounds" in output.output["continuity"]["reason"]
    assert "notCarried" not in output.output["continuity"]
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
    assert set(continuity) <= {"mode", "reason", "version", "sha256", "scale", "glReplay"}
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
    (False, "2e15d1c44f3cc6760fc65d3d857d6c14884eabaa5a50b9842917556ec1fed616"),
    (True, "46302ad0c78b1271a5546e251aa128395846761b258d1bae5f66fa7779dc4ac7"),
])
def test_continuity_inactive_html_is_byte_identical_to_pre_i2(tmp_path, monkeypatch, mode, alpha, expected_sha):
    # Hashes generated from _AssetServer._program_html at 1ff9f89 (before I2) plus
    # the #slideNumberControl hide, using this fixture's exact index.html; include
    # blank lines in the contract.
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
    # The session log is drained by a daemon writer thread; only stop() joins it,
    # so reading before stop() races the writer (flaked under xdist load).
    output.stop()
    records = [json.loads(line) for line in output._log_path.read_text().splitlines()]
    codecs_record = next(record for record in records if record["kind"] == "codecs")
    assets = {entry["asset"] for entry in codecs_record["report"]}
    assert assets == {"movie.mov", "extra-movie.mov"}
    assert codecs_record["warnings"] == ["extra-movie.mov (hvc1) may not play in this output"]


# --- go-to auto-play repair -------------------------------------------------------------------


def read_log(output):
    output.stop()
    return [json.loads(line) for line in output._log_path.read_text().splitlines()]


def last_execute_record(records, operation="goTo"):
    return next(record for record in reversed(records) if record["kind"] == "execute" and record["operation"] == operation)


def test_goto_semantics_armed_by_default(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)
    output.start()
    assert output.capabilities()["goTo"]["semantics"] == "restart-at-initial-state+autoplay"


def test_goto_fires_zero_advance_when_run_length_is_zero(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)
    output.observe()
    fake = FakeCdp.instances[0]
    fake.auto_play_run_length, fake.auto_play_run_kinds = 0, []
    observed = output.execute("goTo", 2)
    assert fake.keys == ["2", "Enter"]
    assert observed.auto_play_deferred is None
    record = last_execute_record(read_log(output))
    assert (record["autoPlayRunLength"], record["autoPlayRunKinds"], record["autoPlayFired"], record["autoPlayDeferredReason"]) == (0, [], False, None)


def test_goto_fires_one_advance_via_key_when_run_length_positive(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)
    output.observe()
    fake = FakeCdp.instances[0]
    fake.auto_play_run_length, fake.auto_play_run_kinds = 1, ["apple:movie-start"]
    observed = output.execute("goTo", 2)
    assert fake.keys == ["2", "Enter", " "]
    assert observed.auto_play_deferred is None
    record = last_execute_record(read_log(output))
    assert (record["autoPlayRunLength"], record["autoPlayRunKinds"], record["autoPlayFired"], record["autoPlayDeferredReason"]) == (1, ["apple:movie-start"], True, None)


def test_goto_fires_one_advance_via_click_in_click_mode(tmp_path, monkeypatch):
    monkeypatch.setenv(live_host.ADVANCE_ENV, "click")
    output = host(tmp_path, monkeypatch)
    output.start()
    fake = FakeCdp.instances[0]
    fake.auto_play_run_length, fake.auto_play_run_kinds = 2, ["apple:movie-start", "apple:movie-start"]
    observed = output.execute("goTo", 2)
    assert fake.keys == ["2", "Enter"]
    assert fake.clicks == 1
    assert observed.auto_play_deferred is None


def test_goto_fails_closed_when_run_length_is_null(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)
    output.observe()
    fake = FakeCdp.instances[0]
    fake.auto_play_run_length = None
    observed = output.execute("goTo", 2)
    assert fake.keys == ["2", "Enter"]
    assert observed.auto_play_deferred == "Movies idle until next advance"
    record = last_execute_record(read_log(output))
    assert record["autoPlayDeferredReason"] == "runLength null"
    assert record["autoPlayFired"] is False


def test_goto_fails_closed_when_can_advance_is_false(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)
    output.observe()
    fake = FakeCdp.instances[0]
    fake.auto_play_run_length, fake.auto_play_run_kinds = 1, ["apple:movie-start"]
    fake.can_advance = False
    observed = output.execute("goTo", 2)
    assert fake.keys == ["2", "Enter"]
    assert observed.auto_play_deferred == "Movies idle until next advance"
    record = last_execute_record(read_log(output))
    assert record["autoPlayDeferredReason"] == "busy"
    assert record["autoPlayFired"] is False


def test_goto_fails_closed_on_settle_timeout(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)
    output.observe()
    fake = FakeCdp.instances[0]
    fake.auto_play_run_length = 1
    fake.busy_on_enter = True  # never settles after the jump
    output.timeout_s = .05
    observed = output.execute("goTo", 2)
    assert observed.auto_play_deferred == "Movies idle until next advance"
    record = last_execute_record(read_log(output))
    assert record["autoPlayDeferredReason"] == "settle timeout"
    assert record["autoPlayFired"] is False


def test_goto_fails_closed_when_state_changes_before_fire(tmp_path, monkeypatch):
    # R1: the run length is read at settle and fired a moment later; re-read the
    # snapshot immediately before firing and abort if anything moved underneath us.
    output = host(tmp_path, monkeypatch)
    output.observe()  # lazily starts the transport (one _wait_settled call, in start())
    fake = FakeCdp.instances[0]
    fake.auto_play_run_length, fake.auto_play_run_kinds = 1, ["apple:movie-start"]
    real_wait_settled = live_host.LiveOutputHost._wait_settled
    calls = {"n": 0}

    def wait_settled(self, *args, **kwargs):
        result = real_wait_settled(self, *args, **kwargs)
        calls["n"] += 1
        if calls["n"] == 1:  # the goTo's own settle (installed after setup's start()), right before the R1 re-read
            fake.revision += 1
        return result

    monkeypatch.setattr(live_host.LiveOutputHost, "_wait_settled", wait_settled)
    observed = output.execute("goTo", 2)
    assert fake.keys == ["2", "Enter"]
    assert observed.auto_play_deferred == "Movies idle until next advance"
    record = last_execute_record(read_log(output))
    assert record["autoPlayDeferredReason"] == "changed before fire"
    assert record["autoPlayFired"] is False


def test_goto_reports_delivery_unknown_when_input_dispatch_is_rejected(tmp_path, monkeypatch):
    # Once key/click delivery is attempted, its outcome may be unknown -- it must
    # never be reported as safely idle (that could invite a second, consuming press).
    output = host(tmp_path, monkeypatch)
    output.observe()
    fake = FakeCdp.instances[0]
    fake.auto_play_run_length, fake.auto_play_run_kinds = 1, ["apple:movie-start"]
    fake.space_rejects = True
    observed = output.execute("goTo", 2)
    assert fake.keys == ["2", "Enter"]  # the rejected space is never recorded
    assert observed.auto_play_deferred is None
    assert observed.go_to_target_reached is True  # the jump itself already settled
    record = last_execute_record(read_log(output))
    assert record["autoPlayDeferredReason"].startswith("delivery unknown:")
    assert record["autoPlayFired"] is None


def test_goto_reports_delivery_unknown_when_ack_times_out_after_dispatch(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)
    output.observe()
    fake = FakeCdp.instances[0]
    fake.auto_play_run_length, fake.auto_play_run_kinds = 1, ["apple:movie-start"]
    real_key = fake.key

    def key(key_value, code, vk):
        if key_value == " ":
            return  # dispatched, but the player never acknowledges it
        real_key(key_value, code, vk)

    fake.key = key
    output.timeout_s = .05
    observed = output.execute("goTo", 2)
    assert observed.auto_play_deferred is None
    assert observed.go_to_target_reached is True
    record = last_execute_record(read_log(output))
    assert record["autoPlayDeferredReason"].startswith("delivery unknown:")
    assert record["autoPlayFired"] is None


def test_goto_reports_fired_when_settle_times_out_after_ack(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)
    output.observe()
    fake = FakeCdp.instances[0]
    fake.auto_play_run_length, fake.auto_play_run_kinds = 1, ["apple:movie-start"]
    real_key = fake.key

    def key(key_value, code, vk):
        real_key(key_value, code, vk)
        if key_value == " ":
            fake.busy = True  # acked, but the fired advance never settles

    fake.key = key
    output.timeout_s = .05
    observed = output.execute("goTo", 2)
    assert fake.keys == ["2", "Enter", " "]
    assert observed.auto_play_deferred is None
    assert observed.go_to_target_reached is True
    record = last_execute_record(read_log(output))
    assert record["autoPlayFired"] is True
    assert record["autoPlayDeferredReason"].startswith("settle unconfirmed:")


def _raise_on_nth_obedlive_read(monkeypatch, n, exc):
    real_evaluate = FakeCdp.evaluate
    calls = {"n": 0}

    def evaluate(self, expression):
        if "__obedLive" in expression:
            calls["n"] += 1
            if calls["n"] == n:
                raise exc
        return real_evaluate(self, expression)

    monkeypatch.setattr(FakeCdp, "evaluate", evaluate)


def test_goto_fails_closed_on_non_timeout_error_at_initial_settle(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)
    output.observe()
    fake = FakeCdp.instances[0]
    fake.auto_play_run_length, fake.auto_play_run_kinds = 1, ["apple:movie-start"]
    _raise_on_nth_obedlive_read(monkeypatch, 3, live_host.LiveHostError("Program browser CDP connection failed."))
    observed = output.execute("goTo", 2)
    assert observed.auto_play_deferred == "Movies idle until next advance"
    assert observed.go_to_target_reached is False  # the initial settle itself never succeeded
    record = last_execute_record(read_log(output))
    assert record["autoPlayDeferredReason"].startswith("pre-dispatch error:")
    assert record["autoPlayFired"] is False


def test_goto_fails_closed_on_non_timeout_error_at_r1_reread(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)
    output.observe()
    fake = FakeCdp.instances[0]
    fake.auto_play_run_length, fake.auto_play_run_kinds = 1, ["apple:movie-start"]
    _raise_on_nth_obedlive_read(monkeypatch, 4, live_host.LiveHostError("Program browser CDP connection failed."))
    observed = output.execute("goTo", 2)
    assert fake.keys == ["2", "Enter"]  # never fired: the failure precedes dispatch
    assert observed.auto_play_deferred == "Movies idle until next advance"
    assert observed.go_to_target_reached is True  # the jump itself already settled
    record = last_execute_record(read_log(output))
    assert record["autoPlayDeferredReason"].startswith("pre-dispatch error:")
    assert record["autoPlayFired"] is False


def test_goto_reports_delivery_unknown_on_error_at_input_delivery(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)
    output.observe()
    fake = FakeCdp.instances[0]
    fake.auto_play_run_length, fake.auto_play_run_kinds = 1, ["apple:movie-start"]
    real_evaluate = FakeCdp.evaluate
    focus_calls = {"n": 0}

    def evaluate(self, expression):
        if "window.focus()" in expression:
            focus_calls["n"] += 1
            if focus_calls["n"] == 2:  # the repair's own focus call, not goTo's
                raise live_host.LiveHostError("Program browser CDP connection failed.")
        return real_evaluate(self, expression)

    monkeypatch.setattr(FakeCdp, "evaluate", evaluate)
    observed = output.execute("goTo", 2)
    assert fake.keys == ["2", "Enter"]  # the space was never reached
    assert observed.auto_play_deferred is None
    assert observed.go_to_target_reached is True
    record = last_execute_record(read_log(output))
    assert record["autoPlayDeferredReason"].startswith("delivery unknown:")
    assert record["autoPlayFired"] is None


def test_goto_reports_fired_on_non_timeout_error_at_post_fire_observation(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)
    output.observe()
    fake = FakeCdp.instances[0]
    fake.auto_play_run_length, fake.auto_play_run_kinds = 1, ["apple:movie-start"]
    _raise_on_nth_obedlive_read(monkeypatch, 6, live_host.LiveHostError("Program browser CDP connection failed."))
    observed = output.execute("goTo", 2)
    assert fake.keys == ["2", "Enter", " "]
    assert observed.auto_play_deferred is None
    assert observed.go_to_target_reached is True
    record = last_execute_record(read_log(output))
    assert record["autoPlayFired"] is True
    assert record["autoPlayDeferredReason"].startswith("settle unconfirmed:")


# --- slide-number overlay swallows a click (attach/click mode) -------------------------------


def test_goto_repair_waits_for_slide_number_overlay_before_clicking(tmp_path, monkeypatch):
    monkeypatch.setenv(live_host.ADVANCE_ENV, "click")
    output = host(tmp_path, monkeypatch)
    output.start()
    fake = FakeCdp.instances[0]
    fake.auto_play_run_length, fake.auto_play_run_kinds = 1, ["apple:movie-start"]
    fake.slide_number_showing = True
    output.timeout_s = 1.0
    real_evaluate = FakeCdp.evaluate
    calls = {"n": 0}

    def evaluate(self, expression):
        if "__obedLive" in expression:
            calls["n"] += 1
            if calls["n"] < 6:
                assert self.clicks == 0  # never clicks while the overlay is up
            if calls["n"] == 6:
                self.slide_number_showing = False
        return real_evaluate(self, expression)

    monkeypatch.setattr(FakeCdp, "evaluate", evaluate)
    observed = output.execute("goTo", 2)
    assert fake.clicks == 1
    assert fake.keys == ["2", "Enter"]  # no space key in click mode
    assert observed.auto_play_deferred is None
    assert calls["n"] >= 6


def test_goto_repair_fails_closed_when_overlay_never_hides(tmp_path, monkeypatch):
    monkeypatch.setenv(live_host.ADVANCE_ENV, "click")
    output = host(tmp_path, monkeypatch)
    output.start()
    fake = FakeCdp.instances[0]
    fake.auto_play_run_length, fake.auto_play_run_kinds = 1, ["apple:movie-start"]
    fake.slide_number_showing = True
    output.timeout_s = .1
    observed = output.execute("goTo", 2)
    assert fake.clicks == 0
    assert fake.keys == ["2", "Enter"]
    assert observed.auto_play_deferred == "Movies idle until next advance"
    assert observed.go_to_target_reached is True  # the jump itself already settled
    record = last_execute_record(read_log(output))
    assert record["autoPlayDeferredReason"].startswith("pre-dispatch error:")
    assert record["autoPlayFired"] is False


def test_advance_click_mode_waits_for_overlay_then_clicks(tmp_path, monkeypatch):
    monkeypatch.setenv(live_host.ADVANCE_ENV, "click")
    output = host(tmp_path, monkeypatch)
    output.start()
    fake = FakeCdp.instances[0]
    fake.slide_number_showing = True
    output.timeout_s = 1.0
    real_evaluate = FakeCdp.evaluate
    calls = {"n": 0}

    def evaluate(self, expression):
        if "__obedLive" in expression:
            calls["n"] += 1
            if calls["n"] < 3:
                assert self.clicks == 0
            if calls["n"] == 3:
                self.slide_number_showing = False
        return real_evaluate(self, expression)

    monkeypatch.setattr(FakeCdp, "evaluate", evaluate)
    output.execute("advance")
    assert fake.clicks == 1
    assert calls["n"] >= 3


def test_advance_click_mode_rejected_when_overlay_never_hides(tmp_path, monkeypatch):
    monkeypatch.setenv(live_host.ADVANCE_ENV, "click")
    output = host(tmp_path, monkeypatch)
    output.start()
    fake = FakeCdp.instances[0]
    fake.slide_number_showing = True
    output.timeout_s = .1
    with pytest.raises(live_host.PlayerCommandRejected, match="slide-number overlay"):
        output.execute("advance")
    assert fake.clicks == 0


def test_advance_key_mode_ignores_the_slide_number_overlay(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)
    output.observe()
    fake = FakeCdp.instances[0]
    fake.slide_number_showing = True
    output.execute("advance")
    assert fake.keys == [" "]
    assert fake.clicks == 0


def test_goto_repair_key_mode_ignores_the_slide_number_overlay(tmp_path, monkeypatch):
    output = host(tmp_path, monkeypatch)
    output.observe()
    fake = FakeCdp.instances[0]
    fake.auto_play_run_length, fake.auto_play_run_kinds = 1, ["apple:movie-start"]
    fake.slide_number_showing = True
    observed = output.execute("goTo", 2)
    assert fake.keys == ["2", "Enter", " "]
    assert observed.auto_play_deferred is None


def test_goto_env_off_disables_the_repair_entirely(tmp_path, monkeypatch):
    monkeypatch.setenv(live_host.GOTO_AUTOPLAY_ENV, "off")
    output = host(tmp_path, monkeypatch)
    output.start()
    assert output.capabilities()["goTo"]["semantics"] == "restart-at-initial-state"
    fake = FakeCdp.instances[0]
    fake.auto_play_run_length, fake.auto_play_run_kinds = 1, ["apple:movie-start"]
    observed = output.execute("goTo", 2)
    assert fake.keys == ["2", "Enter"]
    assert observed.auto_play_deferred is None
    records = read_log(output)
    record = last_execute_record(records)
    assert "autoPlayFired" not in record
    started = next(r for r in records if r["kind"] == "start")
    assert started["goToAutoplayMode"] == "off"


def test_cdp_sockets_accept_messages_larger_than_the_websockets_default():
    # websockets caps an incoming message at 1 MiB by default. A 2560x1440 PNG from
    # Page.captureScreenshot is 0.4-0.7 MB and ~33% larger as base64, so a busy frame
    # crossed the cap, the library closed the socket (1009) and the host reported
    # "Program browser CDP connection failed." about one session in four at that size.
    import inspect

    source = inspect.getsource(live_host.ChromeCdp)
    assert live_host._CDP_MAX_MESSAGE_BYTES >= 32 * 1024 * 1024
    assert source.count("max_size=_CDP_MAX_MESSAGE_BYTES") == 2


# --- G4: the GL-replay host flag (G3+G4 plan section 4, PR #214) ---------------------------
# Every test below pins `live_host.CONTINUITY_VERSION` (4 or 5) so it never depends on the
# core's own version bump landing first.


def _gl_entry() -> dict[str, Any]:
    """A `glReplay` boundary that passes `validate_gl_replay_entry`, sized to the one-movie export."""
    return {
        "atScene": 2, "action": "glReplay", "movieKey": "movie1", "fallback": "retire",
        "slotSizes": [[1920, 1080], [100, 100]],
        "slotRects": [[0.0, 0.0, 1920.0, 1080.0], [150.0, 150.0, 100.0, 100.0]],
        "opacityOverrides": [],
        "instanceId": "movie.mov#0",
        "instanceRect": {"x": 150.0, "y": 150.0, "w": 100.0, "h": 100.0},
        "movieSlot": 1,
    }


def _fake_runtime(*, gl: bool) -> dict[str, Any]:
    first = _gl_entry() if gl else {"atScene": 2, "action": "retire", "movieKey": "movie1"}
    return {
        "movies": {"movie1": {"assetKeys": ["movie.mov"], "footprint": {"x": 150, "y": 150, "w": 100, "h": 100}}},
        "boundaries": [first],
    }


class _FakePlan:
    refusals: list[dict[str, Any]] = []

    def __init__(self, runtime):
        self._runtime = runtime

    def to_runtime(self):
        return copy.deepcopy(self._runtime)


def fake_plan_pair(monkeypatch, *, on: Any = None, off: Any = None) -> list[dict[str, Any]]:
    """Replace `derive_plan` with a spy answering the flag-on runtime `on` only when called with
    `gl_replay=True`, and the flag-off runtime `off` otherwise. An `Unsupported` answer is
    returned as the plan itself. Returns the recorded keyword arguments of every call."""
    on = _fake_runtime(gl=True) if on is None else on
    off = _fake_runtime(gl=False) if off is None else off
    calls: list[dict[str, Any]] = []

    def derive(_root, _slides, **kwargs):
        calls.append(dict(kwargs))
        answer = on if kwargs.get("gl_replay") else off
        return answer if isinstance(answer, live_host.Unsupported) else _FakePlan(answer)

    monkeypatch.setattr(live_host, "derive_plan", derive)
    return calls


def spy_real_derive_plan(monkeypatch) -> list[dict[str, Any]]:
    real = live_host.derive_plan
    calls: list[dict[str, Any]] = []

    def derive(*args, **kwargs):
        calls.append(dict(kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(live_host, "derive_plan", derive)
    return calls


def forbid_gl_module(monkeypatch) -> None:
    """Force the off path: off never builds, validates or injects the GL module; only its
    version and sha are reported. Any call into the builder or its validator is a failure."""
    def boom(*_a, **_k):
        raise AssertionError("the GL-replay module must not be touched on the off path")

    monkeypatch.setattr(live_host, "gl_replay_script", boom)
    monkeypatch.setattr(live_gl_replay_js, "gl_replay_script", boom)
    monkeypatch.setattr(live_gl_replay_js, "validate_gl_replay_entry", boom)


def served_html(output: live_host.LiveOutputHost, tmp_path: Path) -> str:
    page = tmp_path / "served"
    page.mkdir(exist_ok=True)
    (page / "index.html").write_text(
        '<html><head></head><body><div id="stage"></div><script src="assets/player/main.js"></script></body></html>'
    )
    server = live_host._AssetServer(page, b"", resolver=resolver_for(page), continuity_script=output._server.continuity_script)
    return server._program_html().decode()


def ready(monkeypatch) -> None:
    monkeypatch.setattr(FakeCdp, "evaluate", continuity_ready_evaluate(FakeCdp.evaluate, [stage_geometry(1920, 1080, 0, 0, 1920, 1080)]))


@pytest.mark.parametrize("version", [4, 5])
@pytest.mark.parametrize("how", ["unset", "ctor-off", "env-off", "env-blank", "env-off-padded", "continuity-off"])
def test_gl_replay_off_never_touches_the_module_and_serves_todays_recipe(tmp_path, monkeypatch, how, version):
    """Off is the default. It must derive exactly as today (no `gl_replay` kwarg) and inject exactly
    `_continuity_scripts(plan, canvas)`. Off never builds, validates or injects the GL module; only
    its version and sha are reported -- forced by making the builder and its validator raise.
    Continuity off turns GL off even when asked."""
    monkeypatch.setattr(live_host, "CONTINUITY_VERSION", version)
    gl_replay = {"ctor-off": "off", "continuity-off": "auto"}.get(how)
    output = host_with_continuity(tmp_path, monkeypatch, gl_replay=gl_replay)
    if how.startswith("env-"):
        monkeypatch.setenv("OBED_LIVE_GL_REPLAY", {"env-off": "off", "env-blank": "", "env-off-padded": "  OFF "}[how])
    if how == "continuity-off":
        monkeypatch.setenv(live_host.CONTINUITY_ENV, "off")
    forbid_gl_module(monkeypatch)
    calls = spy_real_derive_plan(monkeypatch)
    ready(monkeypatch)
    output.observe()

    assert all("gl_replay" not in kwargs for kwargs in calls)
    info = output.output["continuity"]["glReplay"]
    assert info["mode"] == "off"
    assert "reason" not in info
    if how == "continuity-off":
        assert calls == []
        assert output._server.continuity_script == ""
    else:
        assert len(calls) == 1
        assert output._continuity_mode == "qualified"
        assert output._server.continuity_script == live_host._continuity_scripts(output._continuity_runtime_plan, output._canvas)
        assert all(b["action"] != "glReplay" for b in output._continuity_runtime_plan["boundaries"])
    assert 'id="obed-gl-replay"' not in served_html(output, tmp_path)


def test_gl_replay_auto_injects_the_flag_on_plan_and_the_module_after_the_core(tmp_path, monkeypatch):
    monkeypatch.setattr(live_host, "CONTINUITY_VERSION", 5)
    output = host_with_continuity(tmp_path, monkeypatch, gl_replay="auto")
    calls = fake_plan_pair(monkeypatch)
    ready(monkeypatch)
    output.observe()

    assert calls == [{"resolver": output.resolver, "gl_replay": True}]
    runtime = output._continuity_runtime_plan
    assert runtime == _fake_runtime(gl=True)
    tag = live_gl_replay_js.gl_replay_script(runtime)
    assert tag.startswith('<script id="obed-gl-replay">')
    assert output._server.continuity_script == live_host._continuity_scripts(runtime, output._canvas) + tag
    assert output._continuity_mode == "qualified"
    assert output.output["continuity"]["glReplay"] == {
        "mode": "injected",
        "version": live_gl_replay_js.GL_REPLAY_VERSION,
        "sha256": live_gl_replay_js.js_sha256(),
    }

    document = served_html(output, tmp_path)
    body = document[document.index("<body"):]
    assert (
        body.index('id="obed-output-black"')
        < body.index('id="obed-continuity-plan"')
        < body.index('id="obed-continuity-core"')
        < body.index('id="obed-gl-replay"')
        < body.index('id="obed-output-fit"')
        < body.index('id="stage"')
        < body.index("assets/player/main.js")
    )
    assert document.count('id="obed-gl-replay"') == 1


def test_gl_replay_auto_with_a_v4_core_serves_the_off_plan(tmp_path, monkeypatch):
    """A core older than v5 has no G3 zone: a glReplay plan must never reach it (G1 decision B)."""
    monkeypatch.setattr(live_host, "CONTINUITY_VERSION", 4)
    output = host_with_continuity(tmp_path, monkeypatch, gl_replay="auto")
    calls = fake_plan_pair(monkeypatch)
    ready(monkeypatch)
    output.observe()

    assert all("gl_replay" not in kwargs for kwargs in calls)
    assert output._continuity_runtime_plan == _fake_runtime(gl=False)
    assert output._server.continuity_script == live_host._continuity_scripts(_fake_runtime(gl=False), output._canvas)
    assert 'id="obed-gl-replay"' not in output._server.continuity_script
    info = output.output["continuity"]["glReplay"]
    assert info["mode"] == "unavailable"
    assert info["reason"]


def test_gl_replay_auto_without_an_entry_is_not_applicable_and_byte_identical_to_off(tmp_path, monkeypatch):
    """The real derivation of the one-movie export has no glReplay boundary."""
    monkeypatch.setattr(live_host, "CONTINUITY_VERSION", 5)
    off = host_with_continuity(tmp_path / "off", monkeypatch, gl_replay="off")
    ready(monkeypatch)
    off.observe()

    auto = host_with_continuity(tmp_path / "auto", monkeypatch, gl_replay="auto")
    calls = spy_real_derive_plan(monkeypatch)
    auto.observe()

    assert calls[0].get("gl_replay") is True
    assert "gl_replay" not in calls[-1]
    assert auto._continuity_runtime_plan == off._continuity_runtime_plan
    assert auto._server.continuity_script == off._server.continuity_script
    assert served_html(auto, tmp_path / "auto") == served_html(off, tmp_path / "off")
    info = auto.output["continuity"]["glReplay"]
    assert info["mode"] == "notApplicable"
    assert "reason" not in info


def test_gl_replay_auto_with_an_empty_module_script_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(live_host, "CONTINUITY_VERSION", 5)
    output = host_with_continuity(tmp_path, monkeypatch, gl_replay="auto")
    calls = fake_plan_pair(monkeypatch)
    monkeypatch.setattr(live_host, "gl_replay_script", lambda _runtime: "")
    ready(monkeypatch)
    output.observe()

    assert calls[0].get("gl_replay") is True
    assert "gl_replay" not in calls[-1]
    assert output._continuity_runtime_plan == _fake_runtime(gl=False)
    assert output._server.continuity_script == live_host._continuity_scripts(_fake_runtime(gl=False), output._canvas)
    info = output.output["continuity"]["glReplay"]
    assert info["mode"] == "unavailable"
    assert info["reason"]


def test_gl_replay_auto_with_a_real_invalid_entry_is_unavailable(tmp_path, monkeypatch):
    """The real builder refuses an entry its validator rejects; the host falls back to off."""
    monkeypatch.setattr(live_host, "CONTINUITY_VERSION", 5)
    bad = _fake_runtime(gl=True)
    bad["boundaries"][0]["fallback"] = "pin"
    output = host_with_continuity(tmp_path, monkeypatch, gl_replay="auto")
    fake_plan_pair(monkeypatch, on=bad)
    ready(monkeypatch)
    output.observe()

    assert output._continuity_runtime_plan == _fake_runtime(gl=False)
    assert 'id="obed-gl-replay"' not in output._server.continuity_script
    assert output.output["continuity"]["glReplay"]["mode"] == "unavailable"


@pytest.mark.parametrize("how", ["derive", "to_runtime"])
def test_gl_replay_auto_with_an_unsupported_flag_on_plan_falls_back_to_off(tmp_path, monkeypatch, how):
    monkeypatch.setattr(live_host, "CONTINUITY_VERSION", 5)
    output = host_with_continuity(tmp_path, monkeypatch, gl_replay="auto")
    if how == "derive":
        calls = fake_plan_pair(monkeypatch, on=live_host.Unsupported("unreadable override table"))
    else:
        calls = fake_plan_pair(monkeypatch)
        real_to_runtime = _FakePlan.to_runtime

        def to_runtime(self):
            runtime = real_to_runtime(self)
            if runtime["boundaries"][0]["action"] == "glReplay":
                return live_host.Unsupported("unreadable override table")
            return runtime

        monkeypatch.setattr(_FakePlan, "to_runtime", to_runtime)
    ready(monkeypatch)
    output.observe()

    assert [kwargs.get("gl_replay") for kwargs in calls] == [True, None]
    assert output._continuity_mode == "qualified"
    assert output._continuity_runtime_plan == _fake_runtime(gl=False)
    assert 'id="obed-gl-replay"' not in output._server.continuity_script
    info = output.output["continuity"]["glReplay"]
    assert info == {
        "mode": "unavailable", "reason": "unreadable override table",
        "version": live_gl_replay_js.GL_REPLAY_VERSION, "sha256": live_gl_replay_js.js_sha256(),
    }


@pytest.mark.parametrize("bridge", [None, "obs-cdp"])
@pytest.mark.parametrize("source", ["ctor", "env"])
def test_gl_replay_auto_in_attach_mode_is_not_injected(tmp_path, monkeypatch, source, bridge):
    """OD-2 is lifted only for the managed OBS: an external attach (bridge omitted normalises
    to `obs-cdp`) keeps refusing, since the pool keep-warm and stash order are unmeasured there."""
    monkeypatch.setattr(live_host, "CONTINUITY_VERSION", 5)
    monkeypatch.setenv("OBED_EDOM_OUTPUT_ROOT", str(tmp_path / "preview"))
    kwargs = {} if bridge is None else {"bridge": bridge}
    output = host_with_continuity(tmp_path, monkeypatch, attach=True, gl_replay="auto" if source == "ctor" else None, **kwargs)
    if source == "env":
        monkeypatch.setenv(live_host.GL_REPLAY_ENV, "auto")
    calls = fake_plan_pair(monkeypatch)
    forbid_gl_module(monkeypatch)
    ready(monkeypatch)
    output.observe()

    assert calls and all("gl_replay" not in kwargs for kwargs in calls)
    assert output._continuity_runtime_plan == {**_fake_runtime(gl=False), "transparentBackground": True}
    assert 'id="obed-gl-replay"' not in output._server.continuity_script
    assert output.output["bridge"] == "obs-cdp"
    info = output.output["continuity"]["glReplay"]
    assert info["mode"] == "unavailable"
    assert info["reason"] == "attach output not qualified"


def test_gl_replay_auto_is_not_reported_injected_when_the_codec_refuses_continuity(tmp_path, monkeypatch):
    monkeypatch.setattr(live_host, "CONTINUITY_VERSION", 5)
    output = host_with_continuity(tmp_path, monkeypatch, gl_replay="auto", movie_bytes=_movie_bytes(b"apcn"))
    fake_plan_pair(monkeypatch)
    output.observe()

    assert output._continuity_mode == "unsupported"
    assert output._server.continuity_script == ""
    assert output.output["continuity"]["glReplay"] == {
        "mode": "unavailable", "reason": "continuity unsupported",
        "version": live_gl_replay_js.GL_REPLAY_VERSION, "sha256": live_gl_replay_js.js_sha256(),
    }


def test_gl_replay_auto_falls_back_to_off_when_the_flag_on_to_runtime_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(live_host, "CONTINUITY_VERSION", 5)
    output = host_with_continuity(tmp_path, monkeypatch, gl_replay="auto")
    calls = fake_plan_pair(monkeypatch)
    real_to_runtime = _FakePlan.to_runtime

    def to_runtime(self):
        runtime = real_to_runtime(self)
        if runtime["boundaries"][0]["action"] == "glReplay":
            raise ValueError("glReplay translation blew up")
        return runtime

    monkeypatch.setattr(_FakePlan, "to_runtime", to_runtime)
    ready(monkeypatch)
    output.observe()

    assert [kwargs.get("gl_replay") for kwargs in calls] == [True, None]
    assert output._continuity_mode == "qualified"
    assert output._continuity_runtime_plan == _fake_runtime(gl=False)
    assert 'id="obed-gl-replay"' not in output._server.continuity_script
    assert output.output["continuity"]["glReplay"]["mode"] == "unavailable"
    assert output.output["continuity"]["glReplay"]["reason"] == "glReplay translation blew up"


def test_continuity_is_unsupported_not_a_crash_when_to_runtime_raises(tmp_path, monkeypatch):
    output = host_with_continuity(tmp_path, monkeypatch)

    class RaisingPlan:
        def to_runtime(self):
            raise ValueError("cannot translate")

    monkeypatch.setattr(live_host, "derive_plan", lambda *a, **k: RaisingPlan())
    output.observe()
    assert output._continuity_mode == "unsupported"
    assert output.output["continuity"]["reason"] == "cannot translate"
    assert output._server.continuity_script == ""


@pytest.mark.parametrize("managed,ctor,env,expected", [
    (False, None, None, "off"),
    (False, None, " Auto ", "auto"),
    (False, "auto", None, "auto"),
    (False, "off", "auto", "off"),
    (True, None, None, "auto"),
    (True, None, "off", "off"),
    (True, "off", None, "off"),
])
def test_start_log_records_the_requested_gl_replay_preference(tmp_path, monkeypatch, managed, ctor, env, expected):
    """Under continuity off or attach the continuity record cannot show that `auto` was asked for."""
    monkeypatch.setenv("OBED_EDOM_OUTPUT_ROOT", str(tmp_path / "preview"))
    monkeypatch.setenv(live_host.CONTINUITY_ENV, "off")
    kwargs = {"attach": True, "bridge": "obs-managed", "output_rate": 25} if managed else {}
    output = host_with_continuity(tmp_path, monkeypatch, gl_replay=ctor, **kwargs)
    if env is not None:
        monkeypatch.setenv(live_host.GL_REPLAY_ENV, env)
    output.start()
    records = read_log(output)
    assert next(r for r in records if r["kind"] == "start")["glReplayPreference"] == expected
    assert next(r for r in records if r["kind"] == "continuity")["glReplay"]["mode"] == "off"


@pytest.mark.parametrize("managed,ctor,env,expected", [
    (False, None, "auto", "injected"),
    (False, None, " AUTO ", "injected"),
    (False, None, "off", "off"),
    (False, "off", "auto", "off"),
    (False, "auto", "off", "injected"),
    (False, "auto", "bogus", "injected"),
    (True, "off", "auto", "off"),
    (True, "auto", "off", "injected"),
])
def test_gl_replay_constructor_wins_over_the_env(tmp_path, monkeypatch, managed, ctor, env, expected):
    monkeypatch.setattr(live_host, "CONTINUITY_VERSION", 5)
    if managed:
        output = managed_host(tmp_path, monkeypatch, gl_replay=ctor)
    else:
        output = host_with_continuity(tmp_path, monkeypatch, gl_replay=ctor)
    monkeypatch.setenv(live_host.GL_REPLAY_ENV, env)
    fake_plan_pair(monkeypatch)
    ready(monkeypatch)
    output.observe()
    assert output.output["continuity"]["glReplay"]["mode"] == expected


@pytest.mark.parametrize("value", ["on", "Auto", "", None, True])
def test_gl_replay_constructor_rejects_anything_but_auto_or_off(tmp_path, monkeypatch, value):
    monkeypatch.setenv("OBED_EDOM_OUTPUT_ROOT", str(tmp_path / "preview"))
    (tmp_path / "main.js").write_bytes(player_bytes())
    (tmp_path / "header.json").write_text('{"slideWidth":1920,"slideHeight":1080,"showMode":0}')
    monkeypatch.setattr(live_host, "choose_display", lambda *_a, **_k: live_host.OutputDisplay(9, 10, 20, 2560, 1440))
    with pytest.raises(live_host.LiveHostError, match="GL replay must be auto or off."):
        live_host.LiveOutputHost(tmp_path, [], headless=True, transport_factory=FakeCdp, server_factory=FakeServer, resolver=resolver, gl_replay=value)


@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("value", ["on", "1", "true", "auto-ish"])
def test_invalid_gl_replay_env_refuses_before_starting_resources(tmp_path, monkeypatch, value, managed):
    """A mistyped Keyer opt-out (`false`, `0`) refuses loudly rather than silently defaulting to auto."""
    output = managed_host(tmp_path, monkeypatch) if managed else host_with_continuity(tmp_path, monkeypatch)
    monkeypatch.setenv(live_host.GL_REPLAY_ENV, value)
    with pytest.raises(live_host.LiveHostError, match="OBED_LIVE_GL_REPLAY must be off or auto."):
        output.start()
    assert not FakeCdp.instances
    assert output._server is None


def test_gl_replay_env_name_is_the_documented_one():
    assert live_host.GL_REPLAY_ENV == "OBED_LIVE_GL_REPLAY"


def hook_only_player() -> bytes:
    """Today's served bytes: the observation hook alone, nothing else rewritten."""
    return player_bytes().replace(
        live_runtime._ANCHOR,
        b"UC=new Eg," + live_runtime._INSTALL + b",UC.displayManager.showWaitingIndicator()",
    )


def mm_opacity_host(kind, tmp_path, monkeypatch, **kwargs):
    monkeypatch.setenv("OBED_EDOM_OUTPUT_ROOT", str(tmp_path / "preview"))
    if kind == "hdmi":
        return host(tmp_path, monkeypatch, **kwargs)
    if kind == "attach":
        return attach_host(tmp_path, monkeypatch, **kwargs)
    return managed_host(tmp_path, monkeypatch, **kwargs)


def test_mm_opacity_env_name_is_the_documented_one():
    assert live_host.MM_OPACITY_ENV == "OBED_LIVE_MM_OPACITY"


@pytest.mark.parametrize("kind", ["hdmi", "attach", "managed"])
@pytest.mark.parametrize("ctor,env,expected", [
    (None, None, "auto"),
    (None, "", "auto"),
    (None, "off", "off"),
    (None, "  OFF ", "off"),
    (None, " Auto\t", "auto"),
    ("off", None, "off"),
    ("off", "auto", "off"),
    ("auto", "off", "auto"),
    ("auto", "bogus", "auto"),
])
def test_mm_opacity_preference_precedence_on_every_output(tmp_path, monkeypatch, kind, ctor, env, expected):
    """Default `auto` on HDMI, external attach and managed OBS alike; the constructor wins over the env,
    and the env is trimmed and case-insensitive."""
    output = mm_opacity_host(kind, tmp_path, monkeypatch, **({} if ctor is None else {"mm_opacity": ctor}))
    if env is not None:
        monkeypatch.setenv(live_host.MM_OPACITY_ENV, env)
    output.start()
    served = output._server.patched_player
    mode = "on" if expected == "auto" else "off"
    assert output.output["mmOpacity"] == {"mode": mode, "sha256": hashlib.sha256(served).hexdigest()}
    assert next(r for r in read_log(output) if r["kind"] == "start")["mmOpacityPreference"] == expected


@pytest.mark.parametrize("kind", ["hdmi", "attach", "managed"])
@pytest.mark.parametrize("value", ["on", "1", "false", "auto-ish"])
def test_invalid_mm_opacity_env_refuses_before_starting_resources(tmp_path, monkeypatch, kind, value):
    output = mm_opacity_host(kind, tmp_path, monkeypatch)
    monkeypatch.setenv(live_host.MM_OPACITY_ENV, value)
    with pytest.raises(live_host.LiveHostError, match="OBED_LIVE_MM_OPACITY must be off or auto."):
        output.start()
    assert not FakeCdp.instances
    assert output._server is None
    assert output._log_path is None
    assert "mmOpacity" not in output.output


@pytest.mark.parametrize("kind", ["hdmi", "attach", "managed"])
@pytest.mark.parametrize("value", ["on", "", " off ", "AUTO", "true", None, True])
def test_mm_opacity_constructor_rejects_anything_but_auto_or_off(tmp_path, monkeypatch, kind, value):
    with pytest.raises(live_host.LiveHostError, match="Magic Move opacity must be auto or off."):
        mm_opacity_host(kind, tmp_path, monkeypatch, mm_opacity=value)
    assert not FakeCdp.instances


def test_mm_opacity_off_serves_todays_hook_only_bytes(tmp_path, monkeypatch):
    output = mm_opacity_host("hdmi", tmp_path, monkeypatch, mm_opacity="off")
    output.start()
    assert output._server.patched_player == hook_only_player()
    assert output._server.patched_player == live_runtime.patch_player(player_bytes(), mm_opacity=False)
    assert output.output["mmOpacity"] == {"mode": "off", "sha256": hashlib.sha256(hook_only_player()).hexdigest()}


def test_mm_opacity_auto_serves_the_patched_player(tmp_path, monkeypatch):
    output = mm_opacity_host("hdmi", tmp_path, monkeypatch)
    output.start()
    served = output._server.patched_player
    assert served == live_runtime.patch_player(player_bytes(), mm_opacity=True)
    assert served != hook_only_player()
    for before, after in live_runtime._MM_OPACITY_REPLACEMENTS:
        assert served.count(after) == 1
        assert before not in served
    assert output.output["mmOpacity"] == {"mode": "on", "sha256": hashlib.sha256(served).hexdigest()}


def test_mm_opacity_is_reported_only_once_the_player_is_patched(tmp_path, monkeypatch):
    output = mm_opacity_host("hdmi", tmp_path, monkeypatch)
    assert "mmOpacity" not in output.output
    output.start()
    assert output.output["mmOpacity"]["mode"] == "on"
    assert output.observe().output["mmOpacity"] == output.output["mmOpacity"]


def test_mm_opacity_anchor_missing_refuses_the_session(tmp_path, monkeypatch):
    output = mm_opacity_host("hdmi", tmp_path, monkeypatch)
    broken = b"before;" + live_runtime._ANCHOR + b";after"
    (tmp_path / "main.js").write_bytes(broken)
    monkeypatch.setattr(live_runtime, "PLAYER_SHA256", hashlib.sha256(broken).hexdigest())
    with pytest.raises(live_host.LiveHostError, match="Magic Move opacity anchor"):
        output.start()
    assert not FakeCdp.instances
    assert output._server is None


def test_gl_replay_output_shape_before_and_after_start(tmp_path, monkeypatch):
    monkeypatch.setattr(live_host, "CONTINUITY_VERSION", 5)
    monkeypatch.setenv("OBED_EDOM_OUTPUT_ROOT", str(tmp_path / "preview"))
    output = host_with_continuity(tmp_path, monkeypatch, gl_replay="auto")
    before = output.output["continuity"]["glReplay"]
    assert before == {"mode": "off", "version": live_gl_replay_js.GL_REPLAY_VERSION, "sha256": live_gl_replay_js.js_sha256()}
    fake_plan_pair(monkeypatch)
    ready(monkeypatch)
    output.start()
    info = output.output["continuity"]["glReplay"]
    assert set(info) <= {"mode", "reason", "version", "sha256"}
    assert info["mode"] == "injected"
    assert isinstance(info["sha256"], str) and len(info["sha256"]) == 64
    records = read_log(output)
    record = next(r for r in records if r["kind"] == "continuity")
    assert record["glReplay"] == info


def attach_host(tmp_path, monkeypatch, **kwargs):
    monkeypatch.setenv("OBED_EDOM_OUTPUT_ROOT", str(tmp_path / "preview"))
    (tmp_path / "main.js").write_bytes(player_bytes())
    (tmp_path / "header.json").write_text('{"slideWidth":1920,"slideHeight":1080,"showMode":0}')
    monkeypatch.setattr(live_runtime, "PLAYER_SHA256", hashlib.sha256(player_bytes()).hexdigest())
    monkeypatch.delenv(live_host.MM_OPACITY_ENV, raising=False)
    FakeCdp.instances.clear()
    return live_host.LiveOutputHost(
        tmp_path, [], attach_endpoint="http://127.0.0.1:9222", transport_factory=FakeCdp, server_factory=FakeServer, resolver=resolver, **kwargs,
    )


def test_managed_bridge_is_reported_in_attach_output(tmp_path, monkeypatch):
    result = attach_host(tmp_path, monkeypatch, bridge="obs-managed").output
    assert result["bridge"] == "obs-managed"
    assert result["transport"] == "fill-key"
    assert result["alpha"] is True


def test_default_attach_output_has_obs_cdp_bridge_and_no_rate_warnings_key(tmp_path, monkeypatch):
    result = attach_host(tmp_path, monkeypatch).output
    assert result["bridge"] == "obs-cdp"
    assert "rateWarnings" not in result


def test_screen_mode_output_has_no_rate_warnings_key(tmp_path, monkeypatch):
    output = host_with_continuity(tmp_path, monkeypatch)
    output._codec_report = [{"asset": "movie.mov", "codec": "avc1", "family": "h264", "files": 1, "fps": 25.0}]
    assert "rateWarnings" not in output.output
    assert "bridge" not in output.output


@pytest.mark.parametrize(
    ("fps", "rate", "warns"),
    [
        (30.0, 30, False),
        (29.978, 30, False),
        (29.97, 30, False),
        (30.05, 30, False),
        (30.07, 30, True),
        (29.93, 30, True),
        (25.0, 30, True),
        (30.0, 25, True),
        (25.0, 25, False),
        (None, 30, False),
    ],
)
def test_rate_warnings_use_a_relative_two_tenths_percent_tolerance(tmp_path, monkeypatch, fps, rate, warns):
    output = attach_host(tmp_path, monkeypatch, bridge="obs-managed", output_rate=rate)
    output._codec_report = [{"asset": "clip.mov", "codec": "avc1", "family": "h264", "files": 1, "fps": fps}]
    assert bool(output.output["rateWarnings"]) is warns


@pytest.mark.parametrize(
    ("fps", "rate", "shown"),
    [(29.97, 25, "29.97"), (25.0, 30, "25"), (23.976, 30, "23.976"), (50.0, 25, "50")],
)
def test_rate_warning_wording(tmp_path, monkeypatch, fps, rate, shown):
    output = attach_host(tmp_path, monkeypatch, bridge="obs-managed", output_rate=rate)
    output._codec_report = [
        {"asset": "clip.mov", "codec": "avc1", "family": "h264", "files": 1, "fps": fps},
        {"asset": "unknown.mov", "codec": None, "family": "other", "files": 1, "fps": None},
    ]
    assert output.output["rateWarnings"] == [
        f"clip.mov is {shown} fps but the output is {rate} fps, so it will judder slightly. Re-export it at {rate} fps for smooth motion."
    ]


def test_rate_warnings_empty_list_when_every_movie_matches(tmp_path, monkeypatch):
    output = attach_host(tmp_path, monkeypatch, bridge="obs-managed", output_rate=30)
    assert output.output["rateWarnings"] == []


def managed_host(tmp_path, monkeypatch, **kwargs):
    monkeypatch.setenv("OBED_EDOM_OUTPUT_ROOT", str(tmp_path / "preview"))
    kwargs.setdefault("output_rate", 25)
    return host_with_continuity(tmp_path, monkeypatch, attach=True, bridge="obs-managed", **kwargs)


def _injected_info() -> dict[str, Any]:
    return {"mode": "injected", "version": live_gl_replay_js.GL_REPLAY_VERSION, "sha256": live_gl_replay_js.js_sha256()}


def test_gl_replay_auto_injects_under_the_managed_bridge(tmp_path, monkeypatch):
    """OD-2 is lifted for the managed OBS only: the flag-on plan and the module are served
    exactly as on HDMI, with the attach-mode transparent background merged into the runtime."""
    monkeypatch.setattr(live_host, "CONTINUITY_VERSION", 5)
    output = managed_host(tmp_path, monkeypatch, gl_replay="auto", output_rate=30)
    calls = fake_plan_pair(monkeypatch)
    ready(monkeypatch)
    output.observe()

    assert calls == [{"resolver": output.resolver, "gl_replay": True}]
    runtime = output._continuity_runtime_plan
    assert runtime == {**_fake_runtime(gl=True), "transparentBackground": True}
    tag = live_gl_replay_js.gl_replay_script(runtime)
    assert tag.startswith('<script id="obed-gl-replay">')
    assert output._server.continuity_script == live_host._continuity_scripts(runtime, output._canvas) + tag
    script = output._server.continuity_script
    assert script.index('id="obed-continuity-core"') < script.index('id="obed-gl-replay"')
    assert output._continuity_mode == "qualified"
    result = output.output
    assert result["bridge"] == "obs-managed"
    assert result["continuity"]["glReplay"] == _injected_info()


@pytest.mark.parametrize("env", [None, "", "auto", " AUTO "])
def test_gl_replay_defaults_to_auto_under_the_managed_bridge(tmp_path, monkeypatch, env):
    """Keyer passes no `gl_replay` kwarg; the managed host's own default is `auto`."""
    monkeypatch.setattr(live_host, "CONTINUITY_VERSION", 5)
    output = managed_host(tmp_path, monkeypatch)
    if env is not None:
        monkeypatch.setenv(live_host.GL_REPLAY_ENV, env)
    calls = fake_plan_pair(monkeypatch)
    ready(monkeypatch)
    output.start()

    assert calls == [{"resolver": output.resolver, "gl_replay": True}]
    assert output.output["continuity"]["glReplay"] == _injected_info()
    assert next(r for r in read_log(output) if r["kind"] == "start")["glReplayPreference"] == "auto"


@pytest.mark.parametrize("rate", [25, 30, None])
def test_gl_replay_managed_default_is_auto_at_every_output_rate(tmp_path, monkeypatch, rate):
    """Owner 2026-09-25: the binary-counter re-measurement showed 30 as clean as 25, so the managed default
    does not depend on the output rate."""
    monkeypatch.setattr(live_host, "CONTINUITY_VERSION", 5)
    output = managed_host(tmp_path, monkeypatch, output_rate=rate)
    fake_plan_pair(monkeypatch)
    ready(monkeypatch)
    output.start()

    assert output.output["continuity"]["glReplay"] == _injected_info()
    assert next(r for r in read_log(output) if r["kind"] == "start")["glReplayPreference"] == "auto"


@pytest.mark.parametrize("host", ["managed-default", "hdmi-auto"])
def test_gl_replay_reports_unavailable_when_the_stage_gate_fails(tmp_path, monkeypatch, host):
    """OQ-4: the page stage gate disables the core, so an injected module can never arm;
    the report must say so exactly as the HEVC path does, on either output."""
    monkeypatch.setattr(live_host, "CONTINUITY_VERSION", 5)
    if host == "managed-default":
        output = managed_host(tmp_path, monkeypatch)
    else:
        monkeypatch.setenv("OBED_EDOM_OUTPUT_ROOT", str(tmp_path / "preview"))
        output = host_with_continuity(tmp_path, monkeypatch, gl_replay="auto")
    output.timeout_s = .05
    fake_plan_pair(monkeypatch)
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
    output.start()

    assert disable_calls
    assert output._continuity_mode == "unsupported"
    assert output.output["continuity"]["reason"] == "stage is not the authored size"
    expected = {
        "mode": "unavailable", "reason": "continuity unsupported",
        "version": live_gl_replay_js.GL_REPLAY_VERSION, "sha256": live_gl_replay_js.js_sha256(),
    }
    assert output.output["continuity"]["glReplay"] == expected
    assert next(r for r in read_log(output) if r["kind"] == "continuity")["glReplay"] == expected


@pytest.mark.parametrize("env", ["off", " Off "])
def test_gl_replay_env_off_wins_over_the_managed_default(tmp_path, monkeypatch, env):
    """The Keyer opt-out: no `gl_replay` kwarg from the caller, so the env still decides."""
    monkeypatch.setattr(live_host, "CONTINUITY_VERSION", 5)
    output = managed_host(tmp_path, monkeypatch)
    monkeypatch.setenv(live_host.GL_REPLAY_ENV, env)
    calls = fake_plan_pair(monkeypatch)
    forbid_gl_module(monkeypatch)
    ready(monkeypatch)
    output.observe()

    assert calls and all("gl_replay" not in kwargs for kwargs in calls)
    assert output._continuity_mode == "qualified"
    assert 'id="obed-gl-replay"' not in output._server.continuity_script
    assert 'id="obed-gl-replay"' not in served_html(output, tmp_path)
    assert output.output["continuity"]["glReplay"]["mode"] == "off"


@pytest.mark.parametrize("host", ["hdmi", "external-attach", "hdmi-managed-bridge"])
def test_gl_replay_default_stays_off_outside_the_managed_bridge(tmp_path, monkeypatch, host):
    """The managed default needs both the attach endpoint and the managed bridge: HDMI and an
    external attach stay opt-in, and `bridge="obs-managed"` without attach cannot turn it on."""
    monkeypatch.setattr(live_host, "CONTINUITY_VERSION", 5)
    monkeypatch.setenv("OBED_EDOM_OUTPUT_ROOT", str(tmp_path / "preview"))
    kwargs = {
        "hdmi": {},
        "external-attach": {"attach": True},
        "hdmi-managed-bridge": {"bridge": "obs-managed"},
    }[host]
    output = host_with_continuity(tmp_path, monkeypatch, **kwargs)
    calls = fake_plan_pair(monkeypatch)
    forbid_gl_module(monkeypatch)
    ready(monkeypatch)
    output.start()

    assert calls and all("gl_replay" not in kwargs for kwargs in calls)
    assert 'id="obed-gl-replay"' not in output._server.continuity_script
    info = output.output["continuity"]["glReplay"]
    assert info["mode"] == "off"
    assert "reason" not in info
    assert next(r for r in read_log(output) if r["kind"] == "start")["glReplayPreference"] == "off"


@pytest.mark.parametrize("how", ["ctor", "env"])
def test_gl_replay_managed_default_is_off_when_continuity_is_off(tmp_path, monkeypatch, how):
    monkeypatch.setattr(live_host, "CONTINUITY_VERSION", 5)
    output = managed_host(tmp_path, monkeypatch, **({"continuity": "off"} if how == "ctor" else {}))
    if how == "env":
        monkeypatch.setenv(live_host.CONTINUITY_ENV, "off")
    calls = fake_plan_pair(monkeypatch)
    forbid_gl_module(monkeypatch)
    output.observe()

    assert calls == []
    assert output._continuity_mode == "off"
    assert output._server.continuity_script == ""
    assert output.output["continuity"]["glReplay"]["mode"] == "off"


def test_gl_replay_under_the_managed_bridge_reports_continuity_unsupported_for_hevc(tmp_path, monkeypatch):
    monkeypatch.setattr(live_host, "CONTINUITY_VERSION", 5)
    output = managed_host(tmp_path, monkeypatch, movie_bytes=_movie_bytes(b"hvc1"))
    fake_plan_pair(monkeypatch)
    output.observe()

    assert output._continuity_mode == "unsupported"
    assert output._server.continuity_script == ""
    assert output.output["continuity"]["glReplay"] == {
        "mode": "unavailable", "reason": "continuity unsupported",
        "version": live_gl_replay_js.GL_REPLAY_VERSION, "sha256": live_gl_replay_js.js_sha256(),
    }


@pytest.mark.parametrize(("host_kwargs", "with_fps"), [({}, False), ({"output_rate": 30}, True)])
def test_codec_report_probes_fps_only_when_an_output_rate_is_set(tmp_path, monkeypatch, host_kwargs, with_fps):
    seen = []
    monkeypatch.setattr(live_host, "codec_report", lambda *_a, **kwargs: seen.append(kwargs) or [])
    output = host_with_continuity(tmp_path, monkeypatch, attach=True, **host_kwargs)
    output._resolve_codecs()
    assert seen and seen[0]["with_fps"] is with_fps


REAL_PLAYER_ROOT = Path(__file__).resolve().parents[1] / "output" / "p2-recovery" / "html-adversarial" / "html-player"
REAL_SLIDES = [
    {"playerIndex": index, "originalOrdinal": index + 1, "exportedUuid": uuid, "skipped": False}
    for index, uuid in enumerate([
        "08C861A1-CB39-4832-B189-6DF95B7F3396", "0C652BEB-F445-48CF-BFD0-4194C6B7A438",
        "D4D95253-4C37-40CF-A4A4-62D8DE24EF2A", "7A851F4D-4648-4545-A491-58838A7CD843",
    ])
]


@pytest.mark.skipif(not REAL_PLAYER_ROOT.is_dir(), reason="real player export not available")
@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        (25, [
            "untitled.mov is 30 fps but the output is 25 fps, so it will judder slightly. Re-export it at 25 fps for smooth motion.",
            "vid-20250608-wa0125.mp4 is 29.978 fps but the output is 25 fps, so it will judder slightly. Re-export it at 25 fps for smooth motion.",
        ]),
        # 29.978 is within 0.2 % of 30, so the phone clip does not warn either.
        (30, []),
    ],
)
def test_real_export_rate_warnings_come_from_probed_movie_fps(tmp_path, monkeypatch, rate, expected):
    monkeypatch.setenv("OBED_EDOM_OUTPUT_ROOT", str(tmp_path / "preview"))
    output = live_host.LiveOutputHost(
        REAL_PLAYER_ROOT, REAL_SLIDES, attach_endpoint="http://127.0.0.1:9222", transport_factory=FakeCdp,
        server_factory=FakeServer, resolver=lambda root, relative: root / relative, bridge="obs-managed", output_rate=rate,
    )
    output._codec_report, output._codec_warnings = output._resolve_codecs()
    assert {entry["asset"]: entry["fps"] for entry in output._codec_report} == {"untitled.mov": 30.0, "vid-20250608-wa0125.mp4": 29.978}
    assert output.output["rateWarnings"] == expected
