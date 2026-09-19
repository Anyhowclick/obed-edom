from __future__ import annotations

from threading import Event, Thread

from obed_edom.live_session import LiveSessionService, PlayerCommandRejected, PlayerObservation


class Adapter:
    def __init__(self):
        self.observed = PlayerObservation(original_slide=1, scene_id="one", revision=1)
        self.calls: list[tuple[str, int | None]] = []
        self.stopped = False
        self.fail = False
        self.observe_fail = False
        self.reject = False
        self.keep_busy_for_visibility = False
        self.wait: Event | None = None
        self.release: Event | None = None

    def capabilities(self):
        return {
            "advance": {"supported": True},
            "goTo": {"supported": True},
            "hide": {"supported": True},
            "show": {"supported": True},
        }

    def observe(self):
        if self.observe_fail:
            raise RuntimeError("observation lost")
        return self.observed

    def execute(self, operation, slide=None):
        self.calls.append((operation, slide))
        if self.wait:
            self.wait.set()
            assert self.release
            self.release.wait(2)
        if self.fail:
            raise RuntimeError("player disconnected")
        if self.reject:
            raise PlayerCommandRejected("Player is busy.")
        if operation == "advance":
            self.observed = PlayerObservation(original_slide=2, scene_id="two", revision=2, busy=True)
        elif operation == "goTo":
            self.observed = PlayerObservation(original_slide=slide, scene_id=f"slide-{slide}", revision=2)
        elif operation == "hide":
            self.observed = PlayerObservation(
                original_slide=2 if self.keep_busy_for_visibility else 1,
                scene_id="two" if self.keep_busy_for_visibility else "one",
                revision=2 if self.keep_busy_for_visibility else 1,
                busy=self.keep_busy_for_visibility,
                output_visible=False,
            )
        elif operation == "show":
            self.observed = PlayerObservation(original_slide=1, scene_id="one", revision=1, output_visible=True)
        return self.observed

    def stop(self):
        self.stopped = True


def make_service(tmp_path):
    claims = []
    releases = []
    service = LiveSessionService(
        claim=lambda key, owner, meta: claims.append((key, owner, meta)),
        release=lambda key, owner: releases.append((key, owner)),
    )
    adapter = Adapter()
    state = service.start(
        adapter,
        export_key="preview-a",
        export_root=tmp_path,
        identity={
            "sourceDigest": "source-a",
            "playerDigest": "player-a",
            "runtimeRevision": 1,
            "slides": [
                {"originalOrdinal": 1, "exportedUuid": "one"},
                {"originalOrdinal": 2, "exportedUuid": "two"},
                {"originalOrdinal": 3, "exportedUuid": "three", "skipped": True},
            ],
            "output": {"width": 1920, "height": 1080, "displayId": "home-hdmi"},
        },
    )
    return service, adapter, state, claims, releases


def test_observed_viewport_replaces_pre_start_geometry(tmp_path):
    service, adapter, state, _, _ = make_service(tmp_path)
    adapter.observed = PlayerObservation(
        original_slide=1, scene_id="one", revision=1,
        output={"width": 1512, "height": 895, "canvas": {"width": 1920, "height": 1080}},
    )
    updated = service.state()
    assert updated["output"]["height"] == 895
    assert updated["revision"] > state["revision"]
    updated["output"]["canvas"]["height"] = 1
    assert service.state()["output"]["canvas"]["height"] == 1080


def test_start_claims_asset_and_retains_detected_output(tmp_path):
    _service, _adapter, state, claims, _releases = make_service(tmp_path)

    assert claims == [("preview-a", state["sessionId"], {})]
    assert state["output"] == {
        "width": 1920, "height": 1080, "displayId": "home-hdmi",
        "transport": "hdmi", "alpha": False, "audio": False,
    }
    assert state["capabilities"]["stop"] == {"supported": True}
    assert state["slides"][0]["thumbnailUrl"] == (
        f'/api/live/{state["sessionId"]}/thumbnail/1'
    )
    assert "thumbnailUrl" not in state["slides"][2]


def test_command_stays_accepted_until_observation_settles(tmp_path):
    service, adapter, state, _claims, _releases = make_service(tmp_path)

    accepted = service.command(state["sessionId"], "advance-1", "advance")

    assert accepted["outcome"] == "accepted"
    assert accepted["state"]["originalSlide"] == 1
    assert service.state()["status"] == "busy"
    assert service.command(state["sessionId"], "advance-1", "advance")["outcome"] == "accepted"
    assert adapter.calls == [("advance", None)]

    adapter.observed = PlayerObservation(original_slide=2, scene_id="two", revision=2)
    assert service.state()["status"] == "ready"
    completed = service.command(state["sessionId"], "advance-1", "advance")
    assert completed["outcome"] == "completed"
    assert completed["state"]["originalSlide"] == 2
    assert adapter.calls == [("advance", None)]


def test_inflight_duplicate_executes_once_and_other_navigation_rejects(tmp_path):
    service, adapter, state, _claims, _releases = make_service(tmp_path)
    adapter.wait = Event()
    adapter.release = Event()
    responses = []
    thread = Thread(target=lambda: responses.append(service.command(state["sessionId"], "a", "advance")))
    thread.start()
    assert adapter.wait.wait(1)

    assert service.command(state["sessionId"], "a", "advance")["outcome"] == "accepted"
    rejected = service.command(state["sessionId"], "b", "goTo", 2)
    assert rejected["outcome"] == "rejected"
    assert rejected["reason"] == "A player command is already in progress."

    adapter.release.set()
    thread.join(2)
    assert not thread.is_alive()
    assert adapter.calls == [("advance", None)]
    assert responses[0]["outcome"] == "accepted"


def test_stale_request_and_reused_request_id_are_rejected_without_execution(tmp_path):
    service, adapter, state, _claims, _releases = make_service(tmp_path)

    stale = service.command("live-old", "x", "advance")
    assert stale["outcome"] == "rejected"
    first = service.command(state["sessionId"], "x", "goTo", 2)
    changed = service.command(state["sessionId"], "x", "advance")

    assert first["outcome"] == "completed"
    assert changed["outcome"] == "rejected"
    assert adapter.calls == [("goTo", 2)]


def test_skipped_go_to_and_failed_command_do_not_move_state(tmp_path):
    service, adapter, state, _claims, _releases = make_service(tmp_path)

    unavailable = service.command(state["sessionId"], "skip", "goTo", 3)
    assert unavailable["outcome"] == "rejected"
    assert adapter.calls == []

    adapter.fail = True
    failed = service.command(state["sessionId"], "failure", "advance")
    assert failed["outcome"] == "rejected"
    assert failed["state"]["status"] == "error"
    assert failed["state"]["originalSlide"] == 1


def test_stop_releases_only_the_owned_claim(tmp_path):
    service, adapter, state, claims, releases = make_service(tmp_path)

    stopped = service.command(state["sessionId"], "stop", "stop")

    assert stopped["outcome"] == "completed"
    assert adapter.stopped
    assert releases == [("preview-a", state["sessionId"])]
    assert claims[0][1] == state["sessionId"]
    assert service.command(state["sessionId"], "after-stop", "advance")["outcome"] == "rejected"


def test_hide_completes_during_pending_navigation_and_stop_rejects_navigation(tmp_path):
    service, adapter, state, _claims, _releases = make_service(tmp_path)

    navigation = service.command(state["sessionId"], "advance", "advance")
    assert navigation["outcome"] == "accepted"

    adapter.keep_busy_for_visibility = True
    hidden = service.command(state["sessionId"], "hide", "hide")
    assert hidden["outcome"] == "completed"
    assert hidden["state"]["status"] == "busy"
    assert service.command(state["sessionId"], "advance", "advance")["outcome"] == "accepted"

    service.command(state["sessionId"], "stop", "stop")
    superseded = service.command(state["sessionId"], "advance", "advance")
    assert superseded["outcome"] == "rejected"
    assert superseded["reason"] == "Navigation was superseded by stop."


def test_observation_failure_rejects_every_pending_command(tmp_path):
    service, adapter, state, _claims, _releases = make_service(tmp_path)

    assert service.command(state["sessionId"], "advance", "advance")["outcome"] == "accepted"
    adapter.observe_fail = True
    assert service.state()["status"] == "error"
    rejected = service.command(state["sessionId"], "advance", "advance")
    assert rejected["outcome"] == "rejected"
    assert rejected["reason"] == "Player failed: observation lost"


def test_player_refusal_is_a_command_rejection_not_a_session_failure(tmp_path):
    service, adapter, state, _claims, _releases = make_service(tmp_path)
    adapter.reject = True

    result = service.command(state["sessionId"], "advance", "advance")

    assert result["outcome"] == "rejected"
    assert result["reason"] == "Player is busy."
    assert result["state"]["status"] == "ready"


def test_idle_without_observed_navigation_change_rejects_accepted_navigation(tmp_path):
    service, adapter, state, _claims, _releases = make_service(tmp_path)

    accepted = service.command(state["sessionId"], "advance", "advance")
    assert accepted["outcome"] == "accepted"

    adapter.observed = PlayerObservation(original_slide=1, scene_id="one", revision=1)
    service.state()
    rejected = service.command(state["sessionId"], "advance", "advance")
    assert rejected["outcome"] == "rejected"
    assert rejected["reason"] == "No observed navigation change."


def test_start_failure_keeps_disabled_capabilities_available_to_the_ui(tmp_path):
    adapter = Adapter()
    adapter.observe_fail = True
    service = LiveSessionService(claim=lambda *_args: None, release=lambda *_args: None)

    state = service.start(adapter, export_key="preview-a", export_root=tmp_path, identity={})

    assert state["status"] == "error"
    assert state["capabilities"]["advance"]["supported"] is False
    assert state["capabilities"]["stop"] == {"supported": True}
