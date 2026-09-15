import type { Job } from "../api";
import type { Slot } from "../playlist";
import { DiffResultView } from "./DiffResultView";
import { InspectResultView } from "./InspectResultView";
import { OutlineResultView } from "./OutlineResultView";

export function CheckResultView({
  job,
  onOpen,
  onRunChecks,
  onStartFresh,
  checking,
  onRename,
}: {
  job: Job;
  onOpen: (src: string) => void;
  onRunChecks?: (slots: Slot[]) => void;
  onStartFresh?: () => void;
  checking?: boolean;
  onRename?: (id: string, name: string) => Promise<Job>;
}) {
  const result = (job.result || {}) as { pairs?: unknown; kind?: string };
  if (result.pairs) {
    return (
      <DiffResultView
        job={job}
        onOpen={onOpen}
        onRunChecks={onRunChecks}
        onStartFresh={onStartFresh}
        checking={checking}
        onRename={onRename}
      />
    );
  }
  if (result.kind === "outline") return <OutlineResultView job={job} />;
  return <InspectResultView job={job} onOpen={onOpen} onRename={onRename} />;
}
