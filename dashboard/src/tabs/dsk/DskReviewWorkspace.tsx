import { useEffect, useRef, useState } from "react";
import { dskThumbUrl } from "../../api";
import {
  contiguousCategories,
  dskEditorReducer,
  effectiveAlignment,
  effectiveFrame,
  effectiveViewport,
  selectedComposition,
  selectedMask,
  type DskAlignment,
  type DskEditorAction,
  type DskEditorState,
} from "../../dsk/decisions";

type Props = { jobId: string; state: DskEditorState; onChange: (next: DskEditorState, persist?: boolean) => void };
const alignments: Exclude<DskAlignment, "inherit">[] = ["left", "centre", "right"];
const glyph = (alignment: Exclude<DskAlignment, "inherit">) => <span aria-hidden="true" className={`align-glyph ${alignment}`} />;
function number(value: string) { const parsed = Number(value); return value.trim() && Number.isFinite(parsed) && parsed > 0 ? parsed : null; }

function SlideRail({ jobId, state, dispatch }: { jobId: string; state: DskEditorState; dispatch: (action: DskEditorAction, persist?: boolean) => void }) {
  return <nav className="dsk-rail" aria-label="Source compositions">
    {contiguousCategories(state.review.compositions).map((group, index) => <section key={`${group.key}-${index}`}>
      <h3>{group.label}</h3>
      {group.compositions.map((composition) => <button type="button" key={composition.id} className={`dsk-rail-card ${state.selectedId === composition.id ? "selected" : ""}`} onClick={() => dispatch({ type: "select", id: composition.id })}>
        {composition.thumb ? <img src={dskThumbUrl(jobId, composition.thumb)} alt="" /> : <span className="dsk-thumb-placeholder" />}
        <span className="dsk-rail-meta"><span>{composition.decision.include ? "Included" : "Excluded"}</span><span>{composition.media.length ? `${composition.media.length} media` : ""}</span></span>
      </button>)}
    </section>)}
  </nav>;
}

function OutputPreview({ jobId, state, dispatch }: { jobId: string; state: DskEditorState; dispatch: (action: DskEditorAction, persist?: boolean) => void }) {
  const composition = selectedComposition(state);
  const surface = useRef<HTMLDivElement>(null);
  const gesture = useRef<{ kind: "move" | "resize"; x: number; y: number; frame: ReturnType<typeof effectiveFrame> } | null>(null);
  if (!composition) return null;
  const frame = effectiveFrame(state, composition);
  const canvas = state.review.canvas;
  const move = (event: React.PointerEvent<HTMLDivElement>) => {
    const active = gesture.current; const rect = surface.current?.getBoundingClientRect();
    if (!active || !rect) return;
    const dx = (event.clientX - active.x) * canvas.width / rect.width;
    const dy = (event.clientY - active.y) * canvas.height / rect.height;
    if (active.kind === "resize") dispatch({ type: "viewport", id: composition.id, viewport: { width: active.frame.width + dx, height: active.frame.height - dy, aspectLocked: effectiveViewport(state, composition).aspectLocked } });
    else {
      const x = active.frame.x + dx;
      const anchors: [Exclude<DskAlignment, "inherit">, number][] = [["left", state.review.safeArea.left], ["centre", (canvas.width - active.frame.width) / 2], ["right", state.review.safeArea.right - active.frame.width]];
      const alignment = anchors.reduce((best, item) => Math.abs(item[1] - x) < Math.abs(best[1] - x) ? item : best)[0];
      dispatch({ type: "decision", id: composition.id, change: { alignment } });
    }
  };
  const end = (event: React.PointerEvent<HTMLDivElement>) => { if (!gesture.current) return; gesture.current = null; event.currentTarget.releasePointerCapture?.(event.pointerId); dispatch({ type: "selectMedia", occurrenceId: state.selectedMediaId }, true); };
  return <section className="dsk-output-preview" aria-label="Output preview">
    <div className="dsk-canvas" ref={surface} onPointerMove={move} onPointerUp={end} onPointerCancel={end}>
      <div className="dsk-safe-line" style={{ left: `${state.review.safeArea.left / canvas.width * 100}%`, right: `${(canvas.width - state.review.safeArea.right) / canvas.width * 100}%` }} />
      <div className="dsk-frame" tabIndex={0} aria-label="Output frame. Use left and right arrows to align; Shift plus arrow resizes." style={{ left: `${frame.x / canvas.width * 100}%`, top: `${frame.y / canvas.height * 100}%`, width: `${frame.width / canvas.width * 100}%`, height: `${frame.height / canvas.height * 100}%` }} onKeyDown={(event) => { if (event.key === "ArrowLeft") { event.preventDefault(); dispatch({ type: event.shiftKey ? "viewport" : "decision", id: composition.id, ...(event.shiftKey ? { viewport: { width: frame.width - 1 } } : { change: { alignment: "left" } }) } as DskEditorAction, true); } if (event.key === "ArrowRight") { event.preventDefault(); dispatch({ type: event.shiftKey ? "viewport" : "decision", id: composition.id, ...(event.shiftKey ? { viewport: { width: frame.width + 1 } } : { change: { alignment: "right" } }) } as DskEditorAction, true); } }} onPointerDown={(event) => { if ((event.target as HTMLElement).closest("button")) return; gesture.current = { kind: "move", x: event.clientX, y: event.clientY, frame }; event.currentTarget.setPointerCapture(event.pointerId); }}>
        <span className="dsk-pixel-chip">{frame.width} × {frame.height} px</span>
        {composition.previewLayers.filter((layer) => {
          const media = composition.media.find((item) => item.occurrenceId === layer.occurrenceId);
          return !media || (
            media.sourceModes.includes(composition.decision.source)
            && (composition.decision.contentMode === "full" || media.kind === "movie")
          );
        }).map((layer, index) => {
          const media = composition.media.find((item) => item.occurrenceId === layer.occurrenceId);
          const sourceCrop = media?.sourceCrops?.[composition.decision.source];
          const mask = layer.occurrenceId ? composition.decision.masks[layer.occurrenceId] : undefined;
          const maskPosition = mask ? `${(mask.panX + 1) * 50}% ${(mask.panY + 1) * 50}%` : undefined;
          return <div key={`${layer.occurrenceId || layer.src}-${index}`} className={`dsk-media-layer ${state.selectedMediaId === layer.occurrenceId ? "active" : ""}`} style={{ left: `${layer.slot.x * 100}%`, top: `${layer.slot.y * 100}%`, width: `${layer.slot.width * 100}%`, height: `${layer.slot.height * 100}%` }} onClick={(event) => { event.stopPropagation(); if (layer.occurrenceId) dispatch({ type: "selectMedia", occurrenceId: layer.occurrenceId }); }}>
            {layer.src && <div className="dsk-media-crop" style={{ transformOrigin: maskPosition, transform: mask ? `scale(${mask.zoom})` : undefined }}><img src={dskThumbUrl(jobId, layer.src)} alt="" style={sourceCrop ? { width: `${100 / sourceCrop.width}%`, height: `${100 / sourceCrop.height}%`, left: `${-100 * sourceCrop.x / sourceCrop.width}%`, top: `${-100 * sourceCrop.y / sourceCrop.height}%`, objectFit: "fill" } : { objectPosition: maskPosition }} /></div>}
          </div>;
        })}
        <button type="button" className="dsk-resize-handle" aria-label="Resize output frame" onPointerDown={(event) => { event.stopPropagation(); gesture.current = { kind: "resize", x: event.clientX, y: event.clientY, frame }; event.currentTarget.setPointerCapture(event.pointerId); }} />
      </div>
    </div>
    <div className="dsk-preview-nudges" aria-label="Position controls">
      {alignments.map((alignment) => <button key={alignment} type="button" aria-label={`Align ${alignment}`} aria-pressed={effectiveAlignment(state, composition) === alignment} onClick={() => dispatch({ type: "decision", id: composition.id, change: { alignment } })}>{glyph(alignment)}</button>)}
      <button type="button" aria-label="Widen frame" onClick={() => dispatch({ type: "viewport", id: composition.id, viewport: { width: frame.width + 1 } })}>W +</button>
      <button type="button" aria-label="Narrow frame" onClick={() => dispatch({ type: "viewport", id: composition.id, viewport: { width: frame.width - 1 } })}>W −</button>
    </div>
  </section>;
}

function Inspector({ state, dispatch }: { state: DskEditorState; dispatch: (action: DskEditorAction, persist?: boolean) => void }) {
  const composition = selectedComposition(state); if (!composition) return null;
  const viewport = effectiveViewport(state, composition);
  const activeMovies = composition.media.filter((media) => media.kind === "movie" && media.sourceModes.includes(composition.decision.source));
  const maskable = composition.capabilities.mask && activeMovies.length > 0;
  const selectedMedia = activeMovies.find((media) => media.occurrenceId === state.selectedMediaId)?.occurrenceId || activeMovies[0]?.occurrenceId || "";
  const mask = selectedMask(state, composition, selectedMedia);
  return <aside className="dsk-inspector">
    <label className="dsk-check"><input type="checkbox" checked={composition.decision.include} onChange={(event) => dispatch({ type: "decision", id: composition.id, change: { include: event.target.checked } }, true)} /> Include</label>
    <fieldset><legend>Position</legend><div className="dsk-align-row">{alignments.map((alignment) => <button key={alignment} type="button" aria-label={`Align ${alignment}`} aria-pressed={effectiveAlignment(state, composition) === alignment} onClick={() => dispatch({ type: "decision", id: composition.id, change: { alignment } }, true)}>{glyph(alignment)}</button>)}</div></fieldset>
    <fieldset><legend>Size</legend><div className="dsk-size-row"><label>W<input aria-label="Width" type="number" value={viewport.width} onChange={(event) => { const value = number(event.target.value); if (value != null) dispatch({ type: "viewport", id: composition.id, viewport: { width: value } }); }} onBlur={() => dispatch({ type: "selectMedia", occurrenceId: state.selectedMediaId }, true)} /></label><label>H<input aria-label="Height" type="number" value={viewport.height} onChange={(event) => { const value = number(event.target.value); if (value != null) dispatch({ type: "viewport", id: composition.id, viewport: { height: value } }); }} onBlur={() => dispatch({ type: "selectMedia", occurrenceId: state.selectedMediaId }, true)} /></label></div><label className="dsk-check"><input type="checkbox" checked={viewport.aspectLocked} onChange={(event) => dispatch({ type: "viewport", id: composition.id, viewport: { aspectLocked: event.target.checked } }, true)} /> Lock ratio</label><button type="button" className="link-button" onClick={() => dispatch({ type: "resetViewport", id: composition.id }, true)}>Use defaults</button></fieldset>
    <div className="dsk-segment"><button type="button" aria-pressed={composition.decision.contentMode === "full"} onClick={() => dispatch({ type: "decision", id: composition.id, change: { contentMode: "full" } }, true)}>Full slide</button>{composition.capabilities.videoOnly && activeMovies.length > 0 && <button type="button" aria-pressed={composition.decision.contentMode === "video"} onClick={() => dispatch({ type: "decision", id: composition.id, change: { contentMode: "video" } }, true)}>Video only</button>}</div>
    <div className="dsk-segment source"><button type="button" aria-pressed={composition.decision.source === "lw"} onClick={() => dispatch({ type: "decision", id: composition.id, change: { source: "lw", ...(composition.media.some((media) => media.kind === "movie" && media.sourceModes.includes("lw")) ? {} : { contentMode: "full" }) } }, true)}>LW</button><button type="button" aria-pressed={composition.decision.source === "fw"} onClick={() => dispatch({ type: "decision", id: composition.id, change: { source: "fw", ...(composition.media.some((media) => media.kind === "movie" && media.sourceModes.includes("fw")) ? {} : { contentMode: "full" }) } }, true)}>FW</button></div>
    {maskable && <fieldset><legend>Video mask</legend>{activeMovies.length > 1 && <label>Media<select aria-label="Mask media" value={selectedMedia} onChange={(event) => dispatch({ type: "selectMedia", occurrenceId: event.target.value }, true)}>{activeMovies.map((media, index) => <option key={media.occurrenceId} value={media.occurrenceId}>Video {index + 1}</option>)}</select></label>}<label>Zoom<input aria-label="Zoom" type="range" min="1" max="3" step="0.05" value={mask.zoom} onChange={(event) => dispatch({ type: "mask", id: composition.id, occurrenceId: selectedMedia, mask: { zoom: Number(event.target.value) } })} onMouseUp={() => dispatch({ type: "selectMedia", occurrenceId: selectedMedia }, true)} /></label><label>Pan X<input aria-label="Pan X" type="range" min="-1" max="1" step="0.01" value={mask.panX} onChange={(event) => dispatch({ type: "mask", id: composition.id, occurrenceId: selectedMedia, mask: { panX: Number(event.target.value) } })} onMouseUp={() => dispatch({ type: "selectMedia", occurrenceId: selectedMedia }, true)} /></label><label>Pan Y<input aria-label="Pan Y" type="range" min="-1" max="1" step="0.01" value={mask.panY} onChange={(event) => dispatch({ type: "mask", id: composition.id, occurrenceId: selectedMedia, mask: { panY: Number(event.target.value) } })} onMouseUp={() => dispatch({ type: "selectMedia", occurrenceId: selectedMedia }, true)} /></label></fieldset>}
    {composition.warnings.map((warning) => <p key={warning} className="note">{warning}</p>)}
  </aside>;
}

export function DskReviewWorkspace({ jobId, state, onChange }: Props) {
  const [draft, setDraft] = useState(state); useEffect(() => setDraft(state), [state]);
  const dispatch = (action: DskEditorAction, persist = false) => { const next = dskEditorReducer(draft, action); setDraft(next); onChange(next, persist); };
  return <section className="dsk-workspace"><div className="dsk-defaults"><strong>Global defaults</strong><label>W<input aria-label="Default width" type="number" value={draft.review.defaults.viewport.width} onChange={(event) => { const value = number(event.target.value); if (value != null) dispatch({ type: "defaults", viewport: { width: value } }); }} onBlur={() => dispatch({ type: "selectMedia", occurrenceId: draft.selectedMediaId }, true)} /></label><label>H<input aria-label="Default height" type="number" value={draft.review.defaults.viewport.height} onChange={(event) => { const value = number(event.target.value); if (value != null) dispatch({ type: "defaults", viewport: { height: value } }); }} onBlur={() => dispatch({ type: "selectMedia", occurrenceId: draft.selectedMediaId }, true)} /></label><label className="dsk-check"><input type="checkbox" checked={draft.review.defaults.viewport.aspectLocked} onChange={(event) => dispatch({ type: "defaults", viewport: { aspectLocked: event.target.checked } }, true)} /> Lock ratio</label>{alignments.map((alignment) => <button key={alignment} type="button" aria-label={`Default ${alignment} alignment`} aria-pressed={draft.review.defaults.alignment === alignment} onClick={() => dispatch({ type: "defaults", alignment }, true)}>{glyph(alignment)}</button>)}</div><div className="dsk-editor-grid"><SlideRail jobId={jobId} state={draft} dispatch={dispatch} /><OutputPreview jobId={jobId} state={draft} dispatch={dispatch} /><Inspector state={draft} dispatch={dispatch} /></div></section>;
}
