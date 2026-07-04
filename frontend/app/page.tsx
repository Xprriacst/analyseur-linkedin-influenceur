"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Activity,
  BarChart3,
  CalendarDays,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Copy,
  Download,
  Eye,
  FileText,
  GripVertical,
  Image as ImageIcon,
  ImagePlus,
  Lightbulb,
  Link2,
  Linkedin,
  ListChecks,
  Loader2,
  Lock,
  LogIn,
  LogOut,
  Bookmark,
  BookmarkPlus,
  MessageSquare,
  Pencil,
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
import PostActionsBar, { type PostAction } from "./components/PostActionsBar";
import { authHeaders, supabase } from "./lib/supabase";

const API_URL = "/api";
const DIRECT_API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ??
  "https://analyseur-linkedin-influenceur-api.onrender.com";

// Environnement dev : bandeau d'entête + rappels UI, jamais affichés en prod.
// Piloté par NEXT_PUBLIC_APP_ENV=dev (site Netlify dev) ; fallback = URL backend
// dev (`-api-dev`) pour que l'indicateur marche même si la variable n'est pas posée.
const IS_DEV_ENV =
  process.env.NEXT_PUBLIC_APP_ENV === "dev" ||
  (process.env.NEXT_PUBLIC_BACKEND_URL ?? "").includes("-api-dev");

// Rappel dev-only affiché près des actions Slack : sur dev, l'app Slack renvoie
// les clics de boutons à la prod → l'envoi part mais Valider/Modifier ne se
// testent pas ici. Rend null en prod.
function DevSlackNote() {
  if (!IS_DEV_ENV) return null;
  return (
    <div className="dev-slack-note">
      ⚠️ Sur dev, les boutons Slack ne sont pas testables : le message part bien,
      mais les clics (Valider / Modifier) sont traités par la prod.
    </div>
  );
}

// Solde de crédits : les endpoints coûteux renvoient le nouveau solde. On le
// diffuse via un évènement window pour rafraîchir la pastille de la sidebar
// (gérée par Home) sans prop-drilling à travers le hub « Contenu ».
function emitCredits(balance: unknown) {
  if (typeof balance === "number" && typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("credits:update", { detail: balance }));
  }
}

function toDatetimeLocalValue(date: Date) {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function isoToDatetimeLocalValue(iso: string) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return toDatetimeLocalValue(date);
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
type LinkedInImageAttachment = {
  id: string;
  url: string;
  filename?: string;
  source: "upload" | "generated";
};
type SavedIdea = Idea & { id: string; created_at?: string };
// Image persistée sur un post sauvegardé (URL publique Zernio, format media_items).
type SavedPostMediaItem = { type?: string; url: string; title?: string };
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
  media_items?: SavedPostMediaItem[] | null;
};
type ScheduledPost = {
  id: string;
  post_text: string;
  scheduled_at: string;
  status: "pending" | "published" | "failed" | "cancelled" | string;
  slack_status?: string | null;
  slack_message_ts?: string | null;
  media_items?: LinkedInImageAttachment[] | null;
  error_message?: string | null;
  created_at?: string;
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

const mainViews = ["analyze", "profile", "assistant", "content"] as const;
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
type AnalyzeTab = "analyze" | "influencers";

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

// ALE-141 : un job de génération de posts (file d'attente). Une ligne = une
// requête (un sujet → N variants). Le résultat vit en base : on peut quitter la
// page et revenir, les variants réapparaissent.
type GenerationJob = {
  id: string;
  status: JobStatus;
  topic: string | null;
  editorial_role: string | null;
  web_search: boolean;
  count: number;
  result: { variants?: Variant[]; save_error?: string | null } | null;
  error: string | null;
  created_at: string;
  updated_at: string;
};

function generationJobIsActive(j: GenerationJob): boolean {
  return j.status === "queued" || j.status === "running";
}

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

function ItemRow({ item, onOpen, opening, onCancel, cancelling, onDelete, deleting }: { item: JobItem; onOpen: (i: JobItem) => void; opening: boolean; onCancel: (i: JobItem) => void; cancelling: boolean; onDelete?: (i: JobItem) => void; deleting?: boolean }) {
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
      ) : onDelete ? (
        <button
          type="button"
          className="ghost-button"
          style={{ fontSize: 11, padding: "2px 6px", color: "var(--muted)" }}
          disabled={deleting}
          onClick={(e) => { e.stopPropagation(); onDelete(item); }}
          title="Supprimer cette analyse"
        >
          {deleting ? <Loader2 size={11} className="spinning" /> : <Trash2 size={13} />}
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
  const [deletingItemId, setDeletingItemId] = useState<string | null>(null);

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
      emitCredits((data as any).credits);
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

  async function deleteItem(job: Job, item: JobItem) {
    setDeletingItemId(item.id);
    try {
      const res = await fetch(`${DIRECT_API_URL}/jobs/${job.id}/items/${item.id}`, {
        method: "DELETE",
        headers: await authHeaders(),
      });
      if (res.ok) onJobUpdated({ ...job, items: job.items.filter((it) => it.id !== item.id) });
    } catch {
      /* ignore */
    } finally {
      setDeletingItemId(null);
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
                      onDelete={(it) => deleteItem(job, it)}
                      deleting={deletingItemId === item.id}
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
  const [deletingItemId, setDeletingItemId] = useState<string | null>(null);

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
      emitCredits((data as any).credits);
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

  async function deleteItem(job: Job, item: JobItem) {
    setDeletingItemId(item.id);
    try {
      const res = await fetch(`${DIRECT_API_URL}/jobs/${job.id}/items/${item.id}`, { method: "DELETE", headers: await authHeaders() });
      if (res.ok) onJobUpdated({ ...job, items: job.items.filter((it) => it.id !== item.id) });
    } catch { /* ignore */ } finally { setDeletingItemId(null); }
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
                      onDelete={(it) => deleteItem(job, it)}
                      deleting={deletingItemId === item.id}
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
  restricted,
  ideasAccount,
  onToggleView,
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
  restricted: boolean;
  ideasAccount: boolean;
  onToggleView: () => void;
  jobBadges: { linkedin: { completed: number; total: number } | null; instagram: { completed: number; total: number } | null };
  credits: number | null;
  platform: Platform;
  onNavigate: (v: MainView) => void;
  onLoadReport: (report: Report) => void;
  onPlatformChange: (p: Platform) => void;
  requireAuth: (reason?: string, mode?: AuthMode) => void;

}) {
  const [collapsed, setCollapsed] = useState(false);
  const [collapsedPreferenceLoaded, setCollapsedPreferenceLoaded] = useState(false);

  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem("sidebar-collapsed") === "true");
    } catch {
      /* ignore */
    } finally {
      setCollapsedPreferenceLoaded(true);
    }
  }, []);

  useEffect(() => {
    const w = collapsed ? "64px" : "260px";
    document.documentElement.style.setProperty("--sidebar-w", w);
    if (!collapsedPreferenceLoaded) return;
    try { localStorage.setItem("sidebar-collapsed", String(collapsed)); } catch {}
  }, [collapsed, collapsedPreferenceLoaded]);

  return (
    <aside className={`sidebar${collapsed ? " sidebar-collapsed" : ""}`}>
      <div className="logo">
        <div
          className="logo-mark"
        >
          <Target size={18} strokeWidth={2.5} />
        </div>
        {!collapsed && (
          <div className="logo-text">
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              Cibl
              <span className="beta-badge">Bêta</span>
            </span>
            <span className="logo-sub">SaaS Premium</span>
          </div>
        )}
        <button
          className="sidebar-collapse-btn"
          onClick={() => setCollapsed((value) => !value)}
          title={collapsed ? "Étendre la sidebar" : "Réduire la sidebar"}
          aria-label={collapsed ? "Étendre la sidebar" : "Réduire la sidebar"}
        >
          {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
        </button>
      </div>

      {/* Vue client (compte ideas_only) : navigation réduite à la seule page « idées de posts ». */}
      {restricted && (
        <section className="sidebar-section sidebar-nav-tree">
          <div className="nav-list">
            <button
              className={`nav-item active${collapsed ? " nav-item-collapsed" : ""}`}
              title={collapsed ? "Mes idées de posts" : undefined}
              onClick={() => onNavigate("content")}
            >
              <Sparkles size={14} />
              {!collapsed && <span>Mes idées de posts</span>}
            </button>
          </div>
        </section>
      )}

      {/* Navigation — accordéon : LinkedIn / Instagram déplient leurs sous-onglets (Veille / Contenu), Agent IA au même niveau */}
      {!restricted && (() => {
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
            </div>
          </section>
        );
      })()}

      {!restricted && (
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
      )}

      {/* Compte ideas_only : bascule entre la vue client (réservoir) et la vue complète (agence). */}
      {ideasAccount && (
        <section className="sidebar-section" style={{ marginTop: restricted ? "auto" : 0 }}>
          <div className="nav-list">
            <button
              className={`nav-item${collapsed ? " nav-item-collapsed" : ""}`}
              title={restricted ? "Passer en vue complète (agence)" : "Revenir à la vue client (idées)"}
              onClick={onToggleView}
            >
              {restricted ? <Eye size={14} /> : <Lightbulb size={14} />}
              {!collapsed && <span>{restricted ? "Vue complète (agence)" : "Vue client (idées)"}</span>}
            </button>
          </div>
        </section>
      )}
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

  async function disconnect() {
    setError("");
    setBusy(true);
    try {
      await fetch(`${DIRECT_API_URL}/me/linkedin`, {
        method: "DELETE",
        headers: await authHeaders(),
      });
      setStatus((prev) => prev ? { ...prev, connected: false, account_id: null } : prev);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return { status, busy, error, connect, disconnect };
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
      if (data.state) sessionStorage.setItem("slack_oauth_state", data.state);
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

// ALE-184 : fenêtre de programmation commune à toutes les sections (Générateur,
// Mes contenus, Idée du jour, Agent IA) — date/heure + choix « Valider via
// Slack » ou programmation directe. Les sections ne doivent plus recoder leur
// propre programmation : tout passe par ce composant.
type ScheduleModalImage = { url: string; filename?: string };

function SchedulePostModal({
  text,
  images = [],
  slackConnected,
  onClose,
  onScheduled,
}: {
  text: string;
  images?: ScheduleModalImage[];
  slackConnected: boolean;
  onClose: () => void;
  onScheduled: (viaSlack: boolean) => void;
}) {
  const [scheduleDate, setScheduleDate] = useState(() => {
    // Prefill to tomorrow 9:00 local time
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    tomorrow.setHours(9, 0, 0, 0);
    return toDatetimeLocalValue(tomorrow);
  });
  const [scheduling, setScheduling] = useState(false);
  const [error, setError] = useState("");

  async function doSchedule(validateViaSlack: boolean) {
    setError("");
    setScheduling(true);
    try {
      const localDate = new Date(scheduleDate);
      if (isNaN(localDate.getTime())) throw new Error("Date invalide.");
      if (localDate <= new Date()) throw new Error("La date doit être dans le futur.");
      const res = await fetch(`${DIRECT_API_URL}/me/linkedin/schedule`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({
          content: text,
          scheduled_at: localDate.toISOString(),
          validate_via_slack: validateViaSlack,
          images: images.map((image) => ({
            ...(image.url.startsWith("data:") ? { data_url: image.url } : { url: image.url }),
            filename: image.filename,
          })),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Programmation impossible.");
      onScheduled(validateViaSlack);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setScheduling(false);
    }
  }

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 1000,
      display: "flex", alignItems: "center", justifyContent: "center", padding: 16,
    }}>
      <div className="card" style={{ maxWidth: 520, width: "100%", padding: 24 }}>
        <h3 style={{ marginTop: 0, marginBottom: 8 }}>Programmer ce post</h3>
        <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 12 }}>
          Choisis la date/heure, puis programme directement sur LinkedIn, ou demande d&apos;abord une validation Slack — dans ce cas le post n&apos;est publié à l&apos;heure choisie que s&apos;il est validé sur Slack.
        </p>
        <textarea
          readOnly
          value={text}
          rows={6}
          className="variant-text"
          style={{ width: "100%", boxSizing: "border-box", marginBottom: 12 }}
        />
        {images.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <p className="role-picker-hint" style={{ marginBottom: 8 }}>
              {images.length} image{images.length > 1 ? "s" : ""} {images.length > 1 ? "seront conservées" : "sera conservée"} pour la publication programmée.
            </p>
            <div style={{ display: "flex", gap: 8, overflowX: "auto" }}>
              {images.map((image, idx) => (
                <img
                  key={`${image.url.slice(0, 64)}-${idx}`}
                  src={image.url}
                  alt={`Image programmée ${idx + 1}`}
                  style={{ width: 74, height: 74, objectFit: "cover", borderRadius: 8, border: "1px solid var(--border)" }}
                />
              ))}
            </div>
          </div>
        )}
        <label style={{ fontSize: 13, fontWeight: 500, display: "block", marginBottom: 6 }}>
          Date et heure de publication
        </label>
        <input
          type="datetime-local"
          value={scheduleDate}
          onChange={(e) => setScheduleDate(e.target.value)}
          style={{ width: "100%", boxSizing: "border-box", padding: "8px 10px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)", fontSize: 14, marginBottom: 12 }}
        />
        {error && <p style={{ color: "var(--error, #e53e3e)", fontSize: 13, marginBottom: 8 }}>{error}</p>}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", flexWrap: "wrap" }}>
          <button className="secondary-button" disabled={scheduling} onClick={onClose}>
            Annuler
          </button>
          <button
            className="secondary-button"
            disabled={scheduling || !scheduleDate || !slackConnected}
            title={slackConnected ? "Envoyer une demande de validation Slack avant publication" : "Connecte Slack dans l'onglet Profil pour valider"}
            onClick={() => doSchedule(true)}
          >
            {scheduling ? <Loader2 size={14} className="spinning" /> : <Clock3 size={14} />} Valider via Slack
          </button>
          <button className="primary-button" disabled={scheduling || !scheduleDate} onClick={() => doSchedule(false)}>
            {scheduling ? <><Loader2 size={14} className="spinning" /> Planification…</> : <><Clock3 size={14} /> Programmer sur LinkedIn</>}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Pop-up de génération d'image IA (ALE-68) : prépare d'abord un prompt à partir du
 *  post (gratuit), le montre à l'utilisateur qui peut l'ajuster, puis ne génère
 *  l'image (payante en crédits) qu'après validation explicite. L'image générée
 *  est remontée en data URL via `onGenerated`.
 *  Pendant la génération (~1 min), la pop-up peut être réduite en pastille : la
 *  génération continue et l'image revient en preview à la fin (ALE-190). Quitter
 *  ou recharger la page pendant la génération déclenche l'alerte du navigateur ;
 *  changer d'onglet dans l'app perdrait aussi l'image, d'où « reste sur cette page ». */
function ImageGenModal({ postText, onClose, onGenerated }: { postText: string; onClose: () => void; onGenerated: (dataUrl: string) => void }) {
  const [prompt, setPrompt] = useState("");
  const [loadingPrompt, setLoadingPrompt] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState("");

  // Garde-fou : alerte native du navigateur si on ferme/recharge la page en pleine génération.
  useEffect(() => {
    if (!generating) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [generating]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${DIRECT_API_URL}/generate-image/prompt`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...(await authHeaders()) },
          body: JSON.stringify({ post_text: postText }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Préparation du prompt impossible.");
        if (!cancelled) setPrompt(data.prompt || "");
      } catch (err: any) {
        if (!cancelled) setError(err.message || "Préparation du prompt impossible.");
      } finally {
        if (!cancelled) setLoadingPrompt(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function generate() {
    setError("");
    setGenerating(true);
    try {
      const res = await fetch(`${DIRECT_API_URL}/generate-image`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ post_text: postText, prompt: prompt.trim() || undefined }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Génération d'image impossible.");
      emitCredits(data.credits);
      onGenerated(data.image_data);
      // La pop-up revient (même si elle était réduite) pour montrer le résultat.
      setPreview(data.image_data);
      setMinimized(false);
    } catch (err: any) {
      setError(err.message || "Génération d'image impossible.");
      setMinimized(false);
    } finally {
      setGenerating(false);
    }
  }

  // Réduite en pastille : la génération continue, clic pour rouvrir.
  if (minimized) {
    return (
      <button
        type="button"
        className="card"
        onClick={() => setMinimized(false)}
        title="Rouvrir la génération d'image"
        style={{
          position: "fixed", right: 16, bottom: 16, zIndex: 1000, cursor: "pointer",
          display: "flex", alignItems: "center", gap: 8, padding: "10px 14px",
          fontSize: 13, border: "1px solid var(--border)", boxShadow: "0 8px 24px rgba(0,0,0,0.18)",
        }}
      >
        <Loader2 size={14} className="spinning" /> Image IA en cours de génération…
      </button>
    );
  }

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 1000,
      display: "flex", alignItems: "center", justifyContent: "center", padding: 16,
    }}>
      <div className="card" style={{ maxWidth: 560, width: "100%", padding: 24 }}>
        <h3 style={{ marginTop: 0, marginBottom: 8, display: "flex", alignItems: "center", gap: 8 }}>
          <ImageIcon size={16} /> {preview ? "Image générée" : "Générer une image IA"}
        </h3>
        {preview ? (
          <>
            <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 12 }}>
              Image jointe au post ✓ — tu la retrouves dans les miniatures sous le post
              (avec télécharger / retirer).
            </p>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={preview}
              alt="Image générée"
              style={{ width: "100%", maxHeight: 380, objectFit: "contain", borderRadius: 8, border: "1px solid var(--border)", display: "block" }}
            />
            <div style={{ display: "flex", gap: 8, marginTop: 14, justifyContent: "flex-end" }}>
              <button className="primary-button" onClick={onClose}>Fermer</button>
            </div>
          </>
        ) : (
          <>
            <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 12 }}>
              {generating
                ? "Génération en cours (~1 min). Tu peux réduire cette fenêtre et continuer à travailler — reste simplement sur cette page, l'image sera jointe au post automatiquement."
                : "Voici le prompt préparé à partir de ton post. Ajuste-le si besoin, puis valide pour générer l'image (5 crédits). L'image sera jointe au post."}
            </p>
            {loadingPrompt ? (
              <p style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 8 }}>
                <Loader2 size={14} className="spinning" /> Préparation du prompt…
              </p>
            ) : (
              <textarea
                className="variant-text"
                value={prompt}
                rows={5}
                disabled={generating}
                onChange={(e) => setPrompt(e.target.value)}
                style={{ width: "100%", boxSizing: "border-box" }}
              />
            )}
            {error && <div className="error" style={{ marginTop: 8, fontSize: 13 }}>{error}</div>}
            <div style={{ display: "flex", gap: 8, marginTop: 14, justifyContent: "flex-end", flexWrap: "wrap" }}>
              {generating ? (
                <button className="secondary-button" onClick={() => setMinimized(true)}>
                  Réduire — continuer en arrière-plan
                </button>
              ) : (
                <button className="secondary-button" onClick={onClose}>Annuler</button>
              )}
              <button className="primary-button" disabled={loadingPrompt || generating || !prompt.trim()} onClick={generate}>
                {generating
                  ? <><Loader2 size={13} className="spinning" /> Génération en cours… (~1 min)</>
                  : <><Sparkles size={13} /> Générer l&apos;image</>}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// Cache module-level : survit aux changements d'onglet dans la même session (ALE-145).
// Réinitialisé à chaque refresh de page. `appliedJobId` (ALE-141) mémorise le
// dernier job de génération dont on a injecté le résultat, pour qu'un nouveau
// batch terminé pendant qu'on était sur un autre onglet s'affiche bien au retour
// (un simple ref serait réinitialisé au remontage du composant).
const _genCache: { variants: Variant[]; topic: string; appliedJobId: string | null } = {
  variants: [],
  topic: "",
  appliedJobId: null,
};

function Generator({ isAuthed, requireAuth, seed, generationJobs, onGenerationJobCreated, onRework }: { isAuthed: boolean; requireAuth: (reason?: string) => void; seed?: { topic: string; nonce: number } | null; generationJobs: GenerationJob[]; onGenerationJobCreated: (job: GenerationJob) => void; onRework?: (post: string) => void }) {
  const [variants, setVariants] = useState<Variant[]>(_genCache.variants);
  const [topic, setTopic] = useState(_genCache.topic);
  const [role, setRole] = useState("auto");
  const [loadingPosts, setLoadingPosts] = useState(false);
  const [error, setError] = useState("");
  const linkedin = useLinkedIn(isAuthed);
  const twitter = useTwitter(isAuthed);
  const slack = useSlack(isAuthed);
  const [slackSent, setSlackSent] = useState<Record<number, boolean>>({});
  const [slackSending, setSlackSending] = useState<Record<number, boolean>>({});
  const [confirmSlackIndex, setConfirmSlackIndex] = useState<number | null>(null);
  const [publishing, setPublishing] = useState<number | null>(null);
  const [published, setPublished] = useState<number | null>(null);
  const [drafted, setDrafted] = useState<number | null>(null);
  const [savingVariant, setSavingVariant] = useState<number | null>(null);
  const [savedVariant, setSavedVariant] = useState<number | null>(null);
  const [publishingX, setPublishingX] = useState<number | null>(null);
  const [publishedX, setPublishedX] = useState<number | null>(null);
  const [confirmIndex, setConfirmIndex] = useState<number | null>(null);
  const [confirmXIndex, setConfirmXIndex] = useState<number | null>(null);
  const [publishError, setPublishError] = useState("");
  const [variantImages, setVariantImages] = useState<Record<number, LinkedInImageAttachment[]>>({});
  const [imageModal, setImageModal] = useState<{ index: number; text: string } | null>(null);
  const [imageError, setImageError] = useState("");
  const [editedVariants, setEditedVariants] = useState<Record<number, string>>({});
  const [copiedVariant, setCopiedVariant] = useState<number | null>(null);
  const [variantCount, setVariantCount] = useState(1);
  const [scheduleModal, setScheduleModal] = useState<{ index: number; text: string; images: LinkedInImageAttachment[] } | null>(null);
  const [scheduledIndices, setScheduledIndices] = useState<Record<number, "direct" | "slack">>({});
  const [scheduleError, setScheduleError] = useState("");

  // "Réutiliser" depuis Mes contenus : pré-remplit le sujet et lance la génération.
  useEffect(() => {
    if (!seed?.topic) return;
    setTopic(seed.topic);
    void generateFromTopic(seed.topic);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed?.nonce]);

  // ALE-145 : synchronise le cache module-level à chaque changement de variants/topic,
  // pour les restaurer si le composant est démonté puis remonté (changement d'onglet).
  useEffect(() => { _genCache.variants = variants; }, [variants]);
  useEffect(() => { _genCache.topic = topic; }, [topic]);

  // ALE-141 : la génération tourne en file d'attente côté serveur (jobs portés par
  // Home). On surveille le job le plus récent : tant qu'il est actif, on affiche
  // « génération en cours » ; dès qu'il est `done`, on injecte ses variants (ils
  // survivent ainsi au changement d'onglet ET au refresh, car persistés en base).
  const latestGenJob = generationJobs[0] ?? null;
  const genJobActive = !!latestGenJob && generationJobIsActive(latestGenJob);

  useEffect(() => {
    const job = latestGenJob;
    if (!job || generationJobIsActive(job)) return;
    // Le job le plus récent est terminé : on injecte son résultat une seule fois
    // (suivi via `_genCache.appliedJobId`, persistant au-delà des remontages, pour
    // qu'un batch terminé pendant qu'on était sur un autre onglet s'affiche au retour).
    if (_genCache.appliedJobId === job.id) return;
    _genCache.appliedJobId = job.id;
    if (job.status === "done") {
      setEditedVariants({});
      setVariantImages({});
      setVariants(job.result?.variants || []);
      if (job.topic) setTopic(job.topic);
      setError(job.result?.save_error ? `Posts générés, mais sauvegarde impossible : ${job.result.save_error}` : "");
    } else if (job.status === "error") {
      setError(job.error || "Échec de la génération de posts");
    } else if (job.status === "cancelled") {
      setError("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [latestGenJob?.id, latestGenJob?.status]);

  function imagePayloadForVariant(i: number) {
    return (variantImages[i] || []).map((image) => ({
      ...(image.url.startsWith("data:") ? { data_url: image.url } : { url: image.url }),
      filename: image.filename,
    }));
  }

  // ALE-134 : marque explicitement un post comme « sauvegardé » (persiste aussi
  // le texte édité et les images jointes, ALE-179). Seuls les posts sauvegardés
  // apparaissent dans « Mes contenus ».
  async function saveVariant(i: number, text: string, id?: string) {
    if (!id) return;
    setSavingVariant(i);
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/generated-posts/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ post: text, saved: true, images: imagePayloadForVariant(i) }),
      });
      if (res.ok) {
        setSavedVariant(i);
        setTimeout(() => setSavedVariant((s) => (s === i ? null : s)), 1500);
      }
    } finally {
      setSavingVariant(null);
    }
  }

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
        body: JSON.stringify({ content: text, draft, images: imagePayloadForVariant(i) }),
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
    setScheduleError("");
    setScheduleModal({ index: i, text, images: variantImages[i] || [] });
  }

  // Image générée via la pop-up ImageGenModal → jointe au variant comme un upload.
  function attachGeneratedImage(i: number, dataUrl: string) {
    const attachment: LinkedInImageAttachment = {
      id: `generated-${Date.now()}`,
      url: dataUrl,
      filename: `image-generee-${i + 1}.png`,
      source: "generated",
    };
    setVariantImages((prev) => ({
      ...prev,
      [i]: [...(prev[i] || []), attachment],
    }));
  }

  function addUploadedImages(i: number, files: FileList | null) {
    if (!files?.length) return;
    setImageError("");
    const imageFiles = Array.from(files).filter((file) => file.type.startsWith("image/"));
    if (imageFiles.length !== files.length) {
      setImageError("Seuls les fichiers image sont acceptés.");
    }
    for (const file of imageFiles) {
      if (file.size > 8 * 1024 * 1024) {
        setImageError("LinkedIn limite chaque image à 8 Mo.");
        continue;
      }
      const reader = new FileReader();
      reader.onload = () => {
        const result = typeof reader.result === "string" ? reader.result : "";
        if (!result) return;
        const attachment: LinkedInImageAttachment = {
          id: `upload-${Date.now()}-${file.name}`,
          url: result,
          filename: file.name,
          source: "upload",
        };
        setVariantImages((prev) => ({
          ...prev,
          [i]: [...(prev[i] || []), attachment].slice(0, 20),
        }));
      };
      reader.onerror = () => setImageError(`Lecture impossible pour ${file.name}.`);
      reader.readAsDataURL(file);
    }
  }

  function removeVariantImage(i: number, imageId: string) {
    setVariantImages((prev) => ({
      ...prev,
      [i]: (prev[i] || []).filter((image) => image.id !== imageId),
    }));
  }

  // ALE-141 : lance une génération en file d'attente (non bloquant). On crée le
  // job côté serveur puis on rend la main : le travail tourne en arrière-plan,
  // l'utilisateur peut quitter la page. Le résultat est récupéré par le polling
  // de Home (latestGenJob) et injecté par l'effet ci-dessus.
  async function generateFromTopic(t: string) {
    setError("");
    setLoadingPosts(true);
    try {
      // Sujet optionnel : sans sujet, le backend choisit lui-même un angle (idée = post).
      const body: { topic?: string; editorial_role?: string; count?: number } = { count: variantCount };
      if (t.trim()) body.topic = t.trim();
      if (role !== "auto") body.editorial_role = role;
      const res = await fetch(`${DIRECT_API_URL}/generate/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Échec du lancement de la génération");
      if (typeof data.credits === "number") emitCredits(data.credits);
      onGenerationJobCreated(data as GenerationJob);
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
              onKeyDown={(e) => { if (e.key === "Enter" && !(loadingPosts || genJobActive)) generateFromTopic(topic); }}
            />
            <button className="primary-button" disabled={loadingPosts || genJobActive} onClick={() => generateFromTopic(topic)}>
              {(loadingPosts || genJobActive) ? <Loader2 size={14} className="spinning" /> : <Sparkles size={14} />}
              {genJobActive ? "Génération en cours…" : "Générer"}
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
                ? "Mix automatique : combinaison variée de rôles éditoriaux (performance, story, opinion…) tirés aléatoirement."
                : "Les 3 variants utiliseront ce rôle."}
            </span>
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
          {genJobActive && (
            <div className="web-search-status" role="status" aria-live="polite">
              <Loader2 size={16} className="spinning" />
              <span>
                <strong>Génération en cours…</strong>
                <span>Tu peux quitter cette page — le résultat apparaîtra ici une fois prêt.</span>
              </span>
            </div>
          )}
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
                <PostActionsBar
                  publishBusy={publishing === i && published !== i}
                  publishLabel={published === i ? "Publié ✓" : publishing === i ? "Publication…" : "Publier"}
                  publishActions={[
                    {
                      key: "linkedin",
                      icon: <Linkedin size={14} />,
                      label: published === i ? "Publié sur LinkedIn ✓" : "Publier maintenant sur LinkedIn",
                      disabled: publishing === i,
                      title: linkedin.status?.connected ? "Publier maintenant sur LinkedIn" : "Connecte ton compte LinkedIn dans l'onglet Profil",
                      onClick: () => publishVariant(i, editedVariants[i] ?? v.post),
                    },
                    {
                      key: "schedule",
                      icon: <Clock3 size={14} />,
                      label: scheduledIndices[i] ? "Programmé ✓" : "Programmer…",
                      disabled: publishing === i || !!scheduledIndices[i],
                      title: linkedin.status?.connected
                        ? "Programmer : publication directe à une date, ou validation Slack au préalable"
                        : "Connecte ton compte LinkedIn dans l'onglet Profil",
                      onClick: () => openScheduleModal(i, editedVariants[i] ?? v.post),
                    },
                    ...(slack.status?.connected && v.id
                      ? [{
                          key: "slack",
                          icon: <Send size={14} />,
                          label: slackSent[i] ? "Sur Slack ✓" : "Envoyer sur Slack pour validation",
                          disabled: !!slackSending[i] || !!slackSent[i],
                          onClick: () => setConfirmSlackIndex(i),
                        } satisfies PostAction]
                      : []),
                    ...(twitter.status?.connected
                      ? [{
                          key: "x",
                          icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.742l7.734-8.842L1.254 2.25H8.08l4.253 5.622L18.244 2.25zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>,
                          label: publishingX === i ? "Publication…" : publishedX === i ? "Publié sur X ✓" : "Publier sur X",
                          disabled: publishingX === i,
                          onClick: () => publishVariantX(i, editedVariants[i] ?? v.post),
                        } satisfies PostAction]
                      : []),
                  ]}
                  moreActions={[
                    ...(v.id
                      ? [{
                          key: "save",
                          icon: <Bookmark size={14} />,
                          label: savedVariant === i ? "Sauvegardé ✓" : "Sauvegarder",
                          disabled: savingVariant === i,
                          title: "Sauvegarder ce post dans « Mes contenus »",
                          onClick: () => saveVariant(i, editedVariants[i] ?? v.post, v.id),
                        } satisfies PostAction]
                      : []),
                    {
                      key: "attach",
                      icon: <ImagePlus size={14} />,
                      label: "Joindre des images",
                      filePicker: {
                        accept: "image/png,image/jpeg,image/jpg,image/webp,image/gif",
                        multiple: true,
                        onFiles: (files) => addUploadedImages(i, files),
                      },
                    },
                    {
                      key: "image-ia",
                      icon: <ImageIcon size={14} />,
                      label: "Générer une image IA",
                      title: "Prépare un prompt d'illustration à valider, puis génère l'image (5 crédits)",
                      onClick: () => setImageModal({ index: i, text: editedVariants[i] ?? v.post }),
                    },
                    ...(onRework
                      ? [{
                          key: "rework",
                          icon: <MessageSquare size={14} />,
                          label: "Retravailler avec l'Agent IA",
                          title: "Ouvrir ce post dans l'Agent IA pour le retravailler",
                          onClick: () => onRework(editedVariants[i] ?? v.post),
                        } satisfies PostAction]
                      : []),
                  ]}
                />
                {confirmSlackIndex === i && (
                  <div className="idea-footer" style={{ gap: 8, marginTop: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <span style={{ fontSize: 13 }}>Envoyer ce post sur Slack pour validation ?</span>
                    <DevSlackNote />
                    <button
                      className="primary-button"
                      style={{ fontSize: 12, minHeight: 30, padding: "0 10px" }}
                      disabled={!!slackSending[i]}
                      onClick={async () => {
                        setSlackSending((p) => ({ ...p, [i]: true }));
                        try {
                          await fetch(`${DIRECT_API_URL}/me/integrations/slack/send-posts`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json", ...(await authHeaders()) },
                            body: JSON.stringify({ post_id: v.id, content: editedVariants[i] ?? v.post, images: imagePayloadForVariant(i) }),
                          });
                          setSlackSent((p) => ({ ...p, [i]: true }));
                        } finally {
                          setSlackSending((p) => ({ ...p, [i]: false }));
                          setConfirmSlackIndex(null);
                        }
                      }}
                    >
                      {slackSending[i] ? <Loader2 size={12} className="spinning" /> : null} Confirmer l&apos;envoi
                    </button>
                    <button className="secondary-button" style={{ fontSize: 12, minHeight: 30, padding: "0 10px" }} onClick={() => setConfirmSlackIndex(null)}>Annuler</button>
                  </div>
                )}
                {published === i && (
                  <p className="role-picker-hint" style={{ marginTop: 6 }}>Post publié sur LinkedIn ✓</p>
                )}
                {publishedX === i && (
                  <p className="role-picker-hint" style={{ marginTop: 6 }}>Post publié sur X ✓</p>
                )}
                {scheduledIndices[i] && (
                  <p className="role-picker-hint" style={{ marginTop: 6 }}>
                    {scheduledIndices[i] === "slack" ? "Post programmé ✓ — demande de validation envoyée sur Slack." : "Post programmé sur LinkedIn ✓"}
                  </p>
                )}
                {(variantImages[i] || []).length > 0 && (
                  <div style={{ marginTop: 12 }}>
                    <p className="role-picker-hint" style={{ marginBottom: 8 }}>
                      {(variantImages[i] || []).length} image{(variantImages[i] || []).length > 1 ? "s" : ""} jointe{(variantImages[i] || []).length > 1 ? "s" : ""} au post LinkedIn.
                    </p>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 10, maxWidth: 640 }}>
                      {(variantImages[i] || []).map((image, imageIndex) => (
                        <div key={image.id} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 8, background: "var(--surface)" }}>
                          <img src={image.url} alt={`Image jointe ${imageIndex + 1}`} style={{ width: "100%", aspectRatio: "1 / 1", objectFit: "cover", borderRadius: 6, display: "block" }} />
                          <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
                            <a
                              href={image.url}
                              download={image.filename || `post-image-${i + 1}-${imageIndex + 1}.png`}
                              className="secondary-button"
                              style={{ minHeight: 28, padding: "0 8px", fontSize: 12, textDecoration: "none" }}
                            >
                              <Download size={12} /> Télécharger
                            </a>
                            <button
                              className="secondary-button"
                              style={{ minHeight: 28, padding: "0 8px", fontSize: 12 }}
                              onClick={() => removeVariantImage(i, image.id)}
                            >
                              <Trash2 size={12} /> Retirer
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      {publishError && <div className="error" style={{ marginTop: 12 }}>{publishError}</div>}
      {imageError && <div className="error" style={{ marginTop: 12 }}>{imageError}</div>}

      {imageModal && (
        <ImageGenModal
          postText={imageModal.text}
          onClose={() => setImageModal(null)}
          onGenerated={(dataUrl) => attachGeneratedImage(imageModal.index, dataUrl)}
        />
      )}

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
            {(variantImages[confirmIndex] || []).length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <p className="role-picker-hint" style={{ marginBottom: 8 }}>
                  {(variantImages[confirmIndex] || []).length} image{(variantImages[confirmIndex] || []).length > 1 ? "s" : ""} {(variantImages[confirmIndex] || []).length > 1 ? "seront jointes" : "sera jointe"}.
                </p>
                <div style={{ display: "flex", gap: 8, overflowX: "auto" }}>
                  {(variantImages[confirmIndex] || []).map((image, idx) => (
                    <img
                      key={image.id}
                      src={image.url}
                      alt={`Image jointe ${idx + 1}`}
                      style={{ width: 86, height: 86, objectFit: "cover", borderRadius: 8, border: "1px solid var(--border)" }}
                    />
                  ))}
                </div>
              </div>
            )}
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
        <SchedulePostModal
          text={scheduleModal.text}
          images={scheduleModal.images}
          slackConnected={!!slack.status?.connected}
          onClose={() => setScheduleModal(null)}
          onScheduled={(viaSlack) => {
            setScheduledIndices((prev) => ({ ...prev, [scheduleModal.index]: viaSlack ? "slack" : "direct" }));
            setScheduleModal(null);
          }}
        />
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

type DailyIdea = { id: string; idea_date: string; idea_markdown: string; seed_id?: string | null; created_at?: string; post_text?: string | null; editorial_role?: string | null; hook_type?: string | null; strategy?: string | null; predicted_lift?: string | null; image_url?: string | null; source_url?: string | null };
type IdeaSeed = { id: string; text: string; comment?: string | null; used_at?: string | null; created_at?: string };
type IdeaLine = { id?: string; line: string; source_type?: string; source_ref?: string; source_url?: string };
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
  onRework,
  reservoirOnly = false,
}: {
  isAuthed: boolean;
  requireAuth: (reason?: string) => void;
  onReuse: (topic: string) => void;
  onRework?: (post: string) => void;
  reservoirOnly?: boolean;
}) {
  const [ideas, setIdeas] = useState<DailyIdea[]>([]);
  const [seeds, setSeeds] = useState<IdeaSeed[]>([]);
  const [enabled, setEnabled] = useState(false);
  const [draft, setDraft] = useState("");
  const [draftComment, setDraftComment] = useState("");
  const [loading, setLoading] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const [dragId, setDragId] = useState<string | null>(null);
  // Drag armé uniquement quand on saisit la poignée (le texte reste sélectionnable).
  const [dragArmedId, setDragArmedId] = useState<string | null>(null);
  // Édition d'une idée du réservoir.
  const [editingSeedId, setEditingSeedId] = useState<string | null>(null);
  const [editSeedText, setEditSeedText] = useState("");
  const [editSeedComment, setEditSeedComment] = useState("");
  const [savingSeedEdit, setSavingSeedEdit] = useState(false);

  // ALE-143 : lot d'idées « une ligne »
  const [ideaBatch, setIdeaBatch] = useState<IdeaLine[]>([]);
  const [generatingBatch, setGeneratingBatch] = useState(false);
  const [batchWebSearch, setBatchWebSearch] = useState(false);
  const [batchError, setBatchError] = useState("");
  const [copiedLineId, setCopiedLineId] = useState<string | null>(null);

  async function generateIdeaBatch() {
    if (!isAuthed) { requireAuth("Connecte-toi pour générer des idées."); return; }
    setGeneratingBatch(true); setBatchError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/ideas`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ count: 15, web_search: batchWebSearch }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Génération impossible");
      setIdeaBatch(Array.isArray(data.ideas) ? data.ideas : []);
    } catch (err: any) {
      setBatchError(err.message || "Erreur lors de la génération");
    } finally {
      setGeneratingBatch(false);
    }
  }

  // ALE-136 : le post du jour est postable (copier / sauvegarder / publier / programmer).
  const linkedin = useLinkedIn(isAuthed);
  const twitter = useTwitter(isAuthed);
  const slack = useSlack(isAuthed);
  const [editedPost, setEditedPost] = useState<Record<string, string>>({});
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [savedId, setSavedId] = useState<string | null>(null);
  const [confirmPublishId, setConfirmPublishId] = useState<string | null>(null);
  const [publishingId, setPublishingId] = useState<string | null>(null);
  const [publishedId, setPublishedId] = useState<string | null>(null);
  const [scheduleModalIdea, setScheduleModalIdea] = useState<DailyIdea | null>(null);
  const [scheduledId, setScheduledId] = useState<string | null>(null);
  const [postError, setPostError] = useState("");
  const [publishingXId, setPublishingXId] = useState<string | null>(null);
  const [publishedXId, setPublishedXId] = useState<string | null>(null);
  const [confirmXId, setConfirmXId] = useState<string | null>(null);
  // Génération d'image IA : pop-up de validation du prompt + images jointes (data URLs) par idée.
  const [imageModalIdea, setImageModalIdea] = useState<DailyIdea | null>(null);
  const [ideaImages, setIdeaImages] = useState<Record<string, string[]>>({});

  const postTextOf = (it: DailyIdea) => editedPost[it.id] ?? it.post_text ?? "";

  // Images jointes à la publication : photo d'annonce éventuelle + images IA générées.
  const ideaImagePayload = (it: DailyIdea) => [
    ...(it.image_url ? [{ url: it.image_url }] : []),
    ...(ideaImages[it.id] || []).map((u, n) => ({ url: u, filename: `image-ia-${n + 1}.png` })),
  ];

  function copyPost(it: DailyIdea) {
    navigator.clipboard.writeText(postTextOf(it));
    setCopiedId(it.id);
    setTimeout(() => setCopiedId((c) => (c === it.id ? null : c)), 1500);
  }

  async function savePost(it: DailyIdea) {
    setPostError("");
    setSavingId(it.id);
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/generated-posts`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({
          post: postTextOf(it),
          topic: "Idée du jour",
          editorial_role: it.editorial_role,
          hook_type: it.hook_type,
          strategy: it.strategy,
          predicted_lift: it.predicted_lift,
        }),
      });
      if (res.ok) {
        setSavedId(it.id);
        setTimeout(() => setSavedId((s) => (s === it.id ? null : s)), 1500);
      }
    } finally {
      setSavingId(null);
    }
  }

  async function publishPost(it: DailyIdea) {
    setConfirmPublishId(null);
    if (!linkedin.status?.connected) {
      setPostError("Connecte ton compte LinkedIn dans l'onglet Profil.");
      return;
    }
    setPostError("");
    setPublishingId(it.id);
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/linkedin/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({
          content: postTextOf(it),
          draft: false,
          images: ideaImagePayload(it),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Publication impossible");
      setPublishedId(it.id);
      setTimeout(() => setPublishedId((s) => (s === it.id ? null : s)), 3000);
    } catch (err: any) {
      setPostError(err.message);
    } finally {
      setPublishingId(null);
    }
  }

  function openSchedule(it: DailyIdea) {
    if (!linkedin.status?.connected) {
      setPostError("Connecte d'abord ton compte LinkedIn dans l'onglet Profil.");
      return;
    }
    setPostError("");
    setScheduleModalIdea(it);
  }

  async function publishPostX(it: DailyIdea) {
    setConfirmXId(null);
    setPublishingXId(it.id);
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/x/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ content: postTextOf(it), draft: false }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Publication sur X impossible");
      setPublishedXId(it.id);
      setTimeout(() => setPublishedXId((s) => (s === it.id ? null : s)), 3000);
    } catch (err: any) {
      setPostError(err.message);
    } finally {
      setPublishingXId(null);
    }
  }

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
      // Compte restreint : seul le réservoir est utile (pas de corpus → pas d'idée du jour).
      const sRes = await fetch(`${DIRECT_API_URL}/me/idea-seeds`, { headers });
      const sData = await sRes.json();
      if (!sRes.ok) throw new Error(sData.detail || "Chargement du réservoir impossible");
      setSeeds(Array.isArray(sData) ? sData : []);
      if (!reservoirOnly) {
        const dRes = await fetch(`${DIRECT_API_URL}/me/daily-ideas`, { headers });
        const dData = await dRes.json();
        if (!dRes.ok) throw new Error(dData.detail || "Chargement des idées impossible");
        setIdeas(Array.isArray(dData?.ideas) ? dData.ideas : []);
        setEnabled(!!dData?.enabled);
      }
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
    // Le commentaire d'orientation n'a de sens que pour un lien d'annonce.
    const isLinkDraft = /^https?:\/\/\S+$/i.test(text);
    const comment = isLinkDraft ? draftComment.trim() : "";
    setAdding(true);
    setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/idea-seeds`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify(comment ? { text, comment } : { text }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Ajout impossible");
      setSeeds((prev) => [...prev, data]);
      setDraft("");
      setDraftComment("");
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

  // Glisser-déposer : réordonne le réservoir. Le cron (idée du jour / posts hebdo)
  // pioche ensuite dans ce nouvel ordre.
  function reorderTo(targetId: string) {
    if (!dragId || dragId === targetId) return;
    setSeeds((prev) => {
      const from = prev.findIndex((s) => s.id === dragId);
      const to = prev.findIndex((s) => s.id === targetId);
      if (from < 0 || to < 0 || from === to) return prev;
      const next = [...prev];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      return next;
    });
  }

  async function persistSeedOrder() {
    setDragId(null);
    try {
      const ordered_ids = seeds.map((s) => s.id);
      await fetch(`${DIRECT_API_URL}/me/idea-seeds/reorder`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ ordered_ids }),
      });
    } catch { void loadAll(); }
  }

  // Édition d'une idée du réservoir (texte + commentaire d'orientation).
  function startSeedEdit(s: IdeaSeed) {
    setEditingSeedId(s.id);
    setEditSeedText(s.text || "");
    setEditSeedComment(s.comment || "");
    setError("");
  }

  async function saveSeedEdit(id: string) {
    const text = editSeedText.trim();
    if (text.length < 3) return;
    const isLinkEdit = /^https?:\/\/\S+$/i.test(text);
    // Le commentaire d'orientation n'a de sens que pour un lien d'annonce ;
    // "" = effacer côté backend.
    const comment = isLinkEdit ? editSeedComment.trim() : "";
    setSavingSeedEdit(true);
    setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/idea-seeds/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ text, comment }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Modification impossible");
      setSeeds((prev) => prev.map((s) => (s.id === id ? data : s)));
      setEditingSeedId(null);
    } catch (err: any) {
      setError(err.message || "Modification impossible");
    } finally {
      setSavingSeedEdit(false);
    }
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
      {reservoirOnly && (
        <div className="section-header">
          <div>
            <h2 className="section-title"><Lightbulb size={20} /> Mes idées de posts</h2>
            <p className="section-desc">Ajoute ici tes idées de posts : on s'en sert pour rédiger tes contenus.</p>
          </div>
        </div>
      )}
      {!reservoirOnly && (
      <>
      {/* ALE-143 : bloc « Générer des idées » — lot de one-liners scannables */}
      <section className="card ideas-batch-section">
        <div className="ideas-batch-header">
          <div>
            <h3 style={{ margin: "0 0 4px" }}>💡 Générer des idées</h3>
            <p className="section-desc" style={{ margin: 0 }}>
              Un lot de 15 idées en une ligne, ancrées dans tes vrais posts performants. 3 crédits/lot.
            </p>
          </div>
          <div className="ideas-batch-actions">
            <label className="ideas-web-toggle">
              <input type="checkbox" checked={batchWebSearch} onChange={(e) => setBatchWebSearch(e.target.checked)} />
              <span>Chercher sur le web</span>
            </label>
            <button className="primary-button" onClick={generateIdeaBatch} disabled={generatingBatch}>
              {generatingBatch ? <Loader2 size={14} className="spinning" /> : <Sparkles size={14} />}
              {generatingBatch ? "Génération…" : "Générer"}
            </button>
          </div>
        </div>
        {batchError && <div className="error" style={{ marginTop: 8 }}>{batchError}</div>}
        {ideaBatch.length > 0 && (
          <ul className="ideas-batch-list">
            {ideaBatch.map((idea, i) => (
              <li key={idea.id ?? i} className="idea-line-item">
                <span className="idea-line-text">{idea.line}</span>
                {idea.source_ref && (
                  <span className="idea-line-source">
                    {idea.source_url ? (
                      <a href={idea.source_url} target="_blank" rel="noopener noreferrer">{idea.source_ref}</a>
                    ) : (
                      idea.source_ref
                    )}
                  </span>
                )}
                <div className="idea-line-actions">
                  <button
                    className="secondary-button"
                    style={{ fontSize: 12, minHeight: 28, padding: "0 8px" }}
                    onClick={() => {
                      navigator.clipboard.writeText(idea.line);
                      setCopiedLineId(String(idea.id ?? i));
                      setTimeout(() => setCopiedLineId((c) => c === String(idea.id ?? i) ? null : c), 1500);
                    }}
                  >
                    {copiedLineId === String(idea.id ?? i) ? <CheckCircle2 size={12} /> : <Copy size={12} />}
                  </button>
                  <button
                    className="primary-button"
                    style={{ fontSize: 12, minHeight: 28, padding: "0 8px" }}
                    onClick={() => onReuse(idea.line)}
                  >
                    <Sparkles size={12} /> Développer
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="section-header" style={{ marginTop: 24 }}>
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
        <div className="daily-ideas-lines">
          {ideas.map((it, idx) => {
            const isPost = !!it.post_text;
            const idea = isPost ? null : parseDailyIdeaMarkdown(it.idea_markdown);
            return (
              <details className="card daily-idea-line" key={it.id} open={idx === 0}>
                {/* Ligne fermée = date seule (demande Alex 2026-07-03 : pas d'extrait, trop d'info). */}
                <summary>
                  <span className="daily-line-date">{fmtDate(it.idea_date)}</span>
                  {idx === 0 ? <span className="daily-today-tag">Aujourd'hui</span> : null}
                </summary>
                <div className="daily-line-body">
                  {isPost ? (
                    <>
                      {it.image_url && (
                        <div className="daily-listing-image" style={{ marginBottom: 10 }}>
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img
                            src={it.image_url}
                            alt="Photo du bien"
                            style={{ width: "100%", maxHeight: 220, objectFit: "cover", borderRadius: 8, display: "block" }}
                          />
                          <p className="section-desc" style={{ margin: "6px 0 0", fontSize: 12 }}>
                            <Linkedin size={11} style={{ verticalAlign: "-1px" }} /> Photo de l'annonce — rattachée automatiquement à la publication
                            {it.source_url && <> · <a href={it.source_url} target="_blank" rel="noreferrer">voir l'annonce</a></>}
                          </p>
                        </div>
                      )}
                      <div className="variant-text-wrap">
                        <textarea
                          className="variant-text"
                          rows={10}
                          value={postTextOf(it)}
                          onChange={(e) => setEditedPost((p) => ({ ...p, [it.id]: e.target.value }))}
                          style={{ width: "100%", boxSizing: "border-box" }}
                        />
                        <button
                          type="button"
                          className="variant-copy-button"
                          aria-label={copiedId === it.id ? "Post copié" : "Copier le post"}
                          title={copiedId === it.id ? "Copié ✓" : "Copier le post"}
                          onClick={() => copyPost(it)}
                        >
                          {copiedId === it.id ? <CheckCircle2 size={16} /> : <Copy size={16} />}
                        </button>
                      </div>
                      <PostActionsBar
                        publishBusy={publishingId === it.id}
                        publishLabel={publishedId === it.id ? "Publié ✓" : publishingId === it.id ? "Publication…" : "Publier"}
                        publishActions={[
                          {
                            key: "linkedin",
                            icon: <Linkedin size={14} />,
                            label: publishedId === it.id ? "Publié sur LinkedIn ✓" : "Publier maintenant sur LinkedIn",
                            disabled: publishingId === it.id,
                            title: linkedin.status?.connected ? "Publier maintenant sur LinkedIn" : "Connecte ton compte LinkedIn dans l'onglet Profil",
                            onClick: () => setConfirmPublishId(it.id),
                          },
                          {
                            key: "schedule",
                            icon: <Clock3 size={14} />,
                            label: scheduledId === it.id ? "Programmé ✓" : "Programmer…",
                            title: linkedin.status?.connected
                              ? "Programmer : publication directe à une date, ou validation Slack au préalable"
                              : "Connecte ton compte LinkedIn dans l'onglet Profil",
                            onClick: () => openSchedule(it),
                          },
                          ...(twitter.status?.connected
                            ? [{
                                key: "x",
                                icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.742l7.734-8.842L1.254 2.25H8.08l4.253 5.622L18.244 2.25zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>,
                                label: publishingXId === it.id ? "Publication…" : publishedXId === it.id ? "Publié sur X ✓" : "Publier sur X",
                                disabled: publishingXId === it.id,
                                onClick: () => setConfirmXId(it.id),
                              } satisfies PostAction]
                            : []),
                        ]}
                        moreActions={[
                          {
                            key: "save",
                            icon: <Bookmark size={14} />,
                            label: savedId === it.id ? "Sauvegardé ✓" : "Sauvegarder",
                            disabled: savingId === it.id,
                            title: "Sauvegarder ce post dans « Mes contenus »",
                            onClick: () => savePost(it),
                          },
                          {
                            key: "image-ia",
                            icon: <ImageIcon size={14} />,
                            label: "Générer une image IA",
                            title: "Prépare un prompt d'illustration à valider, puis génère l'image (5 crédits)",
                            onClick: () => setImageModalIdea(it),
                          },
                          ...(onRework
                            ? [{
                                key: "rework",
                                icon: <MessageSquare size={14} />,
                                label: "Retravailler avec l'Agent IA",
                                title: "Ouvrir ce post dans l'Agent IA pour le retravailler",
                                onClick: () => onRework(postTextOf(it)),
                              } satisfies PostAction]
                            : []),
                        ]}
                      />
                      {(ideaImages[it.id] || []).length > 0 && (
                        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 10, maxWidth: 640, marginTop: 12 }}>
                          {(ideaImages[it.id] || []).map((u, n) => (
                            <div key={n} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 8, background: "var(--surface)" }}>
                              {/* eslint-disable-next-line @next/next/no-img-element */}
                              <img src={u} alt={`Image IA ${n + 1}`} style={{ width: "100%", aspectRatio: "1 / 1", objectFit: "cover", borderRadius: 6, display: "block" }} />
                              <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
                                <a href={u} download={`image-ia-${n + 1}.png`} className="secondary-button" style={{ minHeight: 28, padding: "0 8px", fontSize: 12, textDecoration: "none" }}>
                                  <Download size={12} /> Télécharger
                                </a>
                                <button
                                  className="secondary-button"
                                  style={{ minHeight: 28, padding: "0 8px", fontSize: 12 }}
                                  onClick={() => setIdeaImages((prev) => ({ ...prev, [it.id]: (prev[it.id] || []).filter((_, k) => k !== n) }))}
                                >
                                  <Trash2 size={12} /> Retirer
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                      {confirmPublishId === it.id && (
                        <div className="idea-footer" style={{ gap: 8, marginTop: 8, alignItems: "center", flexWrap: "wrap" }}>
                          <span style={{ fontSize: 13 }}>Publier ce post maintenant sur LinkedIn ?</span>
                          <button className="primary-button" style={{ fontSize: 12, minHeight: 30, padding: "0 10px" }} onClick={() => publishPost(it)}>Confirmer</button>
                          <button className="secondary-button" style={{ fontSize: 12, minHeight: 30, padding: "0 10px" }} onClick={() => setConfirmPublishId(null)}>Annuler</button>
                        </div>
                      )}
                      {scheduleModalIdea?.id === it.id && (
                        <SchedulePostModal
                          text={postTextOf(it)}
                          images={ideaImagePayload(it)}
                          slackConnected={!!slack.status?.connected}
                          onClose={() => setScheduleModalIdea(null)}
                          onScheduled={() => {
                            setScheduledId(it.id);
                            setScheduleModalIdea(null);
                            setTimeout(() => setScheduledId((s) => (s === it.id ? null : s)), 3000);
                          }}
                        />
                      )}
                      {confirmXId === it.id && (
                        <div className="idea-footer" style={{ gap: 8, marginTop: 8, alignItems: "center", flexWrap: "wrap" }}>
                          <span style={{ fontSize: 13 }}>Publier ce post maintenant sur X ?</span>
                          <button className="primary-button" style={{ fontSize: 12, minHeight: 30, padding: "0 10px" }} onClick={() => publishPostX(it)}>Confirmer</button>
                          <button className="secondary-button" style={{ fontSize: 12, minHeight: 30, padding: "0 10px" }} onClick={() => setConfirmXId(null)}>Annuler</button>
                        </div>
                      )}
                    </>
                  ) : (
                    <>
                      {idea!.hook && <p className="idea-hook">"{idea!.hook}"</p>}
                      {idea!.angle && <p className="idea-angle">{idea!.angle}</p>}
                      {idea!.why_it_works && <p className="idea-why"><strong>Pourquoi ça marche :</strong> {idea!.why_it_works}</p>}
                      <div className="idea-footer" style={{ flexWrap: "wrap", gap: 8, marginTop: 10 }}>
                        {idea!.funnel && <span className="idea-funnel">{idea!.funnel}</span>}
                        {idea!.hook_type && <span className="badge">{idea!.hook_type}</span>}
                        <button
                          className="primary-button"
                          style={{ fontSize: 12, minHeight: 30, padding: "0 10px", marginLeft: "auto" }}
                          onClick={() => onReuse(idea!.title)}
                        >
                          <Sparkles size={12} /> Générer ce post
                        </button>
                      </div>
                    </>
                  )}
                </div>
              </details>
            );
          })}
        </div>
      )}
      {postError && <div className="error" style={{ marginTop: 8 }}>{postError}</div>}
      {imageModalIdea && (
        <ImageGenModal
          postText={postTextOf(imageModalIdea)}
          onClose={() => setImageModalIdea(null)}
          onGenerated={(dataUrl) => setIdeaImages((prev) => ({
            ...prev,
            [imageModalIdea.id]: [...(prev[imageModalIdea.id] || []), dataUrl],
          }))}
        />
      )}
      </>
      )}

      <div className="card daily-reservoir" style={{ marginTop: reservoirOnly ? 0 : 24 }}>
        <div className="daily-reservoir-head">
          <div>
            <h3 className="daily-subtitle" style={{ margin: 0 }}><Lightbulb size={16} /> Mon réservoir d'idées</h3>
            <p className="section-desc" style={{ margin: "4px 0 0" }}>Ajoute tes idées, ou colle le <strong>lien d'une annonce</strong> : l'idée du jour piochera dedans en priorité. Un lien d'annonce génère un post avec la photo du bien.</p>
          </div>
          {!reservoirOnly && (
            <label className="daily-switch">
              <input type="checkbox" checked={enabled} onChange={toggleEnabled} />
              <span>Recevoir une idée chaque matin</span>
            </label>
          )}
        </div>

        {reservoirOnly && error && <div className="error" style={{ marginTop: 12 }}>{error}</div>}

        <div className="daily-add">
          <input
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void addSeed(); } }}
            placeholder="Une idée de post, ou un lien d'annonce (https://…)"
            maxLength={2000}
          />
          <button className="primary-button" onClick={addSeed} disabled={adding || draft.trim().length < 3}>
            {adding ? <Loader2 size={14} className="spinning" /> : <PlusCircle size={14} />} Ajouter
          </button>
        </div>
        {/* Champ d'orientation : uniquement quand l'idée saisie est un lien d'annonce. */}
        {/^https?:\/\/\S+$/i.test(draft.trim()) && (
          <input
            type="text"
            value={draftComment}
            onChange={(e) => setDraftComment(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void addSeed(); } }}
            placeholder="Commentaire pour orienter le post (optionnel) — ex. « insiste sur la vue mer »"
            maxLength={500}
            style={{ marginTop: 8, width: "100%", boxSizing: "border-box" }}
          />
        )}

        {seeds.length === 0 ? (
          <p style={{ color: "var(--muted)", margin: "12px 0 0", fontSize: 13 }}>Réservoir vide — l'idée du jour s'appuiera sur ton seul benchmark.</p>
        ) : (
          <ul className="daily-seed-list">
            {seeds.map((s) => {
              const isLink = /^https?:\/\/\S+$/i.test((s.text || "").trim());
              const isEditing = editingSeedId === s.id;
              const editIsLink = /^https?:\/\/\S+$/i.test(editSeedText.trim());
              return (
              <li
                key={s.id}
                className={`${s.used_at ? "used" : ""}${dragId === s.id ? " dragging" : ""}`}
                // Drag armé uniquement depuis la poignée : le texte reste sélectionnable.
                draggable={dragArmedId === s.id && !isEditing}
                onDragStart={() => setDragId(s.id)}
                onDragOver={(e) => { e.preventDefault(); reorderTo(s.id); }}
                onDrop={(e) => { e.preventDefault(); setDragArmedId(null); void persistSeedOrder(); }}
                onDragEnd={() => { setDragArmedId(null); void persistSeedOrder(); }}
              >
                <span
                  className="daily-seed-grip"
                  title="Glisser pour réordonner"
                  aria-hidden
                  onMouseDown={() => setDragArmedId(s.id)}
                  onMouseUp={() => setDragArmedId(null)}
                  onTouchStart={() => setDragArmedId(s.id)}
                >
                  <GripVertical size={14} />
                </span>
                {isEditing ? (
                  <span className="daily-seed-text" style={{ display: "grid", gap: 6 }}>
                    <input
                      type="text"
                      value={editSeedText}
                      autoFocus
                      onChange={(e) => setEditSeedText(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void saveSeedEdit(s.id); } if (e.key === "Escape") setEditingSeedId(null); }}
                      maxLength={2000}
                      style={{ width: "100%", boxSizing: "border-box" }}
                    />
                    {editIsLink && (
                      <input
                        type="text"
                        value={editSeedComment}
                        onChange={(e) => setEditSeedComment(e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void saveSeedEdit(s.id); } if (e.key === "Escape") setEditingSeedId(null); }}
                        placeholder="Commentaire pour orienter le post (optionnel)"
                        maxLength={500}
                        style={{ width: "100%", boxSizing: "border-box" }}
                      />
                    )}
                    <span style={{ display: "flex", gap: 6 }}>
                      <button
                        className="primary-button"
                        style={{ fontSize: 12, minHeight: 28, padding: "0 10px" }}
                        disabled={savingSeedEdit || editSeedText.trim().length < 3}
                        onClick={() => void saveSeedEdit(s.id)}
                      >
                        {savingSeedEdit ? <Loader2 size={12} className="spinning" /> : null} Sauvegarder
                      </button>
                      <button className="secondary-button" style={{ fontSize: 12, minHeight: 28, padding: "0 10px" }} onClick={() => setEditingSeedId(null)}>Annuler</button>
                    </span>
                  </span>
                ) : (
                  <span className="daily-seed-text">
                    {isLink ? <><Linkedin size={12} style={{ verticalAlign: "-2px", opacity: 0.6 }} /> {s.text}</> : s.text}
                    {s.comment ? <em style={{ display: "block", fontSize: 12, color: "var(--muted)", marginTop: 2 }}>↳ orientation : {s.comment}</em> : null}
                  </span>
                )}
                {!isEditing && isLink && !s.used_at ? <span className="daily-seed-tag">annonce</span> : null}
                {!isEditing && s.used_at ? <span className="daily-seed-tag"><CheckCircle2 size={12} /> utilisée</span> : null}
                {!isEditing && (
                  <button className="icon-button" title="Modifier" onClick={() => startSeedEdit(s)}><Pencil size={14} /></button>
                )}
                <button className="icon-button" title="Supprimer" onClick={() => deleteSeed(s.id)}><Trash2 size={14} /></button>
              </li>
              );
            })}
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
  onRework,
}: {
  isAuthed: boolean;
  requireAuth: (reason?: string) => void;
  onReuse: (topic: string) => void;
  onRework?: (post: string) => void;
}) {
  const [posts, setPosts] = useState<SavedPost[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState<string | null>(null);
  const [editedPosts, setEditedPosts] = useState<Record<string, string>>({});
  const [savingPost, setSavingPost] = useState<string | null>(null);
  const [savedPost, setSavedPost] = useState<string | null>(null);
  // Tiroir repliable : permet de masquer la liste des posts sauvegardés pour atteindre
  // la section « Posts programmés » sans scroller tout en bas.
  const [savedOpen, setSavedOpen] = useState(true);
  const slack = useSlack(isAuthed);
  const linkedin = useLinkedIn(isAuthed);
  const twitter = useTwitter(isAuthed);
  const [slackSent, setSlackSent] = useState<Record<string, boolean>>({});
  const [slackSending, setSlackSending] = useState<Record<string, boolean>>({});
  const [publishingPost, setPublishingPost] = useState<string | null>(null);
  const [publishedPost, setPublishedPost] = useState<string | null>(null);
  const [publishError, setPublishError] = useState("");
  const [scheduledPosts, setScheduledPosts] = useState<ScheduledPost[]>([]);
  const [cancellingPost, setCancellingPost] = useState<string | null>(null);
  const [editingSchedule, setEditingSchedule] = useState<ScheduledPost | null>(null);
  const [editScheduleText, setEditScheduleText] = useState("");
  const [editScheduleDate, setEditScheduleDate] = useState("");
  const [editingPost, setEditingPost] = useState<string | null>(null);
  const [scheduleEditError, setScheduleEditError] = useState("");

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

  function openEditScheduled(post: ScheduledPost) {
    if (post.status !== "pending") return;
    setEditingSchedule(post);
    setEditScheduleText(post.post_text);
    setEditScheduleDate(isoToDatetimeLocalValue(post.scheduled_at));
    setScheduleEditError("");
  }

  async function updateScheduled() {
    if (!editingSchedule) return;
    const trimmed = editScheduleText.trim();
    if (!trimmed) { setScheduleEditError("Le texte du post ne peut pas être vide."); return; }
    const localDate = new Date(editScheduleDate);
    if (Number.isNaN(localDate.getTime())) { setScheduleEditError("Date invalide."); return; }
    if (localDate <= new Date()) { setScheduleEditError("La date doit être dans le futur."); return; }
    setEditingPost(editingSchedule.id);
    setScheduleEditError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/linkedin/scheduled/${editingSchedule.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ post_text: trimmed, scheduled_at: localDate.toISOString() }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Modification impossible.");
      const updated = data.scheduled_post as ScheduledPost;
      setScheduledPosts((prev) => prev.map((p) => p.id === updated.id ? updated : p));
      setEditingSchedule(null);
    } catch (err: any) {
      setScheduleEditError(err.message);
    } finally {
      setEditingPost(null);
    }
  }

  const [confirmPublishPostId, setConfirmPublishPostId] = useState<string | null>(null);
  const [publishingXPost, setPublishingXPost] = useState<string | null>(null);
  const [publishedXPost, setPublishedXPost] = useState<string | null>(null);
  const [confirmXPostId, setConfirmXPostId] = useState<string | null>(null);
  const [confirmSlackPostId, setConfirmSlackPostId] = useState<string | null>(null);
  const [scheduleForPost, setScheduleForPost] = useState<string | null>(null);
  const [scheduledPostIds, setScheduledPostIds] = useState<Record<string, boolean>>({});
  // ALE-179 : joindre des images à un post sauvegardé.
  const [attachingPost, setAttachingPost] = useState<string | null>(null);
  const [imageErrorLib, setImageErrorLib] = useState("");
  // Génération d'image IA : pop-up de validation du prompt sur un post sauvegardé.
  const [imageModalSaved, setImageModalSaved] = useState<SavedPost | null>(null);

  async function publishSavedPost(p: SavedPost) {
    setConfirmPublishPostId(null);
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
        body: JSON.stringify({ content: text, draft: false, images: savedPostImagePayload(p) }),
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

  async function publishSavedPostX(p: SavedPost) {
    setConfirmXPostId(null);
    setPublishingXPost(p.id);
    try {
      const text = editedPosts[p.id] ?? p.post;
      const res = await fetch(`${DIRECT_API_URL}/me/x/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ content: text, draft: false }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Publication sur X impossible");
      setPublishedXPost(p.id);
      setTimeout(() => setPublishedXPost((s) => s === p.id ? null : s), 3000);
    } catch (err: any) {
      setPublishError(err.message);
    } finally {
      setPublishingXPost(null);
    }
  }

  function openSchedulePost(p: SavedPost) {
    if (!linkedin.status?.connected) {
      setPublishError("Connecte d'abord ton compte LinkedIn dans l'onglet Profil.");
      return;
    }
    setPublishError("");
    setScheduleForPost(p.id);
  }

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
      const pRes = await fetch(`${DIRECT_API_URL}/me/generated-posts`, { headers });
      const pData = await pRes.json();
      if (!pRes.ok) throw new Error(pData.detail || "Chargement des posts impossible");
      setPosts(Array.isArray(pData) ? pData : []);
    } catch (err: any) {
      setError(err.message || "Chargement impossible");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (isAuthed) void loadAll();
    else { setPosts([]); }
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

  // ALE-179 : images d'un post sauvegardé. Les media_items stockés sont des URLs
  // publiques (hébergées par le backend à la sauvegarde) → payload {url}.
  function savedPostImagePayload(p: SavedPost) {
    return (p.media_items || []).filter((m) => m?.url).map((m) => ({ url: m.url, filename: m.title || undefined }));
  }

  async function persistSavedPostImages(p: SavedPost, images: Array<{ url?: string; data_url?: string; filename?: string }>) {
    setAttachingPost(p.id);
    setImageErrorLib("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/generated-posts/${p.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ images }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Enregistrement des images impossible.");
      if (data.media_error) throw new Error("Hébergement des images impossible, réessaie.");
      setPosts((prev) => prev.map((pp) => (pp.id === p.id ? { ...pp, media_items: data.media_items || [] } : pp)));
    } catch (err: any) {
      setImageErrorLib(err.message || "Enregistrement des images impossible.");
    } finally {
      setAttachingPost(null);
    }
  }

  function attachImagesToSavedPost(p: SavedPost, files: FileList | null) {
    if (!files?.length) return;
    setImageErrorLib("");
    const imageFiles = Array.from(files).filter((file) => file.type.startsWith("image/"));
    if (imageFiles.length !== files.length) {
      setImageErrorLib("Seuls les fichiers image sont acceptés.");
    }
    const readers = imageFiles.map((file) => new Promise<{ data_url: string; filename: string } | null>((resolve) => {
      if (file.size > 8 * 1024 * 1024) {
        setImageErrorLib("LinkedIn limite chaque image à 8 Mo.");
        resolve(null);
        return;
      }
      const reader = new FileReader();
      reader.onload = () => resolve(typeof reader.result === "string" && reader.result ? { data_url: reader.result, filename: file.name } : null);
      reader.onerror = () => { setImageErrorLib(`Lecture impossible pour ${file.name}.`); resolve(null); };
      reader.readAsDataURL(file);
    }));
    void Promise.all(readers).then((added) => {
      const fresh = added.filter(Boolean) as Array<{ data_url: string; filename: string }>;
      if (!fresh.length) return;
      const images = [...savedPostImagePayload(p), ...fresh].slice(0, 20);
      void persistSavedPostImages(p, images);
    });
  }

  function removeSavedPostImage(p: SavedPost, url: string) {
    const images = savedPostImagePayload(p).filter((m) => m.url !== url);
    void persistSavedPostImages(p, images);
  }

  if (!isAuthed) {
    return (
      <div className="card" style={{ textAlign: "center", padding: 40 }}>
        <Bookmark size={28} style={{ opacity: 0.4, marginBottom: 12 }} />
        <h2 style={{ margin: "0 0 8px" }}>Mes contenus</h2>
        <p style={{ color: "var(--muted)", marginBottom: 16 }}>
          Connecte-toi pour retrouver les posts que tu as sauvegardés et les réutiliser.
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
        <button
          onClick={() => setSavedOpen((v) => !v)}
          aria-expanded={savedOpen}
          title={savedOpen ? "Replier les posts sauvegardés" : "Déplier les posts sauvegardés"}
          style={{ display: "flex", alignItems: "flex-start", gap: 8, background: "none", border: "none", padding: 0, cursor: "pointer", textAlign: "left", color: "inherit" }}
        >
          <ChevronRight size={20} style={{ marginTop: 2, flexShrink: 0, transform: savedOpen ? "rotate(90deg)" : "none", transition: "transform 0.15s" }} />
          <div>
            <h2 className="section-title"><Bookmark size={20} /> Mes contenus sauvegardés{posts.length ? ` (${posts.length})` : ""}</h2>
            <p className="section-desc">Retrouve les posts que tu as sauvegardés depuis le générateur. Relis-les, copie-les ou réutilise-les.</p>
          </div>
        </button>
        <button className="secondary-button" onClick={loadAll} disabled={loading}>
          {loading ? <Loader2 size={14} className="spinning" /> : <RefreshCw size={14} />}
          Rafraîchir
        </button>
      </div>

      {error &&<div className="error" style={{ marginBottom: 12 }}>{error}</div>}

      {!savedOpen ? null : loading && posts.length === 0 ? (
        <div className="card" style={{ padding: 32, textAlign: "center" }}>
          <Loader2 size={22} className="spinning" style={{ opacity: 0.45 }} />
          <p style={{ color: "var(--muted)" }}>Chargement de tes contenus…</p>
        </div>
      ) : (
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
                <PostActionsBar
                  publishBusy={publishingPost === p.id}
                  publishLabel={publishedPost === p.id ? "Publié ✓" : publishingPost === p.id ? "Publication…" : "Publier"}
                  publishActions={[
                    {
                      key: "linkedin",
                      icon: <Linkedin size={14} />,
                      label: publishedPost === p.id ? "Publié sur LinkedIn ✓" : "Publier maintenant sur LinkedIn",
                      disabled: publishingPost === p.id,
                      title: linkedin.status?.connected ? "Publier maintenant sur LinkedIn" : "Connecte ton compte LinkedIn dans l'onglet Profil",
                      onClick: () => setConfirmPublishPostId(p.id),
                    },
                    {
                      key: "schedule",
                      icon: <Clock3 size={14} />,
                      label: scheduledPostIds[p.id] ? "Programmé ✓" : "Programmer…",
                      disabled: !!scheduledPostIds[p.id],
                      title: linkedin.status?.connected
                        ? "Programmer : publication directe à une date, ou validation Slack au préalable"
                        : "Connecte ton compte LinkedIn dans l'onglet Profil",
                      onClick: () => openSchedulePost(p),
                    },
                    ...(slack.status?.connected
                      ? [{
                          key: "slack",
                          icon: <Send size={14} />,
                          label: slackSent[p.id] || p.slack_status === "pending" ? "Sur Slack ✓" : "Envoyer sur Slack pour validation",
                          disabled: !!slackSending[p.id] || !!slackSent[p.id] || p.slack_status === "pending",
                          onClick: () => setConfirmSlackPostId(p.id),
                        } satisfies PostAction]
                      : []),
                    ...(twitter.status?.connected
                      ? [{
                          key: "x",
                          icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.742l7.734-8.842L1.254 2.25H8.08l4.253 5.622L18.244 2.25zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>,
                          label: publishingXPost === p.id ? "Publication…" : publishedXPost === p.id ? "Publié sur X ✓" : "Publier sur X",
                          disabled: publishingXPost === p.id,
                          onClick: () => setConfirmXPostId(p.id),
                        } satisfies PostAction]
                      : []),
                  ]}
                  moreActions={[
                    {
                      key: "attach",
                      icon: attachingPost === p.id ? <Loader2 size={14} className="spinning" /> : <ImagePlus size={14} />,
                      label: "Joindre des images",
                      disabled: attachingPost === p.id,
                      filePicker: {
                        accept: "image/png,image/jpeg,image/jpg,image/webp,image/gif",
                        multiple: true,
                        onFiles: (files) => attachImagesToSavedPost(p, files),
                      },
                    },
                    {
                      key: "image-ia",
                      icon: <ImageIcon size={14} />,
                      label: "Générer une image IA",
                      disabled: attachingPost === p.id,
                      title: "Prépare un prompt d'illustration à valider, puis génère l'image (5 crédits)",
                      onClick: () => setImageModalSaved(p),
                    },
                    ...(p.topic
                      ? [{
                          key: "regen",
                          icon: <Sparkles size={14} />,
                          label: "Régénérer sur ce sujet",
                          onClick: () => onReuse(p.topic!),
                        } satisfies PostAction]
                      : []),
                    ...(onRework
                      ? [{
                          key: "rework",
                          icon: <MessageSquare size={14} />,
                          label: "Retravailler avec l'Agent IA",
                          title: "Ouvrir ce post dans l'Agent IA pour le retravailler",
                          onClick: () => onRework(editedPosts[p.id] ?? p.post),
                        } satisfies PostAction]
                      : []),
                    {
                      key: "delete",
                      icon: <Trash2 size={14} />,
                      label: "Supprimer",
                      danger: true,
                      onClick: () => deletePost(p.id),
                    },
                  ]}
                />
                {confirmPublishPostId === p.id && (
                  <div className="idea-footer" style={{ gap: 8, marginTop: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <span style={{ fontSize: 13 }}>Publier ce post maintenant sur LinkedIn ?</span>
                    <button className="primary-button" style={{ fontSize: 12, minHeight: 30, padding: "0 10px" }} onClick={() => publishSavedPost(p)}>Confirmer</button>
                    <button className="secondary-button" style={{ fontSize: 12, minHeight: 30, padding: "0 10px" }} onClick={() => setConfirmPublishPostId(null)}>Annuler</button>
                  </div>
                )}
                {scheduleForPost === p.id && (
                  <SchedulePostModal
                    text={editedPosts[p.id] ?? p.post}
                    images={savedPostImagePayload(p)}
                    slackConnected={!!slack.status?.connected}
                    onClose={() => setScheduleForPost(null)}
                    onScheduled={() => {
                      setScheduledPostIds((prev) => ({ ...prev, [p.id]: true }));
                      setScheduleForPost(null);
                    }}
                  />
                )}
                {confirmXPostId === p.id && (
                  <div className="idea-footer" style={{ gap: 8, marginTop: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <span style={{ fontSize: 13 }}>Publier ce post maintenant sur X ?</span>
                    <button className="primary-button" style={{ fontSize: 12, minHeight: 30, padding: "0 10px" }} onClick={() => publishSavedPostX(p)}>Confirmer</button>
                    <button className="secondary-button" style={{ fontSize: 12, minHeight: 30, padding: "0 10px" }} onClick={() => setConfirmXPostId(null)}>Annuler</button>
                  </div>
                )}
                {confirmSlackPostId === p.id && (
                  <div className="idea-footer" style={{ gap: 8, marginTop: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <span style={{ fontSize: 13 }}>Envoyer ce post sur Slack pour validation ?</span>
                    <DevSlackNote />
                    <button
                      className="primary-button"
                      style={{ fontSize: 12, minHeight: 30, padding: "0 10px" }}
                      disabled={!!slackSending[p.id]}
                      onClick={async () => {
                        setSlackSending((prev) => ({ ...prev, [p.id]: true }));
                        try {
                          await fetch(`${DIRECT_API_URL}/me/integrations/slack/send-posts`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json", ...(await authHeaders()) },
                            body: JSON.stringify({ post_id: p.id, content: editedPosts[p.id] ?? p.post, images: savedPostImagePayload(p) }),
                          });
                          setSlackSent((prev) => ({ ...prev, [p.id]: true }));
                          setPosts((prev) => prev.map((pp) => pp.id === p.id ? { ...pp, post: editedPosts[p.id] ?? pp.post, slack_status: "pending" } : pp));
                        } finally {
                          setSlackSending((prev) => ({ ...prev, [p.id]: false }));
                          setConfirmSlackPostId(null);
                        }
                      }}
                    >
                      {slackSending[p.id] ? <Loader2 size={12} className="spinning" /> : null} Confirmer l&apos;envoi
                    </button>
                    <button className="secondary-button" style={{ fontSize: 12, minHeight: 30, padding: "0 10px" }} onClick={() => setConfirmSlackPostId(null)}>Annuler</button>
                  </div>
                )}
                {(p.media_items || []).length > 0 && (
                  <div style={{ marginTop: 12 }}>
                    <p className="role-picker-hint" style={{ marginBottom: 8 }}>
                      {(p.media_items || []).length} image{(p.media_items || []).length > 1 ? "s" : ""} jointe{(p.media_items || []).length > 1 ? "s" : ""} au post LinkedIn.
                    </p>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 10, maxWidth: 640 }}>
                      {(p.media_items || []).map((image, imageIndex) => (
                        <div key={image.url} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 8, background: "var(--surface)" }}>
                          <img src={image.url} alt={`Image jointe ${imageIndex + 1}`} style={{ width: "100%", aspectRatio: "1 / 1", objectFit: "cover", borderRadius: 6, display: "block" }} />
                          <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
                            <a
                              href={image.url}
                              download={image.title || `post-image-${imageIndex + 1}.png`}
                              target="_blank"
                              rel="noreferrer"
                              className="secondary-button"
                              style={{ minHeight: 28, padding: "0 8px", fontSize: 12, textDecoration: "none" }}
                            >
                              <Download size={12} /> Télécharger
                            </a>
                            <button
                              className="secondary-button"
                              style={{ minHeight: 28, padding: "0 8px", fontSize: 12 }}
                              disabled={attachingPost === p.id}
                              onClick={() => removeSavedPostImage(p, image.url)}
                            >
                              <Trash2 size={12} /> Retirer
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {imageErrorLib && attachingPost === null && (
                  <div className="error" style={{ marginTop: 6, fontSize: 13 }}>{imageErrorLib}</div>
                )}
                {publishError && publishingPost === null && publishedPost === null && (
                  <div className="error" style={{ marginTop: 6, fontSize: 13 }}>{publishError}</div>
                )}
              </div>
            ))}
          </div>
        )
      )}

      {linkedin.status?.connected && (
        <div style={{ marginTop: 32 }}>
          <div className="section-header" style={{ marginBottom: 16 }}>
            <div>
              <h2 className="section-title"><Clock3 size={20} /> Posts programmés</h2>
              <p className="section-desc">Posts en attente de publication ou déjà publiés via la programmation LinkedIn.</p>
            </div>
          </div>
          {scheduledPosts.length === 0 ? (
            <div className="card" style={{ padding: 24, textAlign: "center", color: "var(--muted)" }}>
              Aucun post programmé pour l'instant. Programme un post depuis le Générateur.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {scheduledPosts.map((p) => {
                const statusLabel =
                  p.status === "published" ? "Publié ✓"
                  : p.status === "failed" ? "Échec"
                  : p.status === "cancelled" && p.slack_status === "declined" ? "Refusé Slack — annulé"
                  : p.status === "cancelled" ? "Annulé"
                  : p.slack_status === "validated" ? "Validé Slack — en attente"
                  : "Validation Slack en attente";
                const statusColor =
                  p.status === "published" || p.slack_status === "validated" ? "var(--success, #38a169)"
                  : p.status === "failed" ? "var(--error, #e53e3e)"
                  : p.status === "cancelled" ? "var(--muted)"
                  : "var(--accent)";
                return (
                  <div key={p.id} style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "10px 12px", background: "var(--surface)", borderRadius: 8, border: "1px solid var(--border)" }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <p style={{ margin: "0 0 4px", fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.post_text.slice(0, 120)}{p.post_text.length > 120 ? "…" : ""}</p>
                      <p style={{ margin: 0, fontSize: 12, color: "var(--muted)" }}>
                        {new Date(p.scheduled_at).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" })}
                        {" — "}
                        <span style={{ color: statusColor }}>{statusLabel}</span>
                      </p>
                      {p.status === "failed" && p.error_message && <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--error, #e53e3e)" }}>{p.error_message}</p>}
                    </div>
                    {p.status === "pending" && (
                      <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                        <button className="secondary-button" style={{ fontSize: 12, minHeight: 28, padding: "0 10px" }} disabled={editingPost === p.id || cancellingPost === p.id} onClick={() => openEditScheduled(p)}>
                          <Pencil size={12} /> Modifier
                        </button>
                        <button className="secondary-button" style={{ fontSize: 12, minHeight: 28, padding: "0 10px" }} disabled={cancellingPost === p.id || editingPost === p.id} onClick={() => cancelScheduled(p.id)}>
                          {cancellingPost === p.id ? <Loader2 size={12} className="spinning" /> : <Trash2 size={12} />}
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {imageModalSaved && (
        <ImageGenModal
          postText={editedPosts[imageModalSaved.id] ?? imageModalSaved.post}
          onClose={() => setImageModalSaved(null)}
          onGenerated={(dataUrl) => {
            const target = imageModalSaved;
            // Persistée avec le post (hébergement public côté backend, ALE-179) :
            // l'image reste jointe après refresh et part avec les publications.
            void persistSavedPostImages(target, [
              ...savedPostImagePayload(target),
              { data_url: dataUrl, filename: `image-ia-${Date.now()}.png` },
            ]);
          }}
        />
      )}

      {editingSchedule !== null && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}>
          <div className="card" style={{ maxWidth: 560, width: "100%", padding: 24 }}>
            <h3 style={{ marginTop: 0, marginBottom: 8 }}>Modifier le post programmé</h3>
            <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 12 }}>
              Tant que le post est en attente, tu peux corriger son texte et sa date de publication.
            </p>
            <label style={{ fontSize: 13, fontWeight: 500, display: "block", marginBottom: 6 }}>Texte du post</label>
            <textarea value={editScheduleText} rows={8} className="variant-text" style={{ width: "100%", boxSizing: "border-box", marginBottom: 12 }} onChange={(e) => setEditScheduleText(e.target.value)} />
            <label style={{ fontSize: 13, fontWeight: 500, display: "block", marginBottom: 6 }}>Date et heure de publication</label>
            <input type="datetime-local" value={editScheduleDate} onChange={(e) => setEditScheduleDate(e.target.value)} style={{ width: "100%", boxSizing: "border-box", padding: "8px 10px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)", fontSize: 14, marginBottom: 12 }} />
            {scheduleEditError && <p style={{ color: "var(--error, #e53e3e)", fontSize: 13, marginBottom: 8 }}>{scheduleEditError}</p>}
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button className="secondary-button" disabled={editingPost === editingSchedule.id} onClick={() => setEditingSchedule(null)}>Annuler</button>
              <button className="primary-button" disabled={editingPost === editingSchedule.id || !editScheduleDate || !editScheduleText.trim()} onClick={updateScheduled}>
                {editingPost === editingSchedule.id ? <><Loader2 size={14} className="spinning" /> Enregistrement…</> : <><Clock3 size={14} /> Enregistrer</>}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/** Barre d'actions sous une réponse de l'Agent IA : publier / programmer / Slack / X / copier,
 *  comme dans « Mes contenus », en opérant sur le texte brut de la réponse. */
function AssistantMessageActions({
  text,
  linkedin,
  twitter,
  slack,
}: {
  text: string;
  linkedin: ReturnType<typeof useLinkedIn>;
  twitter: ReturnType<typeof useTwitter>;
  slack: ReturnType<typeof useSlack>;
}) {
  const [copied, setCopied] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedPost, setSavedPost] = useState(false);
  const [confirmPub, setConfirmPub] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [published, setPublished] = useState(false);
  const [confirmX, setConfirmX] = useState(false);
  const [publishingX, setPublishingX] = useState(false);
  const [publishedX, setPublishedX] = useState(false);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [scheduled, setScheduled] = useState(false);
  const [slackSending, setSlackSending] = useState(false);
  const [slackSent, setSlackSent] = useState(false);
  const [confirmSlack, setConfirmSlack] = useState(false);
  const [imageModalOpen, setImageModalOpen] = useState(false);
  // Images jointes à la réponse (uploads + image IA générée) : elles partent avec
  // le post à la publication, programmation, envoi Slack et sauvegarde (ALE-188).
  const [images, setImages] = useState<LinkedInImageAttachment[]>([]);
  const [err, setErr] = useState("");

  const btn = { fontSize: 12, minHeight: 30, padding: "0 10px" } as const;
  const xLogo = (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.742l7.734-8.842L1.254 2.25H8.08l4.253 5.622L18.244 2.25zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
  );

  function imagePayload() {
    return images.map((image) => ({
      ...(image.url.startsWith("data:") ? { data_url: image.url } : { url: image.url }),
      filename: image.filename,
    }));
  }

  function addUploadedImages(files: FileList | null) {
    if (!files?.length) return;
    setErr("");
    const imageFiles = Array.from(files).filter((file) => file.type.startsWith("image/"));
    if (imageFiles.length !== files.length) {
      setErr("Seuls les fichiers image sont acceptés.");
    }
    for (const file of imageFiles) {
      if (file.size > 8 * 1024 * 1024) {
        setErr("LinkedIn limite chaque image à 8 Mo.");
        continue;
      }
      const reader = new FileReader();
      reader.onload = () => {
        const result = typeof reader.result === "string" ? reader.result : "";
        if (!result) return;
        setImages((prev) => [...prev, {
          id: `upload-${Date.now()}-${file.name}`,
          url: result,
          filename: file.name,
          source: "upload",
        }]);
      };
      reader.readAsDataURL(file);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { setErr("Copie impossible."); }
  }

  async function publishLinkedIn() {
    setConfirmPub(false);
    if (!linkedin.status?.connected) { setErr("Connecte d'abord ton compte LinkedIn dans l'onglet Profil."); return; }
    setErr(""); setPublishing(true);
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/linkedin/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({
          content: text,
          draft: false,
          images: imagePayload(),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Publication impossible.");
      setPublished(true);
      setTimeout(() => setPublished(false), 3000);
    } catch (e: any) { setErr(e.message); } finally { setPublishing(false); }
  }

  function openSchedule() {
    if (!linkedin.status?.connected) { setErr("Connecte d'abord ton compte LinkedIn dans l'onglet Profil."); return; }
    setErr(""); setScheduleOpen(true);
  }

  async function publishX() {
    setConfirmX(false); setErr(""); setPublishingX(true);
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/x/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ content: text, draft: false }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Publication sur X impossible.");
      setPublishedX(true);
      setTimeout(() => setPublishedX(false), 3000);
    } catch (e: any) { setErr(e.message); } finally { setPublishingX(false); }
  }

  async function sendSlack() {
    setErr(""); setConfirmSlack(false); setSlackSending(true);
    try {
      // Slack a besoin d'un post_id : on persiste d'abord la réponse comme post sauvegardé.
      const saveRes = await fetch(`${DIRECT_API_URL}/me/generated-posts`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ post: text, images: imagePayload() }),
      });
      const saved = await saveRes.json();
      if (!saveRes.ok) throw new Error(saved.detail || "Sauvegarde impossible.");
      const res = await fetch(`${DIRECT_API_URL}/me/integrations/slack/send-posts`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ post_id: saved.id, content: text, images: imagePayload() }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Envoi Slack impossible.");
      setSlackSent(true);
    } catch (e: any) { setErr(e.message); } finally { setSlackSending(false); }
  }

  async function save() {
    setErr(""); setSaving(true);
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/generated-posts`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ post: text, images: imagePayload() }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Sauvegarde impossible.");
      setSavedPost(true);
    } catch (e: any) { setErr(e.message); } finally { setSaving(false); }
  }

  return (
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 10 }}>
      <PostActionsBar
        publishBusy={publishing}
        publishLabel={published ? "Publié ✓" : publishing ? "Publication…" : "Publier"}
        publishActions={[
          {
            key: "linkedin",
            icon: <Linkedin size={14} />,
            label: published ? "Publié sur LinkedIn ✓" : "Publier maintenant sur LinkedIn",
            disabled: publishing,
            title: linkedin.status?.connected ? "Publier maintenant sur LinkedIn" : "Connecte ton compte LinkedIn dans l'onglet Profil",
            onClick: () => setConfirmPub(true),
          },
          {
            key: "schedule",
            icon: <Clock3 size={14} />,
            label: scheduled ? "Programmé ✓" : "Programmer…",
            disabled: scheduled,
            title: linkedin.status?.connected
              ? "Programmer : publication directe à une date, ou validation Slack au préalable"
              : "Connecte ton compte LinkedIn dans l'onglet Profil",
            onClick: openSchedule,
          },
          ...(slack.status?.connected
            ? [{
                key: "slack",
                icon: <Send size={14} />,
                label: slackSent ? "Sur Slack ✓" : "Envoyer sur Slack pour validation",
                disabled: slackSending || slackSent,
                onClick: () => setConfirmSlack(true),
              } satisfies PostAction]
            : []),
          ...(twitter.status?.connected
            ? [{
                key: "x",
                icon: xLogo,
                label: publishingX ? "Publication…" : publishedX ? "Publié sur X ✓" : "Publier sur X",
                disabled: publishingX,
                onClick: () => setConfirmX(true),
              } satisfies PostAction]
            : []),
        ]}
        moreActions={[
          {
            key: "save",
            icon: <BookmarkPlus size={14} />,
            label: savedPost ? "Sauvegardé ✓" : "Sauvegarder",
            disabled: saving || savedPost,
            title: "Sauvegarder ce post dans « Mes contenus »",
            onClick: save,
          },
          {
            key: "attach",
            icon: <ImagePlus size={14} />,
            label: "Joindre des images",
            filePicker: {
              accept: "image/png,image/jpeg,image/jpg,image/webp,image/gif",
              multiple: true,
              onFiles: addUploadedImages,
            },
          },
          {
            key: "image-ia",
            icon: <ImageIcon size={14} />,
            label: "Générer une image IA",
            title: "Prépare un prompt d'illustration à valider, puis génère l'image (5 crédits)",
            onClick: () => setImageModalOpen(true),
          },
        ]}
      >
        <button className="secondary-button" style={btn} onClick={copy}>
          {copied ? <CheckCircle2 size={13} /> : <Copy size={13} />} {copied ? "Copié ✓" : "Copier"}
        </button>
      </PostActionsBar>
      {confirmPub && (
        <div className="idea-footer" style={{ gap: 8, marginTop: 4, alignItems: "center", flexWrap: "wrap", width: "100%" }}>
          <span style={{ fontSize: 13 }}>Publier ce post maintenant sur LinkedIn ?</span>
          <button className="primary-button" style={btn} onClick={publishLinkedIn}>Confirmer</button>
          <button className="secondary-button" style={btn} onClick={() => setConfirmPub(false)}>Annuler</button>
        </div>
      )}
      {scheduleOpen && (
        <SchedulePostModal
          text={text}
          images={images.map((image) => ({ url: image.url, filename: image.filename }))}
          slackConnected={!!slack.status?.connected}
          onClose={() => setScheduleOpen(false)}
          onScheduled={() => { setScheduled(true); setScheduleOpen(false); }}
        />
      )}
      {confirmX && (
        <div className="idea-footer" style={{ gap: 8, marginTop: 4, alignItems: "center", flexWrap: "wrap", width: "100%" }}>
          <span style={{ fontSize: 13 }}>Publier ce post maintenant sur X ?</span>
          <button className="primary-button" style={btn} onClick={publishX}>Confirmer</button>
          <button className="secondary-button" style={btn} onClick={() => setConfirmX(false)}>Annuler</button>
        </div>
      )}
      {confirmSlack && (
        <div className="idea-footer" style={{ gap: 8, marginTop: 4, alignItems: "center", flexWrap: "wrap", width: "100%" }}>
          <span style={{ fontSize: 13 }}>Envoyer ce post sur Slack pour validation ?</span>
          <DevSlackNote />
          <button className="primary-button" style={btn} disabled={slackSending} onClick={sendSlack}>
            {slackSending ? <Loader2 size={12} className="spinning" /> : null} Confirmer
          </button>
          <button className="secondary-button" style={btn} onClick={() => setConfirmSlack(false)}>Annuler</button>
        </div>
      )}
      {imageModalOpen && (
        <ImageGenModal
          postText={text}
          onClose={() => setImageModalOpen(false)}
          onGenerated={(dataUrl) => setImages((prev) => [...prev, {
            id: `generated-${Date.now()}`,
            url: dataUrl,
            filename: "image-ia.png",
            source: "generated",
          }])}
        />
      )}
      {images.length > 0 && (
        <div style={{ width: "100%", marginTop: 8 }}>
          <p className="role-picker-hint" style={{ marginBottom: 8 }}>
            {images.length} image{images.length > 1 ? "s" : ""} jointe{images.length > 1 ? "s" : ""} au post LinkedIn.
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 10, maxWidth: 640 }}>
            {images.map((image, imageIndex) => (
              <div key={image.id} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 8, background: "var(--surface)" }}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={image.url} alt={`Image jointe ${imageIndex + 1}`} style={{ width: "100%", aspectRatio: "1 / 1", objectFit: "cover", borderRadius: 6, display: "block" }} />
                <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
                  <a
                    href={image.url}
                    download={image.filename || `post-image-${imageIndex + 1}.png`}
                    className="secondary-button"
                    style={{ minHeight: 28, padding: "0 8px", fontSize: 12, textDecoration: "none" }}
                  >
                    <Download size={12} /> Télécharger
                  </a>
                  <button
                    className="secondary-button"
                    style={{ minHeight: 28, padding: "0 8px", fontSize: 12 }}
                    onClick={() => setImages((prev) => prev.filter((im) => im.id !== image.id))}
                  >
                    <Trash2 size={12} /> Retirer
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      {err && <div className="error" style={{ marginTop: 4, fontSize: 12, width: "100%" }}>{err}</div>}
    </div>
  );
}

function Assistant({ isAuthed, requireAuth, seed }: { isAuthed: boolean; requireAuth: (reason?: string) => void; seed?: { post: string; nonce: number } | null }) {
  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef<HTMLDivElement | null>(null);
  // Réseaux connectés : permettent les actions (publier / programmer / Slack / X) sur chaque réponse.
  const linkedin = useLinkedIn(isAuthed);
  const twitter = useTwitter(isAuthed);
  const slack = useSlack(isAuthed);

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

  // Démarre une nouvelle conversation quand un seed de post est fourni depuis le Générateur.
  useEffect(() => {
    if (!seed?.post || !isAuthed) return;
    newConversation();
    const seedText = `Voici un post que j'ai généré et que j'aimerais améliorer :\n\n---\n${seed.post}\n---`;
    // setTimeout pour laisser newConversation() vider l'état avant d'envoyer.
    const t = setTimeout(() => sendMessage(seedText), 50);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed?.nonce]);

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
        </div>

        <div className="assistant-messages">
          {messages.length === 0 ? (
            <div className="assistant-welcome">
              <Sparkles size={22} />
              <h3>Demande une idée, un angle ou une réécriture.</h3>
              <p>Exemple : &quot;Écris un post opinion sur les erreurs d&apos;automatisation LinkedIn pour des dirigeants B2B.&quot;</p>
            </div>
          ) : (
            messages.map((m, idx) => (
              <div key={idx} className={`assistant-message ${m.role === "user" ? "user" : "assistant"}`}>
                {m.role === "assistant" ? (
                  <div className="assistant-message-content">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content || (streaming && idx === messages.length - 1 ? "…" : "")}</ReactMarkdown>
                    {m.content && !(streaming && idx === messages.length - 1) && (
                      <AssistantMessageActions text={m.content} linkedin={linkedin} twitter={twitter} slack={slack} />
                    )}
                  </div>
                ) : (
                  <p className="assistant-message-content">{m.content}</p>
                )}
              </div>
            ))
          )}
          {error && <div className="error" style={{ margin: "8px 0" }}>{error}</div>}
          <div ref={endRef} />
        </div>

        <div className="assistant-composer">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              // Entrée = envoyer ; Maj+Entrée = saut de ligne.
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (!streaming && input.trim()) void sendMessage();
              }
            }}
            placeholder="Écris ta demande : idée, brouillon à améliorer, angle, ton..."
            rows={3}
            disabled={streaming}
          />
          <button className="primary-button" disabled={streaming || !input.trim()} onClick={() => sendMessage()}>
            {streaming ? <Loader2 size={14} className="spinning" /> : <Send size={14} />}
            {streaming ? "…" : "Envoyer"}
          </button>
        </div>
        <p className="role-picker-hint" style={{ marginTop: 8 }}>Astuce : Entrée pour envoyer, Maj + Entrée pour un saut de ligne.</p>
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
  const [profileTab, setProfileTab] = useState<"dashboard" | "context">("dashboard");
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
  const [weeklyEnabled, setWeeklyEnabled] = useState(false);
  const [weeklySchedule, setWeeklySchedule] = useState<{day_of_week: number; hour: number; timezone: string}[]>([]);
  const [weeklySaving, setWeeklySaving] = useState(false);
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

  useEffect(() => {
    if (!isAuthed) { setWeeklyEnabled(false); setWeeklySchedule([]); return; }
    (async () => {
      try {
        const res = await fetch(`${DIRECT_API_URL}/me/weekly-posts`, { headers: await authHeaders() });
        if (res.ok) {
          const data = await res.json();
          setWeeklyEnabled(!!data.enabled);
          setWeeklySchedule(data.schedule || []);
        }
      } catch { /* silencieux */ }
    })();
  }, [isAuthed]);

  async function toggleWeeklyEnabled() {
    const next = !weeklyEnabled;
    setWeeklyEnabled(next);
    try {
      await fetch(`${DIRECT_API_URL}/me/weekly-posts/enabled`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ enabled: next }),
      });
      // À la 1ère activation, le backend sème les jours par défaut : on recharge
      // le planning pour afficher la grille pré-remplie tout de suite.
      if (next && weeklySchedule.length === 0) {
        const res = await fetch(`${DIRECT_API_URL}/me/weekly-posts`, { headers: await authHeaders() });
        if (res.ok) setWeeklySchedule((await res.json()).schedule || []);
      }
    } catch { setWeeklyEnabled(!next); }
  }

  async function saveWeeklySchedule(slots: {day_of_week: number; hour: number; timezone: string}[]) {
    setWeeklySaving(true);
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/weekly-posts/schedule`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ schedule: slots }),
      });
      if (res.ok) {
        const data = await res.json();
        setWeeklySchedule(data.schedule || slots);
      }
    } catch { /* silencieux */ } finally { setWeeklySaving(false); }
  }

  function toggleWeeklyDay(day: number) {
    const exists = weeklySchedule.find((s) => s.day_of_week === day);
    const next = exists
      ? weeklySchedule.filter((s) => s.day_of_week !== day)
      : [...weeklySchedule, { day_of_week: day, hour: 9, timezone: "Europe/Paris" }].sort((a, b) => a.day_of_week - b.day_of_week);
    setWeeklySchedule(next);
    void saveWeeklySchedule(next);
  }

  function setWeeklyHour(day: number, hour: number) {
    const next = weeklySchedule.map((s) => s.day_of_week === day ? { ...s, hour } : s);
    setWeeklySchedule(next);
    void saveWeeklySchedule(next);
  }

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
      <div className="tabs">
        <button
          className={`tab ${profileTab === "dashboard" ? "active" : ""}`}
          onClick={() => setProfileTab("dashboard")}
          style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
        >
          <Activity size={14} /> Tableau de bord
        </button>
        <button
          className={`tab ${profileTab === "context" ? "active" : ""}`}
          onClick={() => setProfileTab("context")}
          style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
        >
          <UserRound size={14} /> Contexte éditorial
        </button>
      </div>
      {profileTab === "dashboard" ? (
        <ProgressView isAuthed={isAuthed} requireAuth={requireAuth} />
      ) : (
      <>
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
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="status-pill ok"><CheckCircle2 size={14} /> Connecté</span>
            <button
              className="secondary-button"
              onClick={() => { if (window.confirm("Déconnecter le compte LinkedIn ?")) linkedin.disconnect(); }}
              disabled={linkedin.busy}
              style={{ fontSize: 12 }}
            >
              {linkedin.busy ? <Loader2 size={12} className="spinning" /> : null}
              Déconnecter
            </button>
          </div>
        ) : (
          <button className="primary-button" onClick={linkedin.connect} disabled={linkedin.busy}>
            {linkedin.busy ? <Loader2 size={14} className="spinning" /> : <Linkedin size={14} />}
            {linkedin.busy ? "Redirection…" : "Connecter LinkedIn"}
          </button>
        )}
      </section>
      {linkedin.error ? <div className="error" style={{ marginBottom: 12 }}>{linkedin.error}</div> : null}

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

      <section className="card" style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <CalendarDays size={20} style={{ flexShrink: 0, color: "var(--coral)" }} />
            <div>
              <strong>Posts automatiques de la semaine</strong>
              <p className="section-desc" style={{ margin: 0 }}>
                Génère et programme 3 posts chaque semaine, envoyés sur Slack pour validation avant publication. Requiert LinkedIn et Slack connectés.
              </p>
            </div>
          </div>
          {(!linkedin.status?.connected || !slack.status?.connected) ? (
            <p className="section-desc" style={{ margin: 0, fontSize: 12, color: "var(--muted)" }}>
              {!linkedin.status?.connected && !slack.status?.connected
                ? "⚠️ Connecte LinkedIn et Slack (ci-dessus) pour activer."
                : !linkedin.status?.connected
                ? "⚠️ Connecte LinkedIn (ci-dessus) pour activer."
                : "⚠️ Connecte Slack (ci-dessus) pour activer."}
            </p>
          ) : (
            <label className="daily-switch">
              <input type="checkbox" checked={weeklyEnabled} onChange={toggleWeeklyEnabled} />
              <span>Recevoir 3 posts/semaine à valider</span>
            </label>
          )}
        </div>
        {weeklyEnabled && linkedin.status?.connected && slack.status?.connected && (
          <div style={{ marginTop: 16 }}>
            <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 8 }}>
              Jours de publication (heure locale, fuseau Europe/Paris) :
            </p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
              {["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"].map((label, day) => {
                const slot = weeklySchedule.find((s) => s.day_of_week === day);
                return (
                  <div key={day} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
                    <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13, cursor: "pointer" }}>
                      <input
                        type="checkbox"
                        checked={!!slot}
                        onChange={() => toggleWeeklyDay(day)}
                        style={{ cursor: "pointer" }}
                      />
                      {label}
                    </label>
                    {slot && (
                      <select
                        value={slot.hour}
                        onChange={(e) => setWeeklyHour(day, Number(e.target.value))}
                        style={{ fontSize: 12, padding: "2px 4px", borderRadius: 4, border: "1px solid var(--border)" }}
                      >
                        {Array.from({ length: 24 }, (_, h) => (
                          <option key={h} value={h}>{String(h).padStart(2, "0")}h</option>
                        ))}
                      </select>
                    )}
                  </div>
                );
              })}
            </div>
            {weeklySaving && <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}><Loader2 size={12} className="spinning" style={{ verticalAlign: "-2px" }} /> Sauvegarde…</p>}
            {weeklySchedule.length === 0 && (
              <p style={{ fontSize: 12, color: "var(--coral)", marginTop: 6 }}>Sélectionne au moins un jour.</p>
            )}
          </div>
        )}
      </section>

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
      </>
      )}
    </div>
  );
}

function GlobalDashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [growth, setGrowth] = useState<GrowthRow[]>([]);
  const [loading, setLoading] = useState(true);

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

      {/* AI Strategic Analysis — temporairement désactivée (données en cours d'amélioration) */}
      <div className="card" style={{ marginTop: 16, opacity: 0.55 }}>
        <div className="section-header" style={{ marginBottom: 12 }}>
          <div>
            <h3 style={{ margin: 0 }}>🧠 Analyse stratégique IA</h3>
            <p style={{ fontSize: 13, color: "var(--muted)", margin: "4px 0 0" }}>
              Bientôt disponible — fonctionnalité en cours d'amélioration.
            </p>
          </div>
          <button className="primary-button" disabled aria-disabled title="Bientôt disponible">
            <Sparkles size={14} />
            Bientôt disponible
          </button>
        </div>
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
 * onglet Analyser (séries) et Mes influenceurs. Le Dashboard global (ALE-132)
 * est désormais affiché sous la liste des influenceurs (plus de sous-onglet dédié).
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
        <>
          <InfluencersView
            entries={influencers}
            loading={influencersLoading}
            isAuthed={isAuthed}
            requireAuth={requireAuth}
            onOpenReport={onOpenLibraryReport}
          />
          {isAuthed && (
            <div style={{ marginTop: 32, paddingTop: 8, borderTop: "1px solid var(--border)" }}>
              <GlobalDashboard />
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** Onglet « Contenu » : regroupe Idée du jour, Générateur et Mes contenus en sous-onglets. */
function ContentHub({
  tab,
  onTab,
  seed,
  onReuse,
  onRework,
  isAuthed,
  reservoirOnly = false,
  requireAuth,
  generationJobs,
  onGenerationJobCreated,
}: {
  tab: ContentTab;
  onTab: (t: ContentTab) => void;
  seed?: { topic: string; nonce: number } | null;
  onReuse: (topic: string) => void;
  onRework?: (post: string) => void;
  isAuthed: boolean;
  reservoirOnly?: boolean;
  requireAuth: (reason?: string, mode?: AuthMode) => void;
  generationJobs: GenerationJob[];
  onGenerationJobCreated: (job: GenerationJob) => void;
}) {
  const subTabs: { key: ContentTab; label: string; icon: React.ReactNode }[] = [
    { key: "daily", label: "Idée du jour", icon: <Sparkles size={14} /> },
    { key: "generator", label: "Générateur de posts", icon: <PenTool size={14} /> },
    { key: "library", label: "Mes contenus", icon: <Bookmark size={14} /> },
  ];

  // Compte client restreint : on ne montre que le réservoir d'idées, sans sous-onglets.
  if (reservoirOnly) {
    return (
      <div>
        <DailyIdeasView isAuthed={isAuthed} requireAuth={requireAuth} onReuse={onReuse} reservoirOnly />
      </div>
    );
  }

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

      {tab === "daily" && <DailyIdeasView isAuthed={isAuthed} requireAuth={requireAuth} onReuse={onReuse} onRework={onRework} />}
      {tab === "generator" && <Generator isAuthed={isAuthed} requireAuth={requireAuth} seed={seed} generationJobs={generationJobs} onGenerationJobCreated={onGenerationJobCreated} onRework={onRework} />}
      {tab === "library" && (
        <LibraryView isAuthed={isAuthed} requireAuth={requireAuth} onReuse={onReuse} onRework={onRework} />
      )}
    </div>
  );
}

// --- Onboarding « Cible » : wizard accueil → scan → 2 pages de confirmation ---
type OnbStep = "intro" | "scanning" | "page1" | "page2";
type OnbOption = { label: string; match?: string[] };

const ONB_AUDIENCE_OPTIONS: OnbOption[] = [
  { label: "Dirigeants de PME", match: ["pme", "dirigeant", "tpe", "patron", "ceo", "gérant", "chef d'entreprise"] },
  { label: "Startups & fondateurs", match: ["startup", "fondateur", "founder", "porteur de projet", "scale"] },
  { label: "Freelances & solopreneurs", match: ["freelance", "solo", "indépendant", "consultant indépendant"] },
  { label: "E-commerçants", match: ["e-commerce", "ecommerce", "boutique", "shopify", "vendeur", "retail"] },
  { label: "Coachs & consultants", match: ["coach", "consultant", "formateur"] },
  { label: "Agences & studios", match: ["agence", "studio"] },
  { label: "Éditeurs SaaS / tech", match: ["saas", "éditeur", "logiciel", "cto", "product"] },
];

const ONB_OFFER_OPTIONS: OnbOption[] = [
  { label: "Un SaaS / produit", match: ["saas", "produit", "logiciel", "app", "plateforme", "outil"] },
  { label: "Des prestations sur-mesure", match: ["prestation", "service", "sur-mesure", "freelance", "mission", "développement"] },
  { label: "Du conseil / consulting", match: ["conseil", "consulting", "accompagnement", "stratégie", "audit"] },
  { label: "De la formation", match: ["formation", "cours", "coaching", "bootcamp", "masterclass"] },
  { label: "Une agence / studio", match: ["agence", "studio"] },
];

const ONB_OBJECTIVE_OPTIONS: OnbOption[] = [
  { label: "Générer des leads", match: ["lead", "prospect", "client", "acquisition", "rendez-vous"] },
  { label: "Développer ma notoriété", match: ["notoriété", "visibilité", "personal branding", "marque", "audience", "influence"] },
  { label: "Vendre une offre", match: ["vendre", "vente", "offre", "convertir", "chiffre"] },
  { label: "Recruter", match: ["recrut", "talent", "embauche", "hiring", "équipe"] },
  { label: "Fédérer une communauté", match: ["communauté", "community", "engager", "réseau"] },
];

const ONB_INDUSTRY_OPTIONS: OnbOption[] = [
  { label: "IA & Data", match: ["ia", "intelligence artificielle", "ai", "data", "machine learning", "llm"] },
  { label: "SaaS / Logiciel", match: ["saas", "logiciel", "software"] },
  { label: "Marketing & Growth", match: ["marketing", "growth", "acquisition", "communication", "ads"] },
  { label: "Développement / Tech", match: ["dev", "développ", "code", "engineering", "no-code", "vibecod", "tech"] },
  { label: "Conseil & Services", match: ["conseil", "service", "consulting", "cabinet"] },
  { label: "E-commerce", match: ["e-commerce", "ecommerce", "retail", "boutique"] },
];

const ONB_SCAN_STEPS = [
  "Lecture de ton profil…",
  "Analyse de ton audience…",
  "Identification de ton offre…",
  "On peaufine tout ça…",
];

function onbMatch(text: string | undefined, options: OnbOption[]): string | null {
  const t = (text || "").toLowerCase();
  if (!t) return null;
  for (const o of options) {
    if (o.match?.some((m) => t.includes(m))) return o.label;
  }
  return null;
}

// Un champ = plusieurs choix cochés (multi-select) + un éventuel texte libre « Autre ».
type OnbField = { picks: string[]; other: string };

function onbField(text: string | undefined, options: OnbOption[]): OnbField {
  const m = onbMatch(text, options);
  if (m) return { picks: [m], other: "" };
  return { picks: [], other: (text || "").trim() };
}

function onbJoin(f: OnbField): string {
  return [...f.picks, f.other.trim()].filter(Boolean).join(", ");
}

function onbInitSel(d: Record<string, string>) {
  const audience = onbField(d.target_audience, ONB_AUDIENCE_OPTIONS);
  return {
    displayName: (d.display_name || "").trim(),
    audienceMode: (audience.picks.length || audience.other ? "niche" : "") as "" | "niche" | "large",
    audience,
    offer: onbField(d.core_offer, ONB_OFFER_OPTIONS),
    objective: onbField(d.linkedin_objective, ONB_OBJECTIVE_OPTIONS),
    industry: onbField(d.industry, ONB_INDUSTRY_OPTIONS),
  };
}

function OnbChips({ options, field, onChange, placeholder }: {
  options: OnbOption[];
  field: OnbField;
  onChange: (next: OnbField) => void;
  placeholder?: string;
}) {
  const [showOther, setShowOther] = useState(!!field.other);
  const toggle = (label: string) => {
    const has = field.picks.includes(label);
    onChange({ ...field, picks: has ? field.picks.filter((p) => p !== label) : [...field.picks, label] });
  };
  return (
    <>
      <div className="onb-chips">
        {options.map((o, i) => (
          <button
            key={o.label}
            type="button"
            className={"onb-chip" + (field.picks.includes(o.label) ? " selected" : "")}
            style={{ animationDelay: `${i * 45}ms` }}
            onClick={() => toggle(o.label)}
          >
            {o.label}
          </button>
        ))}
        <button
          type="button"
          className={"onb-chip" + (showOther ? " selected" : "")}
          style={{ animationDelay: `${options.length * 45}ms` }}
          onClick={() => {
            const next = !showOther;
            setShowOther(next);
            if (!next) onChange({ ...field, other: "" });
          }}
        >
          Autre
        </button>
      </div>
      {showOther && (
        <input
          className="onb-other-input"
          value={field.other}
          onChange={(e) => onChange({ ...field, other: e.target.value })}
          placeholder={placeholder || "Précise en quelques mots…"}
          autoFocus
        />
      )}
    </>
  );
}

function OnboardingScreen({ onDone }: { onDone: () => void }) {
  const [step, setStep] = useState<OnbStep>("intro");
  const [aiInput, setAiInput] = useState("");
  const [error, setError] = useState("");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [sel, setSel] = useState(() => onbInitSel({}));
  const [saving, setSaving] = useState(false);
  const [scanIdx, setScanIdx] = useState(0);

  const up = (patch: Partial<ReturnType<typeof onbInitSel>>) =>
    setSel((s) => ({ ...s, ...patch }));

  const inputKind: "linkedin" | "website" | "description" = (() => {
    const v = aiInput.trim();
    if (!v || /\s/.test(v)) return "description";
    if (/linkedin\.com\/in\//i.test(v)) return "linkedin";
    if (/^https?:\/\//i.test(v) || /^www\./i.test(v) || /^[\w-]+(\.[\w-]+)+(\/|$)/i.test(v)) return "website";
    return "description";
  })();

  useEffect(() => {
    if (step !== "scanning") return;
    setScanIdx(0);
    const id = setInterval(
      () => setScanIdx((i) => (i < ONB_SCAN_STEPS.length - 1 ? i + 1 : i)),
      850,
    );
    return () => clearInterval(id);
  }, [step]);

  async function analyze() {
    const trimmed = aiInput.trim();
    if (!trimmed) { setError("Colle ton URL LinkedIn (ou une courte description)."); return; }
    setError(""); setStep("scanning");
    try {
      const isLinkedin = inputKind === "linkedin";
      const isWebsite = inputKind === "website";
      const minWait = new Promise((r) => setTimeout(r, 1800));
      const fetchDraft = (async () => {
        const res = await fetch(`${DIRECT_API_URL}/me/profile/draft`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...(await authHeaders()) },
          body: JSON.stringify({
            activity_description: isLinkedin || isWebsite ? "" : trimmed,
            linkedin_url: isLinkedin ? trimmed : "",
            website_url: isWebsite ? trimmed : "",
            use_apify_linkedin: isLinkedin,
          }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Analyse impossible");
        return (data.profile || {}) as Record<string, string>;
      })();
      const [d] = await Promise.all([fetchDraft, minWait]);
      setDraft(d);
      setSel(onbInitSel(d));
      setStep("page1");
    } catch (err: any) {
      setError(err?.message || "Analyse impossible");
      setStep("intro");
    }
  }

  async function finish() {
    setSaving(true);
    const merged: Record<string, string> = {
      ...draft,
      display_name: sel.displayName.trim() || draft.display_name || "",
      target_audience: sel.audienceMode === "large" ? "Large, pas de niche précise" : onbJoin(sel.audience),
      core_offer: onbJoin(sel.offer),
      linkedin_objective: onbJoin(sel.objective),
      industry: onbJoin(sel.industry),
    };
    try {
      await fetch(`${DIRECT_API_URL}/me/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify(merged),
      });
    } catch { /* best effort — on n'empêche pas d'entrer dans l'app */ }
    onDone();
  }

  return (
    <div className="onb-overlay">
      <div className="onb-shell">
        {(step === "page1" || step === "page2") && (
          <div className="onb-progress">
            <div className="onb-progress-fill" style={{ width: step === "page1" ? "50%" : "100%" }} />
          </div>
        )}

        {step === "intro" && (
          <div className="onb-screen" key="intro">
            <div className="onb-icon-badge"><Target size={26} /></div>
            <h1 className="onb-title">Bienvenue sur Cible</h1>
            <p className="onb-subtitle">Colle ton profil LinkedIn, on prépare tout le reste pour toi.</p>
            <div className="onb-input-row">
              <input
                className="onb-input"
                value={aiInput}
                onChange={(e) => setAiInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") analyze(); }}
                placeholder="https://linkedin.com/in/ton-profil"
                autoFocus
              />
              <button className="onb-cta" onClick={analyze}>
                <Sparkles size={16} /> Analyser
              </button>
            </div>
            {error && <div className="onb-error">{error}</div>}
            <button className="onb-skip" onClick={() => setStep("page1")}>Continuer sans LinkedIn</button>
          </div>
        )}

        {step === "scanning" && (
          <div className="onb-screen onb-scan" key="scan">
            <div className="onb-orb"><Linkedin size={34} /></div>
            <div className="onb-scan-status" key={scanIdx}>{ONB_SCAN_STEPS[scanIdx]}</div>
          </div>
        )}

        {step === "page1" && (
          <div className="onb-screen" key="page1">
            <h2 className="onb-greeting">Ravi de te voir 👋</h2>
            <p className="onb-lead">On a pré-rempli à partir de ton profil. Confirme ou ajuste — tu peux choisir plusieurs réponses 👇</p>

            <div className="onb-block">
              <label className="onb-block-label">Nom et prénom</label>
              <input
                className="onb-other-input"
                style={{ marginTop: 0 }}
                value={sel.displayName}
                onChange={(e) => up({ displayName: e.target.value })}
                placeholder="Ton nom et prénom"
              />
            </div>

            <div className="onb-block">
              <label className="onb-block-label">À qui tu t'adresses&nbsp;?</label>
              <div className="onb-toggle">
                <button
                  className={"onb-toggle-btn" + (sel.audienceMode === "niche" ? " selected" : "")}
                  onClick={() => up({ audienceMode: "niche" })}
                >
                  Une cible précise
                </button>
                <button
                  className={"onb-toggle-btn" + (sel.audienceMode === "large" ? " selected" : "")}
                  onClick={() => up({ audienceMode: "large" })}
                >
                  Un public large
                </button>
              </div>
              {sel.audienceMode === "niche" && (
                <OnbChips
                  options={ONB_AUDIENCE_OPTIONS}
                  field={sel.audience}
                  onChange={(v) => up({ audience: v })}
                  placeholder="Ta niche…"
                />
              )}
            </div>

            <div className="onb-block">
              <label className="onb-block-label">Ce que tu proposes</label>
              <OnbChips options={ONB_OFFER_OPTIONS} field={sel.offer} onChange={(v) => up({ offer: v })} />
            </div>

            <div className="onb-nav">
              <button className="onb-back" onClick={onDone}>Passer</button>
              <button className="onb-cta" onClick={() => setStep("page2")}>
                Continuer <ChevronRight size={16} />
              </button>
            </div>
          </div>
        )}

        {step === "page2" && (
          <div className="onb-screen" key="page2">
            <h2 className="onb-greeting">Presque fini</h2>
            <p className="onb-lead">Deux derniers points et c'est parti.</p>

            <div className="onb-block">
              <label className="onb-block-label">Ton objectif sur LinkedIn</label>
              <OnbChips options={ONB_OBJECTIVE_OPTIONS} field={sel.objective} onChange={(v) => up({ objective: v })} />
            </div>

            <div className="onb-block">
              <label className="onb-block-label">Ton secteur</label>
              <OnbChips options={ONB_INDUSTRY_OPTIONS} field={sel.industry} onChange={(v) => up({ industry: v })} />
            </div>

            <div className="onb-nav">
              <button className="onb-back" onClick={() => setStep("page1")}>
                <ChevronLeft size={16} /> Retour
              </button>
              <button className="onb-cta" onClick={finish} disabled={saving}>
                {saving ? <Loader2 size={16} className="spinning" /> : <Sparkles size={16} />} C'est parti
              </button>
            </div>
          </div>
        )}
      </div>
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
  const [platform, setPlatform] = useState<Platform>("linkedin");
  const [analyzeTab, setAnalyzeTab] = useState<AnalyzeTab>("analyze");
  const [contentTab, setContentTab] = useState<ContentTab>("generator");
  // Sujet pré-rempli quand on "réutilise" une idée/un post depuis Mes contenus.
  const [generatorSeed, setGeneratorSeed] = useState<{ topic: string; nonce: number } | null>(null);
  // Post pré-rempli quand on "retravaille" un variant depuis le Générateur vers l'Agent IA.
  const [assistantSeed, setAssistantSeed] = useState<{ post: string; nonce: number } | null>(null);
  const [loadedReport, setLoadedReport] = useState<Report | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  // ALE-141 : jobs de génération de posts (file d'attente, vit dans Home pour que
  // le polling continue quand on change d'onglet / quitte le générateur).
  const [generationJobs, setGenerationJobs] = useState<GenerationJob[]>([]);
  const [session, setSession] = useState<Session | null>(null);
  const [authOpen, setAuthOpen] = useState(false);
  const [authReason, setAuthReason] = useState("");
  const [authMode, setAuthMode] = useState<AuthMode>("signup");
  const [credits, setCredits] = useState<number | null>(null);
  const [showOnboarding, setShowOnboarding] = useState(false);
  // Le temps de vérifier (côté serveur) si le profil est vide, on affiche un
  // écran de chargement neutre plutôt que l'app qui "flashe" puis l'onboarding.
  const [checkingProfile, setCheckingProfile] = useState(false);
  const userIdRef = useRef<string | null>(null);
  const prevJobActiveRef = useRef(false);
  // Analyse anonyme affichée mais pas encore sauvegardée : sauvée dès l'inscription.
  const pendingAnonResultRef = useRef<Analysis | null>(null);

  const isAuthed = !!session;
  // Rôle « ideas_only » (posé dans app_metadata côté Supabase, non modifiable par
  // l'utilisateur) : compte client partagé client ↔ agence qui DÉMARRE sur la page
  // « idées de posts » mais peut basculer en vue complète pour le travail habituel.
  const ideasAccount = ((session?.user?.app_metadata as Record<string, unknown> | undefined)?.role) === "ideas_only";
  // Vue client (réservoir seul) active ? Persistée par navigateur : l'agence bascule
  // une fois en vue complète, le client reste sur la vue idées de son côté.
  const [clientView, setClientView] = useState(true);
  useEffect(() => {
    try { setClientView(localStorage.getItem("lkd_client_view") !== "full"); } catch { /* ignore */ }
  }, []);
  const restricted = ideasAccount && clientView;

  function toggleClientView() {
    setClientView((v) => {
      const next = !v;
      try { localStorage.setItem("lkd_client_view", next ? "ideas" : "full"); } catch { /* ignore */ }
      return next;
    });
  }

  // Vue client : navigation verrouillée sur la page idées (LinkedIn → Contenu → Idée du jour).
  useEffect(() => {
    if (!restricted) return;
    setView("content");
    setContentTab("daily");
    setPlatform("linkedin");
  }, [restricted]);

  useEffect(() => {
    try {
      const savedPlatform = localStorage.getItem("lkd_platform");
      if (savedPlatform === "linkedin" || savedPlatform === "instagram") {
        setPlatform(savedPlatform);
      }
    } catch {
      /* ignore */
    }
  }, []);

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

  // ALE-141 : génération de posts en file d'attente.
  async function loadGenerationJobs() {
    try {
      const res = await fetch(`${DIRECT_API_URL}/generate/jobs`, { headers: await authHeaders() });
      const data = await res.json();
      if (res.ok && Array.isArray(data)) setGenerationJobs(data);
    } catch { /* ignore */ }
  }

  function onGenerationJobCreated(job: GenerationJob) {
    setGenerationJobs((prev) => [job, ...prev]);
  }

  const anyGenerationJobActive = generationJobs.some(generationJobIsActive);

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

  // ALE-141 : premier chargement des jobs de génération + polling tant qu'un tourne.
  useEffect(() => {
    if (!isAuthed) { setGenerationJobs([]); return; }
    loadGenerationJobs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed, session?.access_token]);

  useEffect(() => {
    if (!isAuthed || !anyGenerationJobActive) return;
    const t = setInterval(loadGenerationJobs, 3000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed, anyGenerationJobActive]);

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
    const { data: sub } = supabase.auth.onAuthStateChange((event, s) => {
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
      // Ne pas fermer une modale que l'utilisateur vient d'ouvrir juste parce que
      // Supabase restaure une session existante au chargement (INITIAL_SESSION).
      // On ne ferme que sur une vraie connexion (SIGNED_IN / création de compte).
      if (event !== "INITIAL_SESSION") setAuthOpen(false);
      setReports([]);
      setInfluencers([]);
      setResult(null);
      setLoadedReport(null);
      setJobs([]);
      setGenerationJobs([]);
      // ALE-145 : purge le cache générateur quand l'utilisateur change (anti fuite cross-user).
      _genCache.variants = [];
      _genCache.topic = "";
      _genCache.appliedJobId = null;
      setError("");
      setView("content");
      setShowOnboarding(false);
      setCheckingProfile(false);
      const loadUserData = () => {
        loadReports(); loadJobs(); loadInfluencerLibrary(); loadGenerationJobs();
      };
      if (uid) {
        // Décision d'onboarding SANS attendre le backend : le flag vit dans les
        // métadonnées Supabase (présentes dans la session/token, zéro réseau).
        //  - onboarding_done   → l'a déjà fait/passé → jamais d'onboarding.
        //  - onboarding_pending → nouveau compte (posé à l'inscription) → onboarding immédiat.
        //  - aucun flag        → compte "legacy" → repli : on vérifie le profil serveur.
        const meta = (s?.user?.user_metadata || {}) as Record<string, unknown>;
        if (meta.onboarding_done === true) {
          setTimeout(loadUserData, 0);
        } else if (meta.onboarding_pending === true) {
          setShowOnboarding(true);
          setTimeout(loadUserData, 0);
        } else {
          // Legacy : petit splash le temps de vérifier le profil. Garde-fou 3,5 s
          // pour ne pas bloquer l'app si le backend est en cold-start.
          setCheckingProfile(true);
          setTimeout(() => {
            loadUserData();
            const guard = setTimeout(() => setCheckingProfile(false), 3500);
            (async () => {
              try {
                const res = await fetch(`${DIRECT_API_URL}/me/profile`, { headers: await authHeaders() });
                if (res.ok) {
                  const p = await res.json();
                  const hasProfile = !!(p.display_name || p.brand_name || p.business_description);
                  if (!hasProfile) setShowOnboarding(true);
                  // Profil déjà rempli : on pose le flag pour un login instantané la prochaine fois.
                  else supabase.auth.updateUser({ data: { onboarding_done: true } }).catch(() => {});
                }
              } catch { /* ignore */ }
              finally { clearTimeout(guard); setCheckingProfile(false); }
            })();
          }, 0);
        }
      }
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
    const slackOauthState = sessionStorage.getItem("slack_oauth_state") || params.get("state") || "";
    sessionStorage.removeItem("slack_oauth_state");
    (async () => {
      try {
        const redirectUri = `${window.location.origin}${window.location.pathname}`;
        await fetch(`${DIRECT_API_URL}/me/integrations/slack/callback`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...(await authHeaders()) },
          body: JSON.stringify({ code, redirect_uri: redirectUri, state: slackOauthState }),
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
      {IS_DEV_ENV && (
        <div className="dev-env-banner">🚧 ENVIRONNEMENT DEV — base partagée avec la prod</div>
      )}
      {showOnboarding && isAuthed && (
        <OnboardingScreen onDone={() => {
          setShowOnboarding(false);
          setView("content");
          // Marque l'onboarding comme fait (dans les métadonnées Supabase) → il ne
          // réapparaîtra plus, même après refresh, sans dépendre du backend.
          supabase.auth.updateUser({ data: { onboarding_pending: false, onboarding_done: true } }).catch(() => {});
        }} />
      )}
      {isAuthed && checkingProfile && !showOnboarding && (
        <div className="onb-overlay">
          <div className="onb-boot"><Loader2 size={30} className="spinning" /></div>
        </div>
      )}
      <div className={IS_DEV_ENV ? "app-shell dev-env" : "app-shell"}>
        <Sidebar
          health={health}
          reports={reports}
          reportsLoading={reportsLoading}
          view={view}
          isAuthed={isAuthed}
          restricted={restricted}
          ideasAccount={ideasAccount}
          onToggleView={toggleClientView}
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
            try { localStorage.setItem("lkd_platform", p); } catch {}
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
        {/* Anti-fuite cross-user : `key` sur l'id utilisateur → tout le sous-arbre
            de contenu (DailyIdeasView, LibraryView, Generator…) est remonté à neuf
            quand on change de compte. Sans ça, leurs états locaux par-utilisateur
            (idées générées, posts sauvegardés…) survivent à un changement de session
            (ex. inscription d'un nouveau compte sans logout : `isAuthed` reste true,
            les useEffect keyés sur [isAuthed] ne se relancent pas). */}
        <main className="main" key={session?.user?.id ?? "anon"}>
          {/* Agent IA et Profil (qui inclut le Tableau de bord) sont indépendants du réseau */}
          {view === "assistant" ? (
            <Assistant isAuthed={isAuthed} requireAuth={requireAuth} seed={assistantSeed} />
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
                  reservoirOnly={restricted}
                  requireAuth={requireAuth}
                  generationJobs={generationJobs}
                  onGenerationJobCreated={onGenerationJobCreated}
                  onReuse={(topic) => {
                    setGeneratorSeed({ topic, nonce: Date.now() });
                    setContentTab("generator");
                  }}
                  onRework={(post) => {
                    setAssistantSeed({ post, nonce: Date.now() });
                    setView("assistant");
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
