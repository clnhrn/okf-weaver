"use client";

import { useEffect, useRef } from "react";

export default function ConfirmModal({
  title,
  message,
  confirmLabel = "Confirm",
  onConfirm,
  onCancel,
}: {
  title: string;
  message: string;
  confirmLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    confirmRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onCancel();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div
        className="modal"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        aria-describedby="modal-msg"
        onClick={(e) => e.stopPropagation()}
      >
        <p id="modal-title" className="modal-title">
          {title}
        </p>
        <p id="modal-msg" className="modal-msg">
          {message}
        </p>
        <div className="modal-actions">
          <button className="ghost-btn" onClick={onCancel}>
            Cancel
          </button>
          <button ref={confirmRef} className="primary danger" onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
