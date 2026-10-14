from __future__ import annotations

import io
import json
import sys
from types import SimpleNamespace

from scripts import live_fixture_session as session


def test_idle_timeout_observes_before_executing_typed_command(monkeypatch, tmp_path):
    calls = []
    observed = SimpleNamespace(original_slide=1, scene_id="scene-1", busy=False, output_visible=True)

    class Host:
        output = {"transport": "fake", "viewport": None, "continuity": None, "logPath": None}

        def __init__(self, destination, slides, display_id=None):
            calls.append(("host", destination, slides, display_id))

        def observe(self):
            calls.append("observe")
            return observed

        def execute(self, command, argument=None):
            calls.append(("execute", command, argument))
            return observed

        def stop(self):
            calls.append("stop")

    def copy_export(source, destination):
        calls.append(("copytree", source, destination))
        (destination / "assets").mkdir(parents=True)
        (destination / "assets/header.json").write_text(json.dumps({"slideList": ["slide-1"]}))

    stdin = io.StringIO("a\nq\n")
    readiness = iter([([], [], []), ([stdin], [], []), ([stdin], [], [])])
    timeouts = []

    def select_stdin(readers, writers, errors, timeout):
        assert readers == [stdin] and not writers and not errors
        timeouts.append(timeout)
        return next(readiness)

    export = tmp_path / "export"
    cache = tmp_path / "cache"
    monkeypatch.setattr(session, "LiveOutputHost", Host)
    monkeypatch.setattr(session, "cache_dir", lambda digest: cache)
    monkeypatch.setattr(session.shutil, "copytree", copy_export)
    monkeypatch.setattr(session.select, "select", select_stdin)
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "argv", ["live_fixture_session.py", "--export", str(export)])

    session.main()

    assert calls[2:5] == ["observe", "observe", ("execute", "advance", None)]
    assert calls[-1] == "stop"
    assert timeouts == [session.IDLE_OBSERVE_INTERVAL_S] * 3
