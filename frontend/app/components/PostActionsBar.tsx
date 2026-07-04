"use client";

import React, { useEffect, useRef, useState } from "react";
import { ChevronUp, Loader2, MoreHorizontal } from "lucide-react";

// Barre d'actions unifiée des cartes de post (ALE-185) : un bouton principal
// « Publier ▴ » (Publier maintenant / Programmer / Slack / X selon les réseaux
// connectés) + un bouton « ⋯ » pour les actions secondaires. Les menus
// s'ouvrent vers le haut (style Cursor). Composant partagé par le Générateur,
// Mes contenus et Idée du jour — chaque section fournit ses actions.

export type PostAction = {
  key: string;
  label: React.ReactNode;
  icon?: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  title?: string;
  danger?: boolean;
  // Action « joindre des fichiers » : rend un <input type=file> caché dans l'item.
  filePicker?: { accept: string; multiple?: boolean; onFiles: (files: FileList | null) => void };
};

function ActionMenu({
  open,
  onClose,
  actions,
  align,
}: {
  open: boolean;
  onClose: () => void;
  actions: PostAction[];
  align: "left" | "right";
}) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: PointerEvent) {
      // Le wrapper contient aussi le bouton déclencheur : son onClick gère le toggle.
      if (ref.current && !ref.current.closest(".action-menu-wrap")?.contains(e.target as Node)) onClose();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="action-menu" role="menu" ref={ref} style={align === "right" ? { right: 0, left: "auto" } : undefined}>
      {actions.map((a) =>
        a.filePicker ? (
          <label
            key={a.key}
            role="menuitem"
            className={`action-menu-item${a.disabled ? " is-disabled" : ""}`}
            title={a.title}
            style={{ cursor: a.disabled ? "not-allowed" : "pointer" }}
          >
            {a.icon}
            <span>{a.label}</span>
            <input
              type="file"
              accept={a.filePicker.accept}
              multiple={a.filePicker.multiple}
              disabled={a.disabled}
              style={{ display: "none" }}
              onChange={(e) => {
                a.filePicker!.onFiles(e.currentTarget.files);
                e.currentTarget.value = "";
                onClose();
              }}
            />
          </label>
        ) : (
          <button
            key={a.key}
            type="button"
            role="menuitem"
            className={`action-menu-item${a.danger ? " danger" : ""}`}
            disabled={a.disabled}
            title={a.title}
            onClick={() => {
              onClose();
              a.onClick?.();
            }}
          >
            {a.icon}
            <span>{a.label}</span>
          </button>
        )
      )}
    </div>
  );
}

export default function PostActionsBar({
  publishActions,
  moreActions,
  publishLabel = "Publier",
  publishBusy = false,
  children,
}: {
  publishActions: PostAction[];
  moreActions: PostAction[];
  publishLabel?: React.ReactNode;
  publishBusy?: boolean;
  children?: React.ReactNode; // éléments additionnels rendus entre les deux boutons (badges, etc.)
}) {
  const [openMenu, setOpenMenu] = useState<"publish" | "more" | null>(null);

  return (
    <div className="post-actions-bar">
      {publishActions.length > 0 && (
        <div className="action-menu-wrap">
          <button
            type="button"
            className="primary-button"
            aria-haspopup="menu"
            aria-expanded={openMenu === "publish"}
            disabled={publishBusy}
            onClick={() => setOpenMenu((m) => (m === "publish" ? null : "publish"))}
          >
            {publishBusy ? <Loader2 size={14} className="spinning" /> : null}
            {publishLabel}
            <ChevronUp size={14} />
          </button>
          <ActionMenu open={openMenu === "publish"} onClose={() => setOpenMenu(null)} actions={publishActions} align="left" />
        </div>
      )}
      {children}
      {moreActions.length > 0 && (
        <div className="action-menu-wrap">
          <button
            type="button"
            className="secondary-button"
            aria-haspopup="menu"
            aria-expanded={openMenu === "more"}
            aria-label="Plus d'actions"
            title="Plus d'actions"
            onClick={() => setOpenMenu((m) => (m === "more" ? null : "more"))}
          >
            <MoreHorizontal size={16} />
          </button>
          <ActionMenu open={openMenu === "more"} onClose={() => setOpenMenu(null)} actions={moreActions} align="left" />
        </div>
      )}
    </div>
  );
}
