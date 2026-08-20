import { useEffect, useState } from "react";
import { deleteJob, getJob, listJobs, patchJob, type Job } from "./api";
import { useRunNav, type FeatureId } from "./nav";

export function jobLabel(job: Job): string {
  const result = (job.result || {}) as Record<string, unknown>;
  const stem = typeof result.stem === "string" ? result.stem : "";
  if (stem) return stem;
  const path = typeof result.path === "string" ? result.path : "";
  if (path) return path.split("/").pop() || path;
  const left = typeof result.leftPath === "string" ? result.leftPath : "";
  const right = typeof result.rightPath === "string" ? result.rightPath : "";
  if (left || right) {
    const a = left.split("/").pop() || left;
    const b = right.split("/").pop() || right;
    return b ? `${a} vs ${b}` : a;
  }
  return job.id;
}

export function libraryJobs(jobs: Job[]): Job[] {
  return jobs.filter((job) => {
    const feature = job.feature || job.kind;
    return feature === "generate" || feature === "diff" || feature === "check" || feature === "dsk" || feature === "resize";
  });
}

export function useJobSessions(feature?: string) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feature]);

  function reload() {
    listJobs(feature)
      .then((loaded) => {
        const next = feature ? loaded : libraryJobs(loaded);
        setJobs(next);
        setActiveId((current) => (current && next.some((job) => job.id === current) ? current : next[0]?.id || null));
      })
      .catch((err) => {
        setSessionError(err instanceof Error ? err.message : String(err));
      });
  }

  const active = jobs.find((job) => job.id === activeId) || jobs[0] || null;

  function upsert(job: Job) {
    setJobs((prev) => {
      const index = prev.findIndex((item) => item.id === job.id);
      if (index >= 0) {
        const next = [...prev];
        next[index] = job;
        return next;
      }
      return [job, ...prev];
    });
    setActiveId(job.id);
  }

  async function persistResult(jobId: string, result: Record<string, unknown>) {
    const updated = await patchJob(jobId, result);
    upsert(updated);
    return updated;
  }

  async function remove(id: string) {
    const job = jobs.find((item) => item.id === id);
    const name = job ? jobLabel(job) : id;
    const ok = window.confirm(
      `Delete saved run “${name}”? This removes the dashboard session and that run’s preview/output files if they are still on disk.`
    );
    if (!ok) return;
    await deleteJob(id);
    setJobs((prev) => {
      const next = prev.filter((item) => item.id !== id);
      setActiveId((current) => (current === id ? next[0]?.id || null : current));
      return next;
    });
  }

  return {
    jobs,
    active,
    activeId,
    setActiveId,
    upsert,
    persistResult,
    remove,
    reload,
    sessionError,
    setSessionError,
  };
}

export function useCurrentJob(feature: FeatureId) {
  const { openRun } = useRunNav();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!openRun || openRun.feature !== feature) return;
    getJob(openRun.jobId)
      .then(setJob)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [openRun, feature]);

  function upsert(next: Job) {
    setJob(next);
  }

  return { job, upsert, error };
}
