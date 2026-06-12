"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  Activity,
  BarChart3,
  CheckCircle2,
  Clock3,
  Download,
  FileText,
  Lightbulb,
  Link2,
  Loader2,
  Lock,
  LogIn,
  LogOut,
  PenTool,
  RefreshCw,
  Sparkles,
  TrendingUp,
  Zap,
} from "lucide-react";
import type { Session } from "@supabase/supabase-js";
import AuthModal, { type AuthMode } from "./components/AuthModal";
import { authHeaders, supabase } from "./lib/supabase";

const API_URL = "/api";
const DIRECT_API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ??
  "https://analyseur-linkedin-influenceur-api.onrender.com";

type Health = { ok: boolean; apify: boolean; anthropic: boolean; model: string };
type Report = { name: string; path: string; updated_at: number; content: string };
type Analysis = {
  handle: string;
  profile: Record<string, any>;
  posts: any[];
  stats: Record<string, any>;
  patterns: Record<string, any>;
  cta_stats: Record<string, any>;
  synthesis: Record<string, any>;
  usage: Record<string, any>;
  markdown: string;
  path: string;
};
type Idea = {
  title: string;
  hook: string;
  hook_type: string;
  funnel: string;
  angle: string;
  why_it_works: string;
  difficulty: string;
  estimated_lift: string;
};
type Variant = {
  hook_type: string;
  strategy: string;
  predicted_lift: string;
  post: string;
};
type DashboardData = {
  influencer_count: number;
  influencers: {
    handle: string;
    name: string;
    headline: string;
    followers: number;
    posts_analyzed: number;
    posts_per_week: number | null;
    avg_engagement: number;
    median_comments: number;
    engagement_rate_pct: number | null;
    top_format: string;
  }[];
  aggregated: {
    total_posts: number;
    total_followers: number;
    avg_likes: number;
    median_likes: number;
    avg_comments: number;
    median_comments: number;
    avg_reposts: number;
    avg_engagement: number;
    median_engagement: number;
    format_distribution: Record<string, number>;
    hook_distribution: Record<string, number>;
    weekday_distribution: Record<string, number>;
  };
};

type GrowthRow = {
  handle: string;
  name: string;
  total_posts: number;
  split_at: number;
  date_post_split: string;
  avg_eng_before: number;
  avg_eng_after: number | null;
  growth_pct: number | null;
};

const tabs = ["Rapport", "Top posts", "Patterns", "Usage", "Tous les posts", "JSON brut"];
const steps = [
  "Scraping du profil",
  "Récupération des posts récents",
  "Calcul des statistiques",
  "Détection des patterns",
  "Classification TOFU/MOFU/BOFU",
  "Génération du rapport",
];

function fmt(value: any) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return value.toLocaleString("fr-FR");
  return String(value);
}

function totalCost(usage?: Record<string, any>) {
  return Number(usage?.apify?.estimated_cost_usd || 0) + Number(usage?.anthropic?.estimated_cost_usd || 0);
}

/* ── Freemium gating helpers ───────────────────────────────────────────── */

const ANON_USED_KEY = "lkd_anon_used";
const ACTIONS_HEADING = "## ✨ Actions à répliquer";

function anonAnalysisUsed(): boolean {
  try {
    return localStorage.getItem(ANON_USED_KEY) === "1";
  } catch {
    return false;
  }
}
function markAnonAnalysisUsed() {
  try {
    localStorage.setItem(ANON_USED_KEY, "1");
  } catch {
    /* ignore */
  }
}

/** 2/3 of n, at least 1 (5→3, 4→3, 3→2). */
function keepTwoThirds(n: number): number {
  return Math.max(1, Math.round((n * 2) / 3));
}

/** Markdown up to (but excluding) the "Actions à répliquer" section. */
function reportBeforeActions(markdown: string): string {
  const idx = markdown.indexOf(ACTIONS_HEADING);
  return idx === -1 ? markdown : markdown.slice(0, idx).trimEnd();
}

const LIST_ITEM_RE = /^(\s*)([-*+]\s+|\d+\.\s+)/;

/**
 * Truncate each substantial bullet/numbered list (≥4 items) to ~2/3 of its
 * items and drop a `[[LOCK:n]]` marker — rendered as a clickable blurred chip
 * by `reportComponents`. Tables and short lists are left untouched.
 */
function truncateLists(markdown: string): string {
  const lines = markdown.split("\n");
  const out: string[] = [];
  let i = 0;
  while (i < lines.length) {
    if (LIST_ITEM_RE.test(lines[i])) {
      let j = i;
      while (j < lines.length && LIST_ITEM_RE.test(lines[j])) j++;
      const run = lines.slice(i, j);
      if (run.length >= 4) {
        const keep = keepTwoThirds(run.length);
        const hidden = run.slice(keep).map(l => l.replace(LIST_ITEM_RE, "").trim()).join(" § ");
        out.push(...run.slice(0, keep), "", `[[BLUR:${hidden}]]`, "");
      } else {
        out.push(...run);
      }
      i = j;
    } else {
      out.push(lines[i]);
      i++;
    }
  }
  return out.join("\n");
}

/** Custom ReactMarkdown renderers: turn `[[BLUR:...]]` paragraphs into blurred list items. */
function reportComponents(_onUnlock: () => void) {
  return {
    p({ children }: { children?: React.ReactNode }) {
      const text = Array.isArray(children) ? children.join("") : children;
      const blur = typeof text === "string" ? text.match(/^\[\[BLUR:(.*)\]\]$/) : null;
      if (blur) {
        const items = blur[1].split(" § ");
        return (
          <ul className="blurred-items" aria-hidden>
            {items.map((item, idx) => <li key={idx}>{item}</li>)}
          </ul>
        );
      }
      return <p>{children}</p>;
    },
  };
}

/** Blurred-content card with a centered sign-up CTA overlay. */
function LockedCard({
  title,
  subtitle,
  ghostLines = 4,
  onUnlock,
}: {
  title: string;
  subtitle?: string;
  ghostLines?: number;
  onUnlock: () => void;
}) {
  return (
    <div className="locked-card">
      <div className="blurred" aria-hidden>
        {Array.from({ length: ghostLines }).map((_, i) => (
          <p key={i} style={{ margin: "0 0 10px" }}>
            {"▮".repeat(18 - (i % 3) * 4)} {"▯".repeat(10 + (i % 4) * 3)}
          </p>
        ))}
      </div>
      <div className="lock-overlay">
        <span className="lock-badge"><Lock size={18} /></span>
        <h4>{title}</h4>
        {subtitle ? <p>{subtitle}</p> : null}
        <button type="button" className="primary-button" onClick={onUnlock}>
          <Sparkles size={14} /> Créer un compte gratuit
        </button>
      </div>
    </div>
  );
}

function Sidebar({
  health,
  reports,
  view,
  isAuthed,
  onNavigate,
  onLoadReport,
  requireAuth,
}: {
  health: Health | null;
  reports: Report[];
  view: MainView;
  isAuthed: boolean;
  onNavigate: (v: MainView) => void;
  onLoadReport: (report: Report) => void;
  requireAuth: (reason?: string, mode?: AuthMode) => void;
}) {
  const navItems: { key: MainView; label: string; icon: React.ReactNode; premium?: boolean }[] = [
    { key: "analyze", label: "Analyser", icon: <Zap size={14} /> },
    { key: "generator", label: "Générateur de posts", icon: <PenTool size={14} />, premium: true },
    { key: "dashboard", label: "Dashboard", icon: <TrendingUp size={14} />, premium: true },
  ];

  return (
    <aside className="sidebar">
      <div className="logo">
        <div className="logo-mark">SD</div>
        <div className="logo-text">
          Strategy Decoder
          <span className="logo-sub">SaaS Premium</span>
        </div>
      </div>

      <button className="primary-button" style={{ width: "100%", marginBottom: 12 }} onClick={() => onNavigate("analyze")}>
        <Sparkles size={14} /> Nouvelle analyse
      </button>

      {/* Sidebar navigation */}
      <section className="sidebar-section">
        <p className="eyebrow">Navigation</p>
        <div className="nav-list">
          {navItems.map((item) => {
            const locked = !!item.premium && !isAuthed;
            return (
              <button
                key={item.key}
                className={`nav-item ${view === item.key ? "active" : ""} ${locked ? "locked" : ""}`}
                onClick={() =>
                  locked
                    ? requireAuth("Crée un compte gratuit pour débloquer le générateur de posts et le dashboard global.")
                    : onNavigate(item.key)
                }
              >
                {item.icon}
                <span>{item.label}</span>
                {locked ? <Lock size={12} className="lock-ico" /> : null}
              </button>
            );
          })}
        </div>
      </section>

      <section className="sidebar-section">
        <p className="eyebrow">Analyses récentes</p>
        <div className="report-list">
          {!isAuthed ? (
            <div className="report-card" onClick={() => requireAuth("Crée un compte gratuit pour conserver ton historique d'analyses.")} style={{ cursor: "pointer" }}>
              <div className="report-icon"><Lock size={13} /></div>
              <div>
                <strong>Historique verrouillé</strong>
                <span>Crée un compte pour le conserver</span>
              </div>
            </div>
          ) : reports.length ? reports.map((report) => (
            <div className="report-card" key={report.path} onClick={() => onLoadReport(report)}>
              <div className="report-icon"><FileText size={13} /></div>
              <div>
                <strong>{report.name}</strong>
                <span>{new Date(report.updated_at * 1000).toLocaleDateString("fr-FR")}</span>
              </div>
            </div>
          )) : (
            <div className="report-card">
              <div className="report-icon"><FileText size={13} /></div>
              <div>
                <strong>Aucun rapport</strong>
                <span>Lance ta première analyse</span>
              </div>
            </div>
          )}
        </div>
      </section>

      <section className="sidebar-section" style={{ marginTop: "auto" }}>
        <div className="config-card">
          <p className="eyebrow" style={{ margin: 0 }}>Config</p>
          <div className="config-row">
            <span>Apify</span>
            <b className={`status-pill ${health?.apify ? "ok" : "no"}`}>{health?.apify ? "OK" : "Manquant"}</b>
          </div>
          <div className="config-row">
            <span>Anthropic</span>
            <b className={`status-pill ${health?.anthropic ? "ok" : "no"}`}>{health?.anthropic ? "OK" : "Manquant"}</b>
          </div>
          <div className="config-row">
            <span>Modèle</span>
            <b className="status-pill" style={{ maxWidth: 100, overflow: "hidden", textOverflow: "ellipsis" }}>{health?.model || "—"}</b>
          </div>
        </div>
      </section>
    </aside>
  );
}

function TopHeader({
  result,
  view,
  isAuthed,
  userEmail,
  onReset,
  onSignIn,
  onSignUp,
  onSignOut,
}: {
  result: Analysis | null;
  view: MainView;
  isAuthed: boolean;
  userEmail?: string;
  onReset: () => void;
  onSignIn: () => void;
  onSignUp: () => void;
  onSignOut: () => void;
}) {
  const viewTitles: Record<MainView, string> = {
    analyze: "Décodeur de stratégie LinkedIn",
    generator: "Générateur de posts",
    dashboard: "Dashboard global",
  };

  return (
    <header className="top-header">
      <div className="header-profile">
        {result && view === "analyze" ? (
          <>
            <div className="avatar" style={{ width: 28, height: 28, borderRadius: 7, fontSize: 11 }}>
              {(result.profile?.name || result.handle || "LI").slice(0, 2).toUpperCase()}
            </div>
            <span style={{ fontWeight: 600, color: "var(--ink)" }}>{result.profile?.name || result.handle}</span>
            <span style={{ color: "var(--border)" }}>·</span>
            <span>{result.profile?.headline?.slice(0, 50)}</span>
          </>
        ) : (
          <span className="header-title">{viewTitles[view]}</span>
        )}
      </div>
      <div className="header-actions">
        {result && view === "analyze" ? (
          <>
            {isAuthed ? (
              <a
                className="secondary-button"
                href={`data:text/markdown;charset=utf-8,${encodeURIComponent(result.markdown)}`}
                download={`${result.handle}.md`}
              >
                <Download size={13} /> Télécharger .md
              </a>
            ) : null}
            <button className="secondary-button" onClick={onReset}>
              <RefreshCw size={13} /> Relancer
            </button>
          </>
        ) : null}
        <div className="header-auth">
          {isAuthed ? (
            <button className="header-user" title={userEmail ?? "Déconnexion"} onClick={onSignOut}>
              <LogOut size={14} />
              <span>{userEmail}</span>
            </button>
          ) : (
            <>
              <button className="secondary-button" onClick={onSignIn}>
                <LogIn size={13} /> Se connecter
              </button>
              <button className="primary-button" onClick={onSignUp}>
                <Sparkles size={13} /> Créer un compte gratuit
              </button>
            </>
          )}
        </div>
      </div>
    </header>
  );
}

function Landing({ onSubmit, loading, error }: {
  onSubmit: (payload: { url: string; limit: number; useCache: boolean; runLlm: boolean }) => void;
  loading: boolean;
  error: string;
}) {
  const [url, setUrl] = useState("");
  const [limit, setLimit] = useState(25);
  const [useCache, setUseCache] = useState(true);
  const [runLlm, setRunLlm] = useState(true);

  return (
    <section className="hero">
      <div className="hero-content">
        <p className="eyebrow">Décodeur de stratégie LinkedIn</p>
        <h1>Décrypte n'importe quelle <span className="gradient-text">stratégie LinkedIn</span> en 60 secondes</h1>
        <p>Colle l'URL d'un profil. On scrape ses posts récents, on extrait hooks, CTAs, mix funnel, et on te dit quoi répliquer.</p>

        <div className="analyzer-card">
          <div className="url-input">
            <Link2 size={16} color="var(--primary)" />
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://www.linkedin.com/in/nom-influenceur/"
              onKeyDown={(e) => e.key === "Enter" && onSubmit({ url, limit, useCache, runLlm })}
            />
            <button
              className="primary-button"
              disabled={loading}
              onClick={() => onSubmit({ url, limit, useCache, runLlm })}
            >
              {loading ? <Loader2 size={14} /> : <Zap size={14} />} Analyser
            </button>
          </div>

          <div className="controls">
            <label className="control">
              <span>Posts à analyser : <b>{limit}</b></span>
              <input type="range" min="10" max="50" value={limit} onChange={(e) => setLimit(Number(e.target.value))} />
            </label>
            <label className="control" onClick={() => setUseCache(!useCache)} style={{ cursor: "pointer" }}>
              <span>Utiliser le cache</span>
              <button className={`switch ${useCache ? "on" : ""}`} onClick={(e) => { e.preventDefault(); setUseCache(!useCache); }} />
            </label>
            <label className="control" onClick={() => setRunLlm(!runLlm)} style={{ cursor: "pointer" }}>
              <span>Synthèse Claude</span>
              <button className={`switch ${runLlm ? "on" : ""}`} onClick={(e) => { e.preventDefault(); setRunLlm(!runLlm); }} />
            </label>
          </div>
        </div>

        {error ? <div className="error">{error}</div> : null}

        <div className="feature-grid">
          <div className="feature">
            <BarChart3 size={18} color="var(--primary)" />
            <h3>Stats déterministes</h3>
            <p>Cadence, timing, formats et médianes d'engagement.</p>
          </div>
          <div className="feature">
            <Activity size={18} color="var(--primary)" />
            <h3>Détection de patterns</h3>
            <p>Hooks, CTAs, signatures et sections récurrentes.</p>
          </div>
          <div className="feature">
            <Sparkles size={18} color="var(--primary)" />
            <h3>Synthèse IA</h3>
            <p>Classification TOFU/MOFU/BOFU et actions à répliquer.</p>
          </div>
        </div>
      </div>
    </section>
  );
}

function LoadingState() {
  return (
    <section className="hero">
      <div className="hero-content">
        <p className="eyebrow">Analyse en cours</p>
        <h1>Construction de ton <span className="gradient-text">rapport stratégique</span></h1>
        <p>Scraping, normalisation et synthèse des derniers signaux de contenu.</p>
        <div className="loading-panel card">
          {steps.map((step, index) => (
            <div className="step" key={step}>
              {index < 2
                ? <CheckCircle2 size={16} color="#10b981" />
                : index === 2
                  ? <span className="spinner" />
                  : <Clock3 size={16} color="var(--muted)" />}
              <span>{step}</span>
            </div>
          ))}
          <p className="eyebrow" style={{ marginTop: 12, marginBottom: 0 }}>Coût estimé ≈ 0,42 $</p>
        </div>
      </div>
    </section>
  );
}

function Kpis({ result }: { result: Analysis }) {
  const profile = result.profile || {};
  const stats = result.stats || {};
  const engagement = stats.engagement || {};
  const usage = result.usage || {};
  return (
    <>
      <div className="kpi-grid">
        <div className="kpi-card"><span>Abonnés</span><div className="metric">{fmt(profile.follower_count)}</div></div>
        <div className="kpi-card"><span>Posts analysés</span><div className="metric">{fmt(stats.count)}</div></div>
        <div className="kpi-card"><span>Posts / semaine</span><div className="metric">{fmt(stats.posts_per_week)}</div></div>
        <div className="kpi-card"><span>Comments médian</span><div className="metric">{fmt(engagement.median_comments)}</div></div>
        <div className="kpi-card"><span>Taux d'engagement</span><div className="metric">{engagement.engagement_rate_pct ? `${engagement.engagement_rate_pct}%` : "—"}</div></div>
      </div>
      <div className="usage-grid">
        <div className="usage-card"><span>Appels Apify</span><div className="metric">{fmt(usage.apify?.runs || 0)}</div></div>
        <div className="usage-card"><span>Items Apify</span><div className="metric">{fmt(usage.apify?.items || 0)}</div></div>
        <div className="usage-card"><span>Tokens Anthropic</span><div className="metric">{fmt((usage.anthropic?.input_tokens || 0) + (usage.anthropic?.output_tokens || 0))}</div></div>
        <div className="usage-card"><span>Coût estimé</span><div className="metric">{totalCost(usage).toFixed(4)} $</div></div>
      </div>
    </>
  );
}

function Bar({ label, value, max }: { label: string; value: number; max: number }) {
  return (
    <div className="bar-row">
      <span>{label}</span>
      <div className="bar-track"><div className="bar-fill" style={{ width: `${Math.max(4, (value / max) * 100)}%` }} /></div>
      <b>{value}</b>
    </div>
  );
}

function Patterns({ result, limit, onUnlock }: { result: Analysis; limit?: number; onUnlock?: () => void }) {
  const patterns = result.patterns || {};
  const stats = result.stats || {};
  const hookEntries = Object.entries(patterns.hook_distribution || {}) as [string, number][];
  const lengthEntries = Object.entries(patterns.length_distribution || {}) as [string, number][];
  const maxHook = Math.max(1, ...hookEntries.map(([, n]) => n));
  const maxLength = Math.max(1, ...lengthEntries.map(([, n]) => n));
  const heat = Array.from({ length: 84 }, (_, i) => ((i * 7) % 11) / 10 + 0.08);

  const cards = [
    <div className="card" key="hooks"><h3>Hooks (1ère ligne)</h3>{hookEntries.map(([label, n]) => <Bar key={label} label={label} value={n} max={maxHook} />)}</div>,
    <div className="card" key="length"><h3>Longueur des posts</h3>{lengthEntries.map(([label, n]) => <Bar key={label} label={label} value={n} max={maxLength} />)}</div>,
    <div className="card" key="cta">
      <h3>CTA détectés</h3>
      <div className="metric">{patterns.cta_count || 0} / {result.posts.length}</div>
      <p><span className="badge">{patterns.cta_share_pct || 0}% des posts</span></p>
      <pre className="raw-json">{JSON.stringify(result.cta_stats, null, 2)}</pre>
    </div>,
    <div className="card" key="rythme"><h3>Rythme de publication</h3><div className="heatmap">{heat.map((a, i) => <span className="heat-cell" style={{ "--a": a } as any} key={i} />)}</div></div>,
    <div className="card" key="signatures"><h3>Signatures visuelles</h3>{(patterns.visual_signatures || []).map(([symbol, n]: [string, number]) => <p key={symbol}><span className="badge">{symbol}</span> présent dans {n} posts</p>)}</div>,
    <div className="card" key="weekday"><h3>Jours de publication</h3>{Object.entries(stats.weekday_distribution || {}).map(([label, n]) => <Bar key={label} label={label} value={Number(n)} max={Math.max(1, ...Object.values(stats.weekday_distribution || {}).map(Number))} />)}</div>,
  ];

  const gated = limit != null && limit < cards.length;
  const shown = gated ? cards.slice(0, limit) : cards;
  return (
    <div className="pattern-grid">
      {shown}
      {gated && onUnlock ? (
        <LockedCard
          title={`+${cards.length - shown.length} patterns à débloquer`}
          subtitle="Crée ton compte gratuit pour voir tous les patterns détectés (rythme, signatures, jours…)."
          ghostLines={4}
          onUnlock={onUnlock}
        />
      ) : null}
    </div>
  );
}

function TopPosts({ result, limit, onUnlock }: { result: Analysis; limit?: number; onUnlock?: () => void }) {
  const allPosts = result.stats?.top_posts_by_comments || [];
  const gated = limit != null && limit < allPosts.length;
  const posts = gated ? allPosts.slice(0, limit) : allPosts;
  return (
    <div className="post-list">
      {posts.map((post: any, i: number) => (
        <div className="post-card" key={`${post.url}-${i}`}>
          <div className="rank">{i + 1}</div>
          <div>
            <p style={{ margin: "0 0 4px", fontSize: 13 }}>{post.text?.slice(0, 200)}…</p>
            <div className="post-meta">
              <span className="badge">{post.format}</span>
              <span className="badge">👍 {fmt(post.likes)}</span>
              <span className="badge">💬 {fmt(post.comments)}</span>
              <span className="badge">🔁 {fmt(post.reposts)}</span>
            </div>
            {post.url ? <a className="secondary-button" href={post.url} target="_blank" style={{ fontSize: 12, minHeight: 28 }}>Voir sur LinkedIn</a> : null}
          </div>
        </div>
      ))}
      {gated && onUnlock ? (
        <LockedCard
          title={`+${allPosts.length - posts.length} top posts à débloquer`}
          subtitle="Crée ton compte gratuit pour voir tous les meilleurs posts et leurs métriques."
          ghostLines={3}
          onUnlock={onUnlock}
        />
      ) : null}
    </div>
  );
}

const LOCKED_TABS = new Set(["Tous les posts", "JSON brut"]);

function Dashboard({
  result,
  isAuthed,
  requireAuth,
}: {
  result: Analysis;
  isAuthed: boolean;
  requireAuth: (reason?: string, mode?: AuthMode) => void;
}) {
  const [tab, setTab] = useState("Rapport");
  const unlock = () => requireAuth("Crée un compte gratuit pour débloquer l'analyse complète et conserver ton historique.");

  const actionsCount = result.synthesis?.actions_to_replicate?.length ?? 0;
  const topPostsCount = result.stats?.top_posts_by_comments?.length ?? 0;

  return (
    <>
      {isAuthed && (result as any).save_error && (
        <div className="error">⚠️ Analyse non sauvegardée : {(result as any).save_error}</div>
      )}
      <Kpis result={result} />
      <div className="tabs">
        {tabs.map((t) => {
          const locked = LOCKED_TABS.has(t) && !isAuthed;
          return (
            <button
              key={t}
              className={`tab ${tab === t ? "active" : ""} ${locked ? "locked" : ""}`}
              onClick={() => (locked ? unlock() : setTab(t))}
            >
              {t}
              {locked ? <Lock size={11} className="lock-ico" /> : null}
            </button>
          );
        })}
      </div>

      {tab === "Rapport" && (
        isAuthed ? (
          <div className="markdown card"><ReactMarkdown>{result.markdown}</ReactMarkdown></div>
        ) : (
          <>
            <div className="markdown card">
              <ReactMarkdown components={reportComponents(unlock)}>
                {truncateLists(reportBeforeActions(result.markdown || ""))}
              </ReactMarkdown>
            </div>
            {actionsCount > 0 && (
              <div style={{ marginTop: 16 }}>
                <LockedCard
                  title={`${actionsCount} action${actionsCount > 1 ? "s" : ""} à répliquer`}
                  subtitle="Le plan d'action concret pour répliquer cette stratégie. Crée ton compte gratuit pour le débloquer."
                  ghostLines={Math.min(actionsCount, 5)}
                  onUnlock={unlock}
                />
              </div>
            )}
          </>
        )
      )}
      {tab === "Top posts" && (
        <TopPosts result={result} limit={isAuthed ? undefined : keepTwoThirds(topPostsCount)} onUnlock={unlock} />
      )}
      {tab === "Patterns" && (
        <Patterns result={result} limit={isAuthed ? undefined : 4} onUnlock={unlock} />
      )}
      {tab === "Usage" && <pre className="raw-json">{JSON.stringify(result.usage, null, 2)}</pre>}
      {tab === "Tous les posts" && <pre className="raw-json">{JSON.stringify(result.posts, null, 2)}</pre>}
      {tab === "JSON brut" && <pre className="raw-json">{JSON.stringify(result, null, 2)}</pre>}
    </>
  );
}

function Generator() {
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [variants, setVariants] = useState<Variant[]>([]);
  const [topic, setTopic] = useState("");
  const [loadingIdeas, setLoadingIdeas] = useState(false);
  const [loadingPosts, setLoadingPosts] = useState(false);
  const [error, setError] = useState("");

  async function fetchIdeas() {
    setError("");
    setLoadingIdeas(true);
    try {
      const res = await fetch(`${DIRECT_API_URL}/ideas`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ count: 5 }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Échec de la génération d'idées");
      setIdeas(data.ideas || []);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoadingIdeas(false);
    }
  }

  async function generateFromTopic(t: string) {
    setError("");
    if (!t.trim()) { setError("Entre un sujet pour le post."); return; }
    setLoadingPosts(true);
    try {
      const res = await fetch(`${DIRECT_API_URL}/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ topic: t.trim() }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Échec de la génération de posts");
      setVariants(data.variants || []);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoadingPosts(false);
    }
  }

  const funnelColors: Record<string, string> = { TOFU: "#10b981", MOFU: "#f59e0b", BOFU: "#ef4444" };
  const hookColors: Record<string, string> = { "stat+contrarian": "#f97316", "story+result": "#10b981", question: "#3b82f6" };

  return (
    <div>
      {/* Ideas section */}
      <div className="section-header">
        <div>
          <h2 className="section-title"><Lightbulb size={20} /> Idées de posts</h2>
          <p className="section-desc">Claude analyse les patterns des influenceurs et propose des idées à fort potentiel.</p>
        </div>
        <button className="secondary-button" onClick={fetchIdeas} disabled={loadingIdeas}>
          {loadingIdeas ? <Loader2 size={14} className="spinning" /> : <Lightbulb size={14} />}
          {loadingIdeas ? "Génération…" : "Générer des idées"}
        </button>
      </div>

      {error && <div className="error">{error}</div>}

      {ideas.length > 0 && (
        <div className="ideas-grid">
          {ideas.map((idea, i) => (
            <div className="idea-card" key={i}>
              <div className="idea-header">
                <span className="idea-funnel" style={{ borderColor: funnelColors[idea.funnel] || "var(--border)", color: funnelColors[idea.funnel] || "var(--muted)" }}>
                  {idea.funnel}
                </span>
                <span className="badge">{idea.hook_type}</span>
                <span className="idea-lift">{idea.estimated_lift}</span>
              </div>
              <h3 className="idea-title">{idea.title}</h3>
              <p className="idea-hook">"{idea.hook}"</p>
              <p className="idea-angle">{idea.angle}</p>
              <p className="idea-why"><strong>Pourquoi ça marche :</strong> {idea.why_it_works}</p>
              <div className="idea-footer">
                <span className={`idea-difficulty ${idea.difficulty}`}>{idea.difficulty}</span>
                <button
                  className="primary-button"
                  style={{ fontSize: 12, minHeight: 30, padding: "0 10px" }}
                  onClick={() => { setTopic(idea.title); generateFromTopic(idea.title); }}
                >
                  <Sparkles size={12} /> Générer ce post
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Post generation */}
      <div className="gen-section">
        <h2 className="section-title"><PenTool size={20} /> Générer des posts</h2>
        <div className="gen-form">
          <div className="url-input">
            <PenTool size={16} color="var(--primary)" />
            <input
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="Sujet du post : ex. les 5 erreurs avec Claude AI…"
              onKeyDown={(e) => e.key === "Enter" && generateFromTopic(topic)}
            />
            <button className="primary-button" disabled={loadingPosts} onClick={() => generateFromTopic(topic)}>
              {loadingPosts ? <Loader2 size={14} className="spinning" /> : <Sparkles size={14} />}
              Générer
            </button>
          </div>
        </div>
      </div>

      {variants.length > 0 && (
        <div className="variants-list">
          {variants.map((v, i) => {
            const color = hookColors[v.hook_type] || "var(--primary)";
            return (
              <div className="variant-card" key={i}>
                <div className="variant-header">
                  <span className="variant-number" style={{ background: color }}>{i + 1}</span>
                  <span className="badge" style={{ borderColor: color, color }}>{v.hook_type}</span>
                  <span className="idea-lift">{v.predicted_lift}</span>
                </div>
                <p className="variant-strategy">{v.strategy}</p>
                <textarea className="variant-text" readOnly value={v.post} rows={14} />
                <button className="secondary-button" onClick={() => navigator.clipboard.writeText(v.post)} style={{ marginTop: 8 }}>
                  Copier le post
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function GlobalDashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [growth, setGrowth] = useState<GrowthRow[]>([]);
  const [aiAnalysis, setAiAnalysis] = useState<string>("");
  const [loadingAi, setLoadingAi] = useState(false);
  const [loading, setLoading] = useState(true);
  const [aiError, setAiError] = useState("");

  useEffect(() => {
    (async () => {
      const headers = await authHeaders();
      fetch(`${API_URL}/dashboard`, { headers })
        .then((r) => r.json())
        .then((d) => { setData(d); setLoading(false); })
        .catch(() => setLoading(false));
      fetch(`${API_URL}/dashboard/growth`, { headers })
        .then((r) => r.json())
        .then((d) => Array.isArray(d) && setGrowth(d))
        .catch(() => null);
    })();
  }, []);

  async function runAiAnalysis() {
    setAiError("");
    setLoadingAi(true);
    try {
      const res = await fetch(`${DIRECT_API_URL}/dashboard/ai-analysis`, { method: "POST", headers: await authHeaders() });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || "Échec de l'analyse IA");
      setAiAnalysis(d.markdown || "");
    } catch (err: any) {
      setAiError(err.message);
    } finally {
      setLoadingAi(false);
    }
  }

  if (loading) return <div className="hero"><div className="hero-content"><p>Chargement du dashboard en cours…</p></div></div>;
  if (!data || data.influencer_count === 0) {
    return (
      <div className="hero">
        <div className="hero-content">
          <p className="eyebrow">Dashboard global</p>
          <h1>Aucun influenceur <span className="gradient-text">analysé</span></h1>
          <p>Lance d'abord des analyses dans l'onglet Analyser pour voir les stats cumulées ici.</p>
        </div>
      </div>
    );
  }

  const agg = data.aggregated;
  const hookEntries = Object.entries(agg.hook_distribution || {});
  const formatEntries = Object.entries(agg.format_distribution || {});
  const maxHook = Math.max(1, ...hookEntries.map(([, n]) => n));
  const maxFormat = Math.max(1, ...formatEntries.map(([, n]) => n));
  const weekdays = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"];
  const wdEntries = weekdays.map((d) => [d, agg.weekday_distribution?.[d] || 0] as [string, number]);
  const maxWd = Math.max(1, ...wdEntries.map(([, n]) => n));

  return (
    <div>
      <div className="section-header" style={{ marginBottom: 16 }}>
        <div>
          <h2 className="section-title"><TrendingUp size={20} /> Dashboard global</h2>
          <p className="section-desc">{data.influencer_count} influenceur{data.influencer_count > 1 ? "s" : ""} analysé{data.influencer_count > 1 ? "s" : ""} — {agg.total_posts} posts au total</p>
        </div>
      </div>

      {/* Global KPIs */}
      <div className="kpi-grid" style={{ gridTemplateColumns: "repeat(6, 1fr)" }}>
        <div className="kpi-card"><span>Influenceurs</span><div className="metric">{data.influencer_count}</div></div>
        <div className="kpi-card"><span>Posts analysés</span><div className="metric">{fmt(agg.total_posts)}</div></div>
        <div className="kpi-card"><span>Abonnés cumulés</span><div className="metric">{fmt(agg.total_followers)}</div></div>
        <div className="kpi-card"><span>Eng. moyen</span><div className="metric">{fmt(Math.round(agg.avg_engagement))}</div></div>
        <div className="kpi-card"><span>Comments moyen</span><div className="metric">{fmt(Math.round(agg.avg_comments * 10) / 10)}</div></div>
        <div className="kpi-card"><span>Likes moyen</span><div className="metric">{fmt(Math.round(agg.avg_likes * 10) / 10)}</div></div>
      </div>

      {/* Influencer comparison table */}
      <div className="card" style={{ marginTop: 16 }}>
        <h3>Comparatif des influenceurs</h3>
        <div style={{ overflowX: "auto" }}>
          <table className="dash-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Influenceur</th>
                <th>Handle</th>
                <th>Followers</th>
                <th>Posts</th>
                <th>Posts/sem</th>
                <th>Eng. moyen</th>
                <th>Likes moyen</th>
                <th>Comments méd.</th>
                <th>Taux eng.</th>
                <th>Format principal</th>
              </tr>
            </thead>
            <tbody>
              {[...data.influencers].sort((a, b) => b.avg_engagement - a.avg_engagement).map((inf, i) => (
                <tr key={inf.handle}>
                  <td><span className="rank">{i + 1}</span></td>
                  <td><strong>{inf.name || inf.handle}</strong></td>
                  <td style={{ color: "var(--muted)", fontSize: 12 }}>{inf.handle}</td>
                  <td>{fmt(inf.followers)}</td>
                  <td>{inf.posts_analyzed}</td>
                  <td>{inf.posts_per_week ?? "—"}</td>
                  <td><strong>{fmt(inf.avg_engagement)}</strong></td>
                  <td>{fmt(Math.round((inf.avg_engagement * 0.7)))}</td>
                  <td>{fmt(inf.median_comments)}</td>
                  <td>{inf.engagement_rate_pct ? `${inf.engagement_rate_pct}%` : "—"}</td>
                  <td><span className="badge">{inf.top_format}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Distributions */}
      <div className="pattern-grid" style={{ marginTop: 16 }}>
        <div className="card">
          <h3>Hooks (tous les influenceurs)</h3>
          {hookEntries.map(([label, n]) => <Bar key={label} label={label} value={n} max={maxHook} />)}
        </div>
        <div className="card">
          <h3>Formats (tous les influenceurs)</h3>
          {formatEntries.map(([label, n]) => <Bar key={label} label={label} value={n} max={maxFormat} />)}
        </div>
        <div className="card">
          <h3>Jours de publication</h3>
          {wdEntries.map(([label, n]) => <Bar key={label} label={label} value={n} max={maxWd} />)}
        </div>
        <div className="card">
          <h3>Stats d'engagement</h3>
          <div className="dash-stat-grid">
            <div><span className="eyebrow">Likes médian</span><div className="metric" style={{ fontSize: 18 }}>{fmt(agg.median_likes)}</div></div>
            <div><span className="eyebrow">Comments médian</span><div className="metric" style={{ fontSize: 18 }}>{fmt(agg.median_comments)}</div></div>
            <div><span className="eyebrow">Repartages moyen</span><div className="metric" style={{ fontSize: 18 }}>{fmt(Math.round(agg.avg_reposts * 10) / 10)}</div></div>
            <div><span className="eyebrow">Eng. médian</span><div className="metric" style={{ fontSize: 18 }}>{fmt(agg.median_engagement)}</div></div>
          </div>
        </div>
      </div>

      {/* Growth since 25th post */}
      {growth.length > 0 && (
        <div className="card" style={{ marginTop: 16 }}>
          <h3>📈 Croissance depuis le 25e post</h3>
          <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 12 }}>
            Compare l'engagement moyen des 25 premiers posts vs les posts suivants — classé par meilleure croissance.
          </p>
          <div style={{ overflowX: "auto" }}>
            <table className="dash-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Influenceur</th>
                  <th>Posts totaux</th>
                  <th>Date post #25</th>
                  <th>Eng. moy (1–25)</th>
                  <th>Eng. moy (26+)</th>
                  <th>Croissance</th>
                </tr>
              </thead>
              <tbody>
                {growth.map((row, i) => {
                  const pct = row.growth_pct;
                  const color = pct === null ? "var(--muted)" : pct >= 0 ? "#10b981" : "#ef4444";
                  return (
                    <tr key={row.handle}>
                      <td><span className="rank">{i + 1}</span></td>
                      <td><strong>{row.name}</strong></td>
                      <td>{row.total_posts}</td>
                      <td>{row.date_post_split}</td>
                      <td>{fmt(row.avg_eng_before)}</td>
                      <td>{row.avg_eng_after !== null ? fmt(row.avg_eng_after) : "—"}</td>
                      <td><strong style={{ color }}>{pct !== null ? `${pct > 0 ? "+" : ""}${pct}%` : "—"}</strong></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* AI Strategic Analysis */}
      <div className="card" style={{ marginTop: 16 }}>
        <div className="section-header" style={{ marginBottom: 12 }}>
          <div>
            <h3 style={{ margin: 0 }}>🧠 Analyse stratégique IA</h3>
            <p style={{ fontSize: 13, color: "var(--muted)", margin: "4px 0 0" }}>
              Claude analyse les données comparatives et produit des recommandations stratégiques actionnables.
            </p>
          </div>
          <button className="primary-button" onClick={runAiAnalysis} disabled={loadingAi}>
            {loadingAi ? <Loader2 size={14} className="spinning" /> : <Sparkles size={14} />}
            {loadingAi ? "Analyse en cours…" : "Lancer l'analyse IA"}
          </button>
        </div>
        {aiError && <div className="error">{aiError}</div>}
        {aiAnalysis && (
          <div className="markdown" style={{ borderTop: "1px solid var(--border)", paddingTop: 16 }}>
            <ReactMarkdown>{aiAnalysis}</ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}

const mainViews = ["analyze", "generator", "dashboard"] as const;
type MainView = typeof mainViews[number];

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [reports, setReports] = useState<Report[]>([]);
  const [result, setResult] = useState<Analysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [view, setView] = useState<MainView>("analyze");
  const [loadedReport, setLoadedReport] = useState<Report | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [authOpen, setAuthOpen] = useState(false);
  const [authReason, setAuthReason] = useState("");
  const [authMode, setAuthMode] = useState<AuthMode>("signup");
  const userIdRef = useRef<string | null>(null);
  // Analyse anonyme affichée mais pas encore sauvegardée : sauvée dès l'inscription.
  const pendingAnonResultRef = useRef<Analysis | null>(null);

  const isAuthed = !!session;

  function requireAuth(reason?: string, mode: AuthMode = "signup") {
    setAuthReason(reason || "");
    setAuthMode(mode);
    setAuthOpen(true);
  }

  async function loadReports() {
    try {
      const res = await fetch(`${API_URL}/reports`, { headers: await authHeaders() });
      const data = await res.json();
      if (res.ok && Array.isArray(data)) setReports(data);
    } catch { /* ignore */ }
  }

  async function persistAnonResult(anon: Analysis) {
    try {
      await fetch(`${DIRECT_API_URL}/analyses/persist`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify(anon),
      });
    } catch { /* best-effort : on ne bloque pas l'UX sur une erreur de save */ }
    loadReports();
  }

  useEffect(() => {
    fetch(`${API_URL}/health`).then((r) => r.json()).then(setHealth).catch(() => null);
    supabase.auth.getSession().then(({ data }) => setSession(data.session));

    // Home ne se démonte jamais : son state par-utilisateur doit être purgé à
    // chaque changement de compte, sinon l'utilisateur suivant voit les données
    // du précédent. Exception : passage anonyme → connecté avec une analyse à
    // l'écran, qu'on conserve et qu'on sauvegarde dans le nouveau compte.
    const { data: sub } = supabase.auth.onAuthStateChange((_event, s) => {
      setSession(s);
      const uid = s?.user?.id ?? null;
      if (uid === userIdRef.current) return;
      const prev = userIdRef.current;
      userIdRef.current = uid;

      if (prev === null && uid && pendingAnonResultRef.current) {
        const anon = pendingAnonResultRef.current;
        pendingAnonResultRef.current = null;
        setAuthOpen(false);
        setError("");
        // L'analyse anonyme portait save_error="aucune session" : on le retire
        // puisqu'on la sauvegarde maintenant dans le compte fraîchement créé.
        const cleaned = { ...anon } as Record<string, unknown>;
        delete cleaned.save_error;
        setResult(cleaned as Analysis);
        setTimeout(() => persistAnonResult(anon), 0);
        return;
      }

      pendingAnonResultRef.current = null;
      setAuthOpen(false);
      setReports([]);
      setResult(null);
      setLoadedReport(null);
      setError("");
      setView("analyze");
      if (uid) setTimeout(() => loadReports(), 0);
    });
    return () => sub.subscription.unsubscribe();
  }, []);

  async function analyze(payload: { url: string; limit: number; useCache: boolean; runLlm: boolean }) {
    setError("");
    if (!payload.url.trim()) { setError("Colle d'abord une URL de profil LinkedIn."); return; }
    if (!isAuthed && anonAnalysisUsed()) {
      requireAuth("Tu as déjà utilisé ton analyse gratuite. Crée un compte gratuit pour continuer.");
      return;
    }
    setLoading(true);
    try {
      const response = await fetch(`${DIRECT_API_URL}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ profile_url: payload.url, limit: payload.limit, use_cache: payload.useCache, run_llm: payload.runLlm }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Échec de l'analyse");
      setResult(data);
      if (isAuthed) {
        loadReports();
      } else {
        markAnonAnalysisUsed();
        pendingAnonResultRef.current = data;
      }
    } catch (err: any) {
      setError(err.message || "Échec de l'analyse");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <div className="app-shell">
        <Sidebar
          health={health}
          reports={reports}
          view={view}
          isAuthed={isAuthed}
          onNavigate={(v) => { setView(v); if (v === "analyze") { setResult(null); setLoadedReport(null); setError(""); } }}
          onLoadReport={(r) => { setLoadedReport(r); setView("analyze"); setResult(null); }}
          requireAuth={requireAuth}
        />
        <TopHeader
          result={result}
          view={view}
          isAuthed={isAuthed}
          userEmail={session?.user?.email ?? undefined}
          onReset={() => { setResult(null); setLoadedReport(null); }}
          onSignIn={() => requireAuth(undefined, "signin")}
          onSignUp={() => requireAuth(undefined, "signup")}
          onSignOut={() => supabase.auth.signOut()}
        />
        <main className="main">
          {view === "analyze" && (
            loading
              ? <LoadingState />
              : result
                ? <Dashboard result={result} isAuthed={isAuthed} requireAuth={requireAuth} />
                : loadedReport
                  ? <div className="markdown card"><ReactMarkdown>{loadedReport.content}</ReactMarkdown></div>
                  : <Landing onSubmit={analyze} loading={loading} error={error} />
          )}
          {view === "generator" && <Generator />}
          {view === "dashboard" && <GlobalDashboard />}
        </main>
      </div>
      <AuthModal open={authOpen} onClose={() => setAuthOpen(false)} reason={authReason} defaultMode={authMode} />
    </>
  );
}
