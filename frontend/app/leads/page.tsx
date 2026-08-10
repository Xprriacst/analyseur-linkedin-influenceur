"use client";

/**
 * Dashboard interne des leads du tunnel /start (questionnaire audit).
 * Accès réservé aux e-mails de l'équipe (gating serveur).
 */

import { useCallback, useEffect, useState, type CSSProperties } from "react";
import Link from "next/link";
import { Loader2, RefreshCw } from "lucide-react";
import { supabase, authHeaders } from "../lib/supabase";

const DIRECT_API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  "https://analyseur-linkedin-influenceur-api-eu.onrender.com";

type Lead = {
  id: string;
  created_at: string;
  full_name: string;
  email: string;
  phone: string;
  linkedin_url?: string | null;
  website_url?: string | null;
  input_kind?: string | null;
  status: string;
  error_message?: string | null;
  sent_at?: string | null;
  niche?: string | null;
  followers?: number | null;
  notion_url?: string | null;
  public_token?: string | null;
};

const STATUS_LABEL: Record<string, string> = {
  pending: "En attente",
  generating: "Génération",
  sent: "Envoyé",
  failed: "Échec envoi",
};

function formatWhen(iso: string): string {
  try {
    return new Intl.DateTimeFormat("fr-FR", {
      dateStyle: "short",
      timeStyle: "short",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

export default function LeadsPage() {
  const [ready, setReady] = useState(false);
  const [denied, setDenied] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [leads, setLeads] = useState<Lead[]>([]);
  const [count, setCount] = useState(0);

  useEffect(() => {
    (async () => {
      const { data } = await supabase.auth.getSession();
      if (!data.session) {
        window.location.href = "/start";
        return;
      }
      setReady(true);
    })();
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/admin/audit-leads?limit=200`, {
        headers: await authHeaders(),
      });
      if (res.status === 404) {
        setDenied(true);
        setLeads([]);
        setCount(0);
        return;
      }
      if (!res.ok) {
        throw new Error((await res.text()) || `Erreur ${res.status}`);
      }
      const data = await res.json();
      setLeads(Array.isArray(data.leads) ? data.leads : []);
      setCount(typeof data.count === "number" ? data.count : 0);
      setDenied(false);
    } catch (exc: unknown) {
      setError(exc instanceof Error ? exc.message : "Chargement impossible.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!ready) return;
    void load();
    const id = window.setInterval(() => void load(), 30_000);
    return () => window.clearInterval(id);
  }, [ready, load]);

  if (!ready) {
    return (
      <main style={shell}>
        <Loader2 className="spin" size={20} />
      </main>
    );
  }

  return (
    <main style={shell}>
      <div style={{ width: "100%", maxWidth: 1100, display: "grid", gap: 20 }}>
        <header style={{ display: "flex", alignItems: "baseline", gap: 16, flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <h1 style={{ margin: 0, fontSize: 24, fontWeight: 650 }}>Leads audit</h1>
            <p style={{ margin: "6px 0 0", color: "var(--muted)", fontSize: 13.5 }}>
              Questionnaires remplis sur <code>/start</code> — rafraîchi toutes les 30 s.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            style={btn}
          >
            {loading ? <Loader2 className="spin" size={14} /> : <RefreshCw size={14} />}
            Actualiser
          </button>
          <Link href="/" style={{ fontSize: 13, color: "var(--muted)" }}>
            ← App
          </Link>
        </header>

        {denied && (
          <div style={bannerWarn}>
            Accès réservé à l&apos;équipe. Connecte-toi avec un compte Clareo.
          </div>
        )}

        {error && !denied && <div style={bannerErr}>{error}</div>}

        {!denied && (
          <>
            <div style={{ fontSize: 13, color: "var(--muted)" }}>
              {count} lead{count === 1 ? "" : "s"}
            </div>

            {count === 0 && !loading ? (
              <div style={empty}>
                Personne n&apos;a encore rempli le formulaire. Dès qu&apos;un prospect laisse
                nom + e-mail + téléphone sur <code>/start</code>, il apparaît ici.
              </div>
            ) : (
              <div style={{ overflowX: "auto", border: "1px solid var(--border)", borderRadius: 12 }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13.5 }}>
                  <thead>
                    <tr style={{ background: "var(--surface-low)", textAlign: "left" }}>
                      {["Quand", "Nom", "Contact", "Profil", "Niche", "Audit", "Statut"].map((h) => (
                        <th key={h} style={th}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {leads.map((lead) => (
                      <tr key={lead.id} style={{ borderTop: "1px solid var(--border)" }}>
                        <td style={td}>{formatWhen(lead.created_at)}</td>
                        <td style={td}>
                          <strong>{lead.full_name}</strong>
                        </td>
                        <td style={td}>
                          <div>{lead.email}</div>
                          <div style={{ color: "var(--muted)" }}>{lead.phone}</div>
                        </td>
                        <td style={td}>
                          {lead.linkedin_url ? (
                            <a href={lead.linkedin_url} target="_blank" rel="noreferrer" style={{ color: "var(--primary)" }}>
                              LinkedIn
                            </a>
                          ) : (
                            "—"
                          )}
                          {lead.followers != null && (
                            <div style={{ color: "var(--muted)", fontSize: 12 }}>
                              {Number(lead.followers).toLocaleString("fr-FR")} abonnés
                            </div>
                          )}
                        </td>
                        <td style={td}>{lead.niche || "—"}</td>
                        <td style={td}>
                          {lead.notion_url ? (
                            <a
                              href={lead.notion_url}
                              target="_blank"
                              rel="noreferrer"
                              style={{ color: "var(--primary)", fontWeight: 600 }}
                            >
                              Page Notion
                            </a>
                          ) : lead.public_token ? (
                            <a
                              href={`/a/${lead.public_token}`}
                              target="_blank"
                              rel="noreferrer"
                              style={{ color: "var(--primary)" }}
                            >
                              Voir l&apos;audit
                            </a>
                          ) : (
                            <span style={{ color: "var(--muted)" }}>—</span>
                          )}
                        </td>
                        <td style={td}>
                          <span style={statusPill(lead.status)}>
                            {STATUS_LABEL[lead.status] || lead.status}
                          </span>
                          {lead.error_message && (
                            <div style={{ marginTop: 4, color: "var(--muted)", fontSize: 11.5, maxWidth: 220 }}>
                              {lead.error_message}
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </main>
  );
}

const shell: CSSProperties = {
  minHeight: "100vh",
  padding: "40px 24px",
  background: "var(--surface-low)",
  display: "grid",
  placeItems: "start center",
};

const btn: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  height: 36,
  padding: "0 14px",
  borderRadius: 10,
  border: "1px solid var(--border)",
  background: "var(--surface)",
  cursor: "pointer",
  fontSize: 13,
};

const th: CSSProperties = {
  padding: "10px 14px",
  fontWeight: 600,
  fontSize: 12,
  color: "var(--muted)",
  textTransform: "uppercase",
  letterSpacing: "0.03em",
};

const td: CSSProperties = {
  padding: "12px 14px",
  verticalAlign: "top",
};

const empty: CSSProperties = {
  padding: 28,
  borderRadius: 12,
  background: "var(--surface)",
  border: "1px dashed var(--border)",
  color: "var(--muted)",
  lineHeight: 1.5,
};

const bannerWarn: CSSProperties = {
  padding: "12px 14px",
  borderRadius: 10,
  background: "rgba(245, 158, 11, 0.12)",
  border: "1px solid rgba(245, 158, 11, 0.35)",
  color: "#92590a",
};

const bannerErr: CSSProperties = {
  padding: "12px 14px",
  borderRadius: 10,
  background: "rgba(239, 68, 68, 0.08)",
  border: "1px solid rgba(239, 68, 68, 0.3)",
  color: "var(--danger)",
};

function statusPill(status: string): CSSProperties {
  const tone =
    status === "sent"
      ? { bg: "rgba(16,185,129,0.12)", fg: "#047857" }
      : status === "failed"
        ? { bg: "rgba(239,68,68,0.1)", fg: "#b91c1c" }
        : { bg: "var(--surface-high)", fg: "var(--muted)" };
  return {
    display: "inline-block",
    padding: "2px 8px",
    borderRadius: 999,
    background: tone.bg,
    color: tone.fg,
    fontSize: 12,
    fontWeight: 600,
  };
}
