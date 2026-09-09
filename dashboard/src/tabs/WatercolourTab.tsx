import { useEffect, useRef, useState } from "react";
import { cancelWatercolour, fetchWatercolourPreview, pollJob, startWatercolour } from "../api";
import { ErrorNotice } from "../components/ErrorNotice";
import { FileWell } from "../components/FileWell";
import { Lightbox, LoadingOverlay } from "../components/PreviewGrid";
import { WatercolourResultView } from "../components/WatercolourResultView";
import { useCurrentJob } from "../sessions";
import { floodFill } from "../watercolour/floodFill";
import { sobelMagnitude, snapToEdge } from "../watercolour/edges";
import { createHistory, push as pushHistory, undo as undoHistory, redo as redoHistory, canUndo, canRedo } from "../watercolour/history";
import { loupeCorner } from "../watercolour/loupe";

type MaskSpec = {
  transparent: boolean;
  rect?: [number, number, number, number];
  foreground?: [number, number][];
  background?: [number, number][];
  keepMask?: string;
  removeMask?: string;
  maskSize?: [number, number];
};

type MaskMode = "rect" | "pen" | "magnetic" | "wand";
type Polarity = "keep" | "remove";

const MASK_STATUS: Record<MaskMode, string> = {
  rect: "Drag to box the landmark",
  pen: "Click to place points",
  magnetic: "Move along an edge",
  wand: "Click a colour to select it",
};

const MASK_HINT: Record<MaskMode, string> = {
  rect: "Drag a box around the landmark. Everything outside the box is removed.",
  pen: "Click to place points around an area, click the first point to close. Keep/Remove decides what the area does.",
  magnetic: "Move along an edge; points snap to it. Click to pin a point, click the first point to close.",
  wand: "Click a colour to select it. Tolerance widens the match.",
};

const WORKING_MAX_SIDE = 640;
const CLOSE_RADIUS_PX = 8;
const AUTO_ANCHOR_STEP = 6;

const transcoded = new Map<File, File>();

async function toSupported(file: File): Promise<File> {
  if (/^image\/(png|jpe?g|webp)$/.test(file.type)) return file;
  const cached = transcoded.get(file);
  if (cached) return cached;
  const bitmap = await createImageBitmap(file);
  const canvas = document.createElement("canvas");
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  const ctx = canvas.getContext("2d")!;
  ctx.drawImage(bitmap, 0, 0);
  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((result) => (result ? resolve(result) : reject(new Error("Could not convert image."))), "image/png");
  });
  const next = new File([blob], file.name.replace(/\.\w+$/, ".png"), { type: "image/png" });
  transcoded.set(file, next);
  return next;
}

function rectOf(drag: { start: [number, number]; now: [number, number] }): [number, number, number, number] {
  return [
    Math.min(drag.start[0], drag.now[0]),
    Math.min(drag.start[1], drag.now[1]),
    Math.abs(drag.now[0] - drag.start[0]),
    Math.abs(drag.now[1] - drag.start[1]),
  ];
}

function encodeMask(mask: Uint8Array, w: number, h: number): string {
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d")!;
  const image = ctx.createImageData(w, h);
  for (let i = 0; i < mask.length; i++) {
    const value = mask[i] ? 255 : 0;
    image.data[i * 4] = value;
    image.data[i * 4 + 1] = value;
    image.data[i * 4 + 2] = value;
    image.data[i * 4 + 3] = 255;
  }
  ctx.putImageData(image, 0, 0);
  return canvas.toDataURL("image/png").replace(/^data:image\/png;base64,/, "");
}

function decodeMaskInto(base64: string, ww: number, wh: number): Promise<Uint8Array> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = ww;
      canvas.height = wh;
      const ctx = canvas.getContext("2d")!;
      ctx.drawImage(img, 0, 0, ww, wh);
      const data = ctx.getImageData(0, 0, ww, wh).data;
      const buffer = new Uint8Array(ww * wh);
      for (let i = 0; i < buffer.length; i++) buffer[i] = data[i * 4] > 127 ? 1 : 0;
      resolve(buffer);
    };
    img.onerror = reject;
    img.src = `data:image/png;base64,${base64}`;
  });
}

function overlayDataUrl(keep: Uint8Array, remove: Uint8Array, w: number, h: number): string {
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d")!;
  const image = ctx.createImageData(w, h);
  for (let i = 0; i < keep.length; i++) {
    const offset = i * 4;
    if (keep[i]) {
      image.data[offset] = 60; image.data[offset + 1] = 200; image.data[offset + 2] = 120; image.data[offset + 3] = 90;
    } else if (remove[i]) {
      image.data[offset] = 220; image.data[offset + 1] = 60; image.data[offset + 2] = 60; image.data[offset + 3] = 90;
    }
  }
  ctx.putImageData(image, 0, 0);
  return canvas.toDataURL("image/png");
}

function MaskEditor({
  file,
  spec,
  mode,
  polarity,
  tolerance,
  magnifierOn,
  compareOn,
  cutoutUrl,
  onChange,
}: {
  file: File;
  spec: MaskSpec;
  mode: MaskMode;
  polarity: Polarity;
  tolerance: number;
  magnifierOn: boolean;
  compareOn: boolean;
  cutoutUrl: string;
  onChange: (next: MaskSpec) => void;
}) {
  const [url, setUrl] = useState("");
  const [size, setSize] = useState<[number, number]>([1, 1]);
  const [drag, setDrag] = useState<{ start: [number, number]; now: [number, number] } | null>(null);
  const [path, setPath] = useState<[number, number][] | null>(null);
  const [cursor, setCursor] = useState<[number, number] | null>(null);
  const [hardAnchors, setHardAnchors] = useState<boolean[]>([]);
  const [travel, setTravel] = useState(0);
  const [hover, setHover] = useState<[number, number] | null>(null);
  const [split, setSplit] = useState(50);
  const [altHeld, setAltHeld] = useState(false);
  const [rect, setRect] = useState({ width: 1, height: 1 });
  const rootRef = useRef<HTMLDivElement | null>(null);
  const workingRef = useRef<{ ww: number; wh: number; data: Uint8ClampedArray } | null>(null);
  const gradRef = useRef<Float32Array | null>(null);
  const keepRef = useRef<Uint8Array | null>(null);
  const removeRef = useRef<Uint8Array | null>(null);
  const [overlayUrl, setOverlayUrl] = useState("");
  const encodeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const next = URL.createObjectURL(file);
    setUrl(next);
    workingRef.current = null;
    gradRef.current = null;
    keepRef.current = null;
    removeRef.current = null;
    setOverlayUrl("");
    return () => {
      URL.revokeObjectURL(next);
      if (encodeTimer.current) clearTimeout(encodeTimer.current);
    };
  }, [file]);

  useEffect(() => {
    function clearAlt() {
      setAltHeld(false);
    }
    window.addEventListener("blur", clearAlt);
    return () => window.removeEventListener("blur", clearAlt);
  }, []);

  function ensureWorking(img: HTMLImageElement): { ww: number; wh: number; data: Uint8ClampedArray } {
    if (workingRef.current) return workingRef.current;
    const scale = Math.min(1, WORKING_MAX_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
    const ww = Math.max(1, Math.round(img.naturalWidth * scale));
    const wh = Math.max(1, Math.round(img.naturalHeight * scale));
    const canvas = document.createElement("canvas");
    canvas.width = ww;
    canvas.height = wh;
    const ctx = canvas.getContext("2d")!;
    ctx.drawImage(img, 0, 0, ww, wh);
    const data = ctx.getImageData(0, 0, ww, wh).data;
    const working = { ww, wh, data: new Uint8ClampedArray(data) };
    workingRef.current = working;
    if (!keepRef.current || keepRef.current.length !== ww * wh) keepRef.current = new Uint8Array(ww * wh);
    if (!removeRef.current || removeRef.current.length !== ww * wh) removeRef.current = new Uint8Array(ww * wh);
    if (spec.keepMask || spec.removeMask) {
      const keep = keepRef.current;
      const remove = removeRef.current;
      Promise.all([
        spec.keepMask ? decodeMaskInto(spec.keepMask, ww, wh) : null,
        spec.removeMask ? decodeMaskInto(spec.removeMask, ww, wh) : null,
      ]).then(([decodedKeep, decodedRemove]) => {
        if (workingRef.current !== working) return;
        if (decodedKeep) keep.set(decodedKeep);
        if (decodedRemove) remove.set(decodedRemove);
        setOverlayUrl(overlayDataUrl(keep, remove, ww, wh));
      });
    }
    return working;
  }

  function ensureGrad(): Float32Array {
    if (gradRef.current) return gradRef.current;
    const working = workingRef.current;
    if (!working) return new Float32Array(0);
    const grad = sobelMagnitude(working.data, working.ww, working.wh);
    gradRef.current = grad;
    return grad;
  }

  function point(event: React.PointerEvent<HTMLImageElement>): [number, number] {
    const box = event.currentTarget.getBoundingClientRect();
    return [
      Math.max(0, Math.min(event.currentTarget.naturalWidth, ((event.clientX - box.left) / box.width) * event.currentTarget.naturalWidth)),
      Math.max(0, Math.min(event.currentTarget.naturalHeight, ((event.clientY - box.top) / box.height) * event.currentTarget.naturalHeight)),
    ];
  }

  function toWorking([x, y]: [number, number]): [number, number] {
    const working = workingRef.current;
    if (!working) return [x, y];
    return [(x / size[0]) * working.ww, (y / size[1]) * working.wh];
  }

  function scheduleSerialise() {
    if (encodeTimer.current) clearTimeout(encodeTimer.current);
    encodeTimer.current = setTimeout(() => {
      const working = workingRef.current;
      const keep = keepRef.current;
      const remove = removeRef.current;
      if (!working || !keep || !remove) return;
      onChange({
        ...spec,
        transparent: true,
        keepMask: encodeMask(keep, working.ww, working.wh),
        removeMask: encodeMask(remove, working.ww, working.wh),
        maskSize: [working.ww, working.wh],
      });
      setOverlayUrl(overlayDataUrl(keep, remove, working.ww, working.wh));
    }, 150);
  }

  function applyRegion(region: Uint8Array) {
    const keep = keepRef.current;
    const remove = removeRef.current;
    if (!keep || !remove) return;
    const target = polarity === "keep" ? keep : remove;
    const other = polarity === "keep" ? remove : keep;
    for (let i = 0; i < region.length; i++) {
      if (region[i]) {
        target[i] = 1;
        other[i] = 0;
      }
    }
    scheduleSerialise();
  }

  function rasterisePath(closed: [number, number][]) {
    const working = workingRef.current;
    if (!working || closed.length < 3) return;
    const canvas = document.createElement("canvas");
    canvas.width = working.ww;
    canvas.height = working.wh;
    const ctx = canvas.getContext("2d")!;
    ctx.beginPath();
    ctx.moveTo(closed[0][0], closed[0][1]);
    for (const [px, py] of closed.slice(1)) ctx.lineTo(px, py);
    ctx.closePath();
    ctx.fillStyle = "#fff";
    ctx.fill("nonzero");
    const data = ctx.getImageData(0, 0, working.ww, working.wh).data;
    const region = new Uint8Array(working.ww * working.wh);
    for (let i = 0; i < region.length; i++) region[i] = data[i * 4 + 3] > 127 ? 1 : 0;
    applyRegion(region);
  }

  function closePath() {
    if (path && path.length >= 3) rasterisePath(path);
    setPath(null);
    setCursor(null);
    setHardAnchors([]);
    setTravel(0);
  }

  function cancelPath() {
    setPath(null);
    setCursor(null);
    setHardAnchors([]);
    setTravel(0);
  }

  function popVertex() {
    setPath((current) => {
      if (!current || current.length === 0) return current;
      if (mode !== "magnetic") return current.slice(0, -1);
      let cut = current.length - 1;
      while (cut > 0 && !hardAnchors[cut]) cut--;
      return current.slice(0, cut);
    });
    setHardAnchors((anchors) => {
      if (anchors.length === 0) return anchors;
      let cut = anchors.length - 1;
      while (cut > 0 && !anchors[cut]) cut--;
      return anchors.slice(0, cut);
    });
  }

  function nearFirst(p: [number, number]): boolean {
    if (!path || path.length < 3) return false;
    const working = workingRef.current;
    if (!working) return false;
    const dx = ((p[0] - path[0][0]) / working.ww) * size[0];
    const dy = ((p[1] - path[0][1]) / working.wh) * size[1];
    return Math.hypot(dx, dy) <= CLOSE_RADIUS_PX;
  }

  const liveRect = drag ? rectOf(drag) : spec.rect;
  const keepPx = keepRef.current ? keepRef.current.reduce((sum, v) => sum + v, 0) : 0;
  const removePx = removeRef.current ? removeRef.current.reduce((sum, v) => sum + v, 0) : 0;

  return (
    <figure className="wash-tile">
      <div
        className="wash-mask"
        ref={rootRef}
        tabIndex={0}
        onKeyDown={(event) => {
          setAltHeld(event.altKey);
          if (mode !== "pen" && mode !== "magnetic") return;
          if (event.key === "Enter") closePath();
          else if (event.key === "Escape") cancelPath();
          else if (event.key === "Backspace") popVertex();
        }}
        onKeyUp={(event) => setAltHeld(event.altKey)}
      >
        <img
          src={url}
          alt="Landmark mask source"
          draggable={false}
          onLoad={(event) => {
            setSize([event.currentTarget.naturalWidth, event.currentTarget.naturalHeight]);
            setRect(event.currentTarget.getBoundingClientRect());
            ensureWorking(event.currentTarget);
          }}
          onPointerDown={(event) => {
            if (event.button !== 0 || compareOn) return;
            event.preventDefault();
            event.currentTarget.setPointerCapture(event.pointerId);
            rootRef.current?.focus();
            if (mode === "rect") {
              setDrag({ start: point(event), now: point(event) });
              return;
            }
            if (mode === "wand") {
              const working = ensureWorking(event.currentTarget);
              const [wx, wy] = toWorking(point(event));
              const region = floodFill(working.data, working.ww, working.wh, Math.round(wx), Math.round(wy), tolerance);
              applyRegion(region);
              return;
            }
            const p = point(event);
            const wp = toWorking(p);
            if (mode === "pen" || mode === "magnetic") {
              if (nearFirst(p)) {
                closePath();
                return;
              }
              setPath((current) => [...(current || []), wp]);
              setHardAnchors((current) => [...current, true]);
              setTravel(0);
            }
          }}
          onPointerMove={(event) => {
            if (compareOn) return;
            const p = point(event);
            setHover(p);
            setRect(event.currentTarget.getBoundingClientRect());
            if (drag) {
              setDrag({ ...drag, now: p });
              return;
            }
            if ((mode === "pen" || mode === "magnetic") && path) {
              const wp = toWorking(p);
              setCursor(wp);
              if (mode === "magnetic" && path.length > 0) {
                const last = path[path.length - 1];
                const step = Math.hypot(wp[0] - last[0], wp[1] - last[1]);
                const nextTravel = travel + step;
                if (nextTravel >= AUTO_ANCHOR_STEP) {
                  const working = workingRef.current;
                  if (working) {
                    const grad = ensureGrad();
                    const [sx, sy] = snapToEdge(grad, working.ww, working.wh, wp[0], wp[1], 8);
                    setPath((current) => [...(current || []), [sx, sy]]);
                    setHardAnchors((current) => [...current, false]);
                    setTravel(0);
                    return;
                  }
                }
                setTravel(nextTravel);
              }
            }
          }}
          onPointerLeave={() => setHover(null)}
          onDoubleClick={() => {
            if (mode === "pen" || mode === "magnetic") closePath();
          }}
          onPointerUp={() => {
            if (mode === "rect" && drag) {
              const [minX, minY, w, h] = rectOf(drag);
              if (w >= 4 && h >= 4) onChange({ ...spec, transparent: true, rect: [minX, minY, w, h] });
            }
            setDrag(null);
          }}
        />
        {liveRect && (
          <div
            className="wash-mask-rect"
            style={{
              left: `${(liveRect[0] / size[0]) * 100}%`,
              top: `${(liveRect[1] / size[1]) * 100}%`,
              width: `${(liveRect[2] / size[0]) * 100}%`,
              height: `${(liveRect[3] / size[1]) * 100}%`,
            }}
          />
        )}
        {overlayUrl && <img className="wash-wand-overlay" src={overlayUrl} alt="" />}
        {(mode === "pen" || mode === "magnetic") && path && workingRef.current && (
          <svg className="wash-pen-overlay" viewBox="0 0 100 100" preserveAspectRatio="none">
            <polyline
              className={`pen-line ${polarity}`}
              vectorEffect="non-scaling-stroke"
              fill="none"
              points={path
                .map(([px, py]) => `${(px / workingRef.current!.ww) * 100},${(py / workingRef.current!.wh) * 100}`)
                .join(" ")}
            />
            {cursor && (
              <line
                className={`pen-line ${polarity}`}
                vectorEffect="non-scaling-stroke"
                x1={(path[path.length - 1][0] / workingRef.current.ww) * 100}
                y1={(path[path.length - 1][1] / workingRef.current.wh) * 100}
                x2={(cursor[0] / workingRef.current.ww) * 100}
                y2={(cursor[1] / workingRef.current.wh) * 100}
              />
            )}
            {path.map(([px, py], index) => (
              <circle
                key={index}
                className={`pen-vertex ${polarity}`}
                cx={(px / workingRef.current!.ww) * 100}
                cy={(py / workingRef.current!.wh) * 100}
                r={index === 0 ? 1.6 : 0.9}
                vectorEffect="non-scaling-stroke"
              />
            ))}
          </svg>
        )}
        {compareOn && cutoutUrl && (
          <>
            <img className="wash-compare-shot" src={cutoutUrl} alt="Cut-out preview" style={{ clipPath: `inset(0 0 0 ${split}%)` }} />
            <div
              className="wash-compare-handle"
              style={{ left: `${split}%` }}
              onPointerDown={(event) => {
                event.currentTarget.setPointerCapture(event.pointerId);
              }}
              onPointerMove={(event) => {
                if (event.buttons !== 1) return;
                const box = rootRef.current!.getBoundingClientRect();
                setSplit(Math.min(100, Math.max(0, ((event.clientX - box.left) / box.width) * 100)));
              }}
            />
          </>
        )}
        {(magnifierOn || altHeld) && hover && !compareOn && (
          <div
            className={`wash-loupe ${loupeCorner(hover[0], hover[1], size[0], size[1])}`}
            style={{
              backgroundImage: `url(${url})`,
              backgroundSize: `${rect.width * 3}px ${rect.height * 3}px`,
              backgroundPosition: `${-(hover[0] / size[0]) * rect.width * 3 + 80}px ${-(hover[1] / size[1]) * rect.height * 3 + 80}px`,
            }}
          />
        )}
      </div>
      <figcaption className="wash-cap">Photo · {file.name}</figcaption>
      <p className="wash-mask-status">{MASK_STATUS[mode]}</p>
      {(keepPx > 0 || removePx > 0) && (
        <small className="wash-hint" style={{ padding: "0 8px 8px", display: "block" }}>
          {keepPx} keep px · {removePx} remove px
        </small>
      )}
    </figure>
  );
}

function LookSlider({
  label,
  hint,
  value,
  onChange,
}: { label: string; hint: string; value: number; onChange: (next: number) => void }) {
  const [text, setText] = useState(value.toFixed(2));

  function commit(next: number) {
    const clamped = Math.min(1, Math.max(0, next));
    setText(clamped.toFixed(2));
    onChange(clamped);
  }

  return (
    <div className="wash-card">
      <label className="ae-scrub has-slider wash-num">
        <span>{label}:</span>
        <input
          type="range"
          className="ae-scrub-slider"
          min="0"
          max="1"
          step="0.05"
          value={value}
          onChange={(event) => commit(Number(event.target.value))}
        />
        <input
          type="number"
          min="0"
          max="1"
          step="0.05"
          value={text}
          onChange={(event) => {
            const raw = event.target.value;
            setText(raw);
            if (/^\d*\.?\d+$/.test(raw)) onChange(Math.min(1, Math.max(0, Number(raw))));
          }}
          onBlur={() => commit(/^\d*\.?\d+$/.test(text) ? Number(text) : value)}
        />
      </label>
      <small className="wash-hint">{hint}</small>
    </div>
  );
}

function usePreviewImage(
  opts: { wash: number; ink: number; file?: File; mask?: string },
  enabled: boolean,
  delay: number
): { url: string; busy: boolean; error: string } {
  const urlRef = useRef("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!enabled) return;
    setBusy(true);
    const controller = new AbortController();
    async function load() {
      try {
        const blob = await fetchWatercolourPreview(
          { washSoftness: opts.wash, inkAmount: opts.ink, file: opts.file, mask: opts.mask },
          controller.signal
        );
        const next = URL.createObjectURL(blob);
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        urlRef.current = next;
        setUrl(next);
        setError("");
        setBusy(false);
      } catch (err) {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : String(err));
          setBusy(false);
        }
      }
    }
    const timer = setTimeout(() => {
      void load();
    }, delay);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [opts.wash, opts.ink, opts.file, opts.mask, enabled, delay]);

  useEffect(() => {
    return () => {
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    };
  }, []);

  return { url, busy, error };
}

function WatercolourPreview({ wash, ink, file }: { wash: number; ink: number; file?: File }) {
  const { url, busy, error } = usePreviewImage({ wash, ink, file }, true, 150);

  return (
    <figure className="wash-tile wash-preview">
      {url ? (
        <img src={url} alt="Watercolour preview" className={`wash-shot${busy ? " busy" : ""}`} />
      ) : (
        <div className="wash-preview-empty">{error || "Rendering preview…"}</div>
      )}
      <figcaption className="wash-cap">Preview · {file ? file.name : "sample photo"}</figcaption>
    </figure>
  );
}

const TOOL_ICONS: Record<string, JSX.Element> = {
  rect: (
    <svg className="maps-icon" viewBox="0 0 16 16" aria-hidden="true">
      <rect x="2.5" y="3.5" width="11" height="9" rx="1" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="2.4 2" />
    </svg>
  ),
  pen: (
    <svg className="maps-icon" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M3 12 3 6 7 3 12 5 13 10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="3" cy="12" r="1.1" fill="currentColor" stroke="none" />
    </svg>
  ),
  magnetic: (
    <svg className="maps-icon" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M2.5 4 3 9.5 8 12.5 13 8" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M11 10.5v2a1.7 1.7 0 0 0 3.4 0v-2" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M11 10.5h1.1M13.3 10.5h1.1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  ),
  wand: (
    <svg className="maps-icon" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M3.5 13 10 6.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M11 3v2.2M13.8 5.8H11.6M12.6 2.4l-1.6 1.6M9.9 5.1l-1.6 1.6" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  ),
  magnifier: (
    <svg className="maps-icon" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="6.8" cy="6.8" r="4" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M9.7 9.7 13 13" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M6.8 5.1v3.4M5.1 6.8h3.4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  ),
  compare: (
    <svg className="maps-icon" viewBox="0 0 16 16" aria-hidden="true">
      <rect x="2.5" y="2.5" width="11" height="11" rx="1" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M8 2.5v11" stroke="currentColor" strokeWidth="1.5" />
      <path d="M6 8 4.7 8" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      <path d="M5.3 6.9 4 8l1.3 1.1M10 8h1.3M10.7 6.9 12 8l-1.3 1.1" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  reset: (
    <svg className="maps-icon" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M5.6 2.5h4.8L13.5 5.6v4.8L10.4 13.5H5.6L2.5 10.4V5.6z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M6.4 6.4 9.6 9.6M9.6 6.4 6.4 9.6" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  ),
  undo: (
    <svg className="maps-icon" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M3.5 8A4.5 4.5 0 1 0 5.2 4.4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M5.6 2.6 5.1 4.9 7.4 5.3" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  redo: (
    <svg className="maps-icon" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M12.5 8A4.5 4.5 0 1 1 10.8 4.4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M10.4 2.6 10.9 4.9 8.6 5.3" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  keep: (
    <svg className="maps-icon" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="8" cy="8" r="5.2" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M8 5.5v5M5.5 8h5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  ),
  remove: (
    <svg className="maps-icon" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="8" cy="8" r="5.2" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M5.5 8h5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  ),
};

function LandmarkMask({
  files,
  index,
  onIndex,
  spec,
  onChange,
  onReset,
  wash,
  ink,
}: {
  files: File[];
  index: number;
  onIndex: (next: number) => void;
  spec: MaskSpec;
  onChange: (next: MaskSpec) => void;
  onReset: () => void;
  wash: number;
  ink: number;
}) {
  const [mode, setMode] = useState<MaskMode>("rect");
  const [polarity, setPolarity] = useState<Polarity>("keep");
  const [magnifierOn, setMagnifierOn] = useState(true);
  const [compareOn, setCompareOn] = useState(false);
  const [tolerance, setTolerance] = useState(24);
  const [resetGeneration, setResetGeneration] = useState(0);
  const [editGeneration, setEditGeneration] = useState(0);
  const [history, setHistory] = useState(() => createHistory(spec));

  const mask = JSON.stringify(spec);
  const { url: cutoutUrl, busy, error } = usePreviewImage({ wash, ink, file: files[index], mask }, Boolean(spec.rect), 250);

  function selectMode(next: MaskMode) {
    setMode(next);
  }

  function handleCommit(next: MaskSpec) {
    onChange(next);
    setHistory((current) => pushHistory(current, next));
  }

  function handleReset() {
    setResetGeneration((current) => current + 1);
    setHistory((current) => pushHistory(current, { transparent: true }));
    onReset();
  }

  function handleUndo() {
    setHistory((current) => {
      const next = undoHistory(current);
      if (next !== current) {
        onChange(next.present);
        setEditGeneration((generation) => generation + 1);
      }
      return next;
    });
  }

  function handleRedo() {
    setHistory((current) => {
      const next = redoHistory(current);
      if (next !== current) {
        onChange(next.present);
        setEditGeneration((generation) => generation + 1);
      }
      return next;
    });
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || target.isContentEditable)) return;
      if (!(event.metaKey || event.ctrlKey)) return;
      const key = event.key.toLowerCase();
      if (key === "z") {
        event.preventDefault();
        if (event.shiftKey) handleRedo();
        else handleUndo();
      } else if (key === "y") {
        event.preventDefault();
        handleRedo();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onChange]);

  const file = files[index];

  return (
    <div className="wash-look" tabIndex={-1}>
      <MaskEditor
        key={`${file.name}-${file.size}-${resetGeneration}-${editGeneration}`}
        file={file}
        spec={spec}
        mode={mode}
        polarity={polarity}
        tolerance={tolerance}
        magnifierOn={magnifierOn}
        compareOn={compareOn}
        cutoutUrl={cutoutUrl}
        onChange={handleCommit}
      />
      <div className="wash-look-col">
        {files.length > 1 && (
          <label className="wash-card">
            <span className="wash-card-title">Photo</span>
            <select value={index} onChange={(event) => onIndex(Number(event.target.value))}>
              {files.map((file, fileIndex) => (
                <option key={`${file.name}-${fileIndex}`} value={fileIndex}>
                  {file.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="maps-stylebar">
          <button
            className={`btn secondary icon-btn toggle${mode === "rect" ? " on" : ""}`}
            type="button"
            title="Landmark box — drag a rectangle"
            aria-label="Landmark box"
            onClick={() => selectMode("rect")}
          >
            {TOOL_ICONS.rect}
          </button>
          <button
            className={`btn secondary icon-btn toggle${mode === "pen" ? " on" : ""}`}
            type="button"
            title="Pen — click points, click the first to close"
            aria-label="Pen"
            onClick={() => selectMode("pen")}
          >
            {TOOL_ICONS.pen}
          </button>
          <button
            className={`btn secondary icon-btn toggle${mode === "magnetic" ? " on" : ""}`}
            type="button"
            title="Magnetic pen — snaps points to edges"
            aria-label="Magnetic pen"
            onClick={() => selectMode("magnetic")}
          >
            {TOOL_ICONS.magnetic}
          </button>
          <button
            className={`btn secondary icon-btn toggle${mode === "wand" ? " on" : ""}`}
            type="button"
            title="Wand — click to select by colour"
            aria-label="Wand"
            onClick={() => selectMode("wand")}
          >
            {TOOL_ICONS.wand}
          </button>
          <button
            className={`btn secondary icon-btn toggle${magnifierOn ? " on" : ""}`}
            type="button"
            title="Magnifier — click to toggle, or hold Option to peek while off"
            aria-label="Magnifier"
            onClick={() => setMagnifierOn((current) => !current)}
          >
            {TOOL_ICONS.magnifier}
          </button>
          <button
            className={`btn secondary icon-btn toggle${compareOn ? " on" : ""}`}
            type="button"
            title="Compare"
            aria-label="Compare"
            onClick={() => setCompareOn((current) => !current)}
          >
            {TOOL_ICONS.compare}
          </button>
          <button
            className="btn secondary icon-btn"
            type="button"
            title="Undo"
            aria-label="Undo"
            disabled={!canUndo(history)}
            onClick={handleUndo}
          >
            {TOOL_ICONS.undo}
          </button>
          <button
            className="btn secondary icon-btn"
            type="button"
            title="Redo"
            aria-label="Redo"
            disabled={!canRedo(history)}
            onClick={handleRedo}
          >
            {TOOL_ICONS.redo}
          </button>
          <button className="btn secondary icon-btn" type="button" title="Reset" aria-label="Reset" onClick={handleReset}>
            {TOOL_ICONS.reset}
          </button>
        </div>
        {(mode === "pen" || mode === "magnetic" || mode === "wand") && (
          <div className="maps-stylebar">
            <button
              className={`btn secondary icon-btn toggle${polarity === "keep" ? " on" : ""}`}
              type="button"
              title="Keep — the traced area is kept"
              aria-label="Keep"
              onClick={() => setPolarity("keep")}
            >
              {TOOL_ICONS.keep}
            </button>
            <button
              className={`btn secondary icon-btn toggle${polarity === "remove" ? " on" : ""}`}
              type="button"
              title="Remove — the traced area is cut away"
              aria-label="Remove"
              onClick={() => setPolarity("remove")}
            >
              {TOOL_ICONS.remove}
            </button>
          </div>
        )}
        {mode === "wand" && (
          <div className="wash-card">
            <label className="ae-scrub has-slider wash-num">
              <span>Tolerance:</span>
              <input
                type="range"
                className="ae-scrub-slider"
                min="0"
                max="100"
                step="1"
                value={tolerance}
                onChange={(event) => setTolerance(Number(event.target.value))}
              />
              <input
                type="number"
                min="0"
                max="100"
                step="1"
                value={tolerance}
                onChange={(event) => setTolerance(Math.min(100, Math.max(0, Number(event.target.value) || 0)))}
              />
            </label>
          </div>
        )}
        <figure className="wash-tile">
          {cutoutUrl ? (
            <img className="wash-shot alpha" src={cutoutUrl} alt="Cut-out preview" />
          ) : (
            <div className="wash-preview-empty">{busy ? "Rendering cut-out…" : "Draw a box to preview"}</div>
          )}
          <figcaption className="wash-cap">Cut-out preview</figcaption>
        </figure>
        <div className="wash-card">
          <small className="wash-hint">{MASK_HINT[mode]}</small>
          {error && <small className="wash-hint">{error}</small>}
          <small className="wash-hint">Hold Option to peek with the magnifier while it is off.</small>
        </div>
      </div>
    </div>
  );
}

export function WatercolourTab() {
  const { job, upsert, error: openError } = useCurrentJob("watercolour");
  const [files, setFiles] = useState<File[]>([]);
  const [wash, setWash] = useState(0.65);
  const [ink, setInk] = useState(0.42);
  const [transparent, setTransparent] = useState(false);
  const [maskFile, setMaskFile] = useState(0);
  const [masks, setMasks] = useState<Record<string, MaskSpec>>({});
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const cancelRef = useRef(false);

  async function selectFiles(next: File[]) {
    const resolved = await Promise.all(next.map(toSupported));
    setFiles(resolved);
    setMasks({});
    setMaskFile(0);
  }

  function resetMask(index: number) {
    setMasks((current) => {
      const next = { ...current };
      delete next[String(index)];
      return next;
    });
  }

  async function convert() {
    setError(null);
    setBusy(true);
    cancelRef.current = false;
    const selectedMasks: Record<string, MaskSpec> = {};
    if (transparent) {
      for (const [index] of files.entries()) {
        const selected = masks[String(index)];
        selectedMasks[String(index)] = { ...(selected || {}), transparent: true };
      }
    }
    try {
      const created = await startWatercolour(files, { washSoftness: wash, inkAmount: ink, masks: selectedMasks });
      upsert(created);
      setFiles([]);
      const done = await pollJob(
        created.id,
        (tick) => {
          setLogs(tick.logs);
          upsert(tick);
        },
        () => cancelRef.current,
        () => cancelWatercolour(created.id)
      );
      upsert(done);
      if (done.status === "error") setError(done.error || "Watercolour batch failed.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const activeIndex = Math.min(maskFile, Math.max(files.length - 1, 0));

  return (
    <div>
      <h1>Watercolour Studio</h1>
      <p className="lede">
        Local, procedural pencil-and-wash conversions. Finished batches are kept under History.
      </p>

      <div className="row">
        <FileWell
          label="Photos"
          hint="Drop photos here or choose files on this Mac"
          accept="image/png,image/jpeg,image/webp,image/avif,image/heic"
          multiple
          onFiles={selectFiles}
          browseLabel="Choose on this Mac"
        />
      </div>
      {files.length > 0 && <p className="note">{files.map((file) => file.name).join(", ")}</p>}

      <h2>Look</h2>
      <div className="wash-look">
        <WatercolourPreview wash={wash} ink={ink} file={files[0]} />
        <div className="wash-look-col">
          <LookSlider label="Wash softness" hint="Higher = paler washes, less pigment" value={wash} onChange={setWash} />
          <LookSlider label="Ink amount" hint="Higher = stronger pencil lines" value={ink} onChange={setInk} />
          <div className="wash-card">
            <label className="check wash-card-head">
              <input type="checkbox" checked={transparent} onChange={(event) => setTransparent(event.target.checked)} />
              <span className="wash-card-title">Transparent landmark output</span>
            </label>
            <small className="wash-hint">Cuts the landmark out so it can be dropped on a map slide</small>
          </div>
        </div>
      </div>
      {transparent && files.length > 0 && (
        <>
          <div className="history-head">
            <h2>Landmark mask</h2>
          </div>
          <LandmarkMask
            files={files}
            index={activeIndex}
            onIndex={setMaskFile}
            spec={masks[String(activeIndex)] || { transparent: true }}
            onChange={(next) => setMasks((current) => ({ ...current, [String(activeIndex)]: next }))}
            onReset={() => resetMask(activeIndex)}
            wash={wash}
            ink={ink}
          />
        </>
      )}

      <div className="actions">
        <button className="btn" type="button" disabled={!files.length || busy} onClick={() => void convert()}>
          Convert {files.length || ""} photo{files.length === 1 ? "" : "s"}
        </button>
      </div>

      <ErrorNotice message={error || openError} onDismiss={error ? () => setError(null) : undefined} />
      {busy && (
        <LoadingOverlay
          title="Painting…"
          logs={logs}
          onCancel={() => {
            cancelRef.current = true;
          }}
        />
      )}
      {job && (
        <WatercolourResultView
          job={job}
          onOpen={setOpen}
          onError={setError}
          onEdit={(p) => {
            setFiles(p.files);
            setMasks(p.masks as Record<string, MaskSpec>);
            setMaskFile(0);
            setWash(p.wash);
            setInk(p.ink);
            setTransparent(p.transparent);
          }}
        />
      )}
      <Lightbox src={open} onClose={() => setOpen(null)} />
    </div>
  );
}
