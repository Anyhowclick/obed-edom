import { useEffect, useMemo, useState } from "react";
import {
  chooseKeynote,
  pollJob,
  startDiff,
  startDiffCheck,
  startOutline,
  validateKeynote,
  type ChosenFile,
  type Job,
} from "../api";
import { CheckResultView } from "../components/CheckResultView";
import { FileWell } from "../components/FileWell";
import { Lightbox, LoadingOverlay } from "../components/PreviewGrid";
import { useLayout } from "../nav";
import type { Slot } from "../playlist";
import { useCurrentJob } from "../sessions";

type Mode = "none" | "outline" | "deck" | "deck+outline" | "pair" | "pair+outline";

function modeOf(outline: ChosenFile | null, a: ChosenFile | null, b: ChosenFile | null): Mode {
  const decks = [a, b].filter(Boolean).length;
  if (decks >= 2) return outline ? "pair+outline" : "pair";
  if (decks === 1) return outline ? "deck+outline" : "deck";
  return outline ? "outline" : "none";
}

const BLURB: Record<Mode, string> = {
  none: "Drop a cued outline, a Keynote, or both.",
  outline: "Checks the cue grammar, scripture references and house style, woven into the script.",
  deck: "House-style checks run read-only on the deck: Bible wording, contrast, overflow, and the rest.",
  "deck+outline":
    "Counts the cues against the slides, then checks the deck's wording against the script.",
  pair: "Matches the two decks, then checks wording and photos. Read-only.",
  "pair+outline":
    "Seeds the pairing from the cues, then resolves any wording difference against the outline first, then LW, then DSK.",
};

function deckLabel(name: string, fallback: string): string {
  if (/dsk/i.test(name)) return "DSK";
  if (/\b(lw|gw|led|fw)\b/i.test(name)) return "LW";
  return fallback;
}

function looksLikeWall(file: ChosenFile | null): boolean {
  return Boolean(file && deckLabel(file.name, "") === "LW");
}

export function CheckTab() {
  const { job, upsert, error: openError } = useCurrentJob("check");
  const { focusMode } = useLayout();
  const [outline, setOutline] = useState<ChosenFile | null>(null);
  const [left, setLeft] = useState<ChosenFile | null>(null);
  const [right, setRight] = useState<ChosenFile | null>(null);
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [lwFinal, setLwFinal] = useState(true);

  const result = (job?.result || undefined) as
    | { path?: string; leftPath?: string; rightPath?: string; outlinePath?: string; kind?: string }
    | undefined;

  useEffect(() => {
    if (!result) return;
    const put = (path: string | undefined, set: (f: ChosenFile | null) => void) => {
      if (path) set({ path, name: path.split("/").pop() || path });
    };
    if (result.kind === "outline") put(result.path, setOutline);
    else put(result.path, setLeft);
    put(result.leftPath, setLeft);
    put(result.rightPath, setRight);
    put(result.outlinePath, setOutline);
  }, [job?.id]);

  const mode = modeOf(outline, left, right);
  const paired = mode === "pair" || mode === "pair+outline";
  const wall = looksLikeWall(left) ? left : looksLikeWall(right) ? right : null;
  const wallPresent = Boolean(wall);
  const wallName = wall?.name || "the LED wall";

  async function pick(which: "outline" | "left" | "right") {
    try {
      const prompt =
        which === "outline"
          ? "Cued outline (.docx or .pdf)"
          : which === "left"
            ? "Final LW Keynote"
            : "Keynote to compare";
      const file = await chooseKeynote(prompt);
      if (which === "outline") setOutline(file);
      else if (which === "left") setLeft(file);
      else setRight(file);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function track(started: Job) {
    upsert(started);
    const done = await pollJob(started.id, (tick) => {
      setLogs(tick.logs);
      upsert(tick);
    });
    upsert(done);
  }

  async function run(fresh = false) {
    if (mode === "none") {
      setError("Choose a cued outline, a Keynote, or both.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      if (paired) {
        const a = left!;
        const b = right!;
        await track(
          await startDiff(
            a.path,
            b.path,
            deckLabel(a.name, "LW"),
            deckLabel(b.name, "Other"),
            fresh,
            outline?.path,
            lwFinal
          )
        );
      } else if (mode === "outline") {
        await track(await startOutline(outline!.path));
      } else {
        const deck = (left || right)!;
        await track(
          await validateKeynote(deck.path, {
            export: true,
            feature: "check",
            outlinePath: outline?.path,
            lwFinal,
          })
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function runChecks(slots: Slot[]) {
    if (!job) return;
    setError(null);
    setBusy(true);
    try {
      await track(await startDiffCheck(job.id, slots));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const overlayTitle = useMemo(() => {
    if (paired) {
      const phase = (job?.result as { phase?: string } | null)?.phase;
      return job?.status === "running" && phase === "match" ? "Checking pairs…" : "Matching Keynotes…";
    }
    return mode === "outline" ? "Reading the outline…" : "Checking Keynote…";
  }, [paired, mode, job?.status, job?.result]);

  return (
    <div className={focusMode ? "diff-tab focus" : "diff-tab"}>
      <div className="diff-setup">
        <h1>Sermon Checker</h1>
        <p className="lede">
          {BLURB[mode]} Read-only: nothing is written back to the outline or the Keynotes. Finished
          checks are kept under History.
        </p>
        <div className="row">
          <FileWell
            label="Cued outline (.docx or .pdf)"
            hint="Optional — _CUED.docx / PDF"
            file={outline}
            tone="document"
            onChoose={() => pick("outline")}
            onPath={(path) => setOutline({ path, name: path.split("/").pop() || path })}
            onClear={() => setOutline(null)}
            onError={setError}
          />
          <FileWell
            label="Keynote (.key)"
            hint="Drop from Finder or choose on this Mac"
            file={left}
            onChoose={() => pick("left")}
            onPath={(path) => setLeft({ path, name: path.split("/").pop() || path })}
            onClear={() => setLeft(null)}
            onError={setError}
          />
          <FileWell
            label="Second Keynote (.key)"
            hint="Optional — add a DSK to compare the two"
            file={right}
            onChoose={() => pick("right")}
            onPath={(path) => setRight({ path, name: path.split("/").pop() || path })}
            onClear={() => setRight(null)}
            onError={setError}
          />
        </div>
        {wallPresent && outline && (
          <label className="final-ask">
            <input
              type="checkbox"
              checked={lwFinal}
              onChange={(event) => setLwFinal(event.target.checked)}
            />
            <span>
              <strong>Has {wallName} been finalised with the Pastor?</strong>{" "}
              {lwFinal
                ? "Yes — the wall is the service, so anything the outline says differently is an out-of-date script."
                : "Not yet — the outline leads, so wording the wall changed is reported against the wall."}
            </span>
          </label>
        )}
        <div className="actions">
          <button
            className="btn run-checks"
            type="button"
            disabled={mode === "none" || busy}
            onClick={() => run()}
          >
            {paired ? "Match pairs" : "Check (read-only)"}
          </button>
        </div>
      </div>
      {(error || openError) && <p className="err">{error || openError}</p>}
      {busy && <LoadingOverlay title={overlayTitle} logs={logs} />}
      {job && (
        <CheckResultView
          job={job}
          onOpen={setOpen}
          onRunChecks={runChecks}
          onStartFresh={() => run(true)}
          checking={busy}
        />
      )}
      <Lightbox src={open} onClose={() => setOpen(null)} />
    </div>
  );
}
