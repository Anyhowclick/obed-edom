"""Authoritative, adapter-independent live playback session."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
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


class PlayerCommandRejected(RuntimeError):
    pass


class PlayerAdapter(Protocol):
    def capabilities(self) -> dict[str, dict[str, Any]]: ...
    def observe(self) -> PlayerObservation: ...
    def execute(self, operation: str, slide: int | None = None) -> PlayerObservation: ...
    def stop(self) -> None: ...


class LiveSessionService:
    def __init__(self, *, claim=claim_export, release=release_owned_claim):
        self._lock = RLock()
        self._claim = claim
        self._release = release
        self._state: dict[str, Any] | None = None
        self._adapter: PlayerAdapter | None = None
        self._inflight = False
        self._requests: dict[str, tuple[tuple[str, int | None], dict[str, Any]]] = {}
        self._pending_navigation: dict[str, tuple[str, int | None, str | None, int | None]] = {}
        self._pending_visibility: dict[str, bool] = {}
        self._player_revision: int | None = None

    def start(self, adapter: PlayerAdapter, *, export_key: str, export_root: Path, identity: dict[str, Any]) -> dict[str, Any]:
        """Load an adapter whose registered export root was validated by the caller."""
        with self._lock:
            if self._state and self._state["status"] != "stopped":
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
            self._adapter = adapter
            self._requests = {}
            self._pending_navigation = {}
            self._pending_visibility = {}
            self._player_revision = None
            self._state = {
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
                "slides": slides,
                "output": {**deepcopy(identity.get("output", {})), "transport": "hdmi", "alpha": False, "audio": False},
                "capabilities": self._disabled_capabilities(),
            }
            try:
                self._observe()
            except Exception as exc:
                self._fail(exc)
            return deepcopy(self._state)

    @staticmethod
    def _disabled_capabilities() -> dict[str, dict[str, Any]]:
        return {
            operation: {"supported": False, "reason": "Not qualified by the player adapter."}
            for operation in ("advance", "goTo", "hide", "show")
        } | {"stop": {"supported": True}}

    def _refresh_capabilities(self) -> None:
        assert self._adapter is not None
        caps = self._adapter.capabilities()
        self._state["capabilities"] = {
            operation: deepcopy(caps.get(operation, {"supported": False, "reason": "Not qualified by the player adapter."}))
            for operation in ("advance", "goTo", "hide", "show")
        }
        self._state["capabilities"]["stop"] = {"supported": True}

    def _completed(self, request_id: str) -> None:
        payload, _request = self._requests[request_id]
        self._requests[request_id] = (payload, {"requestId": request_id, "outcome": "completed", "state": deepcopy(self._state)})

    def _reject_pending(self, reason: str) -> None:
        for request_id in set(self._pending_navigation) | set(self._pending_visibility):
            payload, _request = self._requests[request_id]
            self._requests[request_id] = (payload, {"requestId": request_id, "outcome": "rejected", "reason": reason, "state": deepcopy(self._state)})
        self._pending_navigation.clear()
        self._pending_visibility.clear()

    def _apply(self, observed: PlayerObservation) -> None:
        assert self._state is not None
        update = {
            "originalSlide": observed.original_slide,
            "sceneId": observed.scene_id,
            "buildIndex": observed.build_index,
            "outputVisible": observed.output_visible,
            "status": "busy" if observed.busy else "ready",
        }
        if observed.output is not None:
            update["output"] = deepcopy(observed.output)
        if any(self._state.get(key) != value for key, value in update.items()):
            self._state.update(update)
            self._state["revision"] += 1
        self._state.pop("error", None)
        self._player_revision = observed.revision
        if not observed.busy:
            for request_id, baseline in tuple(self._pending_navigation.items()):
                operation, target, scene, revision = baseline
                changed = observed.scene_id != scene or observed.revision != revision
                complete = changed if operation == "advance" else observed.original_slide == target and observed.revision != revision
                if complete:
                    self._completed(request_id)
                else:
                    payload, _request = self._requests[request_id]
                    self._requests[request_id] = (
                        payload,
                        {
                            "requestId": request_id,
                            "outcome": "rejected",
                            "reason": "No observed navigation change.",
                            "state": deepcopy(self._state),
                        },
                    )
            self._pending_navigation.clear()
        for request_id, visible in tuple(self._pending_visibility.items()):
            if observed.output_visible == visible:
                self._completed(request_id)
                del self._pending_visibility[request_id]

    def _fail(self, exc: Exception) -> None:
        assert self._state is not None
        self._state.update(status="error", error=str(exc))
        self._state["revision"] += 1
        self._reject_pending("Player failed: " + str(exc))

    def _observe(self) -> None:
        assert self._adapter is not None
        observed = self._adapter.observe()
        self._refresh_capabilities()
        self._apply(observed)

    def state(self) -> dict[str, Any] | None:
        with self._lock:
            if self._state and self._adapter and not self._inflight and self._state["status"] not in ("stopped", "error"):
                try:
                    self._observe()
                except Exception as exc:
                    self._fail(exc)
            return deepcopy(self._state)

    def command(self, session_id: str, request_id: str, operation: str, slide: int | None = None) -> dict[str, Any]:
        with self._lock:
            def result(outcome: str, reason: str | None = None) -> dict[str, Any]:
                value = {"requestId": request_id, "outcome": outcome, "state": deepcopy(self._state)}
                if reason:
                    value["reason"] = reason
                return value

            if not self._state or self._state["sessionId"] != session_id:
                return result("rejected", "Session is no longer current.")
            if not request_id:
                return result("rejected", "A request ID is required.")
            payload = (operation, slide)
            previous = self._requests.get(request_id)
            if previous:
                if previous[0] != payload:
                    return result("rejected", "Request ID was already used with a different command.")
                return deepcopy(previous[1])

            def reject(reason: str) -> dict[str, Any]:
                value = result("rejected", reason)
                self._requests[request_id] = (payload, value)
                return deepcopy(value)

            if operation not in ("advance", "goTo", "hide", "show", "stop"):
                return reject("Unknown operation.")
            if self._state["status"] == "stopped":
                return reject("Session is stopped.")
            if self._inflight:
                return reject("A player command is already in progress.")
            if operation != "stop" and self._state["status"] != "error":
                try:
                    self._observe()
                except Exception as exc:
                    self._fail(exc)
                    return reject("Player command failed: " + str(exc))
            if operation != "stop":
                if self._state["status"] == "error":
                    return reject("Player failed; stop this session before loading again.")
                cap = self._state["capabilities"].get(operation, {})
                if not cap.get("supported", False):
                    return reject(cap.get("reason") or "Operation is not supported.")
                if operation in ("advance", "goTo") and self._state["status"] == "busy":
                    return reject("Player is busy.")
            if operation == "goTo":
                if isinstance(slide, bool) or not isinstance(slide, int) or slide < 1:
                    return reject("Enter an original slide number.")
                if not any(item.get("originalOrdinal") == slide and not item.get("skipped") for item in self._state["slides"]):
                    return reject("Original slide is unavailable or skipped.")
            elif slide is not None:
                return reject("Only goTo accepts a slide number.")
            self._inflight = True
            self._state["status"] = "busy"
            self._state["revision"] += 1
            self._requests[request_id] = (payload, result("accepted"))
            if operation in ("advance", "goTo"):
                self._pending_navigation[request_id] = (
                    operation,
                    slide,
                    self._state["sceneId"],
                    self._player_revision,
                )
            elif operation in ("hide", "show"):
                self._pending_visibility[request_id] = operation == "show"
            adapter = self._adapter
            export_key = self._state["exportKey"]

        try:
            assert adapter is not None
            if operation == "stop":
                adapter.stop()
                self._release(export_key, session_id)
                observed = None
            else:
                observed = adapter.execute(operation, slide)
            with self._lock:
                if operation == "stop":
                    self._state.update(status="stopped", outputVisible=False)
                    self._state.pop("error", None)
                    self._state["revision"] += 1
                    self._reject_pending("Navigation was superseded by stop.")
                    value = result("completed")
                    self._requests[request_id] = (payload, value)
                else:
                    if not isinstance(observed, PlayerObservation):
                        raise ValueError("Player returned no observation for the command.")
                    self._refresh_capabilities()
                    self._apply(observed)
                    value = self._requests[request_id][1]
                return deepcopy(value)
        except PlayerCommandRejected as exc:
            with self._lock:
                self._pending_navigation.pop(request_id, None)
                self._pending_visibility.pop(request_id, None)
                try:
                    self._observe()
                except Exception as observe_exc:
                    self._fail(observe_exc)
                    value = result("rejected", "Player command failed: " + str(observe_exc))
                else:
                    value = result("rejected", str(exc))
                self._requests[request_id] = (payload, value)
                return deepcopy(value)
        except Exception as exc:
            with self._lock:
                self._fail(exc)
                value = result("rejected", "Player command failed: " + str(exc))
                self._requests[request_id] = (payload, value)
                return deepcopy(value)
        finally:
            with self._lock:
                self._inflight = False
