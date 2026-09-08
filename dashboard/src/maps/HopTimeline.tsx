import { useRef, type PointerEvent } from "react";
import { resolveHopPhases } from "./captureFly";

type Handle = "out" | "in" | "out-in";
type Phase = "out" | "move" | "in";

const PHASE_EPSILON = 0.005;

export function HopTimeline({
  duration,
  easeIn,
  easeOut,
  disabled = false,
  onChange,
  onCommit,
}: {
  duration: number;
  easeIn?: number;
  easeOut?: number;
  disabled?: boolean;
  onChange: (next: { easeIn: number; easeOut: number }) => void;
  onCommit?: () => void;
}) {
  const track = useRef<HTMLDivElement | null>(null);
  const drag = useRef<{ handle: Handle; x: number; easeIn: number; easeOut: number } | null>(null);
  const phases = resolveHopPhases({ duration, easeIn, easeOut });
  const total = Math.max(0.15, duration);
  const enabled = {
    out: phases.zoomOut > PHASE_EPSILON,
    move: phases.move > PHASE_EPSILON,
    in: phases.zoomIn > PHASE_EPSILON,
  };
  const enabledCount = Number(enabled.out) + Number(enabled.move) + Number(enabled.in);

  function seconds(n: number) {
    return Math.round(n * 100) / 100;
  }

  function apply(handle: Handle, dx: number, startIn: number, startOut: number) {
    const width = track.current?.clientWidth || 1;
    const delta = (dx / width) * total;
    if (handle === "out-in") {
      const nextOut = Math.min(total, Math.max(0, startIn + delta));
      onChange({ easeIn: seconds(nextOut), easeOut: seconds(total - nextOut) });
      return;
    }
    if (handle === "out") {
      const maxOut = Math.max(0, total - startOut);
      onChange({ easeIn: seconds(Math.min(maxOut, Math.max(0, startIn + delta))), easeOut: seconds(startOut) });
      return;
    }
    const maxIn = Math.max(0, total - startIn);
    onChange({ easeIn: seconds(startIn), easeOut: seconds(Math.min(maxIn, Math.max(0, startOut - delta))) });
  }

  function togglePhase(phase: Phase) {
    if (enabled[phase] && enabledCount === 1) return;
    if (phase === "out") {
      if (enabled.out) onChange({ easeIn: 0, easeOut: seconds(phases.zoomIn) });
      else if (enabled.move) onChange({ easeIn: seconds(total * 0.25), easeOut: seconds(phases.zoomIn) });
      else onChange({ easeIn: seconds(total * 0.25), easeOut: seconds(total * 0.75) });
      return;
    }
    if (phase === "in") {
      if (enabled.in) onChange({ easeIn: seconds(phases.zoomOut), easeOut: 0 });
      else if (enabled.move) onChange({ easeIn: seconds(phases.zoomOut), easeOut: seconds(total * 0.25) });
      else onChange({ easeIn: seconds(total * 0.75), easeOut: seconds(total * 0.25) });
      return;
    }
    const zoomTime = phases.zoomOut + phases.zoomIn;
    if (enabled.move) {
      const scale = total / Math.max(PHASE_EPSILON, zoomTime);
      onChange({ easeIn: seconds(phases.zoomOut * scale), easeOut: seconds(phases.zoomIn * scale) });
      return;
    }
    const scale = (total * 0.75) / Math.max(PHASE_EPSILON, zoomTime);
    onChange({ easeIn: seconds(phases.zoomOut * scale), easeOut: seconds(phases.zoomIn * scale) });
  }

  function onHandleDown(handle: Handle, event: PointerEvent<HTMLButtonElement>) {
    if (disabled) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { handle, x: event.clientX, easeIn: phases.zoomOut, easeOut: phases.zoomIn };
  }

  function onHandleMove(event: PointerEvent<HTMLButtonElement>) {
    const current = drag.current;
    if (!current || disabled) return;
    apply(current.handle, event.clientX - current.x, current.easeIn, current.easeOut);
  }

  function onHandleUp(event: PointerEvent<HTMLButtonElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (drag.current) {
      drag.current = null;
      onCommit?.();
    }
  }

  return (
    <div className="hop-tl-wrap">
      <div className="cap">Fly phases</div>
      <div className="hop-phase-toggles" role="group" aria-label="Enabled fly phases">
        {(["out", "move", "in"] as Phase[]).map((phase) => (
          <button
            key={phase}
            type="button"
            className={`hop-phase-toggle${enabled[phase] ? " on" : ""}`}
            aria-pressed={enabled[phase]}
            disabled={disabled || (enabled[phase] && enabledCount === 1)}
            onClick={() => togglePhase(phase)}
          >
            {phase === "out" ? "Zoom out" : phase === "in" ? "Zoom in" : "Move"}
          </button>
        ))}
      </div>
      <div ref={track} className={`hop-tl${disabled ? " disabled" : ""}`}>
        {enabled.out && (
          <div className="hop-tl-clip out" style={{ flexGrow: phases.zoomOut }} title="Zoom out at the start camera">
            <span className="hop-tl-label">Zoom out</span>
            <span className="hop-tl-time">{phases.zoomOut.toFixed(2)}s</span>
          </div>
        )}
        {enabled.out && (enabled.move || enabled.in) && (
          <button
            type="button"
            className="hop-tl-handle"
            aria-label="Zoom out duration"
            disabled={disabled}
            onPointerDown={(event) => onHandleDown(enabled.move ? "out" : "out-in", event)}
            onPointerMove={onHandleMove}
            onPointerUp={onHandleUp}
            onPointerCancel={onHandleUp}
          />
        )}
        {enabled.move && (
          <div className="hop-tl-clip move" style={{ flexGrow: phases.move }} title="Pan at cruise zoom">
            <span className="hop-tl-label">Move</span>
            <span className="hop-tl-time">{phases.move.toFixed(2)}s</span>
          </div>
        )}
        {enabled.move && enabled.in && (
          <button
            type="button"
            className="hop-tl-handle"
            aria-label="Zoom in duration"
            disabled={disabled}
            onPointerDown={(event) => onHandleDown("in", event)}
            onPointerMove={onHandleMove}
            onPointerUp={onHandleUp}
            onPointerCancel={onHandleUp}
          />
        )}
        {enabled.in && (
          <div className="hop-tl-clip in" style={{ flexGrow: phases.zoomIn }} title="Zoom in at the end camera">
            <span className="hop-tl-label">Zoom in</span>
            <span className="hop-tl-time">{phases.zoomIn.toFixed(2)}s</span>
          </div>
        )}
      </div>
      <p className="note">Toggle phases; at least one stays on. With Move off, position changes during the zoom. Play hop and Export share this fly.</p>
    </div>
  );
}
