"""Authoritative, adapter-independent live playback session."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Protocol
from uuid import uuid4

from .html_preview import claim_export, release_owned_claim


@dataclass(frozen=True)
class PlayerObservation:
    original_slide: int | None = None
    scene_id: str | None = None
    build_index: int | None = None
    revision: int | None = None
    busy: bool = False
    output_visible: bool = False
    output: dict[str, Any] | None = None
    auto_play_deferred: str | None = None
    go_to_target_reached: bool = False


class PlayerCommandRejected(RuntimeError):
    pass


class PlayerAdapter(Protocol):
    def capabilities(self) -> dict[str, dict[str, Any]]: ...
    def observe(self) -> PlayerObservation: ...
    def execute(self, operation: str, slide: int | None = None) -> PlayerObservation: ...
    def stop(self) -> None: ...


@dataclass
class _Session:
    adapter: PlayerAdapter
    state: dict[str, Any]
    adapter_lock: Lock = field(default_factory=Lock)
    inflight: object | None = None
    inflight_request_id: str | None = None
    observing: bool = False
    stopping: bool = False
    requests: dict[str, tuple[tuple[str, int | None], dict[str, Any]]] = field(default_factory=dict)
    pending_navigation: dict[str, tuple[str, int | None, str | None, int | None]] = field(default_factory=dict)
    pending_visibility: dict[str, bool] = field(default_factory=dict)
    player_revision: int | None = None


class LiveSessionService:
    _MAX_REQUESTS = 256

    def __init__(self, *, claim=claim_export, release=release_owned_claim):
        self._lock = RLock()
        self._claim = claim
        self._release = release
        self._session: _Session | None = None

    def start(self, adapter: PlayerAdapter, *, export_key: str, export_root: Path, identity: dict[str, Any]) -> dict[str, Any]:
        """Load an adapter whose registered export root was validated by the caller."""
        with self._lock:
            if self._session and self._session.state["status"] != "stopped":
                raise ValueError("Stop the active session before loading another deck.")
            if not export_root.is_dir():
                raise ValueError("The prepared export root is unavailable.")
            session_id = "live-" + uuid4().hex
            slides = deepcopy(identity.get("slides", []))
            for item in slides:
                ordinal = item.get("originalOrdinal")
                if item.get("skipped") or not item.get("exportedUuid") or not isinstance(ordinal, int):
                    continue
                item["thumbnailUrl"] = f"/api/live/{session_id}/thumbnail/{ordinal}"
            self._claim(export_key, session_id, {})
            state = {
                "sessionId": session_id,
                "revision": 0,
                "status": "loading",
                "sourceDigest": identity.get("sourceDigest"),
                "exportKey": export_key,
                "playerDigest": identity.get("playerDigest"),
                "runtimeRevision": identity.get("runtimeRevision"),
                "originalSlide": None,
                "sceneId": None,
                "buildIndex": None,
                "outputVisible": False,
                "autoPlayDeferred": None,
                "slides": slides,
                "output": {"transport": "hdmi", "alpha": False, **deepcopy(identity.get("output", {})), "audio": False},
                "capabilities": self._disabled_capabilities(),
            }
            session = _Session(adapter=adapter, state=state)
            self._session = session
            try:
                self._observe(session)
            except Exception as exc:
                self._fail(session, exc)
            return deepcopy(session.state)

    @staticmethod
    def _disabled_capabilities() -> dict[str, dict[str, Any]]:
        return {
            operation: {"supported": False, "reason": "Not qualified by the player adapter."}
            for operation in ("advance", "goTo", "hide", "show")
        } | {"stop": {"supported": True}}

    def _apply_capabilities(self, session: _Session, caps: dict[str, dict[str, Any]]) -> None:
        session.state["capabilities"] = {
            operation: deepcopy(caps.get(operation, {"supported": False, "reason": "Not qualified by the player adapter."}))
            for operation in ("advance", "goTo", "hide", "show")
        }
        session.state["capabilities"]["stop"] = {"supported": True}

    def _refresh_capabilities(self, session: _Session) -> None:
        self._apply_capabilities(session, session.adapter.capabilities())

    def _store(self, session: _Session, request_id: str, payload: tuple[str, int | None], outcome: str, reason: str | None = None) -> None:
        value: dict[str, Any] = {"requestId": request_id, "outcome": outcome}
        if reason:
            value["reason"] = reason
        session.requests[request_id] = (payload, value)
        self._evict_requests(session, protect=request_id)

    def _evict_requests(self, session: _Session, protect: str | None = None) -> None:
        protected = set(session.pending_navigation) | set(session.pending_visibility)
        if session.inflight_request_id:
            protected.add(session.inflight_request_id)
        if protect:
            protected.add(protect)
        while len(session.requests) > self._MAX_REQUESTS:
            for candidate in session.requests:
                if candidate not in protected:
                    del session.requests[candidate]
                    break
            else:
                break

    def _reply(self, session: _Session, request_id: str) -> dict[str, Any]:
        _payload, value = session.requests[request_id]
        return {**value, "state": deepcopy(session.state)}

    def _reject_now(self, session: _Session, request_id: str, payload: tuple[str, int | None], reason: str) -> dict[str, Any]:
        self._store(session, request_id, payload, "rejected", reason)
        return self._reply(session, request_id)

    def _simple_reject(self, state: dict[str, Any] | None, request_id: str, reason: str) -> dict[str, Any]:
        return {"requestId": request_id, "outcome": "rejected", "reason": reason, "state": deepcopy(state)}

    def _superseded_reply(self, session: _Session, request_id: str) -> dict[str, Any]:
        reason = "Navigation was superseded by stop."
        cached = session.requests.get(request_id)
        if cached and cached[1]["outcome"] == "accepted":
            session.pending_navigation.pop(request_id, None)
            session.pending_visibility.pop(request_id, None)
            self._store(session, request_id, cached[0], "rejected", reason)
        return {"requestId": request_id, "outcome": "rejected", "reason": reason, "state": deepcopy(session.state)}

    def _still_current(self, session: _Session, token: object) -> bool:
        return bool(self._session is session and session.inflight is token and not session.stopping and session.state["status"] != "stopped")

    def _completed(self, session: _Session, request_id: str) -> None:
        payload, _request = session.requests[request_id]
        self._store(session, request_id, payload, "completed")

    def _reject_pending(self, session: _Session, reason: str) -> None:
        request_ids = set(session.pending_navigation) | set(session.pending_visibility)
        if session.inflight_request_id and session.requests.get(session.inflight_request_id, (None, {}))[1].get("outcome") == "accepted":
            request_ids.add(session.inflight_request_id)
        for request_id in request_ids:
            payload, _request = session.requests[request_id]
            self._store(session, request_id, payload, "rejected", reason)
        session.pending_navigation.clear()
        session.pending_visibility.clear()

    def _apply(self, session: _Session, observed: PlayerObservation, *, executed_operation: str | None = None) -> None:
        state = session.state
        update = {
            "originalSlide": observed.original_slide,
            "sceneId": observed.scene_id,
            "buildIndex": observed.build_index,
            "outputVisible": observed.output_visible,
            "status": "busy" if observed.busy else "ready",
        }
        if observed.output is not None:
            update["output"] = deepcopy(observed.output)
        if executed_operation == "goTo":
            update["autoPlayDeferred"] = observed.auto_play_deferred
        elif executed_operation == "advance":
            update["autoPlayDeferred"] = None
        if any(state.get(key) != value for key, value in update.items()):
            state.update(update)
            state["revision"] += 1
        state.pop("error", None)
        session.player_revision = observed.revision
        for request_id, baseline in tuple(session.pending_navigation.items()):
            operation, target, scene, revision = baseline
            target_reached = operation == "goTo" and observed.go_to_target_reached
            if observed.busy and not target_reached:
                continue
            changed = observed.scene_id != scene or observed.revision != revision
            on_target = target_reached or observed.original_slide == target
            complete = changed if operation == "advance" else on_target and observed.revision != revision
            if complete:
                self._completed(session, request_id)
            else:
                payload, _request = session.requests[request_id]
                self._store(session, request_id, payload, "rejected", "No observed navigation change.")
            session.pending_navigation.pop(request_id, None)
        for request_id, visible in tuple(session.pending_visibility.items()):
            if observed.output_visible == visible:
                self._completed(session, request_id)
            else:
                payload, _request = session.requests[request_id]
                self._store(session, request_id, payload, "rejected", "No observed visibility change.")
        session.pending_visibility.clear()

    def _fail(self, session: _Session, exc: Exception) -> None:
        session.state.update(status="error", error=str(exc))
        session.state["revision"] += 1
        self._reject_pending(session, "Player failed: " + str(exc))
        try:
            session.adapter.stop()
        except Exception:
            pass

    def _observe(self, session: _Session) -> None:
        observed = session.adapter.observe()
        self._refresh_capabilities(session)
        self._apply(session, observed)

    def _reobserve(self, session: _Session, adapter: PlayerAdapter) -> tuple[PlayerObservation, dict[str, dict[str, Any]]]:
        with session.adapter_lock:
            observed = adapter.observe()
            caps = adapter.capabilities()
        return observed, caps

    def _pollable(self, session: _Session) -> bool:
        return bool(
            self._session is session
            and not session.inflight
            and not session.stopping
            and session.state["status"] not in ("stopped", "error")
        )

    def state(self) -> dict[str, Any] | None:
        with self._lock:
            session = self._session
            if not session:
                return None
            if session.observing or not self._pollable(session):
                return deepcopy(session.state)
            session.observing = True
            adapter = session.adapter
        try:
            observed, caps = self._reobserve(session, adapter)
        except Exception as exc:
            with self._lock:
                if self._pollable(session):
                    self._fail(session, exc)
                session.observing = False
                return deepcopy(session.state)
        with self._lock:
            if self._pollable(session):
                self._apply_capabilities(session, caps)
                self._apply(session, observed)
            session.observing = False
            return deepcopy(session.state)

    def command(self, session_id: str, request_id: str, operation: str, slide: int | None = None) -> dict[str, Any]:
        with self._lock:
            session = self._session
            if not session or session.state["sessionId"] != session_id:
                return self._simple_reject(session.state if session else None, request_id, "Session is no longer current.")
            if not request_id:
                return self._simple_reject(session.state, request_id, "A request ID is required.")
            payload = (operation, slide)
            previous = session.requests.get(request_id)
            if previous:
                if previous[0] != payload:
                    return self._simple_reject(session.state, request_id, "Request ID was already used with a different command.")
                return self._reply(session, request_id)
            if operation not in ("advance", "goTo", "hide", "show", "stop"):
                return self._reject_now(session, request_id, payload, "Unknown operation.")
            if session.state["status"] == "stopped":
                return self._reject_now(session, request_id, payload, "Session is stopped.")

            if operation == "stop":
                if session.stopping:
                    return self._reject_now(session, request_id, payload, "Stop is already in progress.")
                session.stopping = True
                self._store(session, request_id, payload, "accepted")
                adapter = session.adapter
                export_key = session.state["exportKey"]
                stopping = True
            else:
                stopping = False
                if session.stopping:
                    return self._reject_now(session, request_id, payload, "Stop is in progress.")
                if session.inflight:
                    return self._reject_now(session, request_id, payload, "A player command is already in progress.")
                if operation == "goTo":
                    if isinstance(slide, bool) or not isinstance(slide, int) or slide < 1:
                        return self._reject_now(session, request_id, payload, "Enter an original slide number.")
                    if not any(item.get("originalOrdinal") == slide and not item.get("skipped") for item in session.state["slides"]):
                        return self._reject_now(session, request_id, payload, "Original slide is unavailable or skipped.")
                elif slide is not None:
                    return self._reject_now(session, request_id, payload, "Only goTo accepts a slide number.")
                token = object()
                session.inflight = token
                session.inflight_request_id = request_id
                self._store(session, request_id, payload, "accepted")
                need_observe = session.state["status"] != "error"
                adapter = session.adapter

        if stopping:
            return self._run_stop(session, request_id, payload, adapter, export_key)
        return self._run_command(session, request_id, operation, slide, payload, token, adapter, need_observe)

    def _run_stop(self, session: _Session, request_id: str, payload: tuple[str, int | None], adapter: PlayerAdapter, export_key: str) -> dict[str, Any]:
        try:
            adapter.stop()
            self._release(export_key, session.state["sessionId"])
        except Exception as exc:
            with self._lock:
                session.stopping = False
                return self._reject_now(session, request_id, payload, "Stop failed: " + str(exc))
        with self._lock:
            session.state.update(status="stopped", outputVisible=False)
            session.state.pop("error", None)
            session.state["revision"] += 1
            self._reject_pending(session, "Navigation was superseded by stop.")
            self._store(session, request_id, payload, "completed")
            session.stopping = False
            return self._reply(session, request_id)

    def _run_command(
        self,
        session: _Session,
        request_id: str,
        operation: str,
        slide: int | None,
        payload: tuple[str, int | None],
        token: object,
        adapter: PlayerAdapter,
        need_observe: bool,
    ) -> dict[str, Any]:
        try:
            if need_observe:
                observed, caps = self._reobserve(session, adapter)
                with self._lock:
                    if not self._still_current(session, token):
                        return self._superseded_reply(session, request_id)
                    self._apply_capabilities(session, caps)
                    self._apply(session, observed)

            with self._lock:
                if not self._still_current(session, token):
                    return self._superseded_reply(session, request_id)
                if session.state["status"] == "error":
                    return self._reject_now(session, request_id, payload, "Player failed; stop this session before loading again.")
                cap = session.state["capabilities"].get(operation, {})
                if not cap.get("supported", False):
                    return self._reject_now(session, request_id, payload, cap.get("reason") or "Operation is not supported.")
                if operation in ("advance", "goTo") and session.state["status"] == "busy":
                    return self._reject_now(session, request_id, payload, "Player is busy.")
                session.state["status"] = "busy"
                session.state["revision"] += 1
                if operation in ("advance", "goTo"):
                    session.pending_navigation[request_id] = (
                        operation, slide, session.state["sceneId"], session.player_revision,
                    )
                else:
                    session.pending_visibility[request_id] = operation == "show"

            with session.adapter_lock:
                observed = adapter.execute(operation, slide)
                caps = adapter.capabilities()

            with self._lock:
                if not self._still_current(session, token):
                    return self._superseded_reply(session, request_id)
                if not isinstance(observed, PlayerObservation):
                    raise ValueError("Player returned no observation for the command.")
                self._apply_capabilities(session, caps)
                self._apply(session, observed, executed_operation=operation)
                return self._reply(session, request_id)

        except PlayerCommandRejected as exc:
            with self._lock:
                if not self._still_current(session, token):
                    return self._superseded_reply(session, request_id)
                session.pending_navigation.pop(request_id, None)
                session.pending_visibility.pop(request_id, None)
            try:
                observed, caps = self._reobserve(session, adapter)
            except Exception as observe_exc:
                with self._lock:
                    if not self._still_current(session, token):
                        return self._superseded_reply(session, request_id)
                    self._fail(session, observe_exc)
                    return self._reject_now(session, request_id, payload, "Player command failed: " + str(observe_exc))
            with self._lock:
                if not self._still_current(session, token):
                    return self._superseded_reply(session, request_id)
                self._apply_capabilities(session, caps)
                self._apply(session, observed)
                return self._reject_now(session, request_id, payload, str(exc))

        except Exception as exc:
            with self._lock:
                if not self._still_current(session, token):
                    return self._superseded_reply(session, request_id)
                self._fail(session, exc)
                return self._reject_now(session, request_id, payload, "Player command failed: " + str(exc))

        finally:
            with self._lock:
                if session.inflight is token:
                    session.inflight = None
                    session.inflight_request_id = None
