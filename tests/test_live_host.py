from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from obed_edom import html_preview, live_host, live_runtime


class FakeCdp:
    instances: list["FakeCdp"] = []

    def __init__(self, chrome, profile, display, *, headless=False):
        self.chrome, self.profile, self.display, self.headless = chrome, profile, display, headless
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
    def __init__(self, *_): self.stopped = False
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
