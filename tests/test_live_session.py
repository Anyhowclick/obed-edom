from __future__ import annotations

from threading import Event, Lock, Thread

from obed_edom.live_session import LiveSessionService, PlayerCommandRejected, PlayerObservation


def _identity():
    return {
        "sourceDigest": "source",
        "playerDigest": "player",
        "runtimeRevision": 1,
        "slides": [{"originalOrdinal": 1, "exportedUuid": "one"}],
        "output": {},
    }


class SlowExecuteAdapter:
    def __init__(self):
        self.observed = PlayerObservation(original_slide=1, scene_id="one", revision=1)
        self.execute_started = Event()
        self.execute_release = Event()
        self.stopped = False
        self.stop_calls = 0

    def capabilities(self):
        return {
            "advance": {"supported": True}, "goTo": {"supported": True},
            "hide": {"supported": True}, "show": {"supported": True},
        }

    def observe(self):
        return self.observed

    def execute(self, operation, slide=None):
        self.execute_started.set()
        self.execute_release.wait()
        return PlayerObservation(original_slide=2, scene_id="two", revision=2)

    def stop(self):
        self.stop_calls += 1
        self.stopped = True


class BlockingStopAdapter:
    def __init__(self):
        self.observed = PlayerObservation(original_slide=1, scene_id="one", revision=1)
        self.stop_started = Event()
        self.stop_release = Event()
        self.stop_calls = 0

    def capabilities(self):
        return {
            "advance": {"supported": True}, "goTo": {"supported": True},
            "hide": {"supported": True}, "show": {"supported": True},
        }

    def observe(self):
        return self.observed

    def execute(self, operation, slide=None):
        return self.observed

    def stop(self):
        self.stop_calls += 1
        self.stop_started.set()
        self.stop_release.wait()


class ObserveBlockingAdapter:
    def __init__(self):
        self.observed = PlayerObservation(original_slide=1, scene_id="one", revision=1)
        self.observe_started = Event()
        self.observe_release = Event()
        self.active = 0
        self.overlap_detected = False
        self.guard = Lock()
        self.should_block = False

    def _enter(self):
        with self.guard:
            self.active += 1
            if self.active > 1:
                self.overlap_detected = True

    def _exit(self):
        with self.guard:
            self.active -= 1

    def capabilities(self):
        return {
            "advance": {"supported": True}, "goTo": {"supported": True},
            "hide": {"supported": True}, "show": {"supported": True},
        }

    def observe(self):
        self._enter()
        try:
            if self.should_block:
                self.observe_started.set()
                self.observe_release.wait()
            return self.observed
        finally:
            self._exit()

    def execute(self, operation, slide=None):
        self._enter()
        try:
            return PlayerObservation(original_slide=2, scene_id="two", revision=2)
        finally:
            self._exit()

    def stop(self):
        pass


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
        self.observe_wait: Event | None = None
        self.observe_release: Event | None = None
        self.stopped_during_execute = False
        self.observe_calls = 0
        self.stop_wait: Event | None = None
        self.stop_release: Event | None = None
        self.auto_play_deferred: str | None = None
        self.goto_final_slide: int | None = None
        self.goto_target_reached = False
        self.goto_busy = False

    def capabilities(self):
        return {
            "advance": {"supported": True},
            "goTo": {"supported": True},
            "hide": {"supported": True},
            "show": {"supported": True},
        }

    def observe(self):
        self.observe_calls += 1
        if self.observe_fail:
            raise RuntimeError("observation lost")
        if self.observe_wait:
            self.observe_wait.set()
            assert self.observe_release
            self.observe_release.wait()
        return self.observed

    def execute(self, operation, slide=None):
        self.calls.append((operation, slide))
        if self.wait:
            self.wait.set()
            assert self.release
            self.release.wait()
        if self.stopped_during_execute:
            raise RuntimeError("player stopped")
        if self.fail:
            raise RuntimeError("player disconnected")
        if self.reject:
            raise PlayerCommandRejected("Player is busy.")
        if operation == "advance":
            self.observed = PlayerObservation(original_slide=2, scene_id="two", revision=2, busy=True)
        elif operation == "goTo":
            final_slide = self.goto_final_slide if self.goto_final_slide is not None else slide
            self.observed = PlayerObservation(
                original_slide=final_slide, scene_id=f"slide-{final_slide}", revision=2,
                auto_play_deferred=self.auto_play_deferred,
                go_to_target_reached=self.goto_target_reached,
                busy=self.goto_busy,
            )
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
        if self.stop_wait:
            self.stop_wait.set()
            assert self.stop_release
            self.stop_release.wait()
        self.stopped = True
        self.stopped_during_execute = True
        if self.release:
            self.release.set()


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


def test_loading_snapshot_keeps_the_fill_key_transport_of_keyer_output(tmp_path):
    loading = []
    service = LiveSessionService(claim=lambda *args: None, release=lambda *args: None)
    adapter = Adapter()
    observe = adapter.observe

    def observe_while_loading():
        loading.append(dict(service._session.state["output"]))
        return observe()

    adapter.observe = observe_while_loading
    identity = {**_identity(), "output": {"transport": "fill-key", "alpha": True, "audio": False, "bridge": "obs-managed",
                                          "width": 1920, "height": 1080}}
    state = service.start(adapter, export_key="preview-a", export_root=tmp_path, identity=identity)

    assert loading[0]["transport"] == "fill-key"
    assert loading[0]["alpha"] is True
    assert loading[0]["bridge"] == "obs-managed"
    assert state["output"]["transport"] == "fill-key"


def test_screen_loading_snapshot_output_matches_the_previous_shape_and_key_order(tmp_path):
    import json

    from obed_edom.live_host import OutputDisplay

    screen = {**OutputDisplay(42, 1920, 0, 2560, 1440, False).as_output(), "width": 2560, "height": 1440,
              "canvas": {"width": 1920, "height": 1080}}
    for identity_output in (screen, {"width": 1920, "height": 1080}, {}):
        loading = []
        service = LiveSessionService(claim=lambda *args: None, release=lambda *args: None)
        adapter = Adapter()
        observe = adapter.observe

        def observe_while_loading(observe=observe, loading=loading, service=service):
            loading.append(json.dumps(service._session.state["output"]))
            return observe()

        adapter.observe = observe_while_loading
        service.start(adapter, export_key="preview-a", export_root=tmp_path,
                      identity={**_identity(), "output": identity_output})
        previous = {**identity_output, "transport": "hdmi", "alpha": False, "audio": False}
        assert loading[0] == json.dumps(previous)


def test_command_stays_accepted_until_observation_settles(tmp_path):
    service, adapter, state, _claims, _releases = make_service(tmp_path)

    accepted = service.command(state["sessionId"], "advance-1", "advance")

    assert accepted["outcome"] == "accepted"
    assert accepted["state"]["status"] == "busy"
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
    try:
        assert adapter.wait.wait(1)

        assert service.command(state["sessionId"], "a", "advance")["outcome"] == "accepted"
        rejected = service.command(state["sessionId"], "b", "goTo", 2)
        assert rejected["outcome"] == "rejected"
        assert rejected["reason"] == "A player command is already in progress."
    finally:
        adapter.release.set()
        thread.join(5)
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


def test_stop_succeeds_while_a_command_is_in_flight(tmp_path):
    service, adapter, state, _claims, releases = make_service(tmp_path)
    adapter.wait = Event()
    adapter.release = Event()
    responses = []
    thread = Thread(target=lambda: responses.append(service.command(state["sessionId"], "a", "advance")))
    thread.start()
    try:
        assert adapter.wait.wait(1)

        stopped = service.command(state["sessionId"], "stop", "stop")
        assert stopped["outcome"] == "completed"
        assert service.state()["status"] == "stopped"
    finally:
        adapter.release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert responses[0]["outcome"] == "rejected"
    assert responses[0]["reason"] == "Navigation was superseded by stop."
    assert service.state()["status"] == "stopped"
    assert releases == [("preview-a", state["sessionId"])]


def test_state_poll_blocked_in_observe_does_not_block_stop(tmp_path):
    service, adapter, state, _claims, releases = make_service(tmp_path)
    adapter.observe_wait = Event()
    adapter.observe_release = Event()
    poll_thread = Thread(target=service.state)
    poll_thread.start()
    try:
        assert adapter.observe_wait.wait(1)
        stop_results = []
        stop_thread = Thread(target=lambda: stop_results.append(service.command(state["sessionId"], "stop", "stop")))
        stop_thread.start()
        stop_thread.join(1)
        assert not stop_thread.is_alive()
        assert stop_results[0]["outcome"] == "completed"
        assert releases == [("preview-a", state["sessionId"])]
    finally:
        adapter.observe_release.set()
        poll_thread.join(5)
    assert not poll_thread.is_alive()


def test_stale_poll_observation_is_discarded_after_stop(tmp_path):
    service, adapter, state, _claims, _releases = make_service(tmp_path)
    adapter.observe_wait = Event()
    adapter.observe_release = Event()
    poll_thread = Thread(target=service.state)
    poll_thread.start()
    try:
        assert adapter.observe_wait.wait(1)

        service.command(state["sessionId"], "stop", "stop")
        adapter.observed = PlayerObservation(original_slide=99, scene_id="stale", revision=99)
    finally:
        adapter.observe_release.set()
        poll_thread.join(5)
    assert not poll_thread.is_alive()

    final = service.state()
    assert final["status"] == "stopped"
    assert final["originalSlide"] != 99


def test_request_cache_is_bounded(tmp_path):
    service, _adapter, state, _claims, _releases = make_service(tmp_path)
    for index in range(300):
        service.command(state["sessionId"], f"go-{index}", "goTo", 1)
    assert len(service._session.requests) <= service._MAX_REQUESTS


def test_replay_of_completed_request_returns_current_state(tmp_path):
    service, _adapter, state, _claims, _releases = make_service(tmp_path)
    first = service.command(state["sessionId"], "go", "goTo", 2)
    replay = service.command(state["sessionId"], "go", "goTo", 2)
    assert replay["outcome"] == first["outcome"]
    assert replay["state"] == service.state()


def test_failed_command_stops_owned_resources_but_keeps_export_claim(tmp_path):
    service, adapter, state, _claims, releases = make_service(tmp_path)
    adapter.fail = True

    failed = service.command(state["sessionId"], "failure", "advance")

    assert failed["outcome"] == "rejected"
    assert failed["state"]["status"] == "error"
    assert adapter.stopped
    assert releases == []


def test_interrupted_command_does_not_corrupt_the_next_session(tmp_path):
    service = LiveSessionService(claim=lambda *_args: None, release=lambda *_args: None)
    slow = SlowExecuteAdapter()
    state_a = service.start(slow, export_key="preview-a", export_root=tmp_path, identity=_identity())

    responses = []
    thread = Thread(target=lambda: responses.append(service.command(state_a["sessionId"], "a", "advance")))
    thread.start()
    try:
        assert slow.execute_started.wait(1)

        stopped = service.command(state_a["sessionId"], "stop", "stop")
        assert stopped["outcome"] == "completed"

        adapter_b = Adapter()
        state_b = service.start(adapter_b, export_key="preview-b", export_root=tmp_path, identity=_identity())
        b_advance = service.command(state_b["sessionId"], "b-advance", "advance")
        assert b_advance["outcome"] == "accepted"
        assert b_advance["state"]["status"] == "busy"
    finally:
        slow.execute_release.set()
    thread.join(2)
    assert not thread.is_alive()

    assert responses[0]["outcome"] == "rejected"
    assert responses[0]["reason"] == "Navigation was superseded by stop."
    assert slow.stop_calls == 1
    assert not adapter_b.stopped

    final = service.state()
    assert final["sessionId"] == state_b["sessionId"]
    assert final["status"] == "busy"


def test_concurrent_stop_requests_are_serialized(tmp_path):
    service = LiveSessionService(claim=lambda *_args: None, release=lambda *_args: None)
    adapter = BlockingStopAdapter()
    state = service.start(adapter, export_key="preview-a", export_root=tmp_path, identity=_identity())

    responses = {}
    thread1 = Thread(target=lambda: responses.__setitem__("first", service.command(state["sessionId"], "stop-1", "stop")))
    thread1.start()
    try:
        assert adapter.stop_started.wait(1)

        other = service.command(state["sessionId"], "stop-2", "stop")
        assert other["outcome"] == "rejected"
        assert other["reason"] == "Stop is already in progress."

        replay = service.command(state["sessionId"], "stop-1", "stop")
        assert replay["outcome"] == "accepted"
    finally:
        adapter.stop_release.set()
        thread1.join(5)
    assert not thread1.is_alive()
    assert responses["first"]["outcome"] == "completed"
    assert adapter.stop_calls == 1

    third = service.command(state["sessionId"], "stop-3", "stop")
    assert third["outcome"] == "rejected"
    assert third["reason"] == "Session is stopped."


def test_command_waits_for_blocked_poll_instead_of_overlapping_and_stop_stays_prompt(tmp_path):
    service = LiveSessionService(claim=lambda *_args: None, release=lambda *_args: None)
    adapter = ObserveBlockingAdapter()
    state = service.start(adapter, export_key="preview-a", export_root=tmp_path, identity=_identity())
    adapter.should_block = True

    poll_thread = Thread(target=service.state)
    poll_thread.start()
    command_thread = None
    stop_thread = None
    try:
        assert adapter.observe_started.wait(1)

        command_results = []
        command_thread = Thread(target=lambda: command_results.append(service.command(state["sessionId"], "a", "advance")))
        command_thread.start()

        stop_results = []
        stop_thread = Thread(target=lambda: stop_results.append(service.command(state["sessionId"], "stop", "stop")))
        stop_thread.start()
        stop_thread.join(5)
        assert not stop_thread.is_alive()
        assert stop_results[0]["outcome"] == "completed"
    finally:
        adapter.observe_release.set()
        poll_thread.join(5)
        if command_thread is not None:
            command_thread.join(5)
    assert not poll_thread.is_alive()
    assert command_thread is not None and not command_thread.is_alive()
    assert not adapter.overlap_detected


def test_start_failure_keeps_disabled_capabilities_available_to_the_ui(tmp_path):
    adapter = Adapter()
    adapter.observe_fail = True
    service = LiveSessionService(claim=lambda *_args: None, release=lambda *_args: None)

    state = service.start(adapter, export_key="preview-a", export_root=tmp_path, identity={})

    assert state["status"] == "error"
    assert state["capabilities"]["advance"]["supported"] is False
    assert state["capabilities"]["stop"] == {"supported": True}


def test_stop_before_command_enters_pending_map_matches_replay(tmp_path):
    service, adapter, state, _claims, _releases = make_service(tmp_path)
    adapter.observe_wait = Event()
    adapter.observe_release = Event()
    responses = []
    thread = Thread(target=lambda: responses.append(service.command(state["sessionId"], "a", "advance")))
    thread.start()
    try:
        assert adapter.observe_wait.wait(1)

        stopped = service.command(state["sessionId"], "stop", "stop")
        assert stopped["outcome"] == "completed"
    finally:
        adapter.observe_release.set()
        thread.join(5)
    assert not thread.is_alive()

    assert responses[0]["outcome"] == "rejected"
    assert responses[0]["reason"] == "Navigation was superseded by stop."

    replay = service.command(state["sessionId"], "a", "advance")
    assert replay["outcome"] == "rejected"
    assert replay["reason"] == "Navigation was superseded by stop."


def test_session_b_command_completes_while_session_a_is_still_blocked(tmp_path):
    service = LiveSessionService(claim=lambda *_args: None, release=lambda *_args: None)
    slow = SlowExecuteAdapter()
    state_a = service.start(slow, export_key="preview-a", export_root=tmp_path, identity=_identity())

    responses = []
    thread = Thread(target=lambda: responses.append(service.command(state_a["sessionId"], "a", "advance")))
    thread.start()
    assert slow.execute_started.wait(1)

    stopped = service.command(state_a["sessionId"], "stop", "stop")
    assert stopped["outcome"] == "completed"

    adapter_b = Adapter()
    state_b = service.start(adapter_b, export_key="preview-b", export_root=tmp_path, identity=_identity())

    b_result = service.command(state_b["sessionId"], "b", "advance")
    assert b_result["outcome"] == "accepted"
    assert b_result["state"]["status"] == "busy"
    assert adapter_b.calls == [("advance", None)]
    assert not slow.execute_release.is_set()

    slow.execute_release.set()
    thread.join(2)
    assert not thread.is_alive()
    assert responses[0]["outcome"] == "rejected"
    assert responses[0]["reason"] == "Navigation was superseded by stop."


class CountingBlockingAdapter:
    def __init__(self):
        self.observed = PlayerObservation(original_slide=1, scene_id="one", revision=1)
        self.observe_calls = 0
        self.should_block = False
        self.observe_wait = Event()
        self.observe_release = Event()

    def capabilities(self):
        return {
            "advance": {"supported": True}, "goTo": {"supported": True},
            "hide": {"supported": True}, "show": {"supported": True},
        }

    def observe(self):
        self.observe_calls += 1
        if self.should_block:
            self.observe_wait.set()
            self.observe_release.wait()
        return self.observed

    def execute(self, operation, slide=None):
        return self.observed

    def stop(self):
        pass


def test_stale_poll_from_stopped_session_does_not_block_new_session_polling(tmp_path):
    service = LiveSessionService(claim=lambda *_args: None, release=lambda *_args: None)
    adapter_a = CountingBlockingAdapter()
    state_a = service.start(adapter_a, export_key="preview-a", export_root=tmp_path, identity=_identity())
    adapter_a.should_block = True

    poll_a = Thread(target=service.state)
    poll_a.start()
    poll_b = None
    adapter_b = None
    try:
        assert adapter_a.observe_wait.wait(1)

        service.command(state_a["sessionId"], "stop", "stop")

        adapter_b = CountingBlockingAdapter()
        state_b = service.start(adapter_b, export_key="preview-b", export_root=tmp_path, identity=_identity())
        adapter_b.should_block = True
        adapter_b.observe_calls = 0

        poll_b = Thread(target=service.state)
        poll_b.start()
        assert adapter_b.observe_wait.wait(1)

        second_holder = {}
        adapter_a.observe_release.set()
        poll_a.join(5)
        assert not poll_a.is_alive()

        second_holder["state"] = service.state()
    finally:
        if adapter_b is not None:
            adapter_b.observe_release.set()
        if poll_b is not None:
            poll_b.join(5)
    assert not poll_a.is_alive()
    assert poll_b is not None and not poll_b.is_alive()
    second = second_holder["state"]
    assert second["sessionId"] == state_b["sessionId"]
    assert adapter_b.observe_calls == 1


def test_stop_gates_commands_and_polling(tmp_path):
    service, adapter, state, _claims, _releases = make_service(tmp_path)
    adapter.stop_wait = Event()
    adapter.stop_release = Event()
    stop_results = []
    stop_thread = Thread(target=lambda: stop_results.append(service.command(state["sessionId"], "stop", "stop")))
    stop_thread.start()
    try:
        assert adapter.stop_wait.wait(1)

        rejected = service.command(state["sessionId"], "advance-new", "advance")
        assert rejected["outcome"] == "rejected"
        assert rejected["reason"] == "Stop is in progress."
        assert adapter.calls == []

        before = adapter.observe_calls
        service.state()
        assert adapter.observe_calls == before
    finally:
        adapter.stop_release.set()
        stop_thread.join(5)
    assert not stop_thread.is_alive()
    assert stop_results[0]["outcome"] == "completed"
    assert service.state()["status"] == "stopped"


def test_visibility_command_rejects_on_wrong_observed_visibility_and_bounds_pending(tmp_path):
    service, adapter, state, _claims, _releases = make_service(tmp_path)

    def wrong_show(operation, slide=None):
        return PlayerObservation(original_slide=1, scene_id="one", revision=1, output_visible=False)

    adapter.execute = wrong_show

    result = service.command(state["sessionId"], "show-1", "show")
    assert result["outcome"] == "rejected"
    assert result["reason"] == "No observed visibility change."

    replay = service.command(state["sessionId"], "show-1", "show")
    assert replay["outcome"] == result["outcome"]
    assert replay["reason"] == result["reason"]

    for index in range(300):
        service.command(state["sessionId"], f"show-{index}", "show")
    assert len(service._session.requests) <= service._MAX_REQUESTS
    assert service._session.pending_visibility == {}


def test_stop_failure_then_retry_releases_claim_once(tmp_path):
    claims = []
    releases = []
    service = LiveSessionService(
        claim=lambda key, owner, meta: claims.append((key, owner, meta)),
        release=lambda key, owner: releases.append((key, owner)),
    )
    adapter = Adapter()
    calls = {"n": 0}
    original_stop = adapter.stop

    def flaky_stop():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("stop boom")
        original_stop()

    adapter.stop = flaky_stop
    state = service.start(adapter, export_key="preview-a", export_root=tmp_path, identity=_identity())

    first = service.command(state["sessionId"], "stop-1", "stop")
    assert first["outcome"] == "rejected"
    assert first["reason"].startswith("Stop failed")
    assert first["state"]["status"] != "stopped"
    assert releases == []
    assert service._session.stopping is False

    second = service.command(state["sessionId"], "stop-2", "stop")
    assert second["outcome"] == "completed"
    assert second["state"]["status"] == "stopped"
    assert releases == [("preview-a", state["sessionId"])]


def test_eviction_never_removes_the_request_being_admitted(tmp_path):
    service, _adapter, state, _claims, _releases = make_service(tmp_path)
    service._MAX_REQUESTS = 2
    session = service._session
    for index in range(3):
        request_id = f"pending-{index}"
        session.requests[request_id] = (("advance", None), {"requestId": request_id, "outcome": "accepted"})
        session.pending_navigation[request_id] = ("advance", None, None, None)

    result = service.command(state["sessionId"], "new", "goTo", 1)

    assert "new" in session.requests
    assert result["requestId"] == "new"


class BlockingExecuteAndStopAdapter(BlockingStopAdapter):
    def __init__(self):
        super().__init__()
        self.execute_started = Event()
        self.execute_release = Event()

    def execute(self, operation, slide=None):
        self.execute_started.set()
        self.execute_release.wait()
        return PlayerObservation(original_slide=2, scene_id="two", revision=2)


def test_command_finishing_while_stop_is_in_progress_is_superseded(tmp_path):
    # Codex round 4: Stop is admitted while an advance is inside adapter.execute();
    # the advance returns BEFORE Stop commits "stopped". It must not apply its
    # observation or answer completed, and a replay must agree with what it was told.
    released = []
    service = LiveSessionService(claim=lambda *_args: None, release=lambda *args: released.append(args))
    adapter = BlockingExecuteAndStopAdapter()
    state = service.start(adapter, export_key="preview", export_root=tmp_path, identity=_identity())
    session_id = state["sessionId"]
    advance, stop = [], []
    advancing = Thread(target=lambda: advance.append(service.command(session_id, "advance-1", "advance")))
    stopping = Thread(target=lambda: stop.append(service.command(session_id, "stop-1", "stop")))
    advancing.start()
    try:
        assert adapter.execute_started.wait(2)
        stopping.start()
        assert adapter.stop_started.wait(2)
        adapter.execute_release.set()
        advancing.join(5)
        assert not advancing.is_alive()
        assert advance[0]["outcome"] == "rejected"
        assert advance[0]["reason"] == "Navigation was superseded by stop."
        assert advance[0]["state"]["originalSlide"] == 1
        assert service.command(session_id, "advance-1", "advance")["outcome"] == "rejected"
    finally:
        adapter.execute_release.set()
        adapter.stop_release.set()
    stopping.join(5)
    assert not stopping.is_alive()
    assert stop[0]["outcome"] == "completed"
    assert stop[0]["state"]["status"] == "stopped"
    assert stop[0]["state"]["originalSlide"] == 1
    assert len(released) == 1
    replay = service.command(session_id, "advance-1", "advance")
    assert (replay["outcome"], replay["reason"]) == ("rejected", "Navigation was superseded by stop.")


def test_goto_stays_busy_and_rejects_operator_command_while_in_flight(tmp_path):
    service, adapter, state, _claims, _releases = make_service(tmp_path)
    adapter.wait = Event()
    adapter.release = Event()
    responses = []
    thread = Thread(target=lambda: responses.append(service.command(state["sessionId"], "g", "goTo", 2)))
    thread.start()
    try:
        assert adapter.wait.wait(1)
        assert service.state()["status"] == "busy"
        rejected = service.command(state["sessionId"], "a", "advance")
        assert rejected["outcome"] == "rejected"
        assert rejected["reason"] == "A player command is already in progress."
    finally:
        adapter.release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert responses[0]["outcome"] == "completed"
    assert responses[0]["state"]["status"] == "ready"


def test_auto_play_deferred_is_sticky_set_by_goto_and_cleared_by_advance(tmp_path):
    service, adapter, state, _claims, _releases = make_service(tmp_path)
    assert state["autoPlayDeferred"] is None

    adapter.auto_play_deferred = "Movies idle until next advance"
    deferred = service.command(state["sessionId"], "go-1", "goTo", 2)
    assert deferred["state"]["autoPlayDeferred"] == "Movies idle until next advance"

    adapter.observed = PlayerObservation(original_slide=2, scene_id="slide-2", revision=2)
    polled = service.state()
    assert polled["autoPlayDeferred"] == "Movies idle until next advance"

    adapter.auto_play_deferred = None
    cleared_by_goto = service.command(state["sessionId"], "go-2", "goTo", 1)
    assert cleared_by_goto["state"]["autoPlayDeferred"] is None

    adapter.auto_play_deferred = "Movies idle until next advance"
    service.command(state["sessionId"], "go-3", "goTo", 2)
    assert service.state()["autoPlayDeferred"] == "Movies idle until next advance"
    advanced = service.command(state["sessionId"], "adv-1", "advance")
    assert advanced["state"]["autoPlayDeferred"] is None


def test_goto_completes_when_the_automatic_run_settles_on_a_later_slide(tmp_path):
    service, adapter, state, _claims, _releases = make_service(tmp_path)
    adapter.goto_final_slide = 3
    adapter.goto_target_reached = True

    result = service.command(state["sessionId"], "go-cross", "goTo", 2)

    assert result["outcome"] == "completed"
    assert result["state"]["originalSlide"] == 3


def test_goto_busy_with_target_reached_completes_immediately_and_a_later_poll_cannot_reject_it(tmp_path):
    service, adapter, state, _claims, _releases = make_service(tmp_path)
    adapter.goto_final_slide = 3
    adapter.goto_target_reached = True
    adapter.goto_busy = True

    result = service.command(state["sessionId"], "go-cross-busy", "goTo", 2)

    assert result["outcome"] == "completed"
    assert result["state"]["status"] == "busy"
    assert result["state"]["originalSlide"] == 3

    # A later, plain poll (no marker -- the automatic run finishing on its own) must not
    # re-litigate a request that already resolved; there is nothing left pending to reject.
    adapter.observed = PlayerObservation(original_slide=3, scene_id="slide-3", revision=2, busy=False)
    polled = service.state()
    assert polled["status"] == "ready"
    assert polled["originalSlide"] == 3
    replay = service.command(state["sessionId"], "go-cross-busy", "goTo", 2)
    assert replay["outcome"] == "completed"
