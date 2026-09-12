import { openPath, reveal } from "../api";

function IconOpen() {
  return (
    <svg className="maps-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M14 4h6v6M20 4 10 14M10 5H6a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function IconFolder() {
  return (
    <svg className="maps-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M3 6.5A1.5 1.5 0 0 1 4.5 5h4.6l1.6 2H19.5A1.5 1.5 0 0 1 21 8.5v9A1.5 1.5 0 0 1 19.5 19h-15A1.5 1.5 0 0 1 3 17.5z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export type Artifact = { label: string; path: string };

export function ArtifactActions({
  artifacts,
  onError,
}: {
  artifacts: Artifact[];
  onError?: (message: string) => void;
}) {
  const present = artifacts.filter((artifact) => artifact.path);
  if (present.length === 0) return null;

  async function runOpen(path: string) {
    try {
      await openPath(path);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : String(err));
    }
  }

  async function runReveal(path: string) {
    try {
      await reveal(path);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="actions">
      {present.map((artifact) => (
        <button
          key={artifact.path}
          className="btn secondary"
          type="button"
          title={artifact.path}
          onClick={() => void runOpen(artifact.path)}
        >
          <IconOpen />
          Open {artifact.label}
        </button>
      ))}
      <button
        className="btn secondary"
        type="button"
        title={present[0].path.slice(0, present[0].path.lastIndexOf("/")) || present[0].path}
        onClick={() => void runReveal(present[0].path)}
      >
        <IconFolder />
        Show in enclosing folder
      </button>
    </div>
  );
}
