import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

export type ConfirmOptions = {
  title: string;
  body?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
};

type Pending = ConfirmOptions & { resolve: (ok: boolean) => void };

const CLOSE_MS = 150;

function prefersReducedMotion(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

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
  const cardRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const settled = useRef(false);
  const closeTimer = useRef<number | null>(null);
  const reduce = prefersReducedMotion();
  const [phase, setPhase] = useState<"enter" | "open" | "closing">(reduce ? "open" : "enter");
  const onResolveRef = useRef(onResolve);
  const onExitedRef = useRef(onExited);
  onResolveRef.current = onResolve;
  onExitedRef.current = onExited;

  const finish = useCallback((ok: boolean, instant: boolean) => {
    if (settled.current) return;
    settled.current = true;
    onResolveRef.current(ok);
    if (instant || prefersReducedMotion()) {
      onExitedRef.current();
      return;
    }
    setPhase("closing");
    closeTimer.current = window.setTimeout(() => onExitedRef.current(), CLOSE_MS);
  }, []);

  useEffect(() => {
    if (reduce) return;
    const id = window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => setPhase((current) => (current === "enter" ? "open" : current)));
    });
    return () => window.cancelAnimationFrame(id);
  }, [reduce]);

  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    (danger ? cancelRef : confirmRef).current?.focus();

    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        finish(false, true);
        return;
      }
      if (event.key !== "Tab") return;
      const first = cancelRef.current;
      const last = confirmRef.current;
      if (!first || !last) return;
      const active = document.activeElement;
      if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      prev?.focus?.();
    };
  }, [danger, finish]);

  useEffect(() => {
    return () => {
      if (closeTimer.current != null) window.clearTimeout(closeTimer.current);
    };
  }, []);

  return createPortal(
    <div
      className={`overlay confirm-overlay${phase === "open" ? " is-open" : ""}${phase === "closing" ? " is-closing" : ""}`}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) finish(false, false);
      }}
    >
      <div
        ref={cardRef}
        className="overlay-card confirm-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={body ? bodyId : undefined}
      >
        <h2 id={titleId}>{title}</h2>
        {body ? (
          <p id={bodyId} className="note">
            {body}
          </p>
        ) : null}
        <div className="confirm-actions">
          <button ref={cancelRef} className="btn secondary" type="button" onClick={() => finish(false, false)}>
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            className={danger ? "btn run-checks" : "btn"}
            type="button"
            onClick={() => finish(true, false)}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}
