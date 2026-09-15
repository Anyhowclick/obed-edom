"""Replayable per-finding diagnostics log for the sermon checker.

Writes one JSONL file per check pass: a header pinning the run, then one
record per pair (``text``) or non-text flag (``finding``). ``load_records``
reads it back; ``replay`` re-runs the text classifier over recorded inputs
to verify a diagnostics file still reproduces its own findings.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

SCHEMA = 1


def _sanitize(obj: Any) -> Any:
    """Non-finite floats (NaN/inf) are not valid JSON; null them rather than
    lose the record they live in."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    return obj


class DiagnosticsWriter:
    """Writes records to a sibling temp file; ``commit()`` publishes it onto
    ``path`` with ``os.replace`` only once the caller confirms the pass
    succeeded, so a failed check leaves any previous ``path`` untouched."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.tmp_path = self.path.with_name(self.path.name + ".tmp")
        # Checks only the final path component — a symlinked ancestor is not this
        # guard's concern.
        if self.path.is_symlink() or self.tmp_path.is_symlink():
            raise OSError(f"refusing to write diagnostics through a symlink: {self.path}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.tmp_path.open("w", encoding="utf-8")
        self._failed = False
        self._committed = False
        self.error: str | None = None

    def header(self, **fields: Any) -> None:
        self._write({"kind": "header", "schema": SCHEMA, **fields})

    def record(self, kind: str, **fields: Any) -> None:
        self._write({"kind": kind, **fields})

    def _write(self, obj: dict) -> None:
        if self._failed:
            return
        try:
            line = json.dumps(_sanitize(obj), ensure_ascii=False, default=str)
        except Exception as exc:  # noqa: BLE001
            self.error = self.error or str(exc)
            return
        try:
            self._fh.write(line)
            self._fh.write("\n")
        except Exception as exc:  # noqa: BLE001
            self._failed = True
            self.error = str(exc)

    def commit(self) -> bool:
        """Close the temp file and publish it as ``path``. On any prior or
        closing failure, discard the temp file and leave ``path`` as it was."""
        if self._committed:
            return True
        try:
            self._fh.close()
        except Exception as exc:  # noqa: BLE001
            self._failed = True
            self.error = self.error or str(exc)
        if self._failed:
            self._discard_tmp()
            return False
        try:
            os.replace(self.tmp_path, self.path)
        except OSError as exc:
            self.error = self.error or str(exc)
            self._discard_tmp()
            return False
        self._committed = True
        return True

    def close(self) -> None:
        """Abort without publishing: discard the temp file. No-op after a
        successful ``commit()``."""
        if self._committed:
            return
        try:
            self._fh.close()
        except Exception as exc:  # noqa: BLE001
            self.error = self.error or str(exc)
        self._discard_tmp()

    def _discard_tmp(self) -> None:
        try:
            self.tmp_path.unlink(missing_ok=True)
        except OSError:
            pass

    def __enter__(self) -> "DiagnosticsWriter":
        return self

    def __exit__(self, exc_type: object, *_rest: object) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.close()


def load_records(path: Path) -> tuple[dict, list[dict]]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"Empty diagnostics file: {path}")
    header = json.loads(lines[0])
    if header.get("kind") != "header":
        raise ValueError(f"Diagnostics file missing header: {path}")
    if header.get("schema") != SCHEMA:
        raise ValueError(
            f"Diagnostics schema {header.get('schema')!r} does not match {SCHEMA} in {path}"
        )
    records = [json.loads(line) for line in lines[1:] if line.strip()]
    return header, records


def _selected_attempt(attempts: list[dict]) -> dict | None:
    """The attempt that produced the pair's finding — the first one with a non-None
    ``finding``, since that is where the recording loop broke — or the last attempt
    tried when none fired."""
    if not attempts:
        return None
    for entry in attempts:
        if entry.get("finding") is not None:
            return entry
    return attempts[-1]


def _published_outcome(raw_finding: dict | None, rule_severities: dict) -> dict | None:
    """Map a raw (rule, message, default) finding through the header's pinned
    `ruleSeverities` snapshot, exactly as `validate.make_flag` does at run time."""
    if raw_finding is None:
        return None
    from obed_edom.validate import rule_severity

    rule = raw_finding.get("rule")
    default = raw_finding.get("default") or "warning"
    severity = rule_severity(rule, default, rules=rule_severities or {})
    if severity is None:
        return None
    return {"rule": rule, "message": raw_finding.get("message"), "severity": severity}


def replay(
    path: Path,
    *,
    rule: str | None = None,
    pair: int | None = None,
    verbose: bool = False,
    strict: bool = False,
) -> int:
    from obed_edom.diff_keynotes import select_text_sources, strip_carried_point_title
    from obed_edom.rendered import point_number_lines
    from obed_edom.text_diff import classify_text_diff

    header, records = load_records(path)
    left_label = header.get("leftLabel", "LW")
    right_label = header.get("rightLabel", "DSK")
    point_titles = header.get("pointTitles") or []
    rule_severities = header.get("ruleSeverities") or {}
    mismatches = 0
    message_only = 0
    replayed = 0
    skipped = 0
    for rec in records:
        if rec.get("kind") != "text":
            if rec.get("kind") == "finding":
                skipped += 1
            continue
        recorded_attempts = rec.get("attempts") or []
        recorded_selected = _selected_attempt(recorded_attempts)
        recorded_raw = recorded_selected.get("finding") if recorded_selected else None
        recorded_rule = recorded_raw.get("rule") if recorded_raw else None
        if rule is not None and recorded_rule != rule:
            continue
        if pair is not None and rec.get("pairIndex") != pair:
            continue
        replayed += 1

        left = rec.get("left") or {}
        right = rec.get("right") or {}
        attempts, replay_typed_skip = select_text_sources(
            left.get("text", ""), left.get("typed", ""), left.get("outsidePhotos", ""),
            right.get("text", ""), right.get("typed", ""), right.get("outsidePhotos", ""),
        )
        replay_attempts = []
        replay_selected = None
        replay_carried_acc = None
        for source, a_src, b_src, reason in attempts:
            text = a_src
            carried = None
            if point_titles:
                text, carried = strip_carried_point_title(text, b_src, point_titles)
            replay_carried_acc = replay_carried_acc or carried
            ignore_tokens = sorted(point_number_lines(text))
            finding = classify_text_diff(
                text, b_src, left_label, right_label, ignore_left_tokens=ignore_tokens,
            )
            entry = {
                "source": source,
                "reason": reason,
                "inputLeft": text,
                "inputRight": b_src,
                "ignoreLeftTokens": ignore_tokens,
                "carried": carried,
                "finding": {"rule": finding.rule, "message": finding.message, "default": finding.default}
                if finding
                else None,
            }
            replay_attempts.append(entry)
            if finding is not None:
                replay_selected = entry
                break
        if replay_selected is None and replay_attempts:
            replay_selected = replay_attempts[-1]

        replay_raw = (replay_selected or {}).get("finding")

        def _raw_key(f: dict | None) -> tuple | None:
            return None if f is None else (f.get("rule"), f.get("default"))

        def _attempt_key(entry: dict | None) -> tuple | None:
            if entry is None:
                return None
            return (
                entry.get("source"),
                entry.get("reason"),
                entry.get("inputLeft"),
                entry.get("inputRight"),
                entry.get("ignoreLeftTokens"),
                entry.get("carried"),
                _raw_key(entry.get("finding")),
            )

        sequence_ok = len(replay_attempts) == len(recorded_attempts) and all(
            _attempt_key(replayed_entry) == _attempt_key(recorded_entry)
            for replayed_entry, recorded_entry in zip(replay_attempts, recorded_attempts)
        )
        recorded_carried_acc = rec.get("carried")
        carried_ok = replay_carried_acc == recorded_carried_acc

        selected_ok = bool(recorded_selected) and bool(replay_selected) and (
            sequence_ok
            and carried_ok
            and replay_typed_skip == rec.get("typedSkip")
            and _raw_key(replay_raw) == _raw_key(recorded_raw)
        )

        replayed_outcome = _published_outcome(replay_raw, rule_severities)
        recorded_outcome = rec.get("outcome")
        replayed_rule = replayed_outcome.get("rule") if replayed_outcome else None

        if not selected_ok:
            status = "MISMATCH"
        elif (
            (replayed_outcome is None) != (recorded_outcome is None)
            or (replayed_outcome or {}).get("rule") != (recorded_outcome or {}).get("rule")
            or (replayed_outcome or {}).get("severity") != (recorded_outcome or {}).get("severity")
        ):
            status = "MISMATCH"
        elif (replayed_outcome or {}).get("message") != (recorded_outcome or {}).get("message"):
            status = "MISMATCH(message)"
        else:
            status = "MATCH"

        print(
            f"pair {rec.get('pairNumber')}  {recorded_rule or '-'}  {status}"
            + ("" if status == "MATCH" else f"  recorded={recorded_rule}  replayed={replayed_rule}")
        )
        if status == "MISMATCH":
            mismatches += 1
            if verbose:
                print(f"  recorded attempt={recorded_selected!r}")
                print(f"  replayed attempt={replay_selected!r}")
        elif status == "MISMATCH(message)":
            message_only += 1
            if verbose:
                recorded_message = (recorded_outcome or {}).get("message")
                replayed_message = (replayed_outcome or {}).get("message")
                print(f"  recorded message={recorded_message!r}  replayed message={replayed_message!r}")
    if skipped:
        print(f"({skipped} photo.*/finding record(s) skipped; not replayable)")
    print(f"{replayed} findings replayed, {mismatches} mismatches, {message_only} message-only")
    if strict:
        mismatches += message_only
    return 1 if mismatches else 0
