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

function MaskEditor({
  file,
  spec,
  onChange,
  onReset,
}: {
  file: File;
  spec: MaskSpec;
  onChange: (next: MaskSpec) => void;
  onReset: () => void;
}) {
  const [url, setUrl] = useState("");
  const [dimensions, setDimensions] = useState<[number, number]>([1, 1]);
  const [mode, setMode] = useState<"rect" | "foreground" | "background">("rect");
  const [drag, setDrag] = useState<[number, number] | null>(null);

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

  function add(kind: "foreground" | "background", next: [number, number]) {
    onChange({ ...spec, [kind]: [...(spec[kind] || []), next] });
  }

  return (
    <div className="watercolour-mask">
      <p className="note">
        Draw a box around the landmark, then click Keep or Remove to correct the mask. The checkerboard shows the
        transparent result area.
      </p>
      <div className="maps-stylebar">
        <button className={`btn secondary${mode === "rect" ? " on" : ""}`} type="button" onClick={() => setMode("rect")}>
          Draw foreground box
        </button>
        <button
          className={`btn secondary${mode === "foreground" ? " on" : ""}`}
          type="button"
          onClick={() => setMode("foreground")}
        >
          Keep brush
        </button>
        <button
          className={`btn secondary${mode === "background" ? " on" : ""}`}
          type="button"
          onClick={() => setMode("background")}
        >
          Remove brush
        </button>
        <button className="btn secondary" type="button" onClick={onReset}>
          Reset mask
        </button>
      </div>
      <div className="wash-checker">
        <img
          src={url}
          alt="Landmark mask source"
          className="wash-mask-img"
          onLoad={(event) => setDimensions([event.currentTarget.naturalWidth, event.currentTarget.naturalHeight])}
          onPointerDown={(event) => {
            if (mode === "rect") {
              event.currentTarget.setPointerCapture(event.pointerId);
              setDrag(point(event));
            }
          }}
          onPointerUp={(event) => {
            const next = point(event);
            if (mode === "rect" && drag) {
              onChange({
                ...spec,
                transparent: true,
                rect: [Math.min(drag[0], next[0]), Math.min(drag[1], next[1]), Math.abs(next[0] - drag[0]), Math.abs(next[1] - drag[1])],
              });
            } else if (mode !== "rect") {
              add(mode, next);
            }
            setDrag(null);
          }}
        />
        {spec.rect && (
          <div
            className="wash-mask-rect"
            style={{
              left: `${(spec.rect[0] / dimensions[0]) * 100}%`,
              top: `${(spec.rect[1] / dimensions[1]) * 100}%`,
              width: `${(spec.rect[2] / dimensions[0]) * 100}%`,
              height: `${(spec.rect[3] / dimensions[1]) * 100}%`,
            }}
          />
        )}
      </div>
    </div>
  );
}

function WatercolourPreview({ wash, ink, file }: { wash: number; ink: number; file?: File }) {
  const urlRef = useRef("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setBusy(true);
    const controller = new AbortController();
    async function load() {
      try {
        const blob = await fetchWatercolourPreview({ washSoftness: wash, inkAmount: ink, file }, controller.signal);
        const next = URL.createObjectURL(blob);
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        urlRef.current = next;
        setUrl(next);
        setBusy(false);
      } catch {
        if (!controller.signal.aborted) setBusy(false);
      }
    }
    const timer = setTimeout(() => {
      void load();
    }, 150);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [wash, ink, file]);

  useEffect(() => {
    return () => {
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    };
  }, []);

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
        <div className="wash-look-controls">
          <label className="settings-block wash-look-item">
            <span>Wash softness {wash.toFixed(2)}</span>
            <input type="range" min="0" max="1" step="0.05" value={wash} onChange={(event) => setWash(Number(event.target.value))} />
            <small className="wash-hint">Higher = paler washes, less pigment</small>
          </label>
          <label className="settings-block wash-look-item">
            <span>Ink amount {ink.toFixed(2)}</span>
            <input type="range" min="0" max="1" step="0.05" value={ink} onChange={(event) => setInk(Number(event.target.value))} />
            <small className="wash-hint">Higher = stronger pencil lines</small>
          </label>
          <div className="wash-look-item">
            <label className="check">
              <input type="checkbox" checked={transparent} onChange={(event) => setTransparent(event.target.checked)} />
              <span>Transparent landmark output</span>
            </label>
            <small className="wash-hint">Cuts the landmark out so it can be dropped on a map slide</small>
          </div>
        </div>
        <WatercolourPreview wash={wash} ink={ink} file={files[0]} />
      </div>
      {transparent && files.length > 0 && (
        <>
          <label className="field">
            Photo
            <select value={maskFile} onChange={(event) => setMaskFile(Number(event.target.value))}>
              {files.map((file, index) => (
                <option key={`${file.name}-${index}`} value={index}>
                  {file.name}
                </option>
              ))}
            </select>
          </label>
          <MaskEditor
            file={files[activeIndex]}
            spec={masks[String(activeIndex)] || { transparent: true }}
            onChange={(next) => setMasks((current) => ({ ...current, [String(activeIndex)]: next }))}
            onReset={() => resetMask(activeIndex)}
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
