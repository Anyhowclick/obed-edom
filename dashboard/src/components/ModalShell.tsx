import { useCallback, useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";

const CLOSE_MS = 150;

function prefersReducedMotion(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

type CloseModal = (instant: boolean, beforeClose?: () => void) => void;

export function ModalShell({
  titleId,
  describedBy,
  cardClassName = "",
  initialFocusRef,
  onDismiss,
  onExited,
  children,
}: {
  titleId: string;
  describedBy?: string;
  cardClassName?: string;
  initialFocusRef?: RefObject<HTMLElement>;
  onDismiss: () => void;
  onExited: () => void;
  children: (close: CloseModal) => ReactNode;
}) {
  const cardRef = useRef<HTMLDivElement>(null);
  const settled = useRef(false);
  const closeTimer = useRef<number | null>(null);
  const reduce = prefersReducedMotion();
  const [phase, setPhase] = useState<"enter" | "open" | "closing">(reduce ? "open" : "enter");
  const onDismissRef = useRef(onDismiss);
  const onExitedRef = useRef(onExited);
  onDismissRef.current = onDismiss;
  onExitedRef.current = onExited;

  const close = useCallback<CloseModal>((instant, beforeClose) => {
    if (settled.current) return;
    settled.current = true;
    beforeClose?.();
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
    const previous = document.activeElement as HTMLElement | null;
    (initialFocusRef?.current ?? cardRef.current)?.focus();

    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        close(true, onDismissRef.current);
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(cardRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      ) ?? []);
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!first || !last) {
        event.preventDefault();
        cardRef.current?.focus();
        return;
      }
      event.preventDefault();
      const current = focusable.indexOf(document.activeElement as HTMLElement);
      const next = event.shiftKey
        ? focusable[current <= 0 ? focusable.length - 1 : current - 1]
        : focusable[current < 0 || current === focusable.length - 1 ? 0 : current + 1];
      next.focus();
    }

    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      if (previous?.isConnected) previous.focus();
    };
  }, [close, initialFocusRef]);

  useEffect(() => {
    return () => {
      if (closeTimer.current != null) window.clearTimeout(closeTimer.current);
    };
  }, []);

  return createPortal(
    <div
      className={`overlay confirm-overlay${phase === "open" ? " is-open" : ""}${phase === "closing" ? " is-closing" : ""}`}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close(false, onDismissRef.current);
      }}
    >
      <div
        ref={cardRef}
        className={`overlay-card confirm-card${cardClassName ? ` ${cardClassName}` : ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={describedBy}
        tabIndex={-1}
      >
        {children(close)}
      </div>
    </div>,
    document.body
  );
}
