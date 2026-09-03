"use client";

/**
 * Dashboard interne des leads des tunnels d'onboarding.
 * Accès réservé aux e-mails de l'équipe (gating serveur).
 */

import { useCallback, useEffect, useMemo, useState, type CSSProperties, type FormEvent } from "react";
import Link from "next/link";
import { Loader2, RefreshCw } from "lucide-react";
import { supabase, authHeaders } from "../lib/supabase";

const DIRECT_API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  "https://analyseur-linkedin-influenceur-api-eu.onrender.com";

type LeadType = "audit" | "founders_optin";
type TypeFilter = "all" | LeadType;

type Lead = {
  id: string;
  created_at: string;
  type?: LeadType;
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

type PoolProspect = {
  id: string;
  profile_url: string;
  name?: string | null;
  headline?: string | null;
  created_at?: string;
};

const STATUS_LABEL: Record<string, string> = {
  pending: "En attente",
  generating: "Génération",
  generated: "Généré, non envoyé",
  sent: "Envoyé",
  failed: "Échec génération",
  founders_optin: "Opt-in e-mail",
};

const TYPE_LABEL: Record<LeadType, string> = {
  audit: "Audit",
  founders_optin: "Opt-in",
};

const TYPE_FILTER_OPTIONS: { value: TypeFilter; label: string }[] = [
  { value: "all", label: "Tous" },
  { value: "audit", label: "Audits" },
  { value: "founders_optin", label: "Opt-ins e-mail" },
];

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

function isOptin(lead: Lead): boolean {
  return lead.type === "founders_optin" || lead.status === "founders_optin";
}

export default function LeadsPage() {
  const [ready, setReady] = useState(false);
  const [denied, setDenied] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [leads, setLeads] = useState<Lead[]>([]);
  const [count, setCount] = useState(0);
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [poolCount, setPoolCount] = useState(0);
  const [pool, setPool] = useState<PoolProspect[]>([]);
  const [poolUrls, setPoolUrls] = useState("");
  const [poolFile, setPoolFile] = useState<File | null>(null);
  const [poolBusy, setPoolBusy] = useState(false);
  const [poolMsg, setPoolMsg] = useState("");
  const [poolErr, setPoolErr] = useState("");

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
      const res = await fetch(`${DIRECT_API_URL}/admin/onboarding-leads?limit=200`, {
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

  const loadPool = useCallback(async () => {
    try {
      const res = await fetch(`${DIRECT_API_URL}/admin/prospect-pool?limit=80`, {
        headers: await authHeaders(),
      });
      if (res.status === 404) return;
      if (!res.ok) return;
      const data = await res.json();
      setPool(Array.isArray(data.prospects) ? data.prospects : []);
      setPoolCount(typeof data.count === "number" ? data.count : 0);
    } catch {
      /* best-effort : le tableau onboarding reste lisible si le vivier manque */
    }
  }, []);

  const summarizePoolResult = (data: {
    inserted?: number;
    updated?: number;
    skipped?: number;
    ignored?: number;
    truncated?: boolean;
  }) => {
    const bits = [
      `${data.inserted ?? 0} ajouté${(data.inserted ?? 0) === 1 ? "" : "s"}`,
      `${data.updated ?? 0} enrichi${(data.updated ?? 0) === 1 ? "" : "s"}`,
    ];
    if (data.skipped) bits.push(`${data.skipped} déjà en stock`);
    if (data.ignored) bits.push(`${data.ignored} ligne${data.ignored === 1 ? "" : "s"} ignorée${data.ignored === 1 ? "" : "s"} (pas d'URL LinkedIn)`);
    if (data.truncated) bits.push("fichier tronqué au plafond");
    return bits.join(" · ");
  };

  const importPoolFile = async (event: FormEvent) => {
    event.preventDefault();
    if (!poolFile) {
      setPoolErr("Choisis un fichier CSV ou Excel.");
      return;
    }
    setPoolBusy(true);
    setPoolErr("");
    setPoolMsg("");
    try {
      const body = new FormData();
      body.append("file", poolFile);
      const res = await fetch(`${DIRECT_API_URL}/admin/prospect-pool`, {
        method: "POST",
        headers: await authHeaders(),
        body,
      });
      const text = await res.text();
      if (!res.ok) {
        throw new Error(text || `Erreur ${res.status}`);
      }
      const data = JSON.parse(text);
      setPoolMsg(summarizePoolResult(data));
      setPoolFile(null);
      await loadPool();
    } catch (exc: unknown) {
      setPoolErr(exc instanceof Error ? exc.message : "Import impossible.");
    } finally {
      setPoolBusy(false);
    }
  };

  const importPoolUrls = async (event: FormEvent) => {
    event.preventDefault();
    if (!poolUrls.trim()) {
      setPoolErr("Colle au moins une URL linkedin.com/in/…");
      return;
    }
    setPoolBusy(true);
    setPoolErr("");
    setPoolMsg("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/admin/prospect-pool/urls`, {
        method: "POST",
        headers: { ...(await authHeaders()), "Content-Type": "application/json" },
        body: JSON.stringify({ urls: poolUrls }),
      });
      const text = await res.text();
      if (!res.ok) {
        throw new Error(text || `Erreur ${res.status}`);
      }
      const data = JSON.parse(text);
      setPoolMsg(summarizePoolResult(data));
      setPoolUrls("");
      await loadPool();
    } catch (exc: unknown) {
      setPoolErr(exc instanceof Error ? exc.message : "Import impossible.");
    } finally {
      setPoolBusy(false);
    }
  };

  useEffect(() => {
    if (!ready) return;
    void load();
    void loadPool();
    const id = window.setInterval(() => void load(), 30_000);
    return () => window.clearInterval(id);
  }, [ready, load, loadPool]);

  const filteredLeads = useMemo(() => {
    if (typeFilter === "all") return leads;
    return leads.filter((lead) => {
      const t: LeadType = isOptin(lead) ? "founders_optin" : "audit";
      return t === typeFilter;
    });
  }, [leads, typeFilter]);

  const showAuditCols = typeFilter !== "founders_optin";

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
            <h1 style={{ margin: 0, fontSize: 24, fontWeight: 650 }}>Leads onboarding</h1>
            <p style={{ margin: "6px 0 0", color: "var(--muted)", fontSize: 13.5 }}>
              Audits (<code>/start</code>, <code>/onboarding</code>) et opt-ins e-mail (
              <code>/founders</code>) — rafraîchi toutes les 30 s.
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
            <section
              style={{
                border: "1px solid var(--border)",
                borderRadius: 12,
                padding: 18,
                background: "var(--surface)",
                display: "grid",
                gap: 14,
              }}
            >
              <div>
                <h2 style={{ margin: 0, fontSize: 16, fontWeight: 650 }}>
                  Vivier de prospects — Mode Pilote
                </h2>
                <p style={{ margin: "6px 0 0", color: "var(--muted)", fontSize: 13.5 }}>
                  Alimenté par les cartes publiques (nom, titre, URL LinkedIn) de
                  tous les comptes. Un client en voit <strong>une par jour</strong> tant
                  que son LinkedIn n&apos;est pas connecté. Tu peux aussi coller un
                  fichier ou des URLs — ça n&apos;écrit pas dans tes leads.
                </p>
                <p style={{ margin: "6px 0 0", fontSize: 13, color: "var(--muted)" }}>
                  {poolCount} profil{poolCount === 1 ? "" : "s"} en stock
                </p>
              </div>
              <form
                onSubmit={(e) => void importPoolFile(e)}
                style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}
              >
                <input
                  type="file"
                  accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                  onChange={(e) => setPoolFile(e.target.files?.[0] ?? null)}
                  style={{ fontSize: 13 }}
                />
                <button type="submit" disabled={poolBusy} style={btn}>
                  {poolBusy ? <Loader2 className="spin" size={14} /> : null}
                  Importer le fichier
                </button>
              </form>
              <form onSubmit={(e) => void importPoolUrls(e)} style={{ display: "grid", gap: 8 }}>
                <label style={{ fontSize: 12.5, color: "var(--muted)" }}>
                  Ou colle des URLs (une par ligne)
                  <textarea
                    value={poolUrls}
                    onChange={(e) => setPoolUrls(e.target.value)}
                    rows={4}
                    placeholder={"https://www.linkedin.com/in/marie-pharmacienne\nhttps://www.linkedin.com/in/jean-titulaire"}
                    style={{
                      display: "block",
                      width: "100%",
                      marginTop: 6,
                      padding: "8px 10px",
                      borderRadius: 8,
                      border: "1px solid var(--border)",
                      background: "var(--surface-low)",
                      font: "inherit",
                      fontSize: 13,
                      resize: "vertical",
                    }}
                  />
                </label>
                <button type="submit" disabled={poolBusy} style={{ ...btn, justifySelf: "start" }}>
                  {poolBusy ? <Loader2 className="spin" size={14} /> : null}
                  Ajouter les URLs
                </button>
              </form>
              {poolErr ? <div style={bannerErr}>{poolErr}</div> : null}
              {poolMsg ? (
                <p style={{ margin: 0, fontSize: 13, color: "var(--muted)" }}>{poolMsg}</p>
              ) : null}
              {pool.length > 0 ? (
                <div style={{ overflowX: "auto", border: "1px solid var(--border)", borderRadius: 10 }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                    <thead>
                      <tr style={{ background: "var(--surface-low)", textAlign: "left" }}>
                        {["Nom", "Titre", "Profil"].map((h) => (
                          <th key={h} style={th}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {pool.map((p) => (
                        <tr key={p.id} style={{ borderTop: "1px solid var(--border)" }}>
                          <td style={td}><strong>{p.name?.trim() || "—"}</strong></td>
                          <td style={td}>{p.headline?.trim() || "—"}</td>
                          <td style={td}>
                            <a href={p.profile_url} target="_blank" rel="noreferrer" style={{ color: "var(--primary)" }}>
                              {p.profile_url.replace("https://www.linkedin.com/in/", "/in/")}
                            </a>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </section>

            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 16,
                flexWrap: "wrap",
                fontSize: 13,
                color: "var(--muted)",
              }}
            >
              <span>
                {filteredLeads.length} affiché{filteredLeads.length === 1 ? "" : "s"}
                {typeFilter !== "all" ? ` · ${count} au total` : ""}
              </span>
              <div style={{ display: "inline-flex", gap: 6, flexWrap: "wrap" }}>
                {TYPE_FILTER_OPTIONS.map((opt) => (
                  <label key={opt.value} style={filterLabel}>
                    <input
                      type="radio"
                      name="lead-type-filter"
                      value={opt.value}
                      checked={typeFilter === opt.value}
                      onChange={() => setTypeFilter(opt.value)}
                      style={{ margin: 0 }}
                    />
                    {opt.label}
                  </label>
                ))}
              </div>
            </div>

            {count === 0 && !loading ? (
              <div style={empty}>
                Aucun lead pour l&apos;instant. Dès qu&apos;un visiteur laisse son e-mail sur{" "}
                <code>/founders</code> ou remplit le questionnaire audit, il apparaît ici.
              </div>
            ) : filteredLeads.length === 0 && !loading ? (
              <div style={empty}>Aucun lead pour ce filtre.</div>
            ) : (
              <div style={{ overflowX: "auto", border: "1px solid var(--border)", borderRadius: 12 }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13.5 }}>
                  <thead>
                    <tr style={{ background: "var(--surface-low)", textAlign: "left" }}>
                      {(typeFilter === "all"
                        ? ["Type", "Quand", "Nom", "Contact", "Profil", "Source", "Niche", "Audit", "Statut"]
                        : showAuditCols
                          ? ["Quand", "Nom", "Contact", "Profil", "Niche", "Audit", "Statut"]
                          : ["Quand", "E-mail", "Source", "Statut"]
                      ).map((h) => (
                        <th key={h} style={th}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {filteredLeads.map((lead) => {
                      const optin = isOptin(lead);
                      const leadType: LeadType = optin ? "founders_optin" : "audit";

                      if (!showAuditCols) {
                        return (
                          <tr key={lead.id} style={{ borderTop: "1px solid var(--border)" }}>
                            <td style={td}>{formatWhen(lead.created_at)}</td>
                            <td style={td}>{lead.email}</td>
                            <td style={td}>{lead.input_kind || "—"}</td>
                            <td style={td}>
                              <span style={statusPill(lead.status)}>
                                {STATUS_LABEL[lead.status] || lead.status}
                              </span>
                            </td>
                          </tr>
                        );
                      }

                      return (
                        <tr key={lead.id} style={{ borderTop: "1px solid var(--border)" }}>
                          {typeFilter === "all" && (
                            <td style={td}>
                              <span style={typePill(leadType)}>{TYPE_LABEL[leadType]}</span>
                            </td>
                          )}
                          <td style={td}>{formatWhen(lead.created_at)}</td>
                          <td style={td}>
                            <strong>{lead.full_name?.trim() || "—"}</strong>
                          </td>
                          <td style={td}>
                            <div>{lead.email}</div>
                            {lead.phone?.trim() ? (
                              <div style={{ color: "var(--muted)" }}>{lead.phone}</div>
                            ) : null}
                          </td>
                          <td style={td}>
                            {lead.linkedin_url ? (
                              <a
                                href={lead.linkedin_url}
                                target="_blank"
                                rel="noreferrer"
                                style={{ color: "var(--primary)" }}
                              >
                                LinkedIn
                              </a>
                            ) : lead.website_url ? (
                              <a
                                href={lead.website_url}
                                target="_blank"
                                rel="noreferrer"
                                style={{ color: "var(--primary)" }}
                              >
                                Site
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
                          <td style={td}>{lead.input_kind || "—"}</td>
                          <td style={td}>{lead.niche || "—"}</td>
                          <td style={td}>
                            {optin ? (
                              <span style={{ color: "var(--muted)" }}>—</span>
                            ) : lead.notion_url ? (
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
                              <div
                                style={{
                                  marginTop: 4,
                                  color: "var(--muted)",
                                  fontSize: 11.5,
                                  maxWidth: 220,
                                }}
                              >
                                {lead.error_message}
                              </div>
                            )}
                          </td>
                        </tr>
                      );
                    })}
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

const filterLabel: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  padding: "4px 10px",
  borderRadius: 999,
  border: "1px solid var(--border)",
  background: "var(--surface)",
  color: "var(--text)",
  cursor: "pointer",
  fontSize: 12.5,
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
      : status === "generated"
        ? { bg: "rgba(245,158,11,0.12)", fg: "#b45309" }
        : status === "failed"
        ? { bg: "rgba(239,68,68,0.1)", fg: "#b91c1c" }
        : status === "founders_optin"
          ? { bg: "rgba(99,102,241,0.12)", fg: "#4338ca" }
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

function typePill(type: LeadType): CSSProperties {
  const tone =
    type === "audit"
      ? { bg: "rgba(16,185,129,0.12)", fg: "#047857" }
      : { bg: "rgba(99,102,241,0.12)", fg: "#4338ca" };
  return {
    display: "inline-block",
    padding: "2px 8px",
    borderRadius: 999,
    background: tone.bg,
    color: tone.fg,
    fontSize: 11,
    fontWeight: 700,
    textTransform: "uppercase",
    letterSpacing: "0.04em",
  };
}
