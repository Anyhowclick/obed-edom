import { useId } from "react";
import { ModalShell } from "./ModalShell";

export function PrepareOutputDialog({ title, logs, error, onExited }: {
  title: string;
  logs: string[];
  error: string;
  onExited: () => void;
}) {
  const titleId = useId();
  const appendError = error && logs[logs.length - 1] !== `Error: ${error}`;

  return (
    <ModalShell
      titleId={titleId}
      cardClassName="prepare-output-card"
      onDismiss={() => {}}
      onExited={onExited}
    >
      {(close) => <>
        <h2 id={titleId}>{title}</h2>
        <div className="log prepare-output-log" tabIndex={0}>
          {logs.map((line, index) => (
            <div className={/^(Error|Cannot)/.test(line) ? "prepare-output-line live-alert" : "prepare-output-line"} key={`${index}-${line}`}>
              {line}
            </div>
          ))}
          {appendError && <div className="prepare-output-line live-alert">{error}</div>}
        </div>
        <div className="confirm-actions">
          <button className="btn secondary" type="button" onClick={() => close(false)}>Close</button>
        </div>
      </>}
    </ModalShell>
  );
}
