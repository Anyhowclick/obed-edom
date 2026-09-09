import { useEffect, useMemo, useState } from "react";
import { type Job, listJobs } from "../api";
import { FileWell } from "../components/FileWell";

type MaskSpec = { transparent: boolean; rect?: [number, number, number, number]; foreground?: [number, number][]; background?: [number, number][] };
type Item = { id: string; name: string; original?: string; result?: string; width?: number; height?: number; transparent?: boolean; status: "done" | "error"; error?: string };

function imageUrl(jobId: string, itemId: string, kind: "original" | "result") {
  return `/api/watercolour/${jobId}/items/${itemId}/${kind}`;
}

function MaskEditor({ file, spec, onChange, onReset }: { file: File; spec: MaskSpec; onChange: (next: MaskSpec) => void; onReset: () => void }) {
  const [url, setUrl] = useState("");
  const [dimensions, setDimensions] = useState<[number, number]>([1, 1]);
  const [mode, setMode] = useState<"rect" | "foreground" | "background">("rect");
  const [drag, setDrag] = useState<[number, number] | null>(null);
  useEffect(() => { const next = URL.createObjectURL(file); setUrl(next); return () => URL.revokeObjectURL(next); }, [file]);
  const point = (event: React.PointerEvent<HTMLImageElement>): [number, number] => {
    const box = event.currentTarget.getBoundingClientRect();
    return [Math.max(0, Math.min(event.currentTarget.naturalWidth, (event.clientX - box.left) / box.width * event.currentTarget.naturalWidth)), Math.max(0, Math.min(event.currentTarget.naturalHeight, (event.clientY - box.top) / box.height * event.currentTarget.naturalHeight))];
  };
  const add = (kind: "foreground" | "background", next: [number, number]) => onChange({ ...spec, [kind]: [...(spec[kind] || []), next] });
  return <div className="watercolour-mask"><p className="note">Draw a box around the landmark, then click Keep or Remove to correct the mask. The checkerboard shows the transparent result area.</p><div className="maps-stylebar"><button className={`btn secondary${mode === "rect" ? " on" : ""}`} type="button" onClick={() => setMode("rect")}>Draw foreground box</button><button className={`btn secondary${mode === "foreground" ? " on" : ""}`} type="button" onClick={() => setMode("foreground")}>Keep brush</button><button className={`btn secondary${mode === "background" ? " on" : ""}`} type="button" onClick={() => setMode("background")}>Remove brush</button><button className="btn secondary" type="button" onClick={onReset}>Reset mask</button></div><div style={{ position: "relative", display: "inline-block", background: "repeating-conic-gradient(#ddd 0 25%, #fff 0 50%) 50% / 18px 18px" }}><img src={url} alt="Landmark mask source" style={{ display: "block", maxWidth: "540px", maxHeight: "360px" }} onLoad={(event) => setDimensions([event.currentTarget.naturalWidth, event.currentTarget.naturalHeight])} onPointerDown={(event) => { if (mode === "rect") { event.currentTarget.setPointerCapture(event.pointerId); setDrag(point(event)); } }} onPointerUp={(event) => { const next = point(event); if (mode === "rect" && drag) onChange({ ...spec, transparent: true, rect: [Math.min(drag[0], next[0]), Math.min(drag[1], next[1]), Math.abs(next[0] - drag[0]), Math.abs(next[1] - drag[1])] }); else if (mode !== "rect") add(mode, next); setDrag(null); }} />{spec.rect && <div style={{ position: "absolute", border: "2px solid #e8772a", left: `${spec.rect[0] / dimensions[0] * 100}%`, top: `${spec.rect[1] / dimensions[1] * 100}%`, width: `${spec.rect[2] / dimensions[0] * 100}%`, height: `${spec.rect[3] / dimensions[1] * 100}%`, pointerEvents: "none" }} />}</div></div>;
}

export function WatercolourTab() {
  const [files, setFiles] = useState<File[]>([]);
  const [wash, setWash] = useState(0.65);
  const [ink, setInk] = useState(0.42);
  const [transparent, setTransparent] = useState(false);
  const [maskFile, setMaskFile] = useState(0);
  const [masks, setMasks] = useState<Record<string, MaskSpec>>({});
  const [jobs, setJobs] = useState<Job[]>([]);
  const [mapJobs, setMapJobs] = useState<Job[]>([]);
  const [mapTarget, setMapTarget] = useState("");
  const [error, setError] = useState<string | null>(null);
  const pending = useMemo(() => jobs.some((job) => job.status === "queued" || job.status === "running"), [jobs]);

  async function refresh() {
    try { const [watercolour, maps] = await Promise.all([listJobs("watercolour"), listJobs("maps")]); setJobs(watercolour); setMapJobs(maps.filter((job) => job.status === "done")); } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
  }
  useEffect(() => { void refresh(); }, []);
  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => void refresh(), 600);
    return () => window.clearInterval(timer);
  }, [pending]);

  function selectFiles(next: File[]) {
    setFiles(next);
    setMasks({});
    setMaskFile(0);
  }

  function resetMask(index: number) { setMasks((current) => { const next = { ...current }; delete next[String(index)]; return next; }); }
  async function convertAll() {
    setError(null);
    const selectedMasks: Record<string, MaskSpec> = {};
    if (transparent) {
      for (const [index] of files.entries()) {
        const selected = masks[String(index)];
        selectedMasks[String(index)] = { ...(selected || {}), transparent: true };
      }
    }
    const body = new FormData();
    files.forEach((file) => body.append("files", file));
    body.set("wash_softness", String(wash));
    body.set("ink_amount", String(ink));
    body.set("masks", JSON.stringify(selectedMasks));
    try {
      const response = await fetch("/api/watercolour", { method: "POST", body });
      if (!response.ok) throw new Error((await response.json().catch(() => ({ detail: response.statusText }))).detail);
      selectFiles([]);
      await refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
  }
  async function cancel(jobId: string) {
    const response = await fetch(`/api/watercolour/${jobId}/cancel`, { method: "POST" });
    if (!response.ok) { setError((await response.json().catch(() => ({ detail: response.statusText }))).detail); return; }
    await refresh();
  }
  async function addToMap(jobId: string, item: Item) {
    const [mapId, slideId] = mapTarget.split(":");
    const selectedMap = mapJobs.find((job) => job.id === mapId);
    const maps = selectedMap ? await (await fetch(`/api/jobs/${selectedMap.id}`)).json() as Job : undefined;
    const slide = (maps?.result?.slides as Array<Record<string, unknown>> | undefined)?.find((candidate) => candidate.id === slideId);
    if (!maps || !slide || !item.result || item.status !== "done" || item.transparent !== true) { setError("Choose a completed transparent result and a Maps project and slide."); return; }
    const stored = await fetch(`/api/watercolour/${jobId}/items/${item.id}/add-to-map/${maps.id}/${slideId}`, { method: "POST" });
    if (!stored.ok) { setError((await stored.json().catch(() => ({ detail: stored.statusText }))).detail); return; }
    await refresh();
    setError("Landmark added to the selected Maps slide.");
  }
  return <section className="tab-content"><h1>Watercolour Studio</h1><p className="note">Local, procedural pencil-and-wash conversions. Originals and results remain in this Studio history.</p>
    <FileWell label="Photos" hint="Drop photos here or choose files on this Mac" accept="image/png,image/jpeg,image/webp" multiple onFiles={selectFiles} browseLabel="Choose on this Mac" />
    {files.length > 0 && <p className="note">{files.map((file) => file.name).join(", ")}</p>}
    <label>Wash softness <input type="range" min="0" max="1" step="0.05" value={wash} onChange={(event) => setWash(Number(event.target.value))} /></label>
    <label>Ink amount <input type="range" min="0" max="1" step="0.05" value={ink} onChange={(event) => setInk(Number(event.target.value))} /></label>
    <label><input type="checkbox" checked={transparent} onChange={(event) => setTransparent(event.target.checked)} /> Transparent landmark output</label>
    {transparent && files.length > 0 && <><label>Photo <select value={maskFile} onChange={(event) => setMaskFile(Number(event.target.value))}>{files.map((file, index) => <option key={`${file.name}-${index}`} value={index}>{file.name}</option>)}</select></label><MaskEditor file={files[Math.min(maskFile, files.length - 1)]} spec={masks[String(Math.min(maskFile, files.length - 1))] || { transparent: true }} onChange={(next) => setMasks((current) => ({ ...current, [String(Math.min(maskFile, files.length - 1))]: next }))} onReset={() => resetMask(Math.min(maskFile, files.length - 1))} /></>}
    <button className="btn" type="button" disabled={!files.length || pending} onClick={() => void convertAll()}>Convert {files.length || ""} photo{files.length === 1 ? "" : "s"}</button>
    {error && <p className="error-notice">{error}</p>}
    <label>Maps destination <select value={mapTarget} onChange={(event) => setMapTarget(event.target.value)}><option value="">Choose project and slide</option>{mapJobs.flatMap((map) => ((map.result?.slides as Array<{ id: string; title: string }> | undefined) || []).map((slide) => <option key={`${map.id}:${slide.id}`} value={`${map.id}:${slide.id}`}>{map.id} · {slide.title}</option>))}</select></label>
    {jobs.map((job) => { const items = ((job.result?.items as Item[] | undefined) || []); return <section key={job.id}><h2>{job.status === "running" ? "Converting" : "Watercolour batch"} <span className="note">{job.id}</span></h2>{(job.status === "queued" || job.status === "running") && <button className="btn secondary" type="button" onClick={() => void cancel(job.id)}>Cancel batch</button>}{job.status === "done" && items.some((item) => item.status === "done") && <a className="btn secondary" href={`/api/watercolour/${job.id}/download`}>Download batch</a>}<div className="preview-grid">{items.map((item) => <figure key={item.id}>{item.status === "error" ? <figcaption className="error-notice">{item.name}: {item.error}</figcaption> : <><div><img src={imageUrl(job.id, item.id, "original")} alt={`${item.name} original`} /><img src={imageUrl(job.id, item.id, "result")} alt={`${item.name} pencil and wash`} /></div><figcaption>{item.name} · {item.width}×{item.height}</figcaption><a download={item.result} href={imageUrl(job.id, item.id, "result")}>Download PNG</a> {item.transparent && <button className="btn secondary" type="button" onClick={() => void addToMap(job.id, item)}>Add to map</button>}</>}</figure>)}</div></section>; })}
  </section>;
}
