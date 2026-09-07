import { useRef, type PointerEvent } from "react";
import { resolveHopPhases } from "./captureFly";

type Handle = "out" | "in";

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
  const minP = Math.min(0.05, Math.max(0.15, duration) / 6);

  function seconds(n: number) {
    return Math.round(n * 100) / 100;
  }

  function apply(handle: Handle, dx: number, startIn: number, startOut: number) {
    const width = track.current?.clientWidth || 1;
    const delta = (dx / width) * Math.max(0.15, duration);
    if (handle === "out") {
      const maxOut = Math.max(minP, duration - minP - startOut);
      onChange({ easeIn: seconds(Math.min(maxOut, Math.max(minP, startIn + delta))), easeOut: seconds(startOut) });
      return;
    }
    const maxIn = Math.max(minP, duration - minP - startIn);
    onChange({ easeIn: seconds(startIn), easeOut: seconds(Math.min(maxIn, Math.max(minP, startOut - delta))) });
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
      <div ref={track} className={`hop-tl${disabled ? " disabled" : ""}`}>
        <div className="hop-tl-clip out" style={{ flexGrow: phases.zoomOut }} title="Zoom out at the start camera">
          <span className="hop-tl-label">Zoom out</span>
          <span className="hop-tl-time">{phases.zoomOut.toFixed(2)}s</span>
        </div>
        <button
          type="button"
          className="hop-tl-handle"
          aria-label="Zoom out duration"
          disabled={disabled}
          onPointerDown={(event) => onHandleDown("out", event)}
          onPointerMove={onHandleMove}
          onPointerUp={onHandleUp}
          onPointerCancel={onHandleUp}
        />
        <div className="hop-tl-clip move" style={{ flexGrow: phases.move }} title="Pan at cruise zoom">
          <span className="hop-tl-label">Move</span>
          <span className="hop-tl-time">{phases.move.toFixed(2)}s</span>
        </div>
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
        <div className="hop-tl-clip in" style={{ flexGrow: phases.zoomIn }} title="Zoom in at the end camera">
          <span className="hop-tl-label">Zoom in</span>
          <span className="hop-tl-time">{phases.zoomIn.toFixed(2)}s</span>
        </div>
      </div>
      <p className="note">Drag the joins. Duration above scales all three. Play hop and Export share this fly.</p>
    </div>
  );
}
