"use client";

import { useState } from "react";
import { Linkedin, Loader2 } from "lucide-react";

// Aperçu de publication partagé (ALE-210). Utilisé partout où l'on peut publier
// un post sur LinkedIn (Générateur, Idée du jour, Mes contenus, Assistant IA) :
// une vraie modale avec le texte ÉDITABLE + l'aperçu des images jointes, à valider
// avant l'envoi. Le texte modifié ici est renvoyé au parent via onConfirm.
export type PublishConfirmImage = { url: string; filename?: string };

export default function PublishConfirmModal({
  text,
  images = [],
  busy = false,
  title = "Publier ce post sur LinkedIn ?",
  note = "Le post sera publié immédiatement sur ton compte LinkedIn. Tu peux ajuster le texte ci-dessous avant de confirmer.",
  confirmLabel = "Confirmer la publication",
  onConfirm,
  onClose,
}: {
  text: string;
  images?: PublishConfirmImage[];
  busy?: boolean;
  title?: string;
  note?: string;
  confirmLabel?: string;
  onConfirm: (text: string) => void;
  onClose: () => void;
}) {
  const [value, setValue] = useState(text);
  const trimmed = value.trim();

  return (
    <div
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 1000,
        display: "flex", alignItems: "center", justifyContent: "center", padding: 16,
      }}
      onClick={() => { if (!busy) onClose(); }}
    >
      <div className="card" style={{ maxWidth: 560, width: "100%", padding: 24 }} onClick={(e) => e.stopPropagation()}>
        <h3 style={{ marginTop: 0, marginBottom: 8 }}>{title}</h3>
        <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 12 }}>{note}</p>
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          rows={10}
          className="variant-text"
          style={{ width: "100%", boxSizing: "border-box", marginBottom: 16 }}
          disabled={busy}
        />
        {images.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <p className="role-picker-hint" style={{ marginBottom: 8 }}>
              {images.length} image{images.length > 1 ? "s" : ""} {images.length > 1 ? "seront jointes" : "sera jointe"}.
            </p>
            <div style={{ display: "flex", gap: 8, overflowX: "auto" }}>
              {images.map((image, idx) => (
                <img
                  key={`${image.url}-${idx}`}
                  src={image.url}
                  alt={`Image jointe ${idx + 1}`}
                  style={{ width: 86, height: 86, objectFit: "cover", borderRadius: 8, border: "1px solid var(--border)", flexShrink: 0 }}
                />
              ))}
            </div>
          </div>
        )}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button className="secondary-button" onClick={onClose} disabled={busy}>
            Annuler
          </button>
          <button
            className="primary-button"
            disabled={busy || !trimmed}
            onClick={() => onConfirm(value)}
          >
            {busy
              ? <><Loader2 size={14} className="spinning" /> Publication…</>
              : <><Linkedin size={14} /> {confirmLabel}</>
            }
          </button>
        </div>
      </div>
    </div>
  );
}
