"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Activity,
  BarChart3,
  CheckCircle2,
  ChevronLeft,
  Clock3,
  Copy,
  Download,
  FileText,
  Image as ImageIcon,
  Lightbulb,
  Link2,
  Linkedin,
  ListChecks,
  Loader2,
  Lock,
  LogIn,
  LogOut,
  Bookmark,
  MessageSquare,
  PenTool,
  PlusCircle,
  Trash2,
  RefreshCw,
  Send,
  Settings2,
  Sparkles,
  Target,
  TrendingUp,
  UserRound,
  Users,
  Zap,
} from "lucide-react";
import type { Session } from "@supabase/supabase-js";
import AuthModal, { type AuthMode } from "./components/AuthModal";
import { authHeaders, supabase } from "./lib/supabase";

const API_URL = "/api";
const DIRECT_API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ??
  "https://analyseur-linkedin-influenceur-api.onrender.com";

// Solde de crédits : les endpoints coûteux renvoient le nouveau solde. On le
// diffuse via un évènement window pour rafraîchir la pastille de la sidebar
// (gérée par Home) sans prop-drilling à travers le hub « Contenu ».
function emitCredits(balance: unknown) {
  if (typeof balance === "number" && typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("credits:update", { detail: balance }));
  }
}

type Health = { ok: boolean; apify: boolean; anthropic: boolean; model: string };
type Report = { name: string; path: string; updated_at: number; content: string };
type InfluencerLibraryEntry = {
  influencer_id: string;
  analysis_id: string;
  handle: string;
  name: string;
  headline: string;
  follower_count: number;
  profile_url: string;
  analyzed_at: number;
};
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
  id?: string;
  title: string;
  hook: string;
  hook_type: string;
  funnel: string;
  angle: string;
  why_it_works: string;
  difficulty: string;
  estimated_lift: string;
  slack_status?: string | null;
};
type Variant = {
  id?: string;
  editorial_role?: string;
  hook_type: string;
  strategy: string;
  predicted_lift: string;
  post: string;
};
type SavedIdea = Idea & { id: string; created_at?: string };
type SavedPost = {
  id: string;
  topic?: string;
  editorial_role?: string;
  hook_type?: string;
  strategy?: string;
  predicted_lift?: string;
  post: string;
  created_at?: string;
  slack_status?: string | null;
};
type ChatConversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};
type ChatMessage = {
  id?: string;
  role: "user" | "assistant";
  content: string;
  created_at?: string;
};
type EditorialProfile = {
  id?: string;
  display_name?: string | null;
  brand_name?: string | null;
  industry?: string | null;
  business_description?: string | null;
  location?: string | null;
  target_audience?: string | null;
  core_offer?: string | null;
  tone?: string | null;
  linkedin_objective?: string | null;
  topics_to_cover?: string | null;
  topics_to_avoid?: string | null;
  constraints?: string | null;
  website_url?: string | null;
  linkedin_url?: string | null;
  language?: string | null;
  market?: string | null;
  extra_context?: string | null;
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

const mainViews = ["analyze", "profile", "assistant", "content", "progress"] as const;
type MainView = typeof mainViews[number];

type Platform = "linkedin" | "instagram";

function InstagramIcon({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="2" width="20" height="20" rx="5" ry="5" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="17.5" cy="6.5" r="0.5" fill="currentColor" />
    </svg>
  );
}

/** Sous-onglets de la vue « Analyser » (analyse, influenceurs, dashboard fusionnés). */
type AnalyzeTab = "analyze" | "influencers" | "dashboard";

/** Sous-onglets de la vue « Contenu » (idée du jour, générateur, mes contenus fusionnés). */
type ContentTab = "daily" | "generator" | "library";

const tabs = ["Rapport", "Top posts", "Patterns", "Tous les posts", "JSON brut"];
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

function decodeHandle(handle: string) {
  try {
    return decodeURIComponent(handle);
  } catch {
    return handle;
  }
}

function buildInfluencerLibraryFromLegacy(
  influencersRaw: Record<string, unknown>[],
  analysesRaw: Record<string, unknown>[],
): InfluencerLibraryEntry[] {
  const analysisByHandle = new Map<string, { id: string; created_at: string }>();
  for (const row of analysesRaw) {
    const handle = String(row.handle || "");
    if (!handle || !row.id) continue;
    const entry = { id: String(row.id), created_at: String(row.created_at || "") };
    analysisByHandle.set(handle, entry);
    analysisByHandle.set(decodeHandle(handle), entry);
  }

  const entries: InfluencerLibraryEntry[] = [];
  for (const inf of influencersRaw) {
    const rawHandle = String(inf.handle || "");
    const handle = decodeHandle(rawHandle);
    const analysis = analysisByHandle.get(handle) || analysisByHandle.get(rawHandle);
    if (!analysis) continue;
    let analyzedAt = 0;
    if (analysis.created_at) {
      const ts = Date.parse(analysis.created_at);
      if (!Number.isNaN(ts)) analyzedAt = ts / 1000;
    }
    entries.push({
      influencer_id: String(inf.id),
      analysis_id: analysis.id,
      handle,
      name: (String(inf.name || "")).trim() || handle,
      headline: (String(inf.headline || "")).trim(),
      follower_count: Number(inf.follower_count) || 0,
      profile_url: String(inf.profile_url || `https://www.linkedin.com/in/${rawHandle}/`),
      analyzed_at: analyzedAt,
    });
  }
  return entries.sort((a, b) => (b.analyzed_at || 0) - (a.analyzed_at || 0));
}

const HOOK_LABELS: Record<string, string> = {
  question: "Question directe",
  story: "Histoire / anecdote",
  stat: "Chiffre choc",
  bold_claim: "Affirmation tranchée",
  list: "Liste",
  result: "Résultat chiffré",
  contrarian: "Contre-pied",
  other: "Autre",
};

function hookLabel(key: string) {
  return HOOK_LABELS[key] || key;
}

/* ── Backlog serveur (job queue) ───────────────────────────────────────── */

type JobStatus = "queued" | "running" | "done" | "error" | "cancelled";
type ItemStatus = "pending" | "running" | "done" | "error" | "cancelled";

type JobItem = {
  id: string;
  position: number;
  url: string;
  handle: string | null;
  name: string | null;
  status: ItemStatus;
  error: string | null;
  analysis_id: string | null;
  follower_count: number | null;
  posts_count: number | null;
};

type Job = {
  id: string;
  status: JobStatus;
  total: number;
  completed: number;
  failed: number;
  limit_posts: number | null;
  run_llm: boolean;
  use_cache: boolean;
  platform?: string;
  created_at: string;
  updated_at: string;
  items: JobItem[];
};

const ITEM_STATUS_LABELS: Record<ItemStatus, string> = {
  pending: "En attente",
  running: "Analyse en cours…",
  done: "Terminé",
  error: "Échec",
  cancelled: "Annulé",
};

/** Découpe un bloc de texte en URLs LinkedIn distinctes (une par ligne, dédupliquées). */
function parseUrls(raw: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const line of raw.split(/[\n,]/)) {
    const url = line.trim();
    if (!url || !/linkedin\.com\/in\//i.test(url)) continue;
    const key = url.replace(/\/+$/, "").toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(url);
  }
  return out;
}

/** Découpe un bloc de texte en handles/URLs Instagram distincts (une par ligne, dédupliqués). */
function parseIgHandles(raw: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const line of raw.split(/[\n,]/)) {
    const entry = line.trim();
    if (!entry) continue;
    // Accept instagram.com URLs or @handles or bare handles
    let handle = entry;
    const m = entry.match(/instagram\.com\/([A-Za-z0-9_.]+)/i);
    if (m) {
      handle = m[1].replace(/\/$/, "");
    } else {
      handle = entry.replace(/^@/, "").replace(/\/.*$/, "").replace(/\?.*$/, "");
    }
    if (!handle || handle.length < 1) continue;
    const key = handle.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(handle);
  }
  return out;
}

function jobIsActive(j: Job): boolean {
  return j.status === "queued" || j.status === "running";
}

function jobIsCancelled(j: Job): boolean {
  return j.status === "cancelled";
}

function ItemRow({ item, onOpen, opening, onCancel, cancelling }: { item: JobItem; onOpen: (i: JobItem) => void; opening: boolean; onCancel: (i: JobItem) => void; cancelling: boolean }) {
  const clickable = item.status === "done" && !!item.analysis_id;
  const cancellable = item.status === "pending" || item.status === "running";
  return (
    <div
      className={`backlog-row ${item.status} ${clickable ? "clickable" : ""}`}
      onClick={() => clickable && onOpen(item)}
      role={clickable ? "button" : undefined}
    >
      <span className="backlog-rank">{item.position + 1}</span>
      <span className="backlog-status-ico">
        {opening || item.status === "running" ? <Loader2 size={16} className="spinning" />
          : item.status === "done" ? <CheckCircle2 size={16} color="#10b981" />
          : item.status === "error" ? <span style={{ color: "#ef4444", fontWeight: 700 }}>✕</span>
          : item.status === "cancelled" ? <span style={{ color: "var(--muted)", fontWeight: 700 }}>–</span>
          : <Clock3 size={16} color="var(--muted)" />}
      </span>
      <div className="backlog-main">
        <strong>{item.name || item.handle || item.url}</strong>
        <span className="backlog-url">{item.url}</span>
        {item.status === "error" && item.error ? <span className="backlog-error">{item.error}</span> : null}
      </div>
      {item.status === "done" ? (
        <div className="backlog-meta">
          {item.posts_count != null ? <span className="badge">{fmt(item.posts_count)} posts</span> : null}
          {item.follower_count != null ? <span className="badge">👍 {fmt(item.follower_count)}</span> : null}
        </div>
      ) : null}
      <span className={`status-pill ${item.status === "done" ? "ok" : item.status === "error" ? "no" : item.status === "cancelled" ? "no" : ""}`}>
        {ITEM_STATUS_LABELS[item.status]}
      </span>
      {cancellable ? (
        <button
          type="button"
          className="ghost-button"
          style={{ fontSize: 11, padding: "2px 8px", color: "var(--muted)" }}
          disabled={cancelling}
          onClick={(e) => { e.stopPropagation(); onCancel(item); }}
          title="Annuler ce profil"
        >
          {cancelling ? <Loader2 size={11} className="spinning" /> : "Annuler"}
        </button>
      ) : null}
    </div>
  );
}

function JobsView({ jobs, loading, isAuthed, onCreated, onOpenReport, requireAuth, onJobUpdated }: {
  jobs: Job[];
  loading: boolean;
  isAuthed: boolean;
  onCreated: (job: Job) => void;
  onOpenReport: (markdown: string, name: string) => void;
  requireAuth: (reason?: string, mode?: AuthMode) => void;
  onJobUpdated: (job: Job) => void;
}) {
  const [urls, setUrls] = useState("");
  const [limit, setLimit] = useState(25);
  const [useCache, setUseCache] = useState(true);
  const [runLlm, setRunLlm] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [cancellingId, setCancellingId] = useState<string | null>(null);
  const [cancellingItemId, setCancellingItemId] = useState<string | null>(null);

  // ALE-114 : la Veille LinkedIn ne doit afficher que les séries LinkedIn
  // (les jobs sans `platform` = anciens jobs = LinkedIn).
  const lkJobs = jobs.filter((j) => (j.platform ?? "linkedin") !== "instagram");

  const urlList = parseUrls(urls);

  async function submit() {
    if (urlList.length === 0) { setError("Colle au moins une URL de profil LinkedIn."); return; }
    // Auth requise dans tous les cas (pas d'essai anonyme).
    if (!isAuthed) {
      requireAuth("Crée un compte gratuit pour lancer ton analyse et conserver ton historique.");
      return;
    }
    setSubmitting(true); setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ profile_urls: urlList, limit, use_cache: useCache, run_llm: runLlm }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Échec de la création de la série");
      setUrls("");
      onCreated(data as Job);
    } catch (err: any) {
      setError(err.message || "Échec de la création de la série");
    } finally {
      setSubmitting(false);
    }
  }

  async function cancelJob(jobId: string) {
    setCancellingId(jobId);
    try {
      const res = await fetch(`${DIRECT_API_URL}/jobs/${jobId}/cancel`, {
        method: "POST",
        headers: await authHeaders(),
      });
      const data = await res.json();
      if (res.ok && data?.id) onJobUpdated(data as Job);
    } catch {
      /* le polling remettra le statut à jour */
    } finally {
      setCancellingId(null);
    }
  }

  async function cancelItem(jobId: string, itemId: string) {
    setCancellingItemId(itemId);
    try {
      const res = await fetch(`${DIRECT_API_URL}/jobs/${jobId}/items/${itemId}/cancel`, {
        method: "POST",
        headers: await authHeaders(),
      });
      const data = await res.json();
      if (res.ok && data?.id) onJobUpdated(data as Job);
    } catch {
      /* le polling remettra le statut à jour */
    } finally {
      setCancellingItemId(null);
    }
  }

  async function openItem(item: JobItem) {
    if (!item.analysis_id) return;
    setOpeningId(item.id);
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/analyses/${item.analysis_id}`, { headers: await authHeaders() });
      const data = await res.json();
      if (res.ok && data?.report_markdown) {
        onOpenReport(data.report_markdown, item.name || item.handle || "Rapport");
      } else {
        setError(data?.detail || "Rapport introuvable.");
      }
    } catch (err: any) {
      setError(err.message || "Impossible d'ouvrir le rapport");
    } finally {
      setOpeningId(null);
    }
  }

  return (
    <div>
      <div className="section-header" style={{ marginBottom: 16 }}>
        <div>
          <h2 className="section-title"><ListChecks size={20} /> Analyser des profils</h2>
          <p className="section-desc">Colle un ou plusieurs profils (un par ligne). Chaque série tourne côté serveur : tu peux changer d'onglet ou fermer la page, la progression est conservée.</p>
        </div>
      </div>

      {/* Soumission d'une nouvelle série */}
      <div className="analyzer-card" style={{ marginBottom: 20 }}>
        <div className="url-input url-input--multi">
          <Link2 size={16} color="var(--primary)" style={{ marginTop: 10, flexShrink: 0 }} />
          <textarea
            value={urls}
            onChange={(e) => setUrls(e.target.value)}
            placeholder={"https://www.linkedin.com/in/profil-1/\nhttps://www.linkedin.com/in/profil-2/\nhttps://www.linkedin.com/in/profil-3/"}
            rows={Math.min(8, Math.max(3, urlList.length + 1))}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(); }}
          />
        </div>
        <div className="batch-submit-row">
          <span className="batch-count">
            {urlList.length === 0
              ? "Un profil par ligne — ⌘/Ctrl + Entrée pour lancer"
              : `${urlList.length} profil${urlList.length > 1 ? "s" : ""} dans la série`}
          </span>
          <button className="primary-button" disabled={submitting || urlList.length === 0} onClick={submit}>
            {submitting ? <Loader2 size={14} className="spinning" /> : <Zap size={14} />}
            Lancer la série
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

      {/* Séries existantes (connectés uniquement — l'anonyme n'a qu'un essai) */}
      {!isAuthed ? (
        <div className="report-card" style={{ maxWidth: 720, cursor: "pointer" }} onClick={() => requireAuth("Crée un compte gratuit pour lancer des séries de plusieurs profils et conserver ton historique.")}>
          <div className="report-icon"><Lock size={13} /></div>
          <div><strong>Séries multi-profils & historique</strong><span>Crée un compte gratuit pour analyser plusieurs profils d'un coup et garder tes rapports.</span></div>
        </div>
      ) : loading ? (
        <p style={{ color: "var(--muted)" }}>Chargement des séries…</p>
      ) : lkJobs.length === 0 ? (
        <div className="report-card" style={{ maxWidth: 720 }}>
          <div className="report-icon"><Activity size={13} /></div>
          <div><strong>Aucune série pour l'instant</strong><span>Colle des profils ci-dessus pour lancer ton premier backlog.</span></div>
        </div>
      ) : (
        <div className="jobs-list">
          {lkJobs.map((job) => {
            const active = jobIsActive(job);
            const date = new Date(job.created_at).toLocaleString("fr-FR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
            return (
              <div className="job-block" key={job.id}>
                <div className="job-head">
                  <div className="job-head-main">
                    {active ? <Loader2 size={15} className="spinning" /> : job.status === "cancelled" ? <span style={{ color: "var(--muted)" }}>–</span> : job.failed && !job.completed ? <span style={{ color: "#ef4444" }}>✕</span> : <CheckCircle2 size={15} color="#10b981" />}
                    <strong>Série du {date}</strong>
                    <span className="badge">{job.completed}/{job.total} terminé{job.completed > 1 ? "s" : ""}</span>
                    {job.failed > 0 ? <span className="status-pill no">{job.failed} échec{job.failed > 1 ? "s" : ""}</span> : null}
                    {job.status === "cancelled" ? <span className="status-pill">Annulée</span> : null}
                  </div>
                  {active ? (
                    <button
                      className="ghost-button"
                      style={{ fontSize: 12, padding: "2px 10px", color: "var(--muted)" }}
                      disabled={cancellingId === job.id}
                      onClick={() => cancelJob(job.id)}
                    >
                      {cancellingId === job.id ? <Loader2 size={12} className="spinning" /> : "Annuler"}
                    </button>
                  ) : null}
                </div>
                <div className="backlog-list">
                  {job.items.map((item) => (
                    <ItemRow
                      key={item.id}
                      item={item}
                      onOpen={openItem}
                      opening={openingId === item.id}
                      onCancel={(it) => cancelItem(job.id, it.id)}
                      cancelling={cancellingItemId === item.id}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ── Instagram analyse hub ─────────────────────────────────────────────── */

function InstagramAnalyzeHub({ jobs, loading, isAuthed, onCreated, onOpenReport, requireAuth, onJobUpdated }: {
  jobs: Job[];
  loading: boolean;
  isAuthed: boolean;
  onCreated: (job: Job) => void;
  onOpenReport: (markdown: string, name: string) => void;
  requireAuth: (reason?: string, mode?: AuthMode) => void;
  onJobUpdated: (job: Job) => void;
}) {
  const [handles, setHandles] = useState("");
  const [limit, setLimit] = useState(30);
  const [useCache, setUseCache] = useState(true);
  const [runLlm, setRunLlm] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [cancellingId, setCancellingId] = useState<string | null>(null);
  const [cancellingItemId, setCancellingItemId] = useState<string | null>(null);

  // Filter to only Instagram jobs
  const igJobs = jobs.filter((j) => j.platform === "instagram");
  const handleList = parseIgHandles(handles);

  async function submit() {
    if (handleList.length === 0) { setError("Colle au moins un handle ou une URL Instagram."); return; }
    if (!isAuthed) {
      requireAuth("Crée un compte gratuit pour lancer ton analyse Instagram et conserver ton historique.");
      return;
    }
    setSubmitting(true); setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ profile_urls: handleList, limit, use_cache: useCache, run_llm: runLlm, platform: "instagram" }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Échec de la création de la série");
      setHandles("");
      onCreated(data as Job);
    } catch (err: any) {
      setError(err.message || "Échec de la création de la série");
    } finally {
      setSubmitting(false);
    }
  }

  async function cancelJob(jobId: string) {
    setCancellingId(jobId);
    try {
      const res = await fetch(`${DIRECT_API_URL}/jobs/${jobId}/cancel`, { method: "POST", headers: await authHeaders() });
      const data = await res.json();
      if (res.ok && data?.id) onJobUpdated(data as Job);
    } catch { /* polling will sync */ } finally { setCancellingId(null); }
  }

  async function cancelItem(jobId: string, itemId: string) {
    setCancellingItemId(itemId);
    try {
      const res = await fetch(`${DIRECT_API_URL}/jobs/${jobId}/items/${itemId}/cancel`, { method: "POST", headers: await authHeaders() });
      const data = await res.json();
      if (res.ok && data?.id) onJobUpdated(data as Job);
    } catch { /* polling will sync */ } finally { setCancellingItemId(null); }
  }

  async function openItem(item: JobItem) {
    if (!item.analysis_id) return;
    setOpeningId(item.id);
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/analyses/${item.analysis_id}`, { headers: await authHeaders() });
      const data = await res.json();
      if (res.ok && data?.report_markdown) {
        onOpenReport(data.report_markdown, item.name || item.handle || "Rapport Instagram");
      } else {
        setError(data?.detail || "Rapport introuvable.");
      }
    } catch (err: any) {
      setError(err.message || "Impossible d'ouvrir le rapport");
    } finally {
      setOpeningId(null);
    }
  }

  return (
    <div>
      <div className="section-header" style={{ marginBottom: 16 }}>
        <div>
          <h2 className="section-title"><InstagramIcon size={20} /> Analyser des profils Instagram</h2>
          <p className="section-desc">Colle un ou plusieurs handles Instagram (un par ligne). L'analyse scrape les Reels, détecte les accroches et génère une synthèse stratégique.</p>
        </div>
      </div>

      <div className="analyzer-card" style={{ marginBottom: 20 }}>
        <div className="url-input url-input--multi">
          <InstagramIcon size={16} />
          <textarea
            value={handles}
            onChange={(e) => setHandles(e.target.value)}
            placeholder={"leaplusbeaudesinsta\n@monautrecompte\nhttps://www.instagram.com/untroisieme/"}
            rows={Math.min(8, Math.max(3, handleList.length + 1))}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(); }}
          />
        </div>
        <div className="batch-submit-row">
          <span className="batch-count">
            {handleList.length === 0
              ? "Un handle par ligne — ⌘/Ctrl + Entrée pour lancer"
              : `${handleList.length} compte${handleList.length > 1 ? "s" : ""} dans la série`}
          </span>
          <button className="primary-button" disabled={submitting || handleList.length === 0} onClick={submit}>
            {submitting ? <Loader2 size={14} className="spinning" /> : <Zap size={14} />}
            Lancer la série
          </button>
        </div>
        <div className="controls">
          <label className="control">
            <span>Reels à analyser : <b>{limit}</b></span>
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

      {!isAuthed ? (
        <div className="report-card" style={{ maxWidth: 720, cursor: "pointer" }} onClick={() => requireAuth("Crée un compte gratuit pour analyser des profils Instagram et conserver ton historique.")}>
          <div className="report-icon"><Lock size={13} /></div>
          <div><strong>Historique & séries multi-profils</strong><span>Crée un compte gratuit pour garder tes rapports et analyser plusieurs comptes d'un coup.</span></div>
        </div>
      ) : loading ? (
        <p style={{ color: "var(--muted)" }}>Chargement des séries…</p>
      ) : igJobs.length === 0 ? (
        <div className="report-card" style={{ maxWidth: 720 }}>
          <div className="report-icon"><Activity size={13} /></div>
          <div><strong>Aucune série Instagram pour l'instant</strong><span>Colle des handles ci-dessus pour lancer ton premier backlog Instagram.</span></div>
        </div>
      ) : (
        <div className="jobs-list">
          {igJobs.map((job) => {
            const active = jobIsActive(job);
            const date = new Date(job.created_at).toLocaleString("fr-FR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
            return (
              <div className="job-block" key={job.id}>
                <div className="job-head">
                  <div className="job-head-main">
                    {active ? <Loader2 size={15} className="spinning" /> : job.status === "cancelled" ? <span style={{ color: "var(--muted)" }}>–</span> : job.failed && !job.completed ? <span style={{ color: "#ef4444" }}>✕</span> : <CheckCircle2 size={15} color="#10b981" />}
                    <strong>Série du {date}</strong>
                    <span className="badge">{job.completed}/{job.total} terminé{job.completed > 1 ? "s" : ""}</span>
                    {job.failed > 0 ? <span className="status-pill no">{job.failed} échec{job.failed > 1 ? "s" : ""}</span> : null}
                    {job.status === "cancelled" ? <span className="status-pill">Annulée</span> : null}
                  </div>
                  {active ? (
                    <button
                      className="ghost-button"
                      style={{ fontSize: 12, padding: "2px 10px", color: "var(--muted)" }}
                      disabled={cancellingId === job.id}
                      onClick={() => cancelJob(job.id)}
                    >
                      {cancellingId === job.id ? <Loader2 size={12} className="spinning" /> : "Annuler"}
                    </button>
                  ) : null}
                </div>
                <div className="backlog-list">
                  {job.items.map((item) => (
                    <ItemRow
                      key={item.id}
                      item={item}
                      onOpen={openItem}
                      opening={openingId === item.id}
                      onCancel={(it) => cancelItem(job.id, it.id)}
                      cancelling={cancellingItemId === item.id}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
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

/** Custom ReactMarkdown renderers: items 4+ d'une liste (≥4 items) sont floutés inline. */
function reportComponents(_onUnlock: () => void) {
  function BlurList({ tag: Tag, children }: { tag: "ol" | "ul"; children?: React.ReactNode }) {
    const all = React.Children.toArray(children).filter(React.isValidElement);
    if (all.length < 4) return <Tag>{children}</Tag>;
    const keep = keepTwoThirds(all.length);
    return (
      <Tag>
        {all.slice(0, keep)}
        {all.slice(keep).map((child, i) =>
          React.cloneElement(child as React.ReactElement<any>, { key: `b${i}`, className: "blurred" })
        )}
      </Tag>
    );
  }
  return {
    ol({ children }: { children?: React.ReactNode }) { return <BlurList tag="ol">{children}</BlurList>; },
    ul({ children }: { children?: React.ReactNode }) { return <BlurList tag="ul">{children}</BlurList>; },
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
  reportsLoading,
  view,
  isAuthed,
  jobBadges,
  credits,
  platform,
  onNavigate,
  onLoadReport,
  onPlatformChange,
  requireAuth,
}: {
  health: Health | null;
  reports: Report[];
  reportsLoading: boolean;
  view: MainView;
  isAuthed: boolean;
  jobBadges: { linkedin: { completed: number; total: number } | null; instagram: { completed: number; total: number } | null };
  credits: number | null;
  platform: Platform;
  onNavigate: (v: MainView) => void;
  onLoadReport: (report: Report) => void;
  onPlatformChange: (p: Platform) => void;
  requireAuth: (reason?: string, mode?: AuthMode) => void;

}) {
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try { return localStorage.getItem("sidebar-collapsed") === "true"; } catch { return false; }
  });

  useEffect(() => {
    const w = collapsed ? "64px" : "260px";
    document.documentElement.style.setProperty("--sidebar-w", w);
    try { localStorage.setItem("sidebar-collapsed", String(collapsed)); } catch {}
  }, [collapsed]);

  return (
    <aside className={`sidebar${collapsed ? " sidebar-collapsed" : ""}`}>
      <div className="logo">
        <div
          className={`logo-mark${collapsed ? " logo-mark-toggle" : ""}`}
          onClick={collapsed ? () => setCollapsed(false) : undefined}
          role={collapsed ? "button" : undefined}
          title={collapsed ? "Étendre la sidebar" : undefined}
        >
          <Target size={18} strokeWidth={2.5} />
        </div>
        {!collapsed && (
          <div className="logo-text">
            Cibl
            <span className="logo-sub">SaaS Premium</span>
          </div>
        )}
        {!collapsed && (
          <button
            className="sidebar-collapse-btn"
            onClick={() => setCollapsed(true)}
            title="Réduire la sidebar"
          >
            <ChevronLeft size={14} />
          </button>
        )}
      </div>

      {/* Navigation — accordéon : LinkedIn / Instagram déplient leurs sous-onglets (Veille / Contenu), Agent IA au même niveau */}
      {(() => {
        const isNetworkView = view === "content" || view === "analyze";
        const networks: { key: Platform; label: string; icon: React.ReactNode }[] = [
          { key: "linkedin", label: "LinkedIn", icon: <Linkedin size={14} /> },
          { key: "instagram", label: "Instagram", icon: <InstagramIcon size={14} /> },
        ];
        const subTabs: { key: MainView; label: string; icon: React.ReactNode; premium?: boolean }[] = [
          { key: "analyze", label: "Veille", icon: <ListChecks size={14} /> },
          { key: "content", label: "Contenu", icon: <PenTool size={14} />, premium: true },
        ];
        return (
          <section className="sidebar-section sidebar-nav-tree">
            <div className="nav-list">
              {networks.map((net) => {
                const expanded = platform === net.key && isNetworkView;
                return (
                  <React.Fragment key={net.key}>
                    <button
                      className={`nav-item ${expanded ? "nav-item-open" : ""}${collapsed ? " nav-item-collapsed" : ""}`}
                      title={collapsed ? net.label : undefined}
                      onClick={() => {
                        onPlatformChange(net.key);
                        if (view !== "content" && view !== "analyze") onNavigate("content");
                      }}
                    >
                      {net.icon}
                      {!collapsed && <span>{net.label}</span>}
                    </button>
                    {expanded && subTabs.map((tab) => {
                      const locked = !!tab.premium && !isAuthed;
                      const badge = jobBadges[net.key];
                      const showBadge = tab.key === "analyze" && badge;
                      return (
                        <button
                          key={tab.key}
                          className={`nav-item nav-item-sub ${view === tab.key ? "active" : ""} ${locked ? "locked" : ""}${collapsed ? " nav-item-collapsed" : ""}`}
                          title={collapsed ? tab.label : undefined}
                          onClick={() => {
                            if (locked) {
                              requireAuth("Crée un compte gratuit pour débloquer le générateur de contenu.");
                              return;
                            }
                            onNavigate(tab.key);
                          }}
                        >
                          {tab.icon}
                          {!collapsed && <span>{tab.label}</span>}
                          {!collapsed && showBadge && badge ? (
                            <span className="nav-job-badge"><Loader2 size={11} className="spinning" />{badge.completed}/{badge.total}</span>
                          ) : null}
                          {collapsed && showBadge ? (
                            <span className="nav-job-badge nav-job-badge-dot"><Loader2 size={11} className="spinning" /></span>
                          ) : null}
                          {locked ? <Lock size={12} className="lock-ico" /> : null}
                        </button>
                      );
                    })}
                  </React.Fragment>
                );
              })}
              {(() => {
                const locked = !isAuthed;
                return (
                  <button
                    className={`nav-item ${view === "assistant" ? "active" : ""} ${locked ? "locked" : ""}${collapsed ? " nav-item-collapsed" : ""}`}
                    title={collapsed ? "Agent IA" : undefined}
                    onClick={() => {
                      if (locked) {
                        requireAuth("Crée un compte gratuit pour débloquer l'Agent IA.");
                        return;
                      }
                      onNavigate("assistant");
                    }}
                  >
                    <MessageSquare size={14} />
                    {!collapsed && <span>Agent IA</span>}
                    {locked ? <Lock size={12} className="lock-ico" /> : null}
                  </button>
                );
              })()}
              {(() => {
                const locked = !isAuthed;
                return (
                  <button
                    className={`nav-item ${view === "progress" ? "active" : ""} ${locked ? "locked" : ""}${collapsed ? " nav-item-collapsed" : ""}`}
                    title={collapsed ? "Tableau de bord" : undefined}
                    onClick={() => {
                      if (locked) {
                        requireAuth("Crée un compte gratuit pour accéder au tableau de bord.");
                        return;
                      }
                      onNavigate("progress");
                    }}
                  >
                    <Activity size={14} />
                    {!collapsed && <span>Tableau de bord</span>}
                    {locked ? <Lock size={12} className="lock-ico" /> : null}
                  </button>
                );
              })()}
            </div>
          </section>
        );
      })()}

      <section className="sidebar-section" style={{ marginTop: "auto" }}>
        {!collapsed && <p className="eyebrow"><Settings2 size={12} style={{ verticalAlign: "-2px", marginRight: 5 }} />Réglages</p>}
        <div className="nav-list" style={{ marginBottom: 10 }}>
          {(() => {
            const locked = !isAuthed;
            return (
              <button
                className={`nav-item ${view === "profile" ? "active" : ""} ${locked ? "locked" : ""}${collapsed ? " nav-item-collapsed" : ""}`}
                title={collapsed ? "Mon profil" : undefined}
                onClick={() => {
                  if (locked) {
                    requireAuth("Crée un compte gratuit pour retrouver tes données et ton contexte éditorial.");
                    return;
                  }
                  onNavigate("profile");
                }}
              >
                <UserRound size={14} />
                {!collapsed && <span>Mon profil</span>}
                {locked ? <Lock size={12} className="lock-ico" /> : null}
              </button>
            );
          })()}
        </div>
        {!collapsed && isAuthed && credits !== null && (
          <div style={{ marginBottom: 8 }}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 12, color: credits <= 5 ? "#ef4444" : "var(--muted)", border: "1px solid var(--border)", borderRadius: 20, padding: "3px 10px" }}>
              ✦ {credits} crédit{credits !== 1 ? "s" : ""}
            </span>
          </div>
        )}
        {!collapsed && (
          <div
            title={`Apify : ${health?.apify ? "OK" : "manquant"} · Anthropic : ${health?.anthropic ? "OK" : "manquant"} · Modèle : ${health?.model || "—"}`}
            style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", fontSize: 10.5, color: "var(--muted)" }}
          >
            <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: health?.apify ? "#10b981" : "#ef4444" }} />
              Apify
            </span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: health?.anthropic ? "#10b981" : "#ef4444" }} />
              Anthropic
            </span>
            <span style={{ opacity: 0.7, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "100%" }}>
              {health?.model || "—"}
            </span>
          </div>
        )}
      </section>
    </aside>
  );
}

function InstagramPlaceholder() {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "60vh", textAlign: "center", padding: "40px 24px" }}>
      <div style={{ width: 72, height: 72, borderRadius: 20, background: "linear-gradient(135deg, #f09433 0%, #e6683c 25%, #dc2743 50%, #cc2366 75%, #bc1888 100%)", display: "grid", placeItems: "center", marginBottom: 24 }}>
        <InstagramIcon size={36} />
      </div>
      <h2 style={{ fontWeight: 700, fontSize: 20, marginBottom: 8, color: "var(--ink)" }}>Instagram — Bientôt disponible</h2>
      <p style={{ color: "var(--muted)", maxWidth: 360, lineHeight: 1.6, margin: 0 }}>
        L'analyse et la génération de contenu Instagram arrivent prochainement.<br />
        En attendant, restez sur LinkedIn !
      </p>
    </div>
  );
}

// ── ALE-103 : Contenu Instagram — même structure que LinkedIn (hooks au lieu de posts) ──

function InstagramContentHub({
  tab,
  onTab,
  isAuthed,
  requireAuth,
}: {
  tab: ContentTab;
  onTab: (t: ContentTab) => void;
  isAuthed: boolean;
  requireAuth: (reason?: string, mode?: AuthMode) => void;
}) {
  const subTabs: { key: ContentTab; label: string; icon: React.ReactNode }[] = [
    { key: "daily", label: "Idée du jour", icon: <Sparkles size={14} /> },
    { key: "generator", label: "Générateur de hooks", icon: <PenTool size={14} /> },
    { key: "library", label: "Mes contenus", icon: <Bookmark size={14} /> },
  ];
  return (
    <div>
      <div className="tabs">
        {subTabs.map((t) => (
          <button
            key={t.key}
            className={`tab ${tab === t.key ? "active" : ""}`}
            onClick={() => onTab(t.key)}
            style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>
      {tab === "generator" ? (
        <InstagramGenerator isAuthed={isAuthed} requireAuth={requireAuth} />
      ) : (
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "28px 20px", color: "var(--muted)" }}>
          <Clock3 size={16} />
          <span style={{ fontSize: 14 }}>Bientôt disponible pour Instagram.</span>
        </div>
      )}
    </div>
  );
}

function InstagramGenerator({
  isAuthed,
  requireAuth,
}: {
  isAuthed: boolean;
  requireAuth: (reason?: string, mode?: AuthMode) => void;
}) {
  const [hooks, setHooks] = useState<string[]>([]);
  const [topic, setTopic] = useState("");
  const [hookCount, setHookCount] = useState(8);
  const [loadingHooks, setLoadingHooks] = useState(false);
  const [copiedHook, setCopiedHook] = useState<number | null>(null);

  const [error, setError] = useState("");

  async function generateHooks(t: string) {
    if (!isAuthed) {
      requireAuth("Crée un compte gratuit pour générer des hooks Instagram personnalisés.");
      return;
    }
    setError("");
    setLoadingHooks(true);
    try {
      const res = await fetch(`${DIRECT_API_URL}/instagram/hooks`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ count: hookCount, topic: t.trim() || undefined }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Échec de la génération de hooks");
      setHooks(data.hooks || []);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoadingHooks(false);
    }
  }

  async function copyHook(text: string, idx: number) {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedHook(idx);
      setTimeout(() => setCopiedHook(null), 2000);
    } catch { /* ignore */ }
  }

  return (
    <div>
      {error && <div className="error">{error}</div>}

      {/* Génération de hooks — même structure que « Générer des posts » */}
      <div className="gen-section">
        <h2 className="section-title"><PenTool size={20} /> Générer des hooks</h2>
        <div className="gen-form">
          <div className="url-input">
            <PenTool size={16} color="var(--primary)" />
            <input
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="Sujet du hook (optionnel) : ex. routine matinale, productivité…"
              onKeyDown={(e) => e.key === "Enter" && generateHooks(topic)}
            />
            <button className="primary-button" disabled={loadingHooks} onClick={() => generateHooks(topic)}>
              {loadingHooks ? <Loader2 size={14} className="spinning" /> : <Sparkles size={14} />}
              Générer
            </button>
          </div>
          <div className="role-picker">
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--muted)" }}>
              Nombre de hooks :
              <select
                value={hookCount}
                onChange={(e) => setHookCount(Number(e.target.value))}
                style={{ fontSize: 13, padding: "2px 6px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg)", color: "var(--text)", cursor: "pointer" }}
              >
                <option value={5}>5</option>
                <option value={8}>8</option>
                <option value={12}>12</option>
              </select>
            </label>
            <span className="role-picker-hint">
              Hooks personnalisés selon ton profil éditorial (secteur, audience, offre, ton). Renseigne un sujet pour les orienter.
            </span>
          </div>
        </div>
      </div>

      {hooks.length > 0 && (
        <div className="variants-list">
          {hooks.map((hook, i) => (
            <div className="variant-card" key={i}>
              <div className="variant-header">
                <span className="variant-number" style={{ background: "var(--primary)" }}>{i + 1}</span>
              </div>
              <p style={{ fontSize: 14, color: "var(--ink)", lineHeight: 1.5, margin: "4px 0 10px" }}>{hook}</p>
              <button className="secondary-button" onClick={() => copyHook(hook, i)}>
                {copiedHook === i ? <CheckCircle2 size={14} /> : <Link2 size={14} />}
                {copiedHook === i ? "Copié ✓" : "Copier le hook"}
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Le reste (posts complets, publication, visuels) — bientôt disponible */}
      <div className="card" style={{ padding: 16, opacity: 0.7, display: "flex", alignItems: "center", gap: 10, marginTop: 16 }}>
        <Clock3 size={15} style={{ color: "var(--muted)" }} />
        <span style={{ fontSize: 12, color: "var(--muted)" }}>Génération de posts complets, publication et visuels Instagram — bientôt disponible.</span>
      </div>
    </div>
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
    analyze: "Veille LinkedIn",
    profile: "Mon profil éditorial",
    assistant: "Agent IA",
    content: "Contenu",
    progress: "Tableau de bord",
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

function Landing({ onSubmit, loading, error, onBatch }: {
  onSubmit: (payload: { url: string; limit: number; useCache: boolean; runLlm: boolean }) => void;
  loading: boolean;
  error: string;
  onBatch: () => void;
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
        <p>Colle l'URL d'un profil. On scrape ses posts récents, on extrait hooks, CTAs, mix funnel, et on te dit quoi répliquer. <button type="button" className="link-button" onClick={onBatch}>Plusieurs profils ? → Backlog</button></p>

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
        </div>
      </div>
    </section>
  );
}

function Kpis({ result }: { result: Analysis }) {
  const profile = result.profile || {};
  const stats = result.stats || {};
  const engagement = stats.engagement || {};
  return (
    <div className="kpi-grid">
      <div className="kpi-card"><span>Abonnés</span><div className="metric">{fmt(profile.follower_count)}</div></div>
      <div className="kpi-card"><span>Posts analysés</span><div className="metric">{fmt(stats.count)}</div></div>
      <div className="kpi-card"><span>Posts / semaine</span><div className="metric">{fmt(stats.posts_per_week)}</div></div>
      <div className="kpi-card"><span>Comments médian</span><div className="metric">{fmt(engagement.median_comments)}</div></div>
      <div className="kpi-card"><span>Taux d'engagement</span><div className="metric">{engagement.engagement_rate_pct ? `${engagement.engagement_rate_pct}%` : "—"}</div></div>
    </div>
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
    <div className="card" key="hooks"><h3>Accroches (1ère ligne)</h3>{hookEntries.map(([label, n]) => <Bar key={label} label={hookLabel(label)} value={n} max={maxHook} />)}</div>,
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
          <div className="markdown card"><ReactMarkdown remarkPlugins={[remarkGfm]}>{result.markdown}</ReactMarkdown></div>
        ) : (
          <>
            <div className="markdown card">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={reportComponents(unlock)}>
                {reportBeforeActions(result.markdown || "")}
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
      {tab === "Tous les posts" && <pre className="raw-json">{JSON.stringify(result.posts, null, 2)}</pre>}
      {tab === "JSON brut" && <pre className="raw-json">{JSON.stringify(result, null, 2)}</pre>}
    </>
  );
}

type LinkedInStatus = {
  configured: boolean;
  connected: boolean;
  account_id?: string | null;
  connected_at?: string | null;
};

/** Statut de connexion LinkedIn (via Zernio) + lancement du flux OAuth. */
function useLinkedIn(isAuthed: boolean) {
  const [status, setStatus] = useState<LinkedInStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isAuthed) { setStatus(null); return; }
    (async () => {
      try {
        const res = await fetch(`${DIRECT_API_URL}/me/linkedin/status`, { headers: await authHeaders() });
        if (res.ok) setStatus(await res.json());
      } catch { /* ignore */ }
    })();
  }, [isAuthed]);

  async function connect() {
    setError("");
    setBusy(true);
    try {
      const redirect = `${window.location.origin}${window.location.pathname}?linkedin=connected`;
      const res = await fetch(`${DIRECT_API_URL}/me/linkedin/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ redirect_url: redirect }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Connexion LinkedIn impossible");
      window.location.href = data.auth_url; // Zernio gère l'OAuth puis renvoie vers l'app
    } catch (err: any) {
      setError(err.message);
      setBusy(false);
    }
  }

  return { status, busy, error, connect };
}

type XStatus = {
  configured: boolean;
  connected: boolean;
  account_id?: string | null;
  connected_at?: string | null;
};

/** Statut de connexion X (Twitter) via Zernio + lancement du flux OAuth. */
function useTwitter(isAuthed: boolean) {
  const [status, setStatus] = useState<XStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isAuthed) { setStatus(null); return; }
    (async () => {
      try {
        const res = await fetch(`${DIRECT_API_URL}/me/x/status`, { headers: await authHeaders() });
        if (res.ok) setStatus(await res.json());
      } catch { /* ignore */ }
    })();
  }, [isAuthed]);

  async function connect() {
    setError("");
    setBusy(true);
    try {
      const redirect = `${window.location.origin}${window.location.pathname}?x=connected`;
      const res = await fetch(`${DIRECT_API_URL}/me/x/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ redirect_url: redirect }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Connexion X impossible");
      window.location.href = data.auth_url;
    } catch (err: any) {
      setError(err.message);
      setBusy(false);
    }
  }

  return { status, busy, error, connect };
}

type SlackStatus = {
  connected: boolean;
  configured: boolean;
  team_name?: string | null;
  channel_id?: string | null;
  connected_at?: string | null;
};

function useSlack(isAuthed: boolean) {
  const [status, setStatus] = useState<SlackStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function refresh() {
    if (!isAuthed) { setStatus(null); return; }
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/integrations/slack/status`, { headers: await authHeaders() });
      if (res.ok) setStatus(await res.json());
    } catch { /* ignore */ }
  }

  useEffect(() => { void refresh(); }, [isAuthed]); // eslint-disable-line react-hooks/exhaustive-deps

  async function connect() {
    setError("");
    setBusy(true);
    try {
      const redirectUri = `${window.location.origin}${window.location.pathname}`;
      const res = await fetch(`${DIRECT_API_URL}/me/integrations/slack/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ redirect_uri: redirectUri }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Connexion Slack impossible");
      sessionStorage.setItem("slack_oauth_pending", "1");
      window.location.href = data.auth_url;
    } catch (err: any) {
      setError(err.message);
      setBusy(false);
    }
  }

  async function disconnect() {
    setError("");
    setBusy(true);
    try {
      await fetch(`${DIRECT_API_URL}/me/integrations/slack`, {
        method: "DELETE",
        headers: await authHeaders(),
      });
      setStatus((prev) => prev ? { ...prev, connected: false } : prev);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return { status, busy, error, connect, disconnect, refresh };
}

function Generator({ isAuthed, requireAuth, seed }: { isAuthed: boolean; requireAuth: (reason?: string) => void; seed?: { topic: string; nonce: number } | null }) {
  const [variants, setVariants] = useState<Variant[]>([]);
  const [topic, setTopic] = useState("");
  const [role, setRole] = useState("auto");
  const [webSearch, setWebSearch] = useState(false);
  const [loadingPosts, setLoadingPosts] = useState(false);
  const [error, setError] = useState("");
  const linkedin = useLinkedIn(isAuthed);
  const twitter = useTwitter(isAuthed);
  const slack = useSlack(isAuthed);
  const [slackSent, setSlackSent] = useState<Record<number, boolean>>({});
  const [slackSending, setSlackSending] = useState<Record<number, boolean>>({});
  const [publishing, setPublishing] = useState<number | null>(null);
  const [published, setPublished] = useState<number | null>(null);
  const [drafted, setDrafted] = useState<number | null>(null);
  const [publishingX, setPublishingX] = useState<number | null>(null);
  const [publishedX, setPublishedX] = useState<number | null>(null);
  const [confirmIndex, setConfirmIndex] = useState<number | null>(null);
  const [confirmXIndex, setConfirmXIndex] = useState<number | null>(null);
  const [publishError, setPublishError] = useState("");
  const [variantImages, setVariantImages] = useState<Record<number, string>>({});
  const [generatingImage, setGeneratingImage] = useState<number | null>(null);
  const [imageError, setImageError] = useState("");
  const [editedVariants, setEditedVariants] = useState<Record<number, string>>({});
  const [copiedVariant, setCopiedVariant] = useState<number | null>(null);
  const [variantCount, setVariantCount] = useState(1);
  const [scheduleModal, setScheduleModal] = useState<{ index: number; text: string } | null>(null);
  const [scheduleDate, setScheduleDate] = useState("");
  const [scheduling, setScheduling] = useState(false);
  const [scheduledIndices, setScheduledIndices] = useState<Record<number, boolean>>({});
  const [scheduleError, setScheduleError] = useState("");

  // "Réutiliser" depuis Mes contenus : pré-remplit le sujet et lance la génération.
  useEffect(() => {
    if (!seed?.topic) return;
    setTopic(seed.topic);
    void generateFromTopic(seed.topic);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed?.nonce]);

  function publishVariant(i: number, text: string, draft: boolean = false) {
    if (!isAuthed) { requireAuth("Connecte-toi pour publier sur LinkedIn."); return; }
    if (!linkedin.status?.connected) {
      setPublishError("Connecte d'abord ton compte LinkedIn dans l'onglet Profil.");
      return;
    }
    if (!draft) {
      setConfirmIndex(i);
      return;
    }
    void doPublish(i, text, true);
  }

  async function doPublish(i: number, text: string, draft: boolean = false) {
    setPublishError("");
    setPublished(null);
    setDrafted(null);
    setPublishing(i);
    setConfirmIndex(null);
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/linkedin/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ content: text, draft }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || (draft ? "Enregistrement du brouillon impossible" : "Publication impossible"));
      if (draft) setDrafted(i); else setPublished(i);
    } catch (err: any) {
      setPublishError(err.message);
    } finally {
      setPublishing(null);
    }
  }

  function publishVariantX(i: number, text: string) {
    if (!isAuthed) { requireAuth("Connecte-toi pour publier sur X."); return; }
    if (!twitter.status?.connected) {
      setPublishError("Connecte d'abord ton compte X dans l'onglet Profil.");
      return;
    }
    setConfirmXIndex(i);
  }

  async function doPublishX(i: number, text: string) {
    setPublishError("");
    setPublishedX(null);
    setPublishingX(i);
    setConfirmXIndex(null);
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/x/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ content: text, draft: false }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Publication sur X impossible");
      setPublishedX(i);
    } catch (err: any) {
      setPublishError(err.message);
    } finally {
      setPublishingX(null);
    }
  }

  function copyVariant(i: number, text: string) {
    void navigator.clipboard.writeText(text);
    setCopiedVariant(i);
    setTimeout(() => setCopiedVariant((current) => (current === i ? null : current)), 1500);
  }

  function openScheduleModal(i: number, text: string) {
    if (!isAuthed) { requireAuth("Connecte-toi pour programmer une publication LinkedIn."); return; }
    if (!linkedin.status?.connected) {
      setScheduleError("Connecte d'abord ton compte LinkedIn dans l'onglet Profil.");
      return;
    }
    // Prefill to tomorrow 9:00 local time
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    tomorrow.setHours(9, 0, 0, 0);
    const pad = (n: number) => String(n).padStart(2, "0");
    const localIso = `${tomorrow.getFullYear()}-${pad(tomorrow.getMonth() + 1)}-${pad(tomorrow.getDate())}T${pad(tomorrow.getHours())}:${pad(tomorrow.getMinutes())}`;
    setScheduleDate(localIso);
    setScheduleError("");
    setScheduleModal({ index: i, text });
  }

  async function doSchedule() {
    if (!scheduleModal) return;
    setScheduleError("");
    setScheduling(true);
    try {
      const localDate = new Date(scheduleDate);
      if (isNaN(localDate.getTime())) throw new Error("Date invalide.");
      if (localDate <= new Date()) throw new Error("La date doit être dans le futur.");
      const res = await fetch(`${DIRECT_API_URL}/me/linkedin/schedule`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ content: scheduleModal.text, scheduled_at: localDate.toISOString() }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Planification impossible.");
      setScheduledIndices((prev) => ({ ...prev, [scheduleModal.index]: true }));
      setScheduleModal(null);
    } catch (err: any) {
      setScheduleError(err.message);
    } finally {
      setScheduling(false);
    }
  }

  async function generateImage(i: number, postText: string) {
    setImageError("");
    setGeneratingImage(i);
    try {
      const res = await fetch(`${DIRECT_API_URL}/generate-image`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ post_text: postText }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Échec de la génération d'image");
      emitCredits(data.credits);
      setVariantImages((prev) => ({ ...prev, [i]: data.image_data }));
    } catch (err: any) {
      setImageError(err.message);
    } finally {
      setGeneratingImage(null);
    }
  }

  async function generateFromTopic(t: string) {
    setError("");
    setLoadingPosts(true);
    try {
      // Sujet optionnel : sans sujet, le backend choisit lui-même un angle (idée = post).
      const body: { topic?: string; editorial_role?: string; web_search?: boolean; count?: number } = { count: variantCount };
      if (t.trim()) body.topic = t.trim();
      if (role !== "auto") body.editorial_role = role;
      if (webSearch) body.web_search = true;
      const res = await fetch(`${DIRECT_API_URL}/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Échec de la génération de posts");
      emitCredits(data.credits);
      setEditedVariants({}); // éditions indexées par position : à purger sinon elles contaminent le nouveau batch
      setVariants(data.variants || []);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoadingPosts(false);
    }
  }

  const funnelColors: Record<string, string> = { TOFU: "#10b981", MOFU: "#f59e0b", BOFU: "#ef4444" };
  const hookColors: Record<string, string> = { "stat+contrarian": "#f97316", "story+result": "#10b981", question: "#3b82f6" };
  const roleOptions: { value: string; label: string }[] = [
    { value: "auto", label: "Mix automatique" },
    { value: "performance", label: "Performance" },
    { value: "methodologie", label: "Méthodologie" },
    { value: "autorite", label: "Autorité" },
    { value: "story", label: "Story" },
    { value: "quotidien", label: "Quotidien" },
    { value: "opinion", label: "Opinion" },
    { value: "relationnel", label: "Relationnel" },
  ];
  const roleColors: Record<string, string> = {
    performance: "#f97316",
    methodologie: "#0ea5e9",
    autorite: "#8b5cf6",
    story: "#10b981",
    quotidien: "#14b8a6",
    opinion: "#ef4444",
    relationnel: "#ec4899",
  };
  const roleLabel = (r?: string) => roleOptions.find((o) => o.value === r)?.label || r;

  return (
    <div>
      {error && <div className="error">{error}</div>}

      {/* Post generation */}
      <div className="gen-section">
        <h2 className="section-title"><PenTool size={20} /> Générer des idées de posts</h2>
        <div className="gen-form">
          <div className="url-input">
            <PenTool size={16} color="var(--primary)" />
            <input
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="Sujet du post (optionnel) : ex. les 5 erreurs avec Claude AI…"
              onKeyDown={(e) => e.key === "Enter" && generateFromTopic(topic)}
            />
            <button className="primary-button" disabled={loadingPosts} onClick={() => generateFromTopic(topic)}>
              {loadingPosts ? <Loader2 size={14} className="spinning" /> : <Sparkles size={14} />}
              Générer
            </button>
          </div>
          <div className="role-picker">
            <label className="role-picker-label">Rôle éditorial</label>
            <select className="role-select" value={role} onChange={(e) => setRole(e.target.value)}>
              {roleOptions.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            <span className="role-picker-hint">
              Sujet optionnel : laisse vide et Claude propose lui-même des idées de posts à fort potentiel.
            </span>
            <span className="role-picker-hint">
              {role === "auto"
                ? "Mix automatique : performance + méthodologie/autorité + relationnel/quotidien."
                : "Les 3 variants utiliseront ce rôle."}
            </span>
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--muted)", cursor: "pointer", marginTop: 6 }}>
              <input
                type="checkbox"
                checked={webSearch}
                onChange={(e) => setWebSearch(e.target.checked)}
                style={{ accentColor: "var(--accent)", width: 14, height: 14 }}
              />
              Recherche web en temps réel
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--muted)" }}>
              Variants :
              <select
                value={variantCount}
                onChange={(e) => setVariantCount(Number(e.target.value))}
                style={{ fontSize: 13, padding: "2px 6px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg)", color: "var(--text)", cursor: "pointer" }}
              >
                <option value={1}>1</option>
                <option value={2}>2</option>
                <option value={3}>3</option>
              </select>
            </label>
          </div>
        </div>
      </div>

      {variants.length > 0 && (
        <div className="variants-list">
          {variants.map((v, i) => {
            const roleColor = (v.editorial_role && roleColors[v.editorial_role]) || "var(--primary)";
            const color = hookColors[v.hook_type] || roleColor;
            return (
              <div className="variant-card" key={i}>
                <div className="variant-header">
                  <span className="variant-number" style={{ background: roleColor }}>{i + 1}</span>
                  {v.editorial_role && (
                    <span className="badge role-badge" style={{ borderColor: roleColor, color: roleColor }}>
                      {roleLabel(v.editorial_role)}
                    </span>
                  )}
                  <span className="badge" style={{ borderColor: color, color }}>{v.hook_type}</span>
                  <span className="idea-lift">{v.predicted_lift}</span>
                </div>
                <p className="variant-strategy">{v.strategy}</p>
                <div className="variant-text-wrap">
                  <textarea
                    className="variant-text"
                    value={editedVariants[i] ?? v.post}
                    rows={14}
                    onChange={(e) => setEditedVariants((prev) => ({ ...prev, [i]: e.target.value }))}
                  />
                  <button
                    type="button"
                    className="variant-copy-button"
                    aria-label={copiedVariant === i ? "Post copié" : "Copier le post"}
                    title={copiedVariant === i ? "Copié ✓" : "Copier le post"}
                    onClick={() => copyVariant(i, editedVariants[i] ?? v.post)}
                  >
                    {copiedVariant === i ? <CheckCircle2 size={16} /> : <Copy size={16} />}
                  </button>
                </div>
                {editedVariants[i] !== undefined && editedVariants[i] !== v.post && (
                  <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 4 }}>
                    <span style={{ fontSize: 12, color: "var(--muted)" }}>✏️ Modifié</span>
                    <button className="secondary-button" style={{ fontSize: 12, minHeight: 28, padding: "0 10px" }} onClick={() => setEditedVariants((prev) => { const n = { ...prev }; delete n[i]; return n; })}>
                      Revenir à l&apos;original
                    </button>
                  </div>
                )}
                <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
                  <button
                    className="primary-button"
                    disabled={publishing === i}
                    title={linkedin.status?.connected ? "Publier maintenant sur LinkedIn" : "Connecte ton compte LinkedIn dans l'onglet Profil"}
                    onClick={() => publishVariant(i, editedVariants[i] ?? v.post)}
                  >
                    {publishing === i && published !== i ? <Loader2 size={14} className="spinning" /> : <Linkedin size={14} />}
                    {publishing === i && published !== i ? "Publication…" : published === i ? "Publié ✓" : "Publier sur LinkedIn"}
                  </button>
                  <button
                    className="secondary-button"
                    disabled={publishing === i}
                    title={linkedin.status?.connected ? "Enregistrer comme brouillon dans Zernio" : "Connecte ton compte LinkedIn dans l'onglet Profil"}
                    onClick={() => publishVariant(i, editedVariants[i] ?? v.post, true)}
                  >
                    {publishing === i && drafted !== i ? <Loader2 size={14} className="spinning" /> : <FileText size={14} />}
                    {drafted === i ? "Brouillon ✓" : "Enregistrer en brouillon"}
                  </button>
                  <button
                    className="secondary-button"
                    disabled={publishing === i || scheduling}
                    title={linkedin.status?.connected ? "Programmer la publication à une date/heure choisie" : "Connecte ton compte LinkedIn dans l'onglet Profil"}
                    onClick={() => openScheduleModal(i, editedVariants[i] ?? v.post)}
                  >
                    <Clock3 size={14} />
                    {scheduledIndices[i] ? "Programmé ✓" : "Programmer"}
                  </button>
                  <button
                    className="secondary-button"
                    disabled={generatingImage === i}
                    onClick={() => generateImage(i, editedVariants[i] ?? v.post)}
                  >
                    {generatingImage === i ? <Loader2 size={14} className="spinning" /> : <ImageIcon size={14} />}
                    {generatingImage === i ? "Génération…" : variantImages[i] ? "Régénérer l'image" : "Générer une image"}
                  </button>
                  {slack.status?.connected && v.id && (
                    <button
                      className="secondary-button"
                      disabled={!!slackSending[i] || !!slackSent[i]}
                      onClick={async () => {
                        setSlackSending((p) => ({ ...p, [i]: true }));
                        try {
                          await fetch(`${DIRECT_API_URL}/me/integrations/slack/send-posts`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json", ...(await authHeaders()) },
                            body: JSON.stringify({ post_id: v.id }),
                          });
                          setSlackSent((p) => ({ ...p, [i]: true }));
                        } finally {
                          setSlackSending((p) => ({ ...p, [i]: false }));
                        }
                      }}
                    >
                      {slackSending[i] ? <Loader2 size={14} className="spinning" /> : null}
                      {slackSent[i] ? "Sur Slack ✓" : "Envoyer sur Slack"}
                    </button>
                  )}
                  {twitter.status?.connected && (
                    <button
                      className="secondary-button"
                      disabled={publishingX === i}
                      title="Publier maintenant sur X (Twitter)"
                      onClick={() => publishVariantX(i, editedVariants[i] ?? v.post)}
                    >
                      {publishingX === i ? <Loader2 size={14} className="spinning" /> : <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.742l7.734-8.842L1.254 2.25H8.08l4.253 5.622L18.244 2.25zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>}
                      {publishingX === i ? "Publication…" : publishedX === i ? "Publié ✓" : "Publier sur X"}
                    </button>
                  )}
                </div>
                {published === i && (
                  <p className="role-picker-hint" style={{ marginTop: 6 }}>Post publié sur LinkedIn ✓</p>
                )}
                {drafted === i && (
                  <p className="role-picker-hint" style={{ marginTop: 6 }}>Brouillon enregistré dans Zernio ✓</p>
                )}
                {publishedX === i && (
                  <p className="role-picker-hint" style={{ marginTop: 6 }}>Post publié sur X ✓</p>
                )}
                {scheduledIndices[i] && (
                  <p className="role-picker-hint" style={{ marginTop: 6 }}>Post programmé ✓ — visible dans l&apos;onglet Profil.</p>
                )}
                {variantImages[i] && (
                  <div style={{ marginTop: 12 }}>
                    <img src={variantImages[i]} alt="Image générée" style={{ width: "100%", maxWidth: 400, borderRadius: 8, display: "block" }} />
                    <a
                      href={variantImages[i]}
                      download={`post-image-${i + 1}.png`}
                      className="secondary-button"
                      style={{ display: "inline-flex", alignItems: "center", gap: 6, marginTop: 8, textDecoration: "none" }}
                    >
                      <Download size={14} /> Télécharger
                    </a>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      {publishError && <div className="error" style={{ marginTop: 12 }}>{publishError}</div>}
      {imageError && <div className="error" style={{ marginTop: 12 }}>{imageError}</div>}

      {confirmIndex !== null && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 1000,
          display: "flex", alignItems: "center", justifyContent: "center", padding: 16,
        }}>
          <div className="card" style={{ maxWidth: 560, width: "100%", padding: 24 }}>
            <h3 style={{ marginTop: 0, marginBottom: 8 }}>Publier ce post sur LinkedIn ?</h3>
            <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 12 }}>
              Le post sera publié <strong>immédiatement</strong> sur ton compte LinkedIn.
            </p>
            <textarea
              readOnly
              value={editedVariants[confirmIndex] ?? variants[confirmIndex]?.post ?? ""}
              rows={8}
              className="variant-text"
              style={{ width: "100%", boxSizing: "border-box", marginBottom: 16 }}
            />
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button className="secondary-button" onClick={() => setConfirmIndex(null)}>
                Annuler
              </button>
              <button
                className="primary-button"
                disabled={publishing !== null}
                onClick={() => doPublish(confirmIndex, editedVariants[confirmIndex] ?? variants[confirmIndex]?.post ?? "")}
              >
                {publishing !== null
                  ? <><Loader2 size={14} className="spinning" /> Publication…</>
                  : <><Linkedin size={14} /> Confirmer la publication</>
                }
              </button>
            </div>
          </div>
        </div>
      )}

      {confirmXIndex !== null && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 1000,
          display: "flex", alignItems: "center", justifyContent: "center", padding: 16,
        }}>
          <div className="card" style={{ maxWidth: 560, width: "100%", padding: 24 }}>
            <h3 style={{ marginTop: 0, marginBottom: 8 }}>Publier ce post sur X ?</h3>
            <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 12 }}>
              Le post sera publié <strong>immédiatement</strong> sur ton compte X (Twitter).
            </p>
            <textarea
              readOnly
              value={editedVariants[confirmXIndex] ?? variants[confirmXIndex]?.post ?? ""}
              rows={8}
              className="variant-text"
              style={{ width: "100%", boxSizing: "border-box", marginBottom: 16 }}
            />
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button className="secondary-button" onClick={() => setConfirmXIndex(null)}>
                Annuler
              </button>
              <button
                className="primary-button"
                disabled={publishingX !== null}
                onClick={() => doPublishX(confirmXIndex, editedVariants[confirmXIndex] ?? variants[confirmXIndex]?.post ?? "")}
              >
                {publishingX !== null
                  ? <><Loader2 size={14} className="spinning" /> Publication…</>
                  : <><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.742l7.734-8.842L1.254 2.25H8.08l4.253 5.622L18.244 2.25zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg> Confirmer la publication</>
                }
              </button>
            </div>
          </div>
        </div>
      )}

      {scheduleModal !== null && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 1000,
          display: "flex", alignItems: "center", justifyContent: "center", padding: 16,
        }}>
          <div className="card" style={{ maxWidth: 520, width: "100%", padding: 24 }}>
            <h3 style={{ marginTop: 0, marginBottom: 8 }}>Programmer ce post</h3>
            <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 12 }}>
              Le post sera publié automatiquement sur LinkedIn à la date et l&apos;heure choisies.
            </p>
            <textarea
              readOnly
              value={scheduleModal.text}
              rows={6}
              className="variant-text"
              style={{ width: "100%", boxSizing: "border-box", marginBottom: 12 }}
            />
            <label style={{ fontSize: 13, fontWeight: 500, display: "block", marginBottom: 6 }}>
              Date et heure de publication
            </label>
            <input
              type="datetime-local"
              value={scheduleDate}
              onChange={(e) => setScheduleDate(e.target.value)}
              style={{ width: "100%", boxSizing: "border-box", padding: "8px 10px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)", fontSize: 14, marginBottom: 12 }}
            />
            {scheduleError && <p style={{ color: "var(--error, #e53e3e)", fontSize: 13, marginBottom: 8 }}>{scheduleError}</p>}
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button className="secondary-button" onClick={() => setScheduleModal(null)}>
                Annuler
              </button>
              <button className="primary-button" disabled={scheduling || !scheduleDate} onClick={doSchedule}>
                {scheduling ? <><Loader2 size={14} className="spinning" /> Planification…</> : <><Clock3 size={14} /> Confirmer</>}
              </button>
            </div>
          </div>
        </div>
      )}
      {scheduleError && !scheduleModal && <div className="error" style={{ marginTop: 12 }}>{scheduleError}</div>}
    </div>
  );
}

// ── ALE-69 : Dashboard de progression ────────────────────────────────────────

type ProgressData = {
  corpus: { influencer_count: number; analysis_count: number; last_analysis_at: string | null; active_jobs: number; done_jobs: number };
  content: { ideas_count: number; posts_count: number };
  publishing: { linkedin_connected: boolean; slack_connected: boolean };
  profile: { filled: boolean; has_linkedin_url: boolean };
  credits: { balance: number };
  next_action: string;
};

function ProgressStep({ done, label }: { done: boolean; label: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0" }}>
      <span style={{ width: 20, height: 20, borderRadius: "50%", background: done ? "var(--primary)" : "var(--border)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
        {done ? <CheckCircle2 size={12} color="#fff" /> : <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--muted)", display: "block" }} />}
      </span>
      <span style={{ fontSize: 13, color: done ? "var(--fg)" : "var(--muted)" }}>{label}</span>
    </div>
  );
}

function ProgressView({ isAuthed, requireAuth }: { isAuthed: boolean; requireAuth: (reason?: string) => void }) {
  const [data, setData] = useState<ProgressData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    if (!isAuthed) return;
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/dashboard/progress`, { headers: await authHeaders() });
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || "Impossible de charger la progression");
      setData(json);
    } catch (err: any) {
      setError(err.message || "Chargement impossible");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (isAuthed) void load();
    else setData(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed]);

  if (!isAuthed) {
    return (
      <div className="card" style={{ textAlign: "center", padding: 40 }}>
        <Activity size={28} style={{ opacity: 0.4, marginBottom: 12 }} />
        <h2 style={{ margin: "0 0 8px" }}>Tableau de bord</h2>
        <p style={{ color: "var(--muted)", marginBottom: 16 }}>Connecte-toi pour voir ton avancement.</p>
        <button type="button" className="primary-button" onClick={() => requireAuth()}>Se connecter</button>
      </div>
    );
  }

  return (
    <div>
      <div className="section-header">
        <div>
          <h2 className="section-title"><Activity size={20} /> Tableau de bord</h2>
          <p className="section-desc">Ton avancement global sur Cibl.</p>
        </div>
        <button className="secondary-button" onClick={load} disabled={loading}>
          {loading ? <Loader2 size={14} className="spinning" /> : <RefreshCw size={14} />}
          Rafraîchir
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 12 }}>{error}</div>}

      {loading && !data && (
        <div className="card" style={{ padding: 32, textAlign: "center" }}>
          <Loader2 size={22} className="spinning" style={{ opacity: 0.45 }} />
        </div>
      )}

      {data && (
        <>
          {/* Prochaine action recommandée */}
          <div className="card" style={{ marginBottom: 16, borderLeft: "3px solid var(--primary)", background: "var(--surface2)" }}>
            <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
              <Zap size={18} style={{ color: "var(--primary)", flexShrink: 0, marginTop: 2 }} />
              <div>
                <p style={{ margin: 0, fontWeight: 600, fontSize: 14 }}>Prochaine action</p>
                <p style={{ margin: "4px 0 0", fontSize: 13, color: "var(--muted)" }}>{data.next_action}</p>
              </div>
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 12, marginBottom: 16 }}>
            <div className="card" style={{ textAlign: "center" }}>
              <div style={{ fontSize: 28, fontWeight: 700, color: "var(--primary)" }}>{data.corpus.influencer_count}</div>
              <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>Influenceurs analysés</div>
            </div>
            <div className="card" style={{ textAlign: "center" }}>
              <div style={{ fontSize: 28, fontWeight: 700, color: "var(--primary)" }}>{data.content.ideas_count}</div>
              <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>Idées générées</div>
            </div>
            <div className="card" style={{ textAlign: "center" }}>
              <div style={{ fontSize: 28, fontWeight: 700, color: "var(--primary)" }}>{data.content.posts_count}</div>
              <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>Posts générés</div>
            </div>
            <div className="card" style={{ textAlign: "center" }}>
              <div style={{ fontSize: 28, fontWeight: 700, color: data.credits.balance <= 5 ? "var(--error)" : "var(--primary)" }}>
                {data.credits.balance}
              </div>
              <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>Crédits restants</div>
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div className="card">
              <p style={{ margin: "0 0 12px", fontWeight: 600, fontSize: 14 }}>Configuration</p>
              <ProgressStep done={data.profile.filled} label="Profil éditorial rempli" />
              <ProgressStep done={data.profile.has_linkedin_url} label="URL LinkedIn renseignée" />
              <ProgressStep done={data.corpus.influencer_count > 0} label="Au moins 1 influenceur analysé" />
            </div>
            <div className="card">
              <p style={{ margin: "0 0 12px", fontWeight: 600, fontSize: 14 }}>Publication</p>
              <ProgressStep done={data.publishing.linkedin_connected} label="LinkedIn connecté (Zernio)" />
              <ProgressStep done={data.publishing.slack_connected} label="Slack connecté" />
            </div>
          </div>

          {data.corpus.active_jobs > 0 && (
            <div className="auth-info" style={{ marginTop: 12 }}>
              <Loader2 size={14} className="spinning" style={{ verticalAlign: "-2px", marginRight: 6 }} />
              {data.corpus.active_jobs} analyse(s) en cours dans la queue.
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── Fin ALE-69 ────────────────────────────────────────────────────────────────

type DailyIdea = { id: string; idea_date: string; idea_markdown: string; seed_id?: string | null; created_at?: string };
type IdeaSeed = { id: string; text: string; used_at?: string | null; created_at?: string };
type DailyIdeaCard = Pick<Idea, "title" | "hook" | "hook_type" | "funnel" | "angle" | "why_it_works" | "estimated_lift">;

function parseDailyIdeaMarkdown(markdown: string): DailyIdeaCard {
  const lines = markdown.split(/\r?\n/).map((line) => line.trim());
  const title = lines.find((line) => line.startsWith("## "))?.replace(/^##\s+/, "").trim() || "Idée du jour";
  const hook = lines.find((line) => line.startsWith("**Accroche :**"))
    ?.replace(/^\*\*Accroche :\*\*\s*/, "")
    .trim() || "";
  const why = lines.find((line) => line.startsWith("**Pourquoi ça marche :**"))
    ?.replace(/^\*\*Pourquoi ça marche :\*\*\s*/, "")
    .trim() || "";
  const metaLine = [...lines].reverse().find((line) => line.includes("hook _") || /\b(TOFU|MOFU|BOFU)\b/.test(line)) || "";
  const hookType = metaLine.match(/hook _([^_]+)_/)?.[1]?.trim() || "other";
  const funnel = metaLine.match(/\b(TOFU|MOFU|BOFU)\b/)?.[1] || "TOFU";
  const estimatedLift = metaLine.split("·").map((part) => part.trim()).find((part) => part.startsWith("+")) || "";
  const angleLines = lines.filter((line) =>
    line &&
    !line.startsWith("## ") &&
    !line.startsWith("**Accroche :**") &&
    !line.startsWith("**Pourquoi ça marche :**") &&
    !line.startsWith("_Inspirée") &&
    line !== metaLine
  );

  return {
    title,
    hook,
    hook_type: hookType,
    funnel,
    angle: angleLines.join(" "),
    why_it_works: why,
    estimated_lift: estimatedLift,
  };
}

function DailyIdeasView({
  isAuthed,
  requireAuth,
  onReuse,
}: {
  isAuthed: boolean;
  requireAuth: (reason?: string) => void;
  onReuse: (topic: string) => void;
}) {
  const [ideas, setIdeas] = useState<DailyIdea[]>([]);
  const [seeds, setSeeds] = useState<IdeaSeed[]>([]);
  const [enabled, setEnabled] = useState(false);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");

  const fmtDate = (s?: string) => {
    if (!s) return "";
    try { return new Date(s).toLocaleDateString("fr-FR", { weekday: "long", day: "2-digit", month: "long" }); }
    catch { return s || ""; }
  };

  async function loadAll() {
    if (!isAuthed) return;
    setLoading(true);
    setError("");
    try {
      const headers = await authHeaders();
      const [dRes, sRes] = await Promise.all([
        fetch(`${DIRECT_API_URL}/me/daily-ideas`, { headers }),
        fetch(`${DIRECT_API_URL}/me/idea-seeds`, { headers }),
      ]);
      const dData = await dRes.json();
      const sData = await sRes.json();
      if (!dRes.ok) throw new Error(dData.detail || "Chargement des idées impossible");
      if (!sRes.ok) throw new Error(sData.detail || "Chargement du réservoir impossible");
      setIdeas(Array.isArray(dData?.ideas) ? dData.ideas : []);
      setEnabled(!!dData?.enabled);
      setSeeds(Array.isArray(sData) ? sData : []);
    } catch (err: any) {
      setError(err.message || "Chargement impossible");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (isAuthed) void loadAll();
    else { setIdeas([]); setSeeds([]); setEnabled(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed]);

  async function regenerate() {
    setRegenerating(true);
    setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/daily-ideas/regenerate`, {
        method: "POST",
        headers: { ...(await authHeaders()) },
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Régénération impossible");
      emitCredits(data.credits);
      if (data.idea) {
        setIdeas((prev) => {
          const today = data.idea.idea_date;
          const filtered = prev.filter((i) => i.idea_date !== today);
          return [data.idea, ...filtered];
        });
      }
    } catch (err: any) {
      setError(err.message || "Régénération impossible");
    } finally {
      setRegenerating(false);
    }
  }

  async function addSeed() {
    const text = draft.trim();
    if (text.length < 3) return;
    setAdding(true);
    setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/idea-seeds`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ text }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Ajout impossible");
      setSeeds((prev) => [...prev, data]);
      setDraft("");
    } catch (err: any) {
      setError(err.message || "Ajout impossible");
    } finally {
      setAdding(false);
    }
  }

  async function deleteSeed(id: string) {
    setSeeds((prev) => prev.filter((s) => s.id !== id));
    try {
      await fetch(`${DIRECT_API_URL}/me/idea-seeds/${id}`, { method: "DELETE", headers: await authHeaders() });
    } catch { void loadAll(); }
  }

  async function toggleEnabled() {
    const next = !enabled;
    setEnabled(next);
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/daily-ideas/enabled`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ enabled: next }),
      });
      if (!res.ok) throw new Error();
    } catch {
      setEnabled(!next);
      setError("Impossible de mettre à jour l'option.");
    }
  }

  if (!isAuthed) {
    return (
      <div className="card" style={{ textAlign: "center", padding: 40 }}>
        <Sparkles size={28} style={{ opacity: 0.4, marginBottom: 12 }} />
        <h2 style={{ margin: "0 0 8px" }}>Idée du jour</h2>
        <p style={{ color: "var(--muted)", marginBottom: 16 }}>
          Connecte-toi pour recevoir une idée de post chaque matin et alimenter ton réservoir d'idées.
        </p>
        <button type="button" className="primary-button" onClick={() => requireAuth("Crée un compte gratuit pour activer l'idée du jour.")}>
          <Sparkles size={14} /> Créer un compte gratuit
        </button>
      </div>
    );
  }

  return (
    <div>
      <div className="section-header">
        <div>
          <h2 className="section-title"><Sparkles size={20} /> Idée du jour</h2>
          <p className="section-desc">Chaque matin, une idée de post est générée à partir de ton benchmark d'influenceurs et de ton réservoir d'idées.</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            className="secondary-button"
            onClick={regenerate}
            disabled={regenerating || loading}
            title="Régénérer l'idée du jour (1 crédit)"
            style={{ padding: "0 12px" }}
          >
            {regenerating ? <Loader2 size={14} className="spinning" /> : <RefreshCw size={14} />}
            Régénérer (1 crédit)
          </button>
          <button className="secondary-button" onClick={loadAll} disabled={loading} style={{ padding: "0 12px" }}>
            {loading ? <Loader2 size={14} className="spinning" /> : <RefreshCw size={14} />}
            Rafraîchir
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 12 }}>{error}</div>}

      {ideas.length === 0 ? (
        <div className="card" style={{ padding: 28, textAlign: "center", color: "var(--muted)" }}>
          {loading ? (
            <><Loader2 size={20} className="spinning" style={{ opacity: 0.45 }} /><p>Chargement…</p></>
          ) : (
            <p style={{ margin: 0 }}>
              Pas encore d'idée générée. Active l'option ci-dessous et ajoute des idées à ton réservoir —
              la première arrivera demain matin.
            </p>
          )}
        </div>
      ) : (
        <div className="ideas-grid daily-ideas-grid">
          {ideas.map((it, idx) => {
            const idea = parseDailyIdeaMarkdown(it.idea_markdown);
            return (
              <div
                className="idea-card daily-idea-card"
                key={it.id}
                role="button"
                tabIndex={0}
                onClick={() => onReuse(idea.title)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onReuse(idea.title);
                  }
                }}
              >
                <div className="idea-header">
                  <span className="idea-funnel">{idea.funnel}</span>
                  <span className="badge">{idea.hook_type}</span>
                  {idx === 0 ? <span className="daily-today-tag">Aujourd'hui</span> : null}
                  {idea.estimated_lift && <span className="idea-lift">{idea.estimated_lift}</span>}
                </div>
                <h3 className="idea-title">{idea.title}</h3>
                {idea.hook && <p className="idea-hook">"{idea.hook}"</p>}
                {idea.angle && <p className="idea-angle">{idea.angle}</p>}
                {idea.why_it_works && <p className="idea-why"><strong>Pourquoi ça marche :</strong> {idea.why_it_works}</p>}
                <div className="idea-footer" style={{ flexWrap: "wrap", gap: 8 }}>
                  <span style={{ fontSize: 12, color: "var(--muted)", textTransform: "capitalize" }}>{fmtDate(it.idea_date)}</span>
                  <button
                    className="primary-button"
                    style={{ fontSize: 12, minHeight: 30, padding: "0 10px", marginLeft: "auto" }}
                    onClick={(e) => {
                      e.stopPropagation();
                      onReuse(idea.title);
                    }}
                  >
                    <Sparkles size={12} /> Générer ce post
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div className="card daily-reservoir" style={{ marginTop: 24 }}>
        <div className="daily-reservoir-head">
          <div>
            <h3 className="daily-subtitle" style={{ margin: 0 }}><Lightbulb size={16} /> Mon réservoir d'idées</h3>
            <p className="section-desc" style={{ margin: "4px 0 0" }}>Ajoute tes idées : l'idée du jour piochera dedans en priorité.</p>
          </div>
          <label className="daily-switch">
            <input type="checkbox" checked={enabled} onChange={toggleEnabled} />
            <span>Recevoir une idée chaque matin</span>
          </label>
        </div>

        <div className="daily-add">
          <input
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void addSeed(); } }}
            placeholder="Ex. Mon retour sur 6 mois de cold outreach…"
            maxLength={2000}
          />
          <button className="primary-button" onClick={addSeed} disabled={adding || draft.trim().length < 3}>
            {adding ? <Loader2 size={14} className="spinning" /> : <PlusCircle size={14} />} Ajouter
          </button>
        </div>

        {seeds.length === 0 ? (
          <p style={{ color: "var(--muted)", margin: "12px 0 0", fontSize: 13 }}>Réservoir vide — l'idée du jour s'appuiera sur ton seul benchmark.</p>
        ) : (
          <ul className="daily-seed-list">
            {seeds.map((s) => (
              <li key={s.id} className={s.used_at ? "used" : ""}>
                <span>{s.text}</span>
                {s.used_at ? <span className="daily-seed-tag"><CheckCircle2 size={12} /> utilisée</span> : null}
                <button className="icon-button" title="Supprimer" onClick={() => deleteSeed(s.id)}><Trash2 size={14} /></button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function LibraryView({
  isAuthed,
  requireAuth,
  onReuse,
}: {
  isAuthed: boolean;
  requireAuth: (reason?: string) => void;
  onReuse: (topic: string) => void;
}) {
  const [tab, setTab] = useState<"posts" | "ideas">("posts");
  const [posts, setPosts] = useState<SavedPost[]>([]);
  const [ideas, setIdeas] = useState<SavedIdea[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState<string | null>(null);
  const [editedPosts, setEditedPosts] = useState<Record<string, string>>({});
  const [savingPost, setSavingPost] = useState<string | null>(null);
  const [savedPost, setSavedPost] = useState<string | null>(null);
  const slack = useSlack(isAuthed);
  const linkedin = useLinkedIn(isAuthed);
  const [slackSent, setSlackSent] = useState<Record<string, boolean>>({});
  const [slackSending, setSlackSending] = useState<Record<string, boolean>>({});
  const [publishingPost, setPublishingPost] = useState<string | null>(null);
  const [publishedPost, setPublishedPost] = useState<string | null>(null);
  const [publishError, setPublishError] = useState("");

  async function publishSavedPost(p: SavedPost) {
    if (!linkedin.status?.connected) {
      setPublishError("Connecte d'abord ton compte LinkedIn dans l'onglet Profil.");
      return;
    }
    setPublishError("");
    setPublishingPost(p.id);
    try {
      const text = editedPosts[p.id] ?? p.post;
      const res = await fetch(`${DIRECT_API_URL}/me/linkedin/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ content: text, draft: false }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Publication impossible");
      setPublishedPost(p.id);
      setPosts((prev) => prev.map((pp) => pp.id === p.id ? { ...pp, slack_status: "published" } : pp));
      setTimeout(() => setPublishedPost((s) => s === p.id ? null : s), 3000);
    } catch (err: any) {
      setPublishError(err.message);
    } finally {
      setPublishingPost(null);
    }
  }

  const funnelColors: Record<string, string> = { TOFU: "#10b981", MOFU: "#f59e0b", BOFU: "#ef4444" };
  const roleLabels: Record<string, string> = {
    performance: "Performance", methodologie: "Méthodologie", autorite: "Autorité",
    story: "Story", quotidien: "Quotidien", opinion: "Opinion", relationnel: "Relationnel",
  };
  const fmtDate = (s?: string) => {
    if (!s) return "";
    try { return new Date(s).toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" }); }
    catch { return ""; }
  };

  async function loadAll() {
    if (!isAuthed) return;
    setLoading(true);
    setError("");
    try {
      const headers = await authHeaders();
      const [pRes, iRes] = await Promise.all([
        fetch(`${DIRECT_API_URL}/me/generated-posts`, { headers }),
        fetch(`${DIRECT_API_URL}/me/generated-ideas`, { headers }),
      ]);
      const pData = await pRes.json();
      const iData = await iRes.json();
      if (!pRes.ok) throw new Error(pData.detail || "Chargement des posts impossible");
      if (!iRes.ok) throw new Error(iData.detail || "Chargement des idées impossible");
      setPosts(Array.isArray(pData) ? pData : []);
      setIdeas(Array.isArray(iData) ? iData : []);
    } catch (err: any) {
      setError(err.message || "Chargement impossible");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (isAuthed) void loadAll();
    else { setPosts([]); setIdeas([]); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed]);

  function copy(text: string, id: string) {
    navigator.clipboard.writeText(text);
    setCopied(id);
    setTimeout(() => setCopied((c) => (c === id ? null : c)), 1500);
  }

  async function deletePost(id: string) {
    setPosts((prev) => prev.filter((p) => p.id !== id));
    try {
      await fetch(`${DIRECT_API_URL}/me/generated-posts/${id}`, { method: "DELETE", headers: await authHeaders() });
    } catch { void loadAll(); }
  }

  async function deleteIdea(id: string) {
    setIdeas((prev) => prev.filter((i) => i.id !== id));
    try {
      await fetch(`${DIRECT_API_URL}/me/generated-ideas/${id}`, { method: "DELETE", headers: await authHeaders() });
    } catch { void loadAll(); }
  }

  if (!isAuthed) {
    return (
      <div className="card" style={{ textAlign: "center", padding: 40 }}>
        <Bookmark size={28} style={{ opacity: 0.4, marginBottom: 12 }} />
        <h2 style={{ margin: "0 0 8px" }}>Mes contenus</h2>
        <p style={{ color: "var(--muted)", marginBottom: 16 }}>
          Connecte-toi pour retrouver les posts et idées générés et les réutiliser.
        </p>
        <button type="button" className="primary-button" onClick={() => requireAuth("Crée un compte gratuit pour retrouver tes contenus générés.")}>
          <Sparkles size={14} /> Créer un compte gratuit
        </button>
      </div>
    );
  }

  return (
    <div>
      <div className="section-header">
        <div>
          <h2 className="section-title"><Bookmark size={20} /> Mes contenus sauvegardés</h2>
          <p className="section-desc">Tes posts et idées générés sont enregistrés automatiquement. Relis-les, copie-les ou réutilise-les.</p>
        </div>
        <button className="secondary-button" onClick={loadAll} disabled={loading}>
          {loading ? <Loader2 size={14} className="spinning" /> : <RefreshCw size={14} />}
          Rafraîchir
        </button>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <button className={tab === "posts" ? "primary-button" : "secondary-button"} onClick={() => setTab("posts")}>
          <PenTool size={14} /> Posts ({posts.length})
        </button>
        <button className={tab === "ideas" ? "primary-button" : "secondary-button"} onClick={() => setTab("ideas")}>
          <Lightbulb size={14} /> Idées ({ideas.length})
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 12 }}>{error}</div>}

      {loading && posts.length === 0 && ideas.length === 0 ? (
        <div className="card" style={{ padding: 32, textAlign: "center" }}>
          <Loader2 size={22} className="spinning" style={{ opacity: 0.45 }} />
          <p style={{ color: "var(--muted)" }}>Chargement de tes contenus…</p>
        </div>
      ) : tab === "posts" ? (
        posts.length === 0 ? (
          <div className="card" style={{ padding: 32, textAlign: "center", color: "var(--muted)" }}>
            Aucun post sauvegardé pour l'instant. Génère des posts dans l'onglet « Générateur de posts ».
          </div>
        ) : (
          <div className="variants-list">
            {posts.map((p) => (
              <div className="variant-card" key={p.id}>
                <div className="variant-header" style={{ flexWrap: "wrap" }}>
                  {p.editorial_role && (
                    <span className="badge role-badge">{roleLabels[p.editorial_role] || p.editorial_role}</span>
                  )}
                  {p.hook_type && <span className="badge">{p.hook_type}</span>}
                  {p.predicted_lift && <span className="idea-lift">{p.predicted_lift}</span>}
                  {p.slack_status === "validated" && (
                    <span className="badge" style={{ borderColor: "#10b981", color: "#10b981" }}>✅ Validé Slack</span>
                  )}
                  <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--muted)" }}>{fmtDate(p.created_at)}</span>
                </div>
                {p.topic && <p className="variant-strategy"><strong>Sujet :</strong> {p.topic}</p>}
                <div className="variant-text-wrap">
                  <textarea
                    className="variant-text"
                    value={editedPosts[p.id] ?? p.post}
                    rows={12}
                    onChange={(e) => setEditedPosts((prev) => ({ ...prev, [p.id]: e.target.value }))}
                  />
                  <button
                    type="button"
                    className="variant-copy-button"
                    aria-label={copied === p.id ? "Post copié" : "Copier le post"}
                    title={copied === p.id ? "Copié ✓" : "Copier le post"}
                    onClick={() => copy(editedPosts[p.id] ?? p.post, p.id)}
                  >
                    {copied === p.id ? <CheckCircle2 size={16} /> : <Copy size={16} />}
                  </button>
                </div>
                {editedPosts[p.id] !== undefined && editedPosts[p.id] !== p.post && (
                  <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 4, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 12, color: "var(--muted)" }}>✏️ Modifié</span>
                    <button
                      className="secondary-button"
                      style={{ fontSize: 12, minHeight: 28, padding: "0 10px" }}
                      onClick={() => setEditedPosts((prev) => { const n = { ...prev }; delete n[p.id]; return n; })}
                    >
                      Revenir à l&apos;original
                    </button>
                    <button
                      className="primary-button"
                      style={{ fontSize: 12, minHeight: 28, padding: "0 10px" }}
                      disabled={savingPost === p.id}
                      onClick={async () => {
                        setSavingPost(p.id);
                        try {
                          const res = await fetch(`${DIRECT_API_URL}/me/generated-posts/${p.id}`, {
                            method: "PUT",
                            headers: { "Content-Type": "application/json", ...(await authHeaders()) },
                            body: JSON.stringify({ post: editedPosts[p.id] }),
                          });
                          if (res.ok) {
                            setPosts((prev) => prev.map((pp) => pp.id === p.id ? { ...pp, post: editedPosts[p.id] } : pp));
                            setEditedPosts((prev) => { const n = { ...prev }; delete n[p.id]; return n; });
                            setSavedPost(p.id);
                            setTimeout(() => setSavedPost((s) => s === p.id ? null : s), 1500);
                          }
                        } finally { setSavingPost(null); }
                      }}
                    >
                      {savingPost === p.id ? "Sauvegarde…" : savedPost === p.id ? "Sauvegardé ✓" : "Sauvegarder"}
                    </button>
                  </div>
                )}
                <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
                  {p.topic && (
                    <button className="secondary-button" onClick={() => onReuse(p.topic!)}>
                      <Sparkles size={14} /> Régénérer sur ce sujet
                    </button>
                  )}
                  {p.slack_status === "validated" && (
                    <button
                      className="primary-button"
                      disabled={publishingPost === p.id}
                      onClick={() => publishSavedPost(p)}
                    >
                      {publishingPost === p.id ? <><Loader2 size={14} className="spinning" /> Publication…</> : <><Linkedin size={14} /> Publier sur LinkedIn</>}
                      {publishedPost === p.id && " ✓"}
                    </button>
                  )}
                  {slack.status?.connected && p.slack_status !== "validated" && (
                    <button
                      className="secondary-button"
                      disabled={!!slackSending[p.id] || !!slackSent[p.id] || p.slack_status === "pending"}
                      onClick={async () => {
                        setSlackSending((prev) => ({ ...prev, [p.id]: true }));
                        try {
                          await fetch(`${DIRECT_API_URL}/me/integrations/slack/send-posts`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json", ...(await authHeaders()) },
                            body: JSON.stringify({ post_id: p.id }),
                          });
                          setSlackSent((prev) => ({ ...prev, [p.id]: true }));
                          setPosts((prev) => prev.map((pp) => pp.id === p.id ? { ...pp, slack_status: "pending" } : pp));
                        } finally {
                          setSlackSending((prev) => ({ ...prev, [p.id]: false }));
                        }
                      }}
                    >
                      {slackSending[p.id] ? <Loader2 size={14} className="spinning" /> : null}
                      {slackSent[p.id] || p.slack_status === "pending" ? "Sur Slack ✓" : "Envoyer sur Slack"}
                    </button>
                  )}
                  <button className="secondary-button" style={{ marginLeft: "auto" }} onClick={() => deletePost(p.id)}>
                    <Trash2 size={14} /> Supprimer
                  </button>
                </div>
                {publishError && publishingPost === null && publishedPost === null && (
                  <div className="error" style={{ marginTop: 6, fontSize: 13 }}>{publishError}</div>
                )}
              </div>
            ))}
          </div>
        )
      ) : ideas.length === 0 ? (
        <div className="card" style={{ padding: 32, textAlign: "center", color: "var(--muted)" }}>
          Aucune idée sauvegardée pour l'instant. Génère des idées dans l'onglet « Générateur de posts ».
        </div>
      ) : (
        <div className="ideas-grid">
          {ideas.map((idea) => (
            <div className="idea-card" key={idea.id}>
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
              {idea.why_it_works && <p className="idea-why"><strong>Pourquoi ça marche :</strong> {idea.why_it_works}</p>}
              <div className="idea-footer" style={{ flexWrap: "wrap", gap: 8 }}>
                <span style={{ fontSize: 12, color: "var(--muted)" }}>{fmtDate(idea.created_at)}</span>
                <div style={{ display: "flex", gap: 8, marginLeft: "auto", flexWrap: "wrap" }}>
                  <button
                    type="button"
                    className="compact-copy-button"
                    aria-label={copied === idea.id ? "Accroche copiée" : "Copier l'accroche"}
                    title={copied === idea.id ? "Copié ✓" : "Copier l'accroche"}
                    onClick={() => copy(idea.hook, idea.id)}
                  >
                    {copied === idea.id ? <CheckCircle2 size={14} /> : <Copy size={14} />}
                  </button>
                  {slack.status?.connected && (
                    <button
                      className="secondary-button"
                      style={{ fontSize: 12, minHeight: 30, padding: "0 10px" }}
                      disabled={!!slackSending[idea.id] || !!slackSent[idea.id]}
                      onClick={async () => {
                        setSlackSending((p) => ({ ...p, [idea.id]: true }));
                        try {
                          await fetch(`${DIRECT_API_URL}/me/integrations/slack/send-ideas`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json", ...(await authHeaders()) },
                            body: JSON.stringify({ idea_ids: [idea.id] }),
                          });
                          setSlackSent((p) => ({ ...p, [idea.id]: true }));
                          setIdeas((prev) => prev.map((i) => i.id === idea.id ? { ...i, slack_status: "pending" } : i));
                        } finally {
                          setSlackSending((p) => ({ ...p, [idea.id]: false }));
                        }
                      }}
                    >
                      {slackSending[idea.id] ? <Loader2 size={12} className="spinning" /> : null}
                      {slackSent[idea.id] || idea.slack_status === "pending" ? "Sur Slack ✓" : "Valider sur Slack"}
                    </button>
                  )}
                  <button className="primary-button" style={{ fontSize: 12, minHeight: 30, padding: "0 10px" }} onClick={() => onReuse(idea.title)}>
                    <Sparkles size={12} /> Générer ce post
                  </button>
                  <button className="secondary-button" style={{ fontSize: 12, minHeight: 30, padding: "0 10px" }} onClick={() => deleteIdea(idea.id)}>
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Assistant({ isAuthed, requireAuth }: { isAuthed: boolean; requireAuth: (reason?: string) => void }) {
  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef<HTMLDivElement | null>(null);

  const quickActions = [
    "Donne-moi 5 idées de posts adaptées à mon profil.",
    "Propose un angle performance sur : ",
    "Transforme ce brouillon en post LinkedIn percutant : ",
    "Améliore le hook et la structure de ce post : ",
  ];

  async function loadMessages(conversationId: string) {
    setLoadingHistory(true);
    setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/chat/conversations/${conversationId}/messages`, {
        headers: await authHeaders(),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Conversation introuvable");
      setActiveConversationId(conversationId);
      setMessages(data.messages || []);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoadingHistory(false);
    }
  }

  async function loadConversations(selectFirst = true) {
    if (!isAuthed) return;
    setLoadingHistory(true);
    try {
      const res = await fetch(`${DIRECT_API_URL}/chat/conversations`, {
        headers: await authHeaders(),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Chargement des conversations impossible");
      const list = Array.isArray(data) ? data : [];
      setConversations(list);
      if (selectFirst && list.length && !activeConversationId) {
        await loadMessages(list[0].id);
      }
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoadingHistory(false);
    }
  }

  useEffect(() => {
    if (!isAuthed) {
      setConversations([]);
      setActiveConversationId(null);
      setMessages([]);
      return;
    }
    loadConversations(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, streaming]);

  function newConversation() {
    setActiveConversationId(null);
    setMessages([]);
    setError("");
    setInput("");
  }

  function appendAssistant(delta: string) {
    setMessages((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (!last || last.role !== "assistant") {
        next.push({ role: "assistant", content: delta });
      } else {
        next[next.length - 1] = { ...last, content: last.content + delta };
      }
      return next;
    });
  }

  function handleSseEvent(raw: string) {
    const lines = raw.split("\n");
    let event = "message";
    const dataLines: string[] = [];
    for (const line of lines) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    if (!dataLines.length) return;
    const data = JSON.parse(dataLines.join("\n"));
    if (event === "meta" && data.conversation_id) {
      setActiveConversationId(data.conversation_id);
      emitCredits(data.credits);
    } else if (event === "delta") {
      appendAssistant(data.text || "");
    } else if (event === "error") {
      setError(data.detail || "Réponse interrompue.");
    }
  }

  async function sendMessage(text?: string) {
    if (!isAuthed) { requireAuth("Connecte-toi pour utiliser l'assistant."); return; }
    const content = (text ?? input).trim();
    if (!content || streaming) return;

    setError("");
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content }, { role: "assistant", content: "" }]);
    setStreaming(true);
    try {
      const res = await fetch(`${DIRECT_API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ conversation_id: activeConversationId, message: content }),
      });
      if (!res.ok || !res.body) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Assistant indisponible.");
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() || "";
        for (const chunk of chunks) {
          if (chunk.trim()) handleSseEvent(chunk);
        }
      }
      if (buffer.trim()) handleSseEvent(buffer);
      await loadConversations(false);
    } catch (err: any) {
      setError(err.message || "Assistant indisponible.");
    } finally {
      setStreaming(false);
    }
  }

  if (!isAuthed) {
    return (
      <LockedCard
        title="Assistant conversationnel"
        subtitle="Connecte-toi pour garder l'historique et utiliser ton contexte éditorial."
        onUnlock={() => requireAuth("Crée un compte gratuit pour discuter avec l'assistant.")}
      />
    );
  }

  return (
    <div className="assistant-layout">
      <aside className="assistant-sidebar card">
        <div className="assistant-sidebar-header">
          <p className="eyebrow">Conversations</p>
          <button className="ghost-button" onClick={newConversation} title="Nouvelle conversation">
            <PlusCircle size={14} /> Nouveau
          </button>
        </div>
        <div className="assistant-conversation-list">
          {conversations.length ? conversations.map((conv) => (
            <button
              key={conv.id}
              className={`assistant-conversation ${activeConversationId === conv.id ? "active" : ""}`}
              onClick={() => loadMessages(conv.id)}
            >
              <strong>{conv.title}</strong>
              <span>{new Date(conv.updated_at).toLocaleDateString("fr-FR")}</span>
            </button>
          )) : (
            <p className="assistant-empty">Aucune conversation enregistrée.</p>
          )}
        </div>
      </aside>

      <section className="assistant-panel card">
        <div className="section-header">
          <div>
            <h2 className="section-title"><MessageSquare size={20} /> Assistant LinkedIn</h2>
            <p className="section-desc">Itère sur tes idées et brouillons avec mémoire, contexte client et benchmark influenceurs.</p>
          </div>
          {loadingHistory ? <Loader2 size={16} className="spinning" /> : null}
        </div>

        <div className="assistant-quick-actions">
          {quickActions.map((action) => (
            <button key={action} className="secondary-button" onClick={() => setInput(action)}>
              {action}
            </button>
          ))}
        </div>

        {error && <div className="error">{error}</div>}

        <div className="assistant-messages">
          {!messages.length ? (
            <div className="assistant-welcome">
              <Sparkles size={22} />
              <h3>Demande une idée, un angle ou une réécriture.</h3>
              <p>Exemple : "Écris un post opinion sur les erreurs d'automatisation LinkedIn pour des dirigeants B2B."</p>
            </div>
          ) : messages.map((message, i) => (
            <div key={`${message.id || i}-${message.role}`} className={`assistant-message ${message.role}`}>
              <div className="assistant-message-role">
                {message.role === "user" ? "Toi" : "Assistant"}
              </div>
              <div className="assistant-message-content">
                {message.role === "assistant"
                  ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content || (streaming ? "..." : "")}</ReactMarkdown>
                  : <p>{message.content}</p>}
              </div>
            </div>
          ))}
          <div ref={endRef} />
        </div>

        <div className="assistant-composer">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Écris ta demande : idée, brouillon à améliorer, angle, ton..."
            rows={3}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === "Enter") sendMessage();
            }}
          />
          <button className="primary-button" disabled={streaming || !input.trim()} onClick={() => sendMessage()}>
            {streaming ? <Loader2 size={14} className="spinning" /> : <Send size={14} />}
            {streaming ? "Réponse..." : "Envoyer"}
          </button>
        </div>
        <p className="role-picker-hint" style={{ marginTop: 8 }}>Astuce : Cmd/Ctrl + Entrée pour envoyer.</p>
      </section>
    </div>
  );
}

const EMPTY_EDITORIAL_PROFILE: EditorialProfile = {
  display_name: "",
  brand_name: "",
  industry: "",
  business_description: "",
  location: "",
  target_audience: "",
  core_offer: "",
  tone: "",
  linkedin_objective: "",
  topics_to_cover: "",
  topics_to_avoid: "",
  constraints: "",
  website_url: "",
  linkedin_url: "",
  language: "français",
  market: "",
  extra_context: "",
};

function ProfileView({
  isAuthed,
  requireAuth,
}: {
  isAuthed: boolean;
  requireAuth: (reason?: string, mode?: AuthMode) => void;
}) {
  const [profile, setProfile] = useState<EditorialProfile>(EMPTY_EDITORIAL_PROFILE);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [aiInput, setAiInput] = useState("");
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [draftInfo, setDraftInfo] = useState("");
  const linkedin = useLinkedIn(isAuthed);
  const twitter = useTwitter(isAuthed);
  const slack = useSlack(isAuthed);
  const [scheduledPosts, setScheduledPosts] = useState<Array<{ id: string; post_text: string; scheduled_at: string; status: string; error_message?: string }>>([]);
  const [cancellingPost, setCancellingPost] = useState<string | null>(null);

  useEffect(() => {
    if (!isAuthed || !linkedin.status?.connected) return;
    let cancelled = false;
    authHeaders().then((h) =>
      fetch(`${DIRECT_API_URL}/me/linkedin/scheduled`, { headers: h })
        .then((r) => r.ok ? r.json() : [])
        .then((data) => { if (!cancelled) setScheduledPosts(data); })
        .catch(() => {})
    );
    return () => { cancelled = true; };
  }, [isAuthed, linkedin.status?.connected]);

  async function cancelScheduled(postId: string) {
    setCancellingPost(postId);
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/linkedin/scheduled/${postId}`, {
        method: "DELETE",
        headers: await authHeaders(),
      });
      if (res.ok) setScheduledPosts((prev) => prev.map((p) => p.id === postId ? { ...p, status: "cancelled" } : p));
    } catch (_) {} finally {
      setCancellingPost(null);
    }
  }

  // `Field` lit toujours la dernière valeur du profil via cette ref, ce qui
  // permet de garder une identité de composant stable (useCallback ci-dessous)
  // sans capturer un `profile` périmé.
  const profileRef = useRef(profile);
  profileRef.current = profile;

  useEffect(() => {
    if (!isAuthed) {
      setProfile(EMPTY_EDITORIAL_PROFILE);
      return;
    }
    setLoading(true);
    setError("");
    (async () => {
      try {
        const res = await fetch(`${DIRECT_API_URL}/me/profile`, { headers: await authHeaders() });
        const data = await res.json();
        if (res.status === 404) {
          setProfile(EMPTY_EDITORIAL_PROFILE);
          return;
        }
        if (!res.ok) throw new Error(data.detail || "Impossible de charger le profil");
        setProfile({ ...EMPTY_EDITORIAL_PROFILE, ...(data || {}) });
      } catch (err: any) {
        setError(err.message || "Impossible de charger le profil");
      } finally {
        setLoading(false);
      }
    })();
  }, [isAuthed]);

  function updateField(key: keyof EditorialProfile, value: string) {
    setSaved(false);
    setProfile((prev) => ({ ...prev, [key]: value }));
  }

  async function saveProfile() {
    if (!isAuthed) {
      requireAuth("Crée un compte gratuit pour enregistrer ton contexte éditorial.");
      return;
    }
    setSaving(true);
    setSaved(false);
    setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify(profile),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Sauvegarde impossible");
      setProfile({ ...EMPTY_EDITORIAL_PROFILE, ...(data || {}) });
      setSaved(true);
    } catch (err: any) {
      setError(err.message || "Sauvegarde impossible");
    } finally {
      setSaving(false);
    }
  }

  async function draftProfile() {
    if (!isAuthed) {
      requireAuth("Crée un compte gratuit pour pré-remplir ton contexte éditorial avec l'IA.");
      return;
    }
    const trimmed = aiInput.trim();
    if (!trimmed) {
      setError("Colle une description, une URL LinkedIn ou un site web pour pré-remplir le profil.");
      return;
    }
    // Une seule barre : on devine ce qui a été collé et on le route vers le bon champ.
    const isLinkedin = aiInputKind === "linkedin";
    const isWebsite = aiInputKind === "website";
    setDrafting(true);
    setSaved(false);
    setDraftInfo("");
    setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/profile/draft`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({
          activity_description: isLinkedin || isWebsite ? "" : trimmed,
          linkedin_url: isLinkedin ? trimmed : "",
          website_url: isWebsite ? trimmed : "",
          use_apify_linkedin: isLinkedin, // toujours lire le LinkedIn via Apify
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Pré-remplissage impossible");
      const merged = { ...profile, ...(data.profile || {}) };
      setProfile(merged);
      setDetailsOpen(true); // ouvre le tiroir pour relire les champs pré-remplis
      const sources = data.sources || {};
      const sourceLabels = [
        sources.description ? "description" : "",
        sources.linkedin_analyzed ? "profil LinkedIn analysé" : "",
        sources.linkedin_apify ? "LinkedIn via Apify" : "",
        sources.website_summary ? "site web" : "",
      ].filter(Boolean);
      // Auto-sauvegarde : on persiste tout de suite le profil généré en base.
      const saveRes = await fetch(`${DIRECT_API_URL}/me/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify(merged),
      });
      const saveData = await saveRes.json();
      if (!saveRes.ok) throw new Error(saveData.detail || "Sauvegarde du profil généré impossible");
      setProfile({ ...EMPTY_EDITORIAL_PROFILE, ...(saveData || {}) });
      setSaved(true);
      setDraftInfo(
        sourceLabels.length
          ? `Profil généré depuis : ${sourceLabels.join(", ")} et enregistré. Relis et ajuste si besoin.`
          : "Profil généré et enregistré. Relis et ajuste si besoin."
      );
    } catch (err: any) {
      setError(err.message || "Pré-remplissage impossible");
    } finally {
      setDrafting(false);
    }
  }

  // Défini une seule fois (deps []) → React conserve le même <input> entre les
  // rendus au lieu de le démonter/remonter à chaque frappe (sinon l'input perd
  // le focus et on ne peut taper qu'une lettre à la fois).
  const Field = useCallback(function Field({
    name,
    label,
    placeholder,
    multiline,
  }: {
    name: keyof EditorialProfile;
    label: string;
    placeholder?: string;
    multiline?: boolean;
  }) {
    const value = String(profileRef.current[name] || "");
    return (
      <label className="profile-field">
        <span>{label}</span>
        {multiline ? (
          <textarea
            value={value}
            onChange={(e) => updateField(name, e.target.value)}
            placeholder={placeholder}
            rows={4}
          />
        ) : (
          <input
            value={value}
            onChange={(e) => updateField(name, e.target.value)}
            placeholder={placeholder}
          />
        )}
      </label>
    );
  }, []);

  const filledCount = Object.entries(profile)
    .filter(([key, value]) => key !== "id" && typeof value === "string" && value.trim().length > 0)
    .length;

  // Devine la nature du texte collé dans la barre unique de pré-remplissage.
  const aiInputKind: "linkedin" | "website" | "description" = (() => {
    const v = aiInput.trim();
    if (!v || /\s/.test(v)) return "description"; // contient un espace → c'est une phrase
    if (/linkedin\.com\/in\//i.test(v)) return "linkedin";
    if (/^https?:\/\//i.test(v) || /^www\./i.test(v) || /^[\w-]+(\.[\w-]+)+(\/|$)/i.test(v)) return "website";
    return "description";
  })();

  if (!isAuthed) {
    return (
      <div className="card" style={{ textAlign: "center", padding: 40 }}>
        <Lock size={28} style={{ opacity: 0.4, marginBottom: 12 }} />
        <h2 style={{ margin: "0 0 8px" }}>Contexte éditorial</h2>
        <p style={{ color: "var(--muted)", marginBottom: 16 }}>
          Connecte-toi pour renseigner le profil client que Claude utilisera dans les idées et les posts.
        </p>
        <button type="button" className="primary-button" onClick={() => requireAuth("Crée un compte gratuit pour enregistrer ton contexte éditorial.")}>
          <Sparkles size={14} /> Créer un compte gratuit
        </button>
      </div>
    );
  }

  return (
    <div>
      <div className="section-header">
        <div>
          <h2 className="section-title"><UserRound size={20} /> Contexte éditorial</h2>
          <p className="section-desc">
            Décris le client qui publie. Ce contexte est injecté dans les prompts `/ideas` et `/generate`.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span className={`status-pill ${filledCount >= 6 ? "ok" : ""}`}>{filledCount} champs remplis</span>
          <button className="primary-button" onClick={saveProfile} disabled={saving || loading}>
            {saving ? <Loader2 size={14} className="spinning" /> : <CheckCircle2 size={14} />}
            {saving ? "Sauvegarde…" : "Sauvegarder"}
          </button>
        </div>
      </div>

      <section className="card" style={{ marginBottom: 16, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Linkedin size={20} color="#0a66c2" />
          <div>
            <strong>Publier sur LinkedIn</strong>
            <p className="section-desc" style={{ margin: 0 }}>
              {linkedin.status?.connected
                ? "Compte LinkedIn connecté — tes posts générés peuvent être publiés directement sur LinkedIn en un clic."
                : "Connecte ton compte LinkedIn pour publier tes posts générés directement sur LinkedIn, sans copier-coller."}
            </p>
          </div>
        </div>
        {linkedin.status?.connected ? (
          <span className="status-pill ok"><CheckCircle2 size={14} /> Connecté</span>
        ) : (
          <button className="primary-button" onClick={linkedin.connect} disabled={linkedin.busy}>
            {linkedin.busy ? <Loader2 size={14} className="spinning" /> : <Linkedin size={14} />}
            {linkedin.busy ? "Redirection…" : "Connecter LinkedIn"}
          </button>
        )}
      </section>
      {linkedin.error ? <div className="error" style={{ marginBottom: 12 }}>{linkedin.error}</div> : null}

      {linkedin.status?.connected && scheduledPosts.length > 0 && (
        <section className="card" style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
            <Clock3 size={16} />
            <strong>Posts programmés</strong>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {scheduledPosts.map((p) => (
              <div key={p.id} style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "10px 12px", background: "var(--surface)", borderRadius: 8, border: "1px solid var(--border)" }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ margin: "0 0 4px", fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.post_text.slice(0, 120)}{p.post_text.length > 120 ? "…" : ""}</p>
                  <p style={{ margin: 0, fontSize: 12, color: "var(--muted)" }}>
                    {new Date(p.scheduled_at).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" })}
                    {" — "}
                    <span style={{ color: p.status === "published" ? "var(--success, #38a169)" : p.status === "failed" ? "var(--error, #e53e3e)" : p.status === "cancelled" ? "var(--muted)" : "var(--accent)" }}>
                      {p.status === "pending" ? "En attente" : p.status === "published" ? "Publié ✓" : p.status === "failed" ? "Échec" : "Annulé"}
                    </span>
                  </p>
                  {p.status === "failed" && p.error_message && <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--error, #e53e3e)" }}>{p.error_message}</p>}
                </div>
                {p.status === "pending" && (
                  <button className="secondary-button" style={{ fontSize: 12, minHeight: 28, padding: "0 10px", flexShrink: 0 }} disabled={cancellingPost === p.id} onClick={() => cancelScheduled(p.id)}>
                    {cancellingPost === p.id ? <Loader2 size={12} className="spinning" /> : <Trash2 size={12} />}
                  </button>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="card" style={{ marginBottom: 16, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" style={{ flexShrink: 0 }}><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.742l7.734-8.842L1.254 2.25H8.08l4.253 5.622L18.244 2.25zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
          <div>
            <strong>Publier sur X (Twitter)</strong>
            <p className="section-desc" style={{ margin: 0 }}>
              {twitter.status?.connected
                ? "Compte X connecté — publie tes posts directement sur X en un clic."
                : "Connecte ton compte X pour cross-poster tes posts générés sur X (Twitter)."}
            </p>
          </div>
        </div>
        {twitter.status?.connected ? (
          <span className="status-pill ok"><CheckCircle2 size={14} /> Connecté</span>
        ) : (
          <button className="primary-button" onClick={twitter.connect} disabled={twitter.busy}>
            {twitter.busy ? <Loader2 size={14} className="spinning" /> : <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.742l7.734-8.842L1.254 2.25H8.08l4.253 5.622L18.244 2.25zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>}
            {twitter.busy ? "Redirection…" : "Connecter X"}
          </button>
        )}
      </section>
      {twitter.error ? <div className="error" style={{ marginBottom: 12 }}>{twitter.error}</div> : null}

      <section className="card" style={{ marginBottom: 16, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <svg width="20" height="20" viewBox="0 0 122.8 122.8" style={{ flexShrink: 0 }}><path d="M25.8 77.6h14.9V51.2H25.8v26.4zm7.5-36.3a8.6 8.6 0 100-17.3 8.6 8.6 0 000 17.3zm53 36.3h14.9V61.4c0-13-7-19.1-16.3-19.1-7.5 0-11 4.2-12.9 7.1V51.2H57.1c.2-4.1 0-43.6 0-43.6H72v6.3c2-3 5.5-7.4 13.4-7.4 9.8 0 17.2 6.4 17.2 20.3v26.4-.1zm0 0" fill="none"/><path d="M0 11.1C0 5 5.1 0 11.3 0h100.2c6.2 0 11.3 5 11.3 11.1v100.6c0 6.1-5.1 11.1-11.3 11.1H11.3C5.1 122.8 0 117.8 0 111.7V11.1zm32.2 12.4a8.6 8.6 0 10.1 17.2 8.6 8.6 0 00-.1-17.2zM25.8 77.6h14.9V51.2H25.8v26.4zm36.1 0h14.9V61.4c0-13-7-19.1-16.3-19.1-7.5 0-11 4.2-12.9 7.1V51.2H57.1c.2-4.1 0-43.6 0-43.6H72v6.3c2-3 5.5-7.4 13.4-7.4 9.8 0 17.2 6.4 17.2 20.3v26.4H61.9z" fill="#4A154B"/></svg>
          <div>
            <strong>Valider les idées sur Slack</strong>
            <p className="section-desc" style={{ margin: 0 }}>
              {slack.status?.connected
                ? `Workspace connecté : ${slack.status.team_name || "Slack"} — envoie tes idées générées sur Slack avec boutons ✅ / ❌.`
                : !slack.status?.configured
                  ? "Intégration Slack non configurée sur le serveur (SLACK_CLIENT_ID manquant)."
                  : "Connecte Slack pour valider tes idées de posts directement depuis ton téléphone."}
            </p>
          </div>
        </div>
        {slack.status?.connected ? (
          <button className="secondary-button" onClick={slack.disconnect} disabled={slack.busy} style={{ fontSize: 12 }}>
            {slack.busy ? <Loader2 size={14} className="spinning" /> : null}
            Déconnecter
          </button>
        ) : slack.status?.configured ? (
          <button className="primary-button" onClick={slack.connect} disabled={slack.busy}>
            {slack.busy ? <Loader2 size={14} className="spinning" /> : null}
            {slack.busy ? "Redirection…" : "Connecter Slack"}
          </button>
        ) : null}
      </section>
      {slack.error ? <div className="error" style={{ marginBottom: 12 }}>{slack.error}</div> : null}

      {error ? <div className="error" style={{ marginBottom: 12 }}>{error}</div> : null}
      {draftInfo ? <div className="auth-info" style={{ marginBottom: 12 }}>{draftInfo}</div> : null}
      {saved ? <div className="auth-info" style={{ marginBottom: 12 }}>Profil éditorial sauvegardé. Les prochaines générations utiliseront ce contexte.</div> : null}
      {loading ? (
        <div className="card" style={{ padding: 32, textAlign: "center" }}>
          <Loader2 size={22} className="spinning" style={{ opacity: 0.45 }} />
          <p style={{ color: "var(--muted)" }}>Chargement du profil…</p>
        </div>
      ) : (
        <div className="profile-form">
          <section className="card profile-ai-card">
            <div className="section-header" style={{ marginBottom: 10 }}>
              <div>
                <h3 style={{ margin: "0 0 4px" }}>Pré-remplir avec l'IA</h3>
                <p className="section-desc">
                  Colle une description, une URL LinkedIn ou un site web — l'IA devine et remplit le profil.
                </p>
              </div>
            </div>
            <div className="profile-ai-bar">
              <input
                value={aiInput}
                onChange={(e) => setAiInput(e.target.value)}
                placeholder="Description, URL LinkedIn ou site web…"
                onKeyDown={(e) => { if (e.key === "Enter" && !drafting) draftProfile(); }}
              />
              <button className="primary-button" onClick={draftProfile} disabled={drafting}>
                {drafting ? <Loader2 size={14} className="spinning" /> : <Sparkles size={14} />}
                {drafting ? "Pré-remplissage…" : "Pré-remplir"}
              </button>
            </div>
          </section>

          <details className="profile-drawer" open={detailsOpen} onToggle={(e) => setDetailsOpen((e.target as HTMLDetailsElement).open)}>
            <summary>
              <span><Settings2 size={15} /> Détails du profil éditorial</span>
              <span className="profile-drawer-meta">{filledCount} champs remplis</span>
            </summary>
            <div className="profile-drawer-body">
          <section className="card">
            <h3>Identité & activité</h3>
            <div className="profile-grid">
              <Field name="display_name" label="Nom public" placeholder="Marc Delcourt" />
              <Field name="brand_name" label="Marque / société" placeholder="ScaleOps Studio" />
              <Field name="industry" label="Secteur / niche" placeholder="Automatisation IA pour dirigeants de PME" />
              <Field name="location" label="Localisation" placeholder="Paris" />
              <Field name="market" label="Marché" placeholder="Entrepreneurs B2B en forte croissance" />
              <Field name="language" label="Langue" placeholder="français" />
            </div>
            <Field
              name="business_description"
              label="Description courte de l'activité"
              placeholder="J'aide les dirigeants qui grandissent vite à structurer leur acquisition sans passer 2 heures par jour sur LinkedIn."
              multiline
            />
          </section>

          <section className="card">
            <h3>Positionnement éditorial</h3>
            <div className="profile-grid">
              <Field name="tone" label="Ton souhaité" placeholder="Direct, lucide, utile, ambitieux sans être agressif" />
              <Field name="core_offer" label="Offre / expertise" placeholder="Systèmes IA et routines LinkedIn sobres pour fondateurs occupés" />
            </div>
            <Field name="target_audience" label="Audience cible" placeholder="Fondateurs, consultants experts et dirigeants B2B déjà tractionnés, mais débordés par le contenu." multiline />
            <Field name="linkedin_objective" label="Objectif LinkedIn" placeholder="Publier régulièrement, créer de la confiance et générer des conversations qualifiées avec moins de temps passé à écrire." multiline />
          </section>

          <section className="card">
            <h3>Sujets & contraintes</h3>
            <Field name="topics_to_cover" label="Sujets à couvrir" placeholder="Croissance, délégation, IA concrète, routines de publication, arbitrages de fondateur, systèmes simples." multiline />
            <Field name="topics_to_avoid" label="Sujets à éviter" placeholder="Hype IA vide, promesses de revenus, hacks LinkedIn agressifs, ton gourou." multiline />
            <Field name="constraints" label="Contraintes de style" placeholder="Pas de threadbait. Pas de CTA commentaire forcé. Montrer qu'on peut être régulier sans devenir créateur à plein temps." multiline />
            <Field name="extra_context" label="Contexte additionnel" placeholder="Tout ce que Claude doit savoir pour mieux écrire au nom du client." multiline />
          </section>

          <section className="card">
            <h3>Liens</h3>
            <div className="profile-grid">
              <Field name="website_url" label="Site web" placeholder="https://..." />
              <Field name="linkedin_url" label="Profil LinkedIn" placeholder="https://www.linkedin.com/in/..." />
            </div>
          </section>
            </div>
          </details>
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
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{aiAnalysis}</ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}

function InfluencersView({
  entries,
  loading,
  isAuthed,
  requireAuth,
  onOpenReport,
}: {
  entries: InfluencerLibraryEntry[];
  loading: boolean;
  isAuthed: boolean;
  requireAuth: (reason?: string, mode?: AuthMode) => void;
  onOpenReport: (entry: InfluencerLibraryEntry) => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"date" | "name">("date");
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [error, setError] = useState("");

  if (!isAuthed) {
    return (
      <div className="card" style={{ textAlign: "center", padding: 40 }}>
        <Lock size={28} style={{ opacity: 0.4, marginBottom: 12 }} />
        <h2 style={{ margin: "0 0 8px" }}>Mes influenceurs</h2>
        <p style={{ color: "var(--muted)", marginBottom: 16 }}>
          Connecte-toi pour retrouver tous tes profils analysés et leurs rapports.
        </p>
        <button type="button" className="primary-button" onClick={() => requireAuth("Crée un compte gratuit pour voir tes influenceurs analysés.")}>
          <Sparkles size={14} /> Créer un compte gratuit
        </button>
      </div>
    );
  }

  const q = query.trim().toLowerCase();
  const filtered = entries
    .filter((e) => {
      if (!q) return true;
      return (
        e.name.toLowerCase().includes(q)
        || e.handle.toLowerCase().includes(q)
        || e.headline.toLowerCase().includes(q)
      );
    })
    .sort((a, b) => {
      if (sort === "name") return a.name.localeCompare(b.name, "fr");
      return (b.analyzed_at || 0) - (a.analyzed_at || 0);
    });

  async function open(entry: InfluencerLibraryEntry) {
    setError("");
    setOpeningId(entry.analysis_id);
    try {
      await onOpenReport(entry);
    } catch (err: any) {
      setError(err.message || "Impossible d'ouvrir le rapport");
    } finally {
      setOpeningId(null);
    }
  }

  return (
    <div>
      <div className="section-header" style={{ marginBottom: 16 }}>
        <div>
          <h2 className="section-title"><Users size={20} /> Mes influenceurs</h2>
          <p className="section-desc">
            Tous tes profils analysés — une ligne par influenceur, avec la dernière analyse à date.
          </p>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16, display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        <input
          type="search"
          className="url-input"
          style={{ flex: "1 1 220px", minHeight: 40, padding: "8px 12px" }}
          placeholder="Rechercher par nom, handle ou headline…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <label className="control" style={{ margin: 0 }}>
          <span>Trier par</span>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as "date" | "name")}
            style={{ marginLeft: 8, padding: "6px 10px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--surface)" }}
          >
            <option value="date">Date d'analyse</option>
            <option value="name">Nom</option>
          </select>
        </label>
        <span style={{ fontSize: 13, color: "var(--muted)" }}>
          {filtered.length} profil{filtered.length > 1 ? "s" : ""}
        </span>
      </div>

      {error && <div className="error" style={{ marginBottom: 12 }}>{error}</div>}

      {loading ? (
        <div className="card" style={{ textAlign: "center", padding: 32 }}>
          <Loader2 size={24} className="spinning" style={{ opacity: 0.5 }} />
          <p style={{ marginTop: 12, color: "var(--muted)" }}>Chargement de tes influenceurs…</p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="card" style={{ textAlign: "center", padding: 32 }}>
          <FileText size={24} style={{ opacity: 0.35, marginBottom: 8 }} />
          <p style={{ margin: 0, color: "var(--muted)" }}>
            {entries.length === 0
              ? "Aucun profil analysé pour l'instant. Lance une série dans l'onglet Analyser."
              : "Aucun profil ne correspond à ta recherche."}
          </p>
        </div>
      ) : (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ overflowX: "auto" }}>
            <table className="dash-table">
              <thead>
                <tr>
                  <th>Influenceur</th>
                  <th>Handle</th>
                  <th>Abonnés</th>
                  <th>Dernière analyse</th>
                  <th>Profil</th>
                  <th>Rapport</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((entry) => (
                  <tr key={entry.influencer_id}>
                    <td>
                      <strong>{entry.name}</strong>
                      {entry.headline ? (
                        <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2, maxWidth: 280 }}>
                          {entry.headline.slice(0, 80)}{entry.headline.length > 80 ? "…" : ""}
                        </div>
                      ) : null}
                    </td>
                    <td style={{ color: "var(--muted)", fontSize: 12 }}>{entry.handle}</td>
                    <td>{entry.follower_count ? fmt(entry.follower_count) : "—"}</td>
                    <td>
                      {entry.analyzed_at
                        ? new Date(entry.analyzed_at * 1000).toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" })
                        : "—"}
                    </td>
                    <td>
                      <a href={entry.profile_url} target="_blank" rel="noopener noreferrer" className="secondary-button" style={{ padding: "4px 10px", fontSize: 12 }}>
                        LinkedIn
                      </a>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="primary-button"
                        style={{ padding: "4px 12px", fontSize: 12 }}
                        disabled={openingId === entry.analysis_id}
                        onClick={() => open(entry)}
                      >
                        {openingId === entry.analysis_id
                          ? <Loader2 size={12} className="spinning" />
                          : <FileText size={12} />}
                        Voir
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Vue « Analyser » fusionnée : barre de sous-onglets qui regroupe l'ancien
 * onglet Analyser (séries), Mes influenceurs et Dashboard global.
 */
function AnalyzeHub({
  tab,
  onTab,
  jobs,
  jobsLoading,
  onJobCreated,
  onJobUpdated,
  onOpenReport,
  influencers,
  influencersLoading,
  onOpenLibraryReport,
  isAuthed,
  requireAuth,
}: {
  tab: AnalyzeTab;
  onTab: (t: AnalyzeTab) => void;
  jobs: Job[];
  jobsLoading: boolean;
  onJobCreated: (job: Job) => void;
  onJobUpdated: (job: Job) => void;
  onOpenReport: (markdown: string, name: string) => void;
  influencers: InfluencerLibraryEntry[];
  influencersLoading: boolean;
  onOpenLibraryReport: (entry: InfluencerLibraryEntry) => Promise<void>;
  isAuthed: boolean;
  requireAuth: (reason?: string, mode?: AuthMode) => void;
}) {
  const subTabs: { key: AnalyzeTab; label: string; icon: React.ReactNode }[] = [
    { key: "analyze", label: "Analyser", icon: <ListChecks size={14} /> },
    { key: "influencers", label: "Mes influenceurs", icon: <Users size={14} /> },
    { key: "dashboard", label: "Dashboard", icon: <TrendingUp size={14} /> },
  ];

  return (
    <div>
      <div className="tabs">
        {subTabs.map((t) => (
          <button
            key={t.key}
            className={`tab ${tab === t.key ? "active" : ""}`}
            onClick={() => onTab(t.key)}
            style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>

      {tab === "analyze" && (
        <JobsView
          jobs={jobs}
          loading={jobsLoading}
          isAuthed={isAuthed}
          onCreated={onJobCreated}
          onJobUpdated={onJobUpdated}
          onOpenReport={onOpenReport}
          requireAuth={requireAuth}
        />
      )}
      {tab === "influencers" && (
        <InfluencersView
          entries={influencers}
          loading={influencersLoading}
          isAuthed={isAuthed}
          requireAuth={requireAuth}
          onOpenReport={onOpenLibraryReport}
        />
      )}
      {tab === "dashboard" && <GlobalDashboard />}
    </div>
  );
}

/** Onglet « Contenu » : regroupe Idée du jour, Générateur et Mes contenus en sous-onglets. */
function ContentHub({
  tab,
  onTab,
  seed,
  onReuse,
  isAuthed,
  requireAuth,
}: {
  tab: ContentTab;
  onTab: (t: ContentTab) => void;
  seed?: { topic: string; nonce: number } | null;
  onReuse: (topic: string) => void;
  isAuthed: boolean;
  requireAuth: (reason?: string, mode?: AuthMode) => void;
}) {
  const subTabs: { key: ContentTab; label: string; icon: React.ReactNode }[] = [
    { key: "daily", label: "Idée du jour", icon: <Sparkles size={14} /> },
    { key: "generator", label: "Générateur de posts", icon: <PenTool size={14} /> },
    { key: "library", label: "Mes contenus", icon: <Bookmark size={14} /> },
  ];

  return (
    <div>
      <div className="tabs">
        {subTabs.map((t) => (
          <button
            key={t.key}
            className={`tab ${tab === t.key ? "active" : ""}`}
            onClick={() => onTab(t.key)}
            style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>

      {tab === "daily" && <DailyIdeasView isAuthed={isAuthed} requireAuth={requireAuth} onReuse={onReuse} />}
      {tab === "generator" && <Generator isAuthed={isAuthed} requireAuth={requireAuth} seed={seed} />}
      {tab === "library" && (
        <LibraryView isAuthed={isAuthed} requireAuth={requireAuth} onReuse={onReuse} />
      )}
    </div>
  );
}

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [reports, setReports] = useState<Report[]>([]);
  const [reportsLoading, setReportsLoading] = useState(false);
  const [influencers, setInfluencers] = useState<InfluencerLibraryEntry[]>([]);
  const [influencersLoading, setInfluencersLoading] = useState(false);
  const [result, setResult] = useState<Analysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [view, setView] = useState<MainView>("content");
  const [platform, setPlatform] = useState<Platform>(() => {
    if (typeof window === "undefined") return "linkedin";
    return (localStorage.getItem("lkd_platform") as Platform) ?? "linkedin";
  });
  const [analyzeTab, setAnalyzeTab] = useState<AnalyzeTab>("analyze");
  const [contentTab, setContentTab] = useState<ContentTab>("generator");
  // Sujet pré-rempli quand on "réutilise" une idée/un post depuis Mes contenus.
  const [generatorSeed, setGeneratorSeed] = useState<{ topic: string; nonce: number } | null>(null);
  const [loadedReport, setLoadedReport] = useState<Report | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [session, setSession] = useState<Session | null>(null);
  const [authOpen, setAuthOpen] = useState(false);
  const [authReason, setAuthReason] = useState("");
  const [authMode, setAuthMode] = useState<AuthMode>("signup");
  const [credits, setCredits] = useState<number | null>(null);
  const userIdRef = useRef<string | null>(null);
  const prevJobActiveRef = useRef(false);
  // Analyse anonyme affichée mais pas encore sauvegardée : sauvée dès l'inscription.
  const pendingAnonResultRef = useRef<Analysis | null>(null);

  const isAuthed = !!session;

  function requireAuth(reason?: string, mode: AuthMode = "signup") {
    setAuthReason(reason || "");
    setAuthMode(mode);
    setAuthOpen(true);
  }

  async function loadReports() {
    setReportsLoading(true);
    try {
      const res = await fetch(`${API_URL}/reports?limit=3`, { headers: await authHeaders() });
      const data = await res.json();
      if (res.ok && Array.isArray(data)) setReports(data.slice(0, 3));
    } catch { /* ignore */ } finally { setReportsLoading(false); }
  }

  async function loadInfluencerLibrary() {
    setInfluencersLoading(true);
    try {
      const headers = await authHeaders();
      // Backend Render déploie depuis main : /me/influencers/library pas encore dispo.
      // Deux appels existants suffisent ; réactiver /library après merge dev→main.
      const [infRes, anaRes] = await Promise.all([
        fetch(`${API_URL}/me/influencers`, { headers }),
        fetch(`${API_URL}/me/analyses?limit=100`, { headers }),
      ]);
      if (!infRes.ok || !anaRes.ok) return;
      const influencersRaw = await infRes.json();
      const analysesRaw = await anaRes.json();
      if (!Array.isArray(influencersRaw) || !Array.isArray(analysesRaw)) return;
      setInfluencers(buildInfluencerLibraryFromLegacy(influencersRaw, analysesRaw));
    } catch { /* ignore */ } finally { setInfluencersLoading(false); }
  }

  // Les séries vivent dans Home (pas dans JobsView) : le polling continue quand
  // on change d'onglet, et la sidebar affiche un badge de progression partout.
  async function loadJobs() {
    try {
      const res = await fetch(`${DIRECT_API_URL}/jobs`, { headers: await authHeaders() });
      const data = await res.json();
      if (res.ok && Array.isArray(data)) setJobs(data);
    } catch { /* ignore */ } finally { setJobsLoading(false); }
  }

  function onJobCreated(job: Job) {
    setJobs((prev) => [job, ...prev]);
    loadReports();
    loadInfluencerLibrary();
  }

  // Remplace une série par sa version à jour (retournée par cancel série/item),
  // pour un affichage immédiat même si le polling s'est arrêté.
  function onJobUpdated(job: Job) {
    setJobs((prev) => prev.map((j) => (j.id === job.id ? job : j)));
  }

  const activeJob = jobs.find(jobIsActive) ?? null;
  const anyJobActive = !!activeJob;
  // ALE-114 : badge de progression par réseau (un job Instagram ne doit pas
  // s'afficher sur la Veille LinkedIn et inversement ; platform absent = linkedin).
  const activeLkJob = jobs.find((j) => jobIsActive(j) && (j.platform ?? "linkedin") !== "instagram") ?? null;
  const activeIgJob = jobs.find((j) => jobIsActive(j) && j.platform === "instagram") ?? null;

  // Rapports : rechargés à la connexion ET à chaque refresh de token.
  // Sinon, si le token stocké est expiré au chargement, /reports renvoie 401,
  // loadReports avale l'erreur, et le TOKEN_REFRESHED suivant est ignoré par le
  // garde uid de onAuthStateChange → la liste reste vide jusqu'à une action.
  useEffect(() => {
    if (!isAuthed) { setReports([]); return; }
    loadReports();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed, session?.access_token]);

  useEffect(() => {
    if (!isAuthed) { setInfluencers([]); return; }
    loadInfluencerLibrary();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed, session?.access_token]);

  useEffect(() => {
    if (!isAuthed) { setCredits(null); return; }
    (async () => {
      try {
        const res = await fetch(`${DIRECT_API_URL}/me/credits`, { headers: await authHeaders() });
        if (res.ok) { const d = await res.json(); setCredits(d.balance ?? null); }
      } catch { /* ignore */ }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed, session?.access_token]);

  // Rafraîchit le solde en direct après chaque action coûteuse (cf. emitCredits).
  useEffect(() => {
    const onCredits = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (typeof detail === "number") setCredits(detail);
    };
    window.addEventListener("credits:update", onCredits);
    return () => window.removeEventListener("credits:update", onCredits);
  }, []);

  // Premier chargement des séries + polling tant qu'une série tourne (toutes pages).
  // Keyé sur le token (pas seulement isAuthed) pour les mêmes raisons que les rapports.
  useEffect(() => {
    if (!isAuthed) { setJobs([]); return; }
    setJobsLoading(true);
    loadJobs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed, session?.access_token]);

  useEffect(() => {
    if (!isAuthed || !anyJobActive) return;
    const t = setInterval(loadJobs, 3000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed, anyJobActive]);

  useEffect(() => {
    if (prevJobActiveRef.current && !anyJobActive && isAuthed) {
      loadReports();
      loadInfluencerLibrary();
    }
    prevJobActiveRef.current = anyJobActive;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anyJobActive, isAuthed]);

  async function persistAnonResult(anon: Analysis) {
    try {
      await fetch(`${DIRECT_API_URL}/analyses/persist`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify(anon),
      });
    } catch { /* best-effort : on ne bloque pas l'UX sur une erreur de save */ }
    loadReports();
    loadInfluencerLibrary();
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
      setInfluencers([]);
      setResult(null);
      setLoadedReport(null);
      setJobs([]);
      setError("");
      setView("content");
      if (uid) setTimeout(() => { loadReports(); loadJobs(); loadInfluencerLibrary(); }, 0);
    });
    return () => sub.subscription.unsubscribe();
  }, []);

  // Retour du flux OAuth LinkedIn (Zernio) : on relit le compte connecté côté
  // serveur, on nettoie l'URL, puis on bascule sur l'onglet Profil.
  useEffect(() => {
    if (!isAuthed) return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("linkedin") !== "connected") return;
    (async () => {
      try {
        await fetch(`${DIRECT_API_URL}/me/linkedin/refresh`, { method: "POST", headers: await authHeaders() });
      } catch { /* ignore */ }
      params.delete("linkedin");
      const qs = params.toString();
      window.history.replaceState({}, "", window.location.pathname + (qs ? `?${qs}` : ""));
      setView("profile");
    })();
  }, [isAuthed]);

  // Retour du flux OAuth X (Zernio) : même logique que LinkedIn.
  useEffect(() => {
    if (!isAuthed) return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("x") !== "connected") return;
    (async () => {
      try {
        await fetch(`${DIRECT_API_URL}/me/x/refresh`, { method: "POST", headers: await authHeaders() });
      } catch { /* ignore */ }
      params.delete("x");
      const qs = params.toString();
      window.history.replaceState({}, "", window.location.pathname + (qs ? `?${qs}` : ""));
      setView("profile");
    })();
  }, [isAuthed]);

  // Retour du flux OAuth Slack : le code arrive en query param.
  // On vérifie sessionStorage pour distinguer des autres OAuth éventuels.
  useEffect(() => {
    if (!isAuthed) return;
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    if (!code || !sessionStorage.getItem("slack_oauth_pending")) return;
    sessionStorage.removeItem("slack_oauth_pending");
    (async () => {
      try {
        const redirectUri = `${window.location.origin}${window.location.pathname}`;
        await fetch(`${DIRECT_API_URL}/me/integrations/slack/callback`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...(await authHeaders()) },
          body: JSON.stringify({ code, redirect_uri: redirectUri }),
        });
      } catch { /* ignore */ }
      params.delete("code");
      params.delete("state");
      const qs = params.toString();
      window.history.replaceState({}, "", window.location.pathname + (qs ? `?${qs}` : ""));
      setView("profile");
    })();
  }, [isAuthed]);

  /** Ouvre un rapport (depuis le backlog) dans la vue markdown de l'onglet Analyser. */
  function openReport(markdown: string, name: string) {
    setLoadedReport({ name, path: name, updated_at: Date.now() / 1000, content: markdown });
    setResult(null);
    setView("analyze");
    setAnalyzeTab("analyze");
  }

  async function openLibraryReport(entry: InfluencerLibraryEntry) {
    const res = await fetch(`${DIRECT_API_URL}/me/analyses/${entry.analysis_id}`, { headers: await authHeaders() });
    const data = await res.json();
    if (!res.ok || !data?.report_markdown) {
      throw new Error(data?.detail || "Rapport introuvable.");
    }
    setLoadedReport({
      name: entry.name,
      path: entry.analysis_id,
      updated_at: entry.analyzed_at || Date.now() / 1000,
      content: data.report_markdown,
    });
    setResult(null);
    setView("analyze");
    setAnalyzeTab("influencers");
  }

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
          reportsLoading={reportsLoading}
          view={view}
          isAuthed={isAuthed}
          jobBadges={{
            linkedin: activeLkJob ? { completed: activeLkJob.completed, total: activeLkJob.total } : null,
            instagram: activeIgJob ? { completed: activeIgJob.completed, total: activeIgJob.total } : null,
          }}
          credits={credits}
          platform={platform}
          onNavigate={(v) => {
            setView(v);
            if (v === "analyze" || v === "profile") {
              setResult(null);
              setLoadedReport(null);
              setError("");
            }
          }}
          onLoadReport={(r) => { setLoadedReport(r); setView("analyze"); setResult(null); }}
          onPlatformChange={(p) => {
            setPlatform(p);
            localStorage.setItem("lkd_platform", p);
          }}
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
          {/* Agent IA, Profil et Tableau de bord sont indépendants du réseau */}
          {view === "assistant" ? (
            <Assistant isAuthed={isAuthed} requireAuth={requireAuth} />
          ) : view === "progress" ? (
            <ProgressView isAuthed={isAuthed} requireAuth={requireAuth} />
          ) : view === "profile" ? (
            <ProfileView isAuthed={isAuthed} requireAuth={requireAuth} />
          ) : platform === "instagram" ? (
            view === "content" ? (
              <InstagramContentHub tab={contentTab} onTab={setContentTab} isAuthed={isAuthed} requireAuth={requireAuth} />
            ) : view === "analyze" ? (
              loadedReport ? (
                <>
                  <button className="secondary-button" style={{ marginBottom: 12 }} onClick={() => setLoadedReport(null)}>
                    ← Retour aux analyses
                  </button>
                  <div className="markdown card"><ReactMarkdown remarkPlugins={[remarkGfm]}>{loadedReport.content}</ReactMarkdown></div>
                </>
              ) : (
                <InstagramAnalyzeHub
                  jobs={jobs}
                  loading={jobsLoading}
                  isAuthed={isAuthed}
                  onCreated={onJobCreated}
                  onOpenReport={(markdown, name) => { setLoadedReport({ content: markdown, name, path: "", updated_at: Date.now() / 1000 }); }}
                  requireAuth={requireAuth}
                  onJobUpdated={onJobUpdated}
                />
              )
            ) : (
              <InstagramPlaceholder />
            )
          ) : (
            <>
              {view === "analyze" && (
                loading
                  ? <LoadingState />
                  : result
                    ? <Dashboard result={result} isAuthed={isAuthed} requireAuth={requireAuth} />
                    : loadedReport
                      ? (
                        <>
                          <button className="secondary-button" style={{ marginBottom: 12 }} onClick={() => setLoadedReport(null)}>
                            ← Retour aux analyses
                          </button>
                          <div className="markdown card"><ReactMarkdown remarkPlugins={[remarkGfm]}>{loadedReport.content}</ReactMarkdown></div>
                        </>
                      )
                      : (
                        <AnalyzeHub
                          tab={analyzeTab}
                          onTab={setAnalyzeTab}
                          jobs={jobs}
                          jobsLoading={jobsLoading}
                          onJobCreated={onJobCreated}
                          onJobUpdated={onJobUpdated}
                          onOpenReport={openReport}
                          influencers={influencers}
                          influencersLoading={influencersLoading}
                          onOpenLibraryReport={openLibraryReport}
                          isAuthed={isAuthed}
                          requireAuth={requireAuth}
                        />
                      )
              )}
              {view === "content" && (
                <ContentHub
                  tab={contentTab}
                  onTab={setContentTab}
                  seed={generatorSeed}
                  isAuthed={isAuthed}
                  requireAuth={requireAuth}
                  onReuse={(topic) => {
                    setGeneratorSeed({ topic, nonce: Date.now() });
                    setContentTab("generator");
                  }}
                />
              )}
            </>
          )}
        </main>
      </div>
      <AuthModal open={authOpen} onClose={() => setAuthOpen(false)} reason={authReason} defaultMode={authMode} />
    </>
  );
}
