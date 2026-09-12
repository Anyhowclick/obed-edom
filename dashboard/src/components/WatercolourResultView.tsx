import { useEffect, useState } from "react";
import {
  addWatercolourToMap,
  fetchWatercolourOriginal,
  fetchWatercolourSpec,
  listJobs,
  watercolourDownloadUrl,
  watercolourImageUrl,
  type Job,
} from "../api";
import { jobLabel } from "../sessions";
import { JobName } from "./JobName";

export type Item = {
  id: string;
  name: string;
  original?: string;
  result?: string;
  width?: number;
  height?: number;
  transparent?: boolean;
  status: "done" | "error" | "cancelled";
  error?: string;
};

function mapLabel(job: Job): string {
  const result = (job.result || {}) as { destPath?: string; slides?: { title?: string }[] };
  if (result.destPath) return result.destPath.split("/").pop() || result.destPath;
  const first = result.slides?.[0]?.title;
  return first || jobLabel(job);
}

export function WatercolourResultView({
  job,
  onOpen,
  onError,
  onEdit,
  onRename,
}: {
  job: Job;
  onOpen: (src: string) => void;
  onError: (message: string | null) => void;
  onEdit?: (payload: { files: File[]; masks: Record<string, unknown>; transparent: boolean; wash: number; ink: number }) => void;
  onRename?: (id: string, name: string) => Promise<Job>;
}) {
  const [mapJobs, setMapJobs] = useState<Job[]>([]);
  const [target, setTarget] = useState("");
  const [added, setAdded] = useState(false);

  function loadMapJobs() {
    return listJobs("maps")
      .then((jobs) => setMapJobs(jobs.filter((candidate) => candidate.status === "done")))
      .catch((err) => onError(err instanceof Error ? err.message : String(err)));
  }

  useEffect(() => {
    void loadMapJobs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.id]);

  const items = (job.result?.items as Item[] | undefined) || [];
  const hasDone = items.some((item) => item.status === "done");
  const hasTransparent = items.some((item) => item.transparent === true);

  async function addToMap(item: Item) {
    const [mapsJobId, slideId] = target.split(":");
    if (!mapsJobId || !slideId) return;
    setAdded(false);
    try {
      await addWatercolourToMap(job.id, item.id, mapsJobId, slideId);
      onError(null);
      setAdded(true);
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    }
  }

  async function editAgain() {
    const done = items.filter((item) => item.status === "done");
    try {
      const files: File[] = [];
      const masks: Record<string, unknown> = {};
      const specs: unknown[] = [];
      for (let index = 0; index < done.length; index += 1) {
        const item = done[index];
        const [file, spec] = await Promise.all([
          fetchWatercolourOriginal(job.id, item.id, item.name),
          fetchWatercolourSpec(job.id, item.id),
        ]);
        files.push(file);
        masks[String(index)] = spec;
        specs.push(spec);
      }
      const result = (job.result || {}) as { washSoftness?: number; inkAmount?: number };
      onError(null);
      onEdit?.({
        files,
        masks,
        transparent: specs.some((spec) => (spec as { transparent?: boolean } | null)?.transparent === true),
        wash: result.washSoftness ?? 0.65,
        ink: result.inkAmount ?? 0.42,
      });
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div>
      {onRename && <JobName job={job} onRename={onRename} className="note" />}
      {hasDone && (
        <div className="actions">
          <a className="btn secondary" href={watercolourDownloadUrl(job.id)}>
            Download batch
          </a>
          {onEdit && (
            <button className="btn secondary" type="button" onClick={() => void editAgain()}>
              Edit again
            </button>
          )}
        </div>
      )}
      {hasTransparent && (
        <label className="field">
          Add landmarks to
          <select value={target} onChange={(event) => setTarget(event.target.value)} onFocus={() => void loadMapJobs()}>
            <option value="">Choose a map slide</option>
            {mapJobs.map((map) => {
              const slides = (map.result?.slides as { id: string; title: string }[] | undefined) || [];
              if (slides.length === 1) {
                return (
                  <option key={map.id} value={`${map.id}:${slides[0].id}`}>
                    {mapLabel(map)}
                  </option>
                );
              }
              return (
                <optgroup key={map.id} label={mapLabel(map)}>
                  {slides.map((slide) => (
                    <option key={`${map.id}:${slide.id}`} value={`${map.id}:${slide.id}`}>
                      {slide.title}
                    </option>
                  ))}
                </optgroup>
              );
            })}
          </select>
        </label>
      )}
      <div className="wash-grid">
        {items.map((item) => (
          <figure key={item.id} className="wash-tile">
            {item.status === "error" ? (
              <figcaption className="err">
                {item.name}: {item.error}
              </figcaption>
            ) : item.status === "cancelled" ? (
              <figcaption className="note">{item.name}: cancelled</figcaption>
            ) : (
              <>
                <div className="wash-pair">
                  <img
                    className="wash-shot"
                    src={watercolourImageUrl(job.id, item.id, "original")}
                    alt={`${item.name} original`}
                    onClick={() => onOpen(watercolourImageUrl(job.id, item.id, "original"))}
                  />
                  <img
                    className={`wash-shot${item.transparent ? " alpha" : ""}`}
                    src={watercolourImageUrl(job.id, item.id, "result")}
                    alt={`${item.name} pencil and wash`}
                    onClick={() => onOpen(watercolourImageUrl(job.id, item.id, "result"))}
                  />
                </div>
                <figcaption className="wash-cap">
                  {item.name} · {item.width}×{item.height}
                </figcaption>
                <div className="row-acts">
                  <a className="btn secondary" download href={watercolourImageUrl(job.id, item.id, "result")}>
                    Download PNG
                  </a>
                  {item.transparent && (
                    <button className="btn secondary" type="button" disabled={!target} onClick={() => void addToMap(item)}>
                      Add to map
                    </button>
                  )}
                </div>
              </>
            )}
          </figure>
        ))}
      </div>
      {added && <p className="ok">Added to that slide.</p>}
    </div>
  );
}
