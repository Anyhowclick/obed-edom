import { useMemo, useState } from "react";
import { generateDocx, pollJob, previewUrl, reveal, type Flag, type Job } from "../api";
import { FileWell } from "../components/FileWell";
import { Lightbox, LoadingOverlay, PreviewGrid } from "../components/PreviewGrid";
import { ValidationPanel } from "../components/ValidationPanel";

type GenResult = {
  stem: string;
  outputDir: string;
  lwKey?: string;
  dskKey?: string;
  cuedDocx?: string;
  reviewPath?: string;
  previewFiles: { lw: string[]; dsk: string[] };
  flags: Flag[];
  lwCount: number;
  dskCount: number;
};

export function GeneratorTab() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [deck, setDeck] = useState<"lw" | "dsk">("lw");
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const active = jobs.find((j) => j.id === activeId) || jobs[0];
  const result = (active?.result || null) as GenResult | null;

  async function run(files: File[]) {
    const docx = files.filter((f) => f.name.toLowerCase().endsWith(".docx"));
    if (!docx.length) {
      setError("Drop one or more .docx outline files.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const created = await generateDocx(docx);
      setJobs((prev) => [...created, ...prev]);
      setActiveId(created[0]?.id || null);
      for (const job of created) {
        const done = await pollJob(job.id, (tick) => {
          setLogs(tick.logs);
          setJobs((prev) => prev.map((j) => (j.id === tick.id ? tick : j)));
        });
        setJobs((prev) => prev.map((j) => (j.id === done.id ? done : j)));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const urls = useMemo(() => {
    if (!active || !result) return [];
    const names = result.previewFiles?.[deck] || [];
    return names.map((name, i) => ({
      src: previewUrl(active.id, deck, name),
      label: `${deck.toUpperCase()} ${i + 1}`,
    }));
  }, [active, result, deck]);

  const running = jobs.some((j) => j.status === "queued" || j.status === "running");

  return (
    <div>
      <h1>Sermon Base Generator</h1>
      <p className="lede">
        Drop sermon or offering outlines. Each file is generated in sequence (Keynote is single-instance)
        into LW and DSK decks plus preview PNGs.
      </p>
      <FileWell
        label="Sermon outline (.docx)"
        hint="Drag and drop one or more Word outlines"
        accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        multiple
        onFiles={run}
      />
      {error && <p className="err">{error}</p>}
      {(busy || running) && <LoadingOverlay title="Generating decks…" logs={logs} />}

      {jobs.length > 0 && (
        <div className="split">
          <div className="job-list">
            {jobs.map((job) => {
              const stem = ((job.result as GenResult | undefined)?.stem) || job.id;
              return (
                <button
                  key={job.id}
                  className={job.id === active?.id ? "active" : ""}
                  type="button"
                  onClick={() => setActiveId(job.id)}
                >
                  {stem}
                  <div className="cap">{job.status}</div>
                </button>
              );
            })}
          </div>
          <div>
            {active?.status === "error" && <p className="err">{active.error}</p>}
            {result && active?.status === "done" && (
              <>
                <p className="note">
                  {result.lwCount} LW · {result.dskCount} DSK · {result.outputDir}
                </p>
                <div className="actions">
                  {result.lwKey && (
                    <button className="btn secondary" type="button" onClick={() => reveal(result.lwKey!)}>
                      Show LW.key
                    </button>
                  )}
                  {result.dskKey && (
                    <button className="btn secondary" type="button" onClick={() => reveal(result.dskKey!)}>
                      Show DSK.key
                    </button>
                  )}
                  {result.cuedDocx && (
                    <button className="btn secondary" type="button" onClick={() => reveal(result.cuedDocx!)}>
                      Show cued outline
                    </button>
                  )}
                  {result.reviewPath && (
                    <button className="btn secondary" type="button" onClick={() => reveal(result.reviewPath!)}>
                      Show review.pdf
                    </button>
                  )}
                </div>
                <div className="seg">
                  <button type="button" className={deck === "lw" ? "on" : ""} onClick={() => setDeck("lw")}>
                    LW previews
                  </button>
                  <button type="button" className={deck === "dsk" ? "on" : ""} onClick={() => setDeck("dsk")}>
                    DSK previews
                  </button>
                </div>
                <PreviewGrid urls={urls} onOpen={setOpen} />
                <ValidationPanel flags={result.flags || []} />
              </>
            )}
          </div>
        </div>
      )}
      <Lightbox src={open} onClose={() => setOpen(null)} />
    </div>
  );
}
