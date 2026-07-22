"use client";

import { useState } from "react";
import { Linkedin, Loader2 } from "lucide-react";
import CrossNetworkPanels, { type CrossPostsDraft } from "./CrossNetworkPanels";

// Aperçu de publication partagé (ALE-210). Utilisé partout où l'on peut publier
// un post sur LinkedIn (Générateur, Idée du jour, Mes contenus, Assistant IA) :
// une vraie modale avec le texte ÉDITABLE + l'aperçu des images jointes, à valider
// avant l'envoi. Le texte modifié ici est renvoyé au parent via onConfirm.
//
// ALE-59 : rangée de logos X/Reddit (vue agence) — un clic adapte le post via
// l'IA et empile la version sous le texte LinkedIn ; les versions actives sont
// renvoyées au parent en 2e argument d'onConfirm, qui les publie après le
// succès LinkedIn (publishCrossNetworks).
export type PublishConfirmImage = { url: string; filename?: string };

export default function PublishConfirmModal({
  text,
  images = [],
  busy = false,
  title = "Publier le post",
  note = "Relis et ajuste chaque version avant de confirmer. La publication est immédiate.",
  confirmLabel = "Confirmer la publication",
  crossNetworks = true,
  onConfirm,
  onClose,
}: {
  text: string;
  images?: PublishConfirmImage[];
  busy?: boolean;
  title?: string;
  note?: string;
  confirmLabel?: string;
  crossNetworks?: boolean;
  onConfirm: (text: string, cross?: CrossPostsDraft | null) => void;
  onClose: () => void;
}) {
  const [value, setValue] = useState(text);
  const [cross, setCross] = useState<CrossPostsDraft | null>(null);
  const [crossValid, setCrossValid] = useState(true);
  const trimmed = value.trim();
  const networkCount = 1 + (cross?.x ? 1 : 0) + (cross?.reddit ? 1 : 0);

  return (
    <div
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 1000,
        display: "flex", alignItems: "center", justifyContent: "center", padding: 16,
      }}
      onClick={() => { if (!busy) onClose(); }}
    >
      <div className="card" style={{ maxWidth: 620, width: "100%", padding: 24, maxHeight: "90vh", overflowY: "auto" }} onClick={(e) => e.stopPropagation()}>
        <h3 style={{ marginTop: 0, marginBottom: 8 }}>{title}</h3>
        <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 12 }}>{note}</p>
        {crossNetworks && (
          <CrossNetworkPanels
            baseText={value}
            disabled={busy}
            onChange={(c, valid) => { setCross(c); setCrossValid(valid); }}
          />
        )}
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
              {images.length} image{images.length > 1 ? "s" : ""} {images.length > 1 ? "seront jointes" : "sera jointe"} au post LinkedIn.
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
            disabled={busy || !trimmed || !crossValid}
            onClick={() => onConfirm(value, cross)}
          >
            {busy
              ? <><Loader2 size={14} className="spinning" /> Publication…</>
              : networkCount > 1
                ? <>Publier sur {networkCount} réseaux</>
                : <><Linkedin size={14} /> {confirmLabel}</>
            }
          </button>
        </div>
      </div>
    </div>
  );
}
