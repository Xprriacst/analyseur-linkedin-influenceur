"use client";

import React, { useEffect, useState } from "react";
import { X } from "lucide-react";

// Vignette d'image cliquable : ouvre l'image en grand dans un aperçu plein
// écran (clic sur le fond ou Échap pour fermer). Utilisée par les grilles
// d'images jointes/générées des cartes de post.
export default function ZoomableImage({
  src,
  alt,
  thumbStyle,
}: {
  src: string;
  alt: string;
  thumbStyle?: React.CSSProperties;
}) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <button
        type="button"
        className="img-zoom-thumb"
        title="Agrandir l'image"
        aria-label={`Agrandir : ${alt}`}
        onClick={() => setOpen(true)}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={src}
          alt={alt}
          style={{ width: "100%", aspectRatio: "1 / 1", objectFit: "cover", borderRadius: 6, display: "block", ...thumbStyle }}
        />
      </button>
      {open && (
        <div className="img-zoom-overlay" role="dialog" aria-label={alt} onClick={() => setOpen(false)}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={src} alt={alt} className="img-zoom-full" onClick={(e) => e.stopPropagation()} />
          <button type="button" className="img-zoom-close" aria-label="Fermer l'aperçu" onClick={() => setOpen(false)}>
            <X size={18} />
          </button>
        </div>
      )}
    </>
  );
}
