"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { authHeaders, supabase } from "../lib/supabase";

// ALE-59 — Publication multi-réseaux (X + Reddit).
//
// Rangée de logos + panneaux empilés sous le post LinkedIn (mock-up validé :
// pas d'onglets). Un clic sur un logo grisé active le réseau : l'IA adapte le
// post (appel débité), la version apparaît dessous, éditable. Désactiver puis
// réactiver ré-affiche la version déjà adaptée sans re-débiter.
//
// Réservé à la vue agence : le composant se rend à vide pour un compte client
// `ideas_only` (même source de vérité que la bascule de vue : app_metadata).

const DIRECT_API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ??
  "https://analyseur-linkedin-influenceur-api.onrender.com";

export const X_TWEET_MAX = 280;
const REDDIT_TITLE_MAX = 300;

export type CrossPostsDraft = {
  x?: { tweets: string[] };
  reddit?: { title: string; subreddit: string; body: string };
};

type NetStatus = { configured: boolean; connected: boolean } | null;

type SubredditSuggestion = {
  name: string;
  reason?: string;
  in_library?: boolean;
  selfpromo_tolerance?: number | null;
  min_karma_advised?: number | null;
  notes?: string | null;
  exists?: boolean | null;
  subscribers?: number | null;
};

/** Découpe un texte en tweets ≤ 280 (miroir de src/crosspost.py) : paragraphes
 * regroupés tant qu'ils tiennent, longs paragraphes coupés aux phrases/espaces.
 * C'est ce qui part réellement au serveur — le compteur de la pop-up n'est
 * qu'un indicateur, la bascule en thread est automatique. */
export function splitIntoTweets(text: string, limit: number = X_TWEET_MAX): string[] {
  const cleaned = (text || "").trim();
  if (!cleaned) return [];
  if (cleaned.length <= limit) return [cleaned];
  const tweets: string[] = [];
  let current = "";
  const pushChunks = (chunk: string) => {
    let remaining = chunk;
    while (remaining.length > limit) {
      let cut = remaining.lastIndexOf(" ", limit);
      if (cut <= 0) cut = limit;
      tweets.push(remaining.slice(0, cut).trim());
      remaining = remaining.slice(cut).trim();
    }
    return remaining;
  };
  for (const rawPara of cleaned.split("\n\n")) {
    const para = rawPara.trim();
    if (!para) continue;
    const candidate = current ? `${current}\n\n${para}` : para;
    if (candidate.length <= limit) { current = candidate; continue; }
    if (current) { tweets.push(current); current = ""; }
    if (para.length <= limit) { current = para; continue; }
    // Paragraphe seul trop long : phrases d'abord, espaces en dernier recours.
    const sentences = para.split(/(?<=[.!?…])\s+/);
    for (const sentence of sentences) {
      const cand = current ? `${current} ${sentence}` : sentence;
      if (cand.length <= limit) { current = cand; continue; }
      if (current) { tweets.push(current); current = ""; }
      current = sentence.length <= limit ? sentence : pushChunks(sentence);
    }
  }
  if (current) tweets.push(current);
  return tweets.slice(0, 10);
}

/** Publie les versions X/Reddit après le succès de la publication LinkedIn.
 * Best-effort réseau par réseau : renvoie le récapitulatif à afficher. */
export async function publishCrossNetworks(cross: CrossPostsDraft | null | undefined): Promise<{ published: string[]; errors: string[] }> {
  const published: string[] = [];
  const errors: string[] = [];
  if (!cross) return { published, errors };
  if (cross.x) {
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/x/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ content: cross.x.tweets.join("\n\n"), tweets: cross.x.tweets }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Publication sur X impossible");
      published.push(cross.x.tweets.length > 1 ? `X (thread de ${cross.x.tweets.length})` : "X");
    } catch (err: any) {
      errors.push(`X : ${err.message}`);
    }
  }
  if (cross.reddit) {
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/reddit/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ body: cross.reddit.body, title: cross.reddit.title, subreddit: cross.reddit.subreddit }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Publication sur Reddit impossible");
      published.push(`Reddit (r/${cross.reddit.subreddit})`);
    } catch (err: any) {
      errors.push(`Reddit : ${err.message}`);
    }
  }
  return { published, errors };
}

export const XLogo = ({ size = 19, color }: { size?: number; color?: string }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
    <path fill={color ?? "currentColor"} d="M18.24 2.25h3.31l-7.23 8.26L22.83 21.75h-6.66l-5.22-6.82-5.97 6.82H1.66l7.73-8.84L1.17 2.25h6.83l4.71 6.23 5.53-6.23zm-1.16 17.52h1.83L7.08 4.13H5.12l11.96 15.64z" />
  </svg>
);

export const RedditLogo = ({ size = 19, color }: { size?: number; color?: string }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
    <path fill={color ?? "currentColor"} d="M22 12.06c0-1.22-.99-2.2-2.2-2.2-.6 0-1.13.24-1.53.62-1.5-1.08-3.57-1.78-5.87-1.86l1-4.71 3.27.7a1.58 1.58 0 1 0 .16-.78l-3.65-.78a.4.4 0 0 0-.47.31l-1.12 5.25c-2.34.07-4.44.77-5.96 1.87-.4-.38-.93-.62-1.53-.62-1.21 0-2.2.98-2.2 2.2 0 .9.53 1.66 1.3 2-.03.22-.05.44-.05.67 0 3.39 3.95 6.14 8.82 6.14s8.82-2.75 8.82-6.14c0-.22-.02-.45-.05-.66.77-.35 1.31-1.12 1.31-2.01zM6.7 13.62c0-.87.71-1.58 1.58-1.58s1.58.71 1.58 1.58-.71 1.58-1.58 1.58-1.58-.71-1.58-1.58zm8.85 4.17c-1.08 1.08-3.15 1.16-3.76 1.16s-2.68-.08-3.75-1.16a.41.41 0 0 1 .58-.58c.68.68 2.13.92 3.17.92s2.5-.24 3.18-.92a.41.41 0 1 1 .58.58zm-.28-2.59c-.87 0-1.58-.71-1.58-1.58s.71-1.58 1.58-1.58 1.58.71 1.58 1.58-.71 1.58-1.58 1.58z" />
  </svg>
);

function Chip({ tone = "neutral", children }: { tone?: "neutral" | "ok" | "warn"; children: React.ReactNode }) {
  const styles: Record<string, React.CSSProperties> = {
    neutral: { background: "var(--surface)", color: "var(--muted)" },
    ok: { background: "#e7f8f1", color: "#0b7a58" },
    warn: { background: "#fef3e2", color: "#b45309" },
  };
  return (
    <span style={{ fontSize: 11, padding: "3px 8px", borderRadius: 999, whiteSpace: "nowrap", ...styles[tone] }}>
      {children}
    </span>
  );
}

function SubredditChips({ s }: { s: SubredditSuggestion }) {
  const tolerance = s.selfpromo_tolerance ?? null;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
      {s.exists === true && (
        <Chip tone="ok">
          ✓ Vérifié{typeof s.subscribers === "number" && s.subscribers > 0 ? ` · ${s.subscribers.toLocaleString("fr-FR")} membres` : ""}
        </Chip>
      )}
      {s.exists === false && <Chip tone="warn">⚠ Introuvable sur Reddit</Chip>}
      {tolerance !== null && tolerance <= 2 && <Chip tone="warn">⚠ Autopromo mal vue — reste 100 % valeur</Chip>}
      {tolerance !== null && tolerance >= 4 && <Chip tone="ok">Autopromo tolérée si transparente</Chip>}
      {typeof s.min_karma_advised === "number" && <Chip>Karma min. conseillé : {s.min_karma_advised}</Chip>}
      {s.notes ? <span style={{ fontSize: 11, color: "var(--muted)", flexBasis: "100%" }}>{s.notes}</span> : null}
    </div>
  );
}

const fieldLabelStyle: React.CSSProperties = {
  display: "flex", alignItems: "center", justifyContent: "space-between",
  fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em",
  color: "var(--muted)", margin: "0 0 6px",
};

function Counter({ len, max }: { len: number; max: number }) {
  return (
    <span style={{ textTransform: "none", letterSpacing: 0, fontVariantNumeric: "tabular-nums", ...(len > max ? { color: "#ef4444", fontWeight: 600 } : {}) }}>
      {len.toLocaleString("fr-FR")} / {max}
    </span>
  );
}

export default function CrossNetworkPanels({
  baseText,
  disabled = false,
  onChange,
}: {
  /** Texte LinkedIn courant — la matière première de l'adaptation. */
  baseText: string;
  disabled?: boolean;
  onChange: (cross: CrossPostsDraft | null, valid: boolean) => void;
}) {
  const [agency, setAgency] = useState(false);
  // Feature flags (déploiement progressif) : la liste vient du SERVEUR
  // (/me/features), fail closed pendant le chargement — sans flag, la rangée
  // de logos n'existe pas pour ce compte.
  const [feats, setFeats] = useState<string[] | null>(null);
  const [xStatus, setXStatus] = useState<NetStatus>(null);
  const [redditStatus, setRedditStatus] = useState<NetStatus>(null);
  const [hint, setHint] = useState("");

  const [xActive, setXActive] = useState(false);
  const [xLoading, setXLoading] = useState(false);
  const [xError, setXError] = useState("");
  const [xText, setXText] = useState("");
  const [xAdapted, setXAdapted] = useState(false);

  const [redditActive, setRedditActive] = useState(false);
  const [redditLoading, setRedditLoading] = useState(false);
  const [redditError, setRedditError] = useState("");
  const [redditAdapted, setRedditAdapted] = useState(false);
  const [redditTitle, setRedditTitle] = useState("");
  const [redditBody, setRedditBody] = useState("");
  const [suggestions, setSuggestions] = useState<SubredditSuggestion[]>([]);
  const [selectedSub, setSelectedSub] = useState("");
  const [customMode, setCustomMode] = useState(false);
  const [customName, setCustomName] = useState("");
  const [customChecking, setCustomChecking] = useState(false);

  // Vue agence uniquement : un compte client `ideas_only` ne voit rien de tout ça.
  useEffect(() => {
    let alive = true;
    supabase.auth.getSession().then(({ data }) => {
      if (!alive) return;
      const role = (data.session?.user?.app_metadata as Record<string, unknown> | undefined)?.role;
      setAgency(role !== "ideas_only");
      if (role !== "ideas_only") {
        authHeaders().then((headers) => {
          fetch(`${DIRECT_API_URL}/me/features`, { headers })
            .then((r) => (r.ok ? r.json() : { features: [] }))
            .then((d) => { if (alive) setFeats(Array.isArray(d?.features) ? d.features : []); })
            .catch(() => { if (alive) setFeats([]); });
          fetch(`${DIRECT_API_URL}/me/x/status`, { headers }).then((r) => (r.ok ? r.json() : null)).then((s) => { if (alive) setXStatus(s); }).catch(() => {});
          fetch(`${DIRECT_API_URL}/me/reddit/status`, { headers }).then((r) => (r.ok ? r.json() : null)).then((s) => { if (alive) setRedditStatus(s); }).catch(() => {});
        });
      }
    });
    return () => { alive = false; };
  }, []);

  const selectedSuggestion = useMemo(
    () => suggestions.find((s) => s.name === selectedSub) ?? null,
    [suggestions, selectedSub],
  );

  // Remonte l'état au parent à chaque changement pertinent.
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  useEffect(() => {
    const cross: CrossPostsDraft = {};
    let valid = true;
    if (xActive) {
      const tweets = splitIntoTweets(xText);
      if (tweets.length > 0 && !xLoading) cross.x = { tweets };
      else valid = false;
    }
    if (redditActive) {
      const sub = customMode ? "" : selectedSub;
      if (!redditLoading && redditTitle.trim() && redditTitle.trim().length <= REDDIT_TITLE_MAX && redditBody.trim() && sub) {
        cross.reddit = { title: redditTitle.trim(), subreddit: sub, body: redditBody.trim() };
      } else {
        valid = false;
      }
    }
    const any = !!cross.x || !!cross.reddit;
    onChangeRef.current(any ? cross : null, valid);
  }, [xActive, xText, xLoading, redditActive, redditLoading, redditTitle, redditBody, selectedSub, customMode]);

  async function adaptX() {
    setXLoading(true);
    setXError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/publish/adapt/x`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ content: baseText }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Adaptation X impossible");
      setXText((data.tweets || []).join("\n\n"));
      setXAdapted(true);
    } catch (err: any) {
      setXError(err.message || "Adaptation X impossible");
    } finally {
      setXLoading(false);
    }
  }

  async function adaptReddit() {
    setRedditLoading(true);
    setRedditError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/publish/adapt/reddit`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ content: baseText }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Adaptation Reddit impossible");
      setRedditTitle(data.title || "");
      setRedditBody(data.body || "");
      const subs: SubredditSuggestion[] = Array.isArray(data.suggestions) ? data.suggestions : [];
      setSuggestions(subs);
      setSelectedSub(subs[0]?.name || "");
      setCustomMode(subs.length === 0);
      setRedditAdapted(true);
    } catch (err: any) {
      setRedditError(err.message || "Adaptation Reddit impossible");
    } finally {
      setRedditLoading(false);
    }
  }

  async function checkCustomSubreddit() {
    const name = customName.trim().replace(/^\/?(r\/)?/i, "").replace(/\/+$/, "");
    if (!name) return;
    setCustomChecking(true);
    setRedditError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/reddit/subreddit-info?name=${encodeURIComponent(name)}`, {
        headers: await authHeaders(),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Vérification impossible");
      if (data.exists === false) throw new Error(`r/${name} est introuvable sur Reddit (ou privé).`);
      setSuggestions((prev) => [...prev.filter((s) => s.name !== data.name), { ...data, reason: "ajouté à la main" }]);
      setSelectedSub(data.name);
      setCustomMode(false);
      setCustomName("");
    } catch (err: any) {
      setRedditError(err.message || "Vérification impossible");
    } finally {
      setCustomChecking(false);
    }
  }

  function toggleX() {
    setHint("");
    if (xActive) { setXActive(false); return; }
    if (!xStatus?.connected) {
      setHint("Connecte ton compte X dans Mon profil → Connexions pour publier sur X.");
      return;
    }
    setXActive(true);
    if (!xAdapted && !xLoading) void adaptX();
  }

  function toggleReddit() {
    setHint("");
    if (redditActive) { setRedditActive(false); return; }
    if (!redditStatus?.connected) {
      setHint("Connecte ton compte Reddit dans Mon profil → Connexions pour publier sur Reddit.");
      return;
    }
    setRedditActive(true);
    if (!redditAdapted && !redditLoading) void adaptReddit();
  }

  // Rien à proposer : vue client, ou compte sans aucun des deux flags
  // (déploiement progressif — fail closed tant que les droits ne sont pas lus).
  const hasX = (feats || []).includes("x");
  const hasReddit = (feats || []).includes("reddit");
  if (!agency || (!hasX && !hasReddit)) return null;
  const activeCount = 1 + (xActive ? 1 : 0) + (redditActive ? 1 : 0);

  const netButtonStyle = (pressed: boolean, color: string): React.CSSProperties => ({
    display: "inline-flex", alignItems: "center", justifyContent: "center",
    width: 38, height: 38, borderRadius: 10, cursor: disabled ? "default" : "pointer",
    border: `1.5px solid ${pressed ? color : "var(--border)"}`,
    background: pressed ? `color-mix(in srgb, ${color} 7%, var(--surface, #fff))` : "transparent",
    color: pressed ? color : "#b9b9c4",
    padding: 0, transition: "border-color 0.15s, color 0.15s",
  });

  return (
    <div data-testid="cross-network-panels">
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", padding: "4px 0 12px" }}>
        <span style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--muted)" }}>Réseaux</span>
        <span title="LinkedIn (toujours actif)" aria-label="LinkedIn — toujours actif" style={{ ...netButtonStyle(true, "#0a66c2"), cursor: "default" }}>
          <svg width={19} height={19} viewBox="0 0 24 24" aria-hidden="true"><path fill="#0a66c2" d="M4.98 3.5C4.98 4.88 3.87 6 2.5 6S0 4.88 0 3.5 1.12 1 2.5 1s2.48 1.12 2.48 2.5zM.22 8.1h4.56V23H.22V8.1zM8.34 8.1h4.37v2.03h.06c.61-1.15 2.1-2.37 4.32-2.37 4.62 0 5.47 3.04 5.47 7v8.24h-4.55v-7.3c0-1.74-.03-3.98-2.43-3.98-2.43 0-2.8 1.9-2.8 3.86V23H8.34V8.1z" /></svg>
        </span>
        {/* Logos inactifs tant que le statut de connexion n'est pas chargé : un
            clic trop tôt afficherait à tort « connecte ton compte ». Chaque
            logo n'existe que pour un compte porteur du flag correspondant. */}
        {hasX && (
          <button
            type="button"
            aria-pressed={xActive}
            aria-label="Publier aussi sur X"
            disabled={disabled || xStatus === null}
            onClick={toggleX}
            style={netButtonStyle(xActive, "#1b1b23")}
            onMouseEnter={(e) => { if (!xActive) e.currentTarget.style.color = "#1b1b23"; }}
            onMouseLeave={(e) => { if (!xActive) e.currentTarget.style.color = "#b9b9c4"; }}
          >
            <XLogo />
          </button>
        )}
        {hasReddit && (
          <button
            type="button"
            aria-pressed={redditActive}
            aria-label="Publier aussi sur Reddit"
            disabled={disabled || redditStatus === null}
            onClick={toggleReddit}
            style={netButtonStyle(redditActive, "#ff4500")}
            onMouseEnter={(e) => { if (!redditActive) e.currentTarget.style.color = "#ff4500"; }}
            onMouseLeave={(e) => { if (!redditActive) e.currentTarget.style.color = "#b9b9c4"; }}
          >
            <RedditLogo />
          </button>
        )}
        <span style={{ fontSize: 12, color: "var(--muted)" }}>
          {activeCount === 1
            ? "LinkedIn seul — clique un logo pour adapter le post à un autre réseau"
            : "Le post sera adapté à chaque réseau avant l’envoi"}
        </span>
      </div>
      {hint && <p style={{ fontSize: 12.5, color: "#b45309", margin: "0 0 10px" }}>{hint}</p>}

      {xActive && (
        <section style={{ borderTop: "1px solid var(--border)", padding: "12px 0" }} data-testid="x-panel">
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <XLogo size={15} color="#1b1b23" />
            <span style={{ fontSize: 13, fontWeight: 600 }}>X</span>
            <span style={{ fontSize: 11, color: "var(--muted)" }}>adapté par l’IA — éditable</span>
          </div>
          {xLoading ? (
            <p style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--muted)", fontSize: 13 }}>
              <span className="spinning" style={{ width: 14, height: 14, borderRadius: "50%", border: "2px solid var(--border)", borderTopColor: "var(--primary)", display: "inline-block" }} />
              Adaptation du post pour X…
            </p>
          ) : xError ? (
            <p style={{ fontSize: 13, color: "#ef4444" }}>
              {xError}{" "}
              <button type="button" className="secondary-button" style={{ minHeight: 26, padding: "0 8px", fontSize: 12 }} onClick={() => void adaptX()}>Réessayer</button>
            </p>
          ) : (
            <>
              <p style={fieldLabelStyle}><span>Version X</span><Counter len={xText.length} max={X_TWEET_MAX} /></p>
              <textarea
                value={xText}
                onChange={(e) => setXText(e.target.value)}
                rows={5}
                className="variant-text"
                style={{ width: "100%", boxSizing: "border-box" }}
                disabled={disabled}
                aria-label="Version X du post"
              />
              <p style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--muted)", margin: "8px 0 0" }}>
                <span style={{ color: "var(--primary)" }}>✦</span>
                {splitIntoTweets(xText).length > 1
                  ? `Au-delà de 280 caractères, le texte part en thread — ici ${splitIntoTweets(xText).length} tweets.`
                  : "Au-delà de 280 caractères, le texte partira en thread."}
              </p>
            </>
          )}
        </section>
      )}

      {redditActive && (
        <section style={{ borderTop: "1px solid var(--border)", padding: "12px 0" }} data-testid="reddit-panel">
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <RedditLogo size={15} color="#ff4500" />
            <span style={{ fontSize: 13, fontWeight: 600 }}>Reddit</span>
            <span style={{ fontSize: 11, color: "var(--muted)" }}>adapté par l’IA — éditable</span>
          </div>
          {redditLoading ? (
            <p style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--muted)", fontSize: 13 }}>
              <span className="spinning" style={{ width: 14, height: 14, borderRadius: "50%", border: "2px solid var(--border)", borderTopColor: "var(--primary)", display: "inline-block" }} />
              Adaptation du post pour Reddit…
            </p>
          ) : redditError && !redditAdapted ? (
            <p style={{ fontSize: 13, color: "#ef4444" }}>
              {redditError}{" "}
              <button type="button" className="secondary-button" style={{ minHeight: 26, padding: "0 8px", fontSize: 12 }} onClick={() => void adaptReddit()}>Réessayer</button>
            </p>
          ) : (
            <>
              <p style={fieldLabelStyle}><span>Subreddit</span></p>
              <select
                value={customMode ? "__custom__" : selectedSub}
                onChange={(e) => {
                  if (e.target.value === "__custom__") { setCustomMode(true); }
                  else { setCustomMode(false); setSelectedSub(e.target.value); }
                }}
                disabled={disabled}
                aria-label="Subreddit"
                style={{ width: "100%", boxSizing: "border-box", padding: "8px 10px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)", fontSize: 13.5 }}
              >
                {suggestions.map((s, i) => (
                  <option key={s.name} value={s.name}>
                    r/{s.name}{i === 0 && s.reason !== "ajouté à la main" ? " — suggéré pour ton profil" : ""}
                  </option>
                ))}
                <option value="__custom__">Autre…</option>
              </select>
              {customMode && (
                <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                  <input
                    type="text"
                    value={customName}
                    onChange={(e) => setCustomName(e.target.value)}
                    placeholder="r/nomdusubreddit"
                    aria-label="Nom du subreddit"
                    style={{ flex: 1, boxSizing: "border-box", padding: "8px 10px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)", fontSize: 13.5 }}
                    onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void checkCustomSubreddit(); } }}
                  />
                  <button type="button" className="secondary-button" disabled={customChecking || !customName.trim()} onClick={() => void checkCustomSubreddit()}>
                    {customChecking ? "Vérification…" : "Vérifier"}
                  </button>
                </div>
              )}
              {redditError && <p style={{ fontSize: 12.5, color: "#ef4444", margin: "8px 0 0" }}>{redditError}</p>}
              {!customMode && selectedSuggestion && <SubredditChips s={selectedSuggestion} />}

              <p style={{ ...fieldLabelStyle, marginTop: 12 }}>
                <span>Titre (obligatoire)</span>
                <Counter len={redditTitle.length} max={REDDIT_TITLE_MAX} />
              </p>
              <input
                type="text"
                value={redditTitle}
                onChange={(e) => setRedditTitle(e.target.value)}
                disabled={disabled}
                aria-label="Titre du post Reddit"
                style={{ width: "100%", boxSizing: "border-box", padding: "8px 10px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)", fontSize: 13.5 }}
              />
              <p style={{ ...fieldLabelStyle, marginTop: 12 }}><span>Corps du post</span></p>
              <textarea
                value={redditBody}
                onChange={(e) => setRedditBody(e.target.value)}
                rows={7}
                className="variant-text"
                style={{ width: "100%", boxSizing: "border-box" }}
                disabled={disabled}
                aria-label="Corps du post Reddit"
              />
            </>
          )}
        </section>
      )}
    </div>
  );
}
