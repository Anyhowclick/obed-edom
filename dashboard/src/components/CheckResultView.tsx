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
}: {
  job: Job;
  onOpen: (src: string) => void;
  onRunChecks?: (slots: Slot[]) => void;
  onStartFresh?: () => void;
  checking?: boolean;
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
      />
    );
  }
  if (result.kind === "outline") return <OutlineResultView job={job} />;
  return <InspectResultView job={job} onOpen={onOpen} />;
}
