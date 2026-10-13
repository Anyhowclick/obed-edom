import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { ModalShell } from "./ModalShell";

export type ConfirmOptions = {
  title: string;
  body?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
};

type Pending = ConfirmOptions & { resolve: (ok: boolean) => void };

export function useConfirm(): [(opts: ConfirmOptions) => Promise<boolean>, ReactNode] {
  const [pending, setPending] = useState<Pending | null>(null);
  const pendingRef = useRef<Pending | null>(null);
  pendingRef.current = pending;

  const confirm = useCallback((opts: ConfirmOptions) => {
    return new Promise<boolean>((resolve) => {
      pendingRef.current?.resolve(false);
      setPending({ ...opts, resolve });
    });
  }, []);

  useEffect(() => {
    return () => {
      pendingRef.current?.resolve(false);
    };
  }, []);

  const node = pending ? (
    <ConfirmDialog
      title={pending.title}
      body={pending.body}
      confirmLabel={pending.confirmLabel ?? "OK"}
      cancelLabel={pending.cancelLabel ?? "Cancel"}
      danger={pending.danger}
      onResolve={(ok) => pending.resolve(ok)}
      onExited={() => {
        setPending((current) => (current === pending ? null : current));
      }}
    />
  ) : null;

  return [confirm, node];
}

export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  cancelLabel,
  danger,
  onResolve,
  onExited,
}: {
  title: string;
  body?: string;
  confirmLabel: string;
  cancelLabel: string;
  danger?: boolean;
  onResolve: (ok: boolean) => void;
  onExited: () => void;
}) {
  const titleId = useId();
  const bodyId = useId();
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const onResolveRef = useRef(onResolve);
  onResolveRef.current = onResolve;

  return (
    <ModalShell
      titleId={titleId}
      describedBy={body ? bodyId : undefined}
      initialFocusRef={danger ? cancelRef : confirmRef}
      onDismiss={() => onResolveRef.current(false)}
      onExited={onExited}
    >
      {(close) => <>
        <h2 id={titleId}>{title}</h2>
        {body ? (
          <p id={bodyId} className="note">
            {body}
          </p>
        ) : null}
        <div className="confirm-actions">
          <button ref={cancelRef} className="btn secondary" type="button" onClick={() => close(false, () => onResolveRef.current(false))}>
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            className={danger ? "btn run-checks" : "btn"}
            type="button"
            onClick={() => close(false, () => onResolveRef.current(true))}
          >
            {confirmLabel}
          </button>
        </div>
      </>}
    </ModalShell>
  );
}
