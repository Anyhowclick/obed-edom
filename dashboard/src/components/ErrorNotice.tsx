import { useEffect, useState } from "react";
import { IconClose } from "./icons";

export function ErrorNotice({ message, onDismiss }: { message: string | null | undefined; onDismiss?: () => void }) {
  const [dismissed, setDismissed] = useState<string | null>(null);

  useEffect(() => {
    if (dismissed != null && dismissed !== message) setDismissed(null);
  }, [dismissed, message]);

  if (!message || dismissed === message) return null;

  return (
    <div className="error-notice" role="alert">
      <span className="error-notice-message">{message}</span>
      <button
        className="error-notice-close"
        type="button"
        aria-label="Dismiss error"
        title="Dismiss"
        onClick={() => {
          setDismissed(message);
          onDismiss?.();
        }}
      >
        <IconClose />
      </button>
    </div>
  );
}
