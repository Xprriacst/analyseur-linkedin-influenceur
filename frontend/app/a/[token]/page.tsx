"use client";

/**
 * Page publique d'un audit complet — accessible sans compte via /a/<token>.
 * Miroir du contenu aussi poussé dans Notion (lien stocké sur le lead).
 */

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Loader2 } from "lucide-react";

const DIRECT_API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  "https://analyseur-linkedin-influenceur-api-eu.onrender.com";

export default function PublicAuditPage() {
  const params = useParams<{ token: string }>();
  const token = typeof params?.token === "string" ? params.token : "";
  const [html, setHtml] = useState("");
  const [notionUrl, setNotionUrl] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const res = await fetch(`${DIRECT_API_URL}/public/audit/${encodeURIComponent(token)}`);
        if (!res.ok) {
          throw new Error(res.status === 404 ? "Audit introuvable." : `Erreur ${res.status}`);
        }
        const data = await res.json();
        setHtml(typeof data.html === "string" ? data.html : "");
        setNotionUrl(typeof data.notion_url === "string" ? data.notion_url : "");
      } catch (exc: unknown) {
        setError(exc instanceof Error ? exc.message : "Chargement impossible.");
      } finally {
        setLoading(false);
      }
    })();
  }, [token]);

  if (loading) {
    return (
      <main style={{ minHeight: "100vh", display: "grid", placeItems: "center" }}>
        <Loader2 className="spin" size={22} />
      </main>
    );
  }

  if (error) {
    return (
      <main style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24 }}>
        <p style={{ color: "var(--muted)" }}>{error}</p>
      </main>
    );
  }

  return (
    <main style={{ minHeight: "100vh", background: "#f2f2f7" }}>
      {notionUrl && (
        <div
          style={{
            maxWidth: 620,
            margin: "0 auto",
            padding: "16px 12px 0",
            fontSize: 13,
            color: "#5d6070",
          }}
        >
          Aussi sur Notion :{" "}
          <a href={notionUrl} target="_blank" rel="noreferrer" style={{ color: "#4648d4" }}>
            ouvrir la page
          </a>
        </div>
      )}
      <div dangerouslySetInnerHTML={{ __html: html }} />
    </main>
  );
}
