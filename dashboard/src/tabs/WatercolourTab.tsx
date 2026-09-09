import { useEffect, useRef, useState } from "react";
import { cancelWatercolour, fetchWatercolourPreview, pollJob, startWatercolour } from "../api";
import { ErrorNotice } from "../components/ErrorNotice";
import { FileWell } from "../components/FileWell";
import { Lightbox, LoadingOverlay } from "../components/PreviewGrid";
import { WatercolourResultView } from "../components/WatercolourResultView";
import { useCurrentJob } from "../sessions";

type MaskSpec = {
  transparent: boolean;
  rect?: [number, number, number, number];
  foreground?: [number, number][];
  background?: [number, number][];
};

type MaskMode = "rect" | "foreground" | "background";

const MASK_STATUS: Record<MaskMode, string> = {
  rect: "Drag to box the landmark",
  foreground: "Click to keep",
  background: "Click to remove",
};

function rectOf(drag: { start: [number, number]; now: [number, number] }): [number, number, number, number] {
  return [
    Math.min(drag.start[0], drag.now[0]),
    Math.min(drag.start[1], drag.now[1]),
    Math.abs(drag.now[0] - drag.start[0]),
    Math.abs(drag.now[1] - drag.start[1]),
  ];
}

function MaskEditor({
  file,
  spec,
  mode,
  onChange,
}: {
  file: File;
  spec: MaskSpec;
  mode: MaskMode;
  onChange: (next: MaskSpec) => void;
}) {
  const [url, setUrl] = useState("");
  const [size, setSize] = useState<[number, number]>([1, 1]);
  const [drag, setDrag] = useState<{ start: [number, number]; now: [number, number] } | null>(null);

  useEffect(() => {
    const next = URL.createObjectURL(file);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [file]);

  function point(event: React.PointerEvent<HTMLImageElement>): [number, number] {
    const box = event.currentTarget.getBoundingClientRect();
    return [
      Math.max(0, Math.min(event.currentTarget.naturalWidth, ((event.clientX - box.left) / box.width) * event.currentTarget.naturalWidth)),
      Math.max(0, Math.min(event.currentTarget.naturalHeight, ((event.clientY - box.top) / box.height) * event.currentTarget.naturalHeight)),
    ];
  }

  const liveRect = drag ? rectOf(drag) : spec.rect;

  return (
    <figure className="wash-tile">
      <div className="wash-mask">
        <img
          src={url}
          alt="Landmark mask source"
          draggable={false}
          onLoad={(event) => setSize([event.currentTarget.naturalWidth, event.currentTarget.naturalHeight])}
          onPointerDown={(event) => {
            if (event.button !== 0) return;
            event.preventDefault();
            event.currentTarget.setPointerCapture(event.pointerId);
            if (mode === "rect") setDrag({ start: point(event), now: point(event) });
          }}
          onPointerMove={(event) => {
            if (drag) setDrag({ ...drag, now: point(event) });
          }}
          onPointerUp={(event) => {
            if (mode === "rect" && drag) {
              const [minX, minY, w, h] = rectOf(drag);
              if (w >= 4 && h >= 4) onChange({ ...spec, transparent: true, rect: [minX, minY, w, h] });
            } else if (mode !== "rect") {
              const next = point(event);
              onChange({ ...spec, [mode]: [...(spec[mode] || []), next] });
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
        {(spec.foreground || []).map((pt, index) => (
          <div
            key={`fg-${index}`}
            className="wash-mask-dot keep"
            style={{ left: `${(pt[0] / size[0]) * 100}%`, top: `${(pt[1] / size[1]) * 100}%` }}
          />
        ))}
        {(spec.background || []).map((pt, index) => (
          <div
            key={`bg-${index}`}
            className="wash-mask-dot remove"
            style={{ left: `${(pt[0] / size[0]) * 100}%`, top: `${(pt[1] / size[1]) * 100}%` }}
          />
        ))}
      </div>
      <figcaption className="wash-cap">Photo · {file.name}</figcaption>
      <p className="wash-mask-status">{MASK_STATUS[mode]}</p>
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
  const { url, busy } = usePreviewImage({ wash, ink, file }, true, 150);

  return (
    <figure className="wash-tile wash-preview">
      {url ? (
        <img src={url} alt="Watercolour preview" className={`wash-shot${busy ? " busy" : ""}`} />
      ) : (
        <div className="wash-preview-empty">Rendering preview…</div>
      )}
      <figcaption className="wash-cap">Preview · {file ? file.name : "sample photo"}</figcaption>
    </figure>
  );
}

function CutoutPreview({ wash, ink, file, spec }: { wash: number; ink: number; file: File; spec: MaskSpec }) {
  const mask = JSON.stringify(spec);
  const { url, busy, error } = usePreviewImage({ wash, ink, file, mask }, Boolean(spec.rect), 250);

  return (
    <figure className="wash-tile">
      {spec.rect && url ? (
        <img src={url} alt="Landmark cut-out preview" className={`wash-shot alpha${busy ? " busy" : ""}`} />
      ) : (
        <div className="wash-preview-empty">Draw the landmark box to see the cut-out.</div>
      )}
      <figcaption className="wash-cap">Cut-out · {file.name}</figcaption>
      {error && <small className="wash-hint">{error}</small>}
    </figure>
  );
}

const MASK_HINT: Record<MaskMode, string> = {
  rect: "Drag a box around the landmark. Everything outside the box is removed.",
  foreground: "Click parts inside the box that were wrongly cut away.",
  background: "Click parts that should be transparent.",
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
  const keep = (spec.foreground || []).length;
  const remove = (spec.background || []).length;

  return (
    <div className="wash-look">
      <MaskEditor file={files[index]} spec={spec} mode={mode} onChange={onChange} />
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
        <div className="wash-card">
          <span className="wash-card-title">Mask tools</span>
          <div className="maps-stylebar">
            <button className={`btn secondary toggle${mode === "rect" ? " on" : ""}`} type="button" onClick={() => setMode("rect")}>
              Landmark box
            </button>
            <button
              className={`btn secondary toggle${mode === "foreground" ? " on" : ""}`}
              type="button"
              onClick={() => setMode("foreground")}
            >
              Keep
            </button>
            <button
              className={`btn secondary toggle${mode === "background" ? " on" : ""}`}
              type="button"
              onClick={() => setMode("background")}
            >
              Remove
            </button>
            <button className="btn secondary" type="button" onClick={onReset}>
              Reset
            </button>
          </div>
          <small className="wash-hint">{MASK_HINT[mode]}</small>
          {keep + remove > 0 && (
            <small className="wash-hint">
              {keep} keep · {remove} remove points
            </small>
          )}
        </div>
        <div className="wash-card">
          <span className="wash-card-title">Cut-out preview</span>
          <CutoutPreview wash={wash} ink={ink} file={files[index]} spec={spec} />
          <small className="wash-hint">This is what Add to map will place on the slide.</small>
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

  function selectFiles(next: File[]) {
    setFiles(next);
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
          accept="image/png,image/jpeg,image/webp"
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
          <h2>Landmark mask</h2>
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
      {job && <WatercolourResultView job={job} onOpen={setOpen} onError={setError} />}
      <Lightbox src={open} onClose={() => setOpen(null)} />
    </div>
  );
}
