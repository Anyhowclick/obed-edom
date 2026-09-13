import { openPath, reveal } from "../api";
import { IconFolder, IconOpen } from "./icons";

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
