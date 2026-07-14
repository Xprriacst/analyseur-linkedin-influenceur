"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Activity,
  AlertCircle,
  BarChart3,
  CalendarDays,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Copy,
  CreditCard,
  Download,
  Eye,
  FileText,
  GripVertical,
  Image as ImageIcon,
  ImagePlus,
  Inbox as InboxIcon,
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
  X,
  XCircle,
  Zap,
} from "lucide-react";
import type { Session } from "@supabase/supabase-js";
import AuthModal, { type AuthMode } from "./components/AuthModal";
import PostActionsBar, { type PostAction } from "./components/PostActionsBar";
import PublishConfirmModal from "./components/PublishConfirmModal";
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

// ── Skeletons de chargement (ALE-266) ────────────────────────────────────
// Remplacent les spinners pour le chargement de CONTENU : la forme s'affiche en
// gris teinté (balayage), le vrai contenu se fond dedans. Les primitives .sk
// vivent dans globals.css. `Sk` = un bloc gris ; les composés ci-dessous
// reproduisent la silhouette de chaque écran.
function Sk({
  w, h = 10, r = 7, circle = false, className = "", style,
}: {
  w?: number | string; h?: number | string; r?: number; circle?: boolean;
  className?: string; style?: React.CSSProperties;
}) {
  return (
    <span
      className={`sk${circle ? " circle" : ""}${className ? " " + className : ""}`}
      style={{ display: "block", width: w ?? "100%", height: h, borderRadius: circle ? "50%" : r, ...style }}
    />
  );
}

// Liste de conversations (Inbox) : n lignes « avatar rond + nom ».
function ConvListSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="sk-list" aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", marginBottom: 4 }}>
          <Sk circle w={14} h={14} />
          <Sk h={10} w={`${72 - (i % 3) * 14}%`} />
        </div>
      ))}
    </div>
  );
}

// Cartes de post (Mes contenus / listes de variants) : entête + bloc de texte.
function PostCardsSkeleton({ cards = 3 }: { cards?: number }) {
  return (
    <div className="variants-list sk-list" aria-hidden>
      {Array.from({ length: cards }).map((_, i) => (
        <div className="variant-card" key={i}>
          <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
            <Sk h={16} w={90} r={6} />
            <Sk h={16} w={64} r={6} />
            <Sk h={16} w={70} r={6} style={{ marginLeft: "auto" }} />
          </div>
          <div style={{ display: "grid", gap: 8 }}>
            <Sk h={10} w="100%" />
            <Sk h={10} w="96%" />
            <Sk h={10} w="88%" />
            <Sk h={10} w="70%" />
          </div>
        </div>
      ))}
    </div>
  );
}

// Fil de messages (Inbox) : quelques bulles gauche/droite en attendant le fil.
function MsgThreadSkeleton() {
  const bubbles: Array<{ side: "in" | "out"; w: number }> = [
    { side: "in", w: 62 }, { side: "out", w: 48 }, { side: "in", w: 70 }, { side: "out", w: 40 },
  ];
  return (
    <div className="sk-list" aria-hidden style={{ display: "flex", flexDirection: "column", gap: 10, padding: 4 }}>
      {bubbles.map((b, i) => (
        <Sk key={i} h={34} w={`${b.w}%`} r={12} style={{ alignSelf: b.side === "in" ? "flex-start" : "flex-end" }} />
      ))}
    </div>
  );
}

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
/** Tendances transverses calculées sur l'ensemble des rapports (GET /me/influencer-trends). */
type TrendRow = {
  key?: string;
  label: string;
  lift_pct: number;
  posts: number;
  reports?: number;
  wins?: number;
};
type TrendsRankingRow = {
  influencer_id: string;
  analysis_id: string;
  handle: string;
  name: string;
  followers: number;
  median_engagement: number;
  engagement_rate_pct: number | null;
  posts: number;
};
type InfluencerTrends = {
  insufficient?: boolean;
  report_count: number;
  post_count: number;
  updated_at?: string | null;
  min_reports?: number;
  cta?: {
    accounts: number;
    winning: number;
    ratio_median: number;
    ratio_min: number;
    ratio_max: number;
    posts_with: number;
    posts_without: number;
  } | null;
  comments_share?: { top_accounts: number; share_median_pct: number; share_max_pct: number } | null;
  hooks?: TrendRow[];
  stages?: TrendRow[];
  formats?: TrendRow[];
  length_buckets?: TrendRow[];
  weekdays?: TrendRow[];
  benchmark?: {
    best: { name: string; followers: number; rate_pct: number };
    biggest: { name: string; followers: number; rate_pct: number };
    high_freq?: { threshold: number; accounts: number; max_rate_pct: number };
  } | null;
  frequency?: {
    buckets: { label: string; accounts: number; median_rate_pct: number }[];
    ratio: number | null;
  } | null;
  ranking: TrendsRankingRow[];
};

const mainViews = ["analyze", "profile", "assistant", "content", "inbox", "prospecting"] as const;
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

/** Sous-onglets de la vue « Contenu » (idée du jour, générateur, mes contenus fusionnés). */
// ALE-223 : « Mes contenus » et « Ma bibliothèque » fusionnés dans un seul
// sous-onglet (clé "library", label « Ma bibliothèque »), présenté en tiroirs.
// ALE-257 : la Veille (analyse de profils, classement, tendances, monitoring) est
// fusionnée dans Contenu sous un sous-onglet « analyses » (page unique qui défile).
// ALE-286 : plus de sous-onglet « Idée du jour » côté agence — la génération
// d'idées est passée dans le parcours guidé du Générateur. La vue client
// (compte `ideas_only`) continue de l'afficher, via la branche `reservoirOnly`.
type ContentTab = "analyses" | "generator" | "library";

// « Mon profil » empilait sur une seule page trois métiers sans rapport : le contexte
// éditorial, les comptes à relier, et ce qui tourne tout seul. Un onglet par métier.
type ProfileTab = "profile" | "connections" | "automations";

const PROFILE_TABS: { key: ProfileTab; label: string; icon: React.ReactNode }[] = [
  { key: "profile", label: "Mon profil", icon: <UserRound size={14} /> },
  { key: "connections", label: "Connexions", icon: <Link2 size={14} /> },
  { key: "automations", label: "Automatisations", icon: <Zap size={14} /> },
];

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
  template_id?: string | null;
  // ALE-286 : post dont le client a demandé de s'inspirer (chemin « J'ai une inspiration »).
  inspiration_text?: string | null;
  inspiration_author?: string | null;
  inspiration_url?: string | null;
  result: { variants?: Variant[]; save_error?: string | null } | null;
  error: string | null;
  created_at: string;
  updated_at: string;
};

// ALE-286 : un post LinkedIn lu depuis son lien, servant de référence à la génération.
type InspirationPost = {
  text: string;
  author?: string | null;
  url?: string | null;
  image_url?: string | null;
};

function generationJobIsActive(j: GenerationJob): boolean {
  return j.status === "queued" || j.status === "running";
}

// ALE-261 : un job de génération d'image IA (file d'attente). `target_key` est
// un identifiant opaque choisi par l'écran appelant (ex. "variant:2",
// "saved:<uuid>") qui désigne le bloc de post auquel l'image doit se
// rattacher — c'est ce qui permet de fermer la pop-up et de retrouver l'image
// sur le bon post à son arrivée, même après changement d'onglet ou refresh.
type ImageJob = {
  id: string;
  status: JobStatus;
  post_text: string;
  prompt: string | null;
  reference_template_id: string | null;
  target_key: string;
  result: { image_data?: string; prompt_used?: string; credits?: number | null } | null;
  error: string | null;
  created_at: string;
  updated_at: string;
};

function imageJobIsActive(j: ImageJob): boolean {
  return j.status === "queued" || j.status === "running";
}

/** Job d'image le plus récent pour un `target_key` donné (la liste est triée du plus récent au plus ancien). */
function latestImageJobFor(jobs: ImageJob[], targetKey: string): ImageJob | null {
  return jobs.find((j) => j.target_key === targetKey) ?? null;
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

function JobsView({ jobs, loading, isAuthed, onCreated, onOpenReport, requireAuth, onJobUpdated, part = "full" }: {
  jobs: Job[];
  loading: boolean;
  isAuthed: boolean;
  onCreated: (job: Job) => void;
  onOpenReport: (markdown: string, name: string) => void;
  requireAuth: (reason?: string, mode?: AuthMode) => void;
  onJobUpdated: (job: Job) => void;
  // ALE-257 : "launch" = seul le bloc de lancement de série, "series" = seule la
  // liste des séries (rangée dans un tiroir repliable par le parent), "full" = les
  // deux (comportement historique, encore utilisé hors de la page Analyses).
  part?: "launch" | "series" | "full";
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
      {part !== "series" && (
      <>
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
      </>
      )}

      {error ? <div className="error">{error}</div> : null}

      {part !== "launch" && (
      <>
      {/* Séries existantes (connectés uniquement — l'anonyme n'a qu'un essai) */}
      {!isAuthed ? (
        <div className="report-card" style={{ maxWidth: 720, cursor: "pointer" }} onClick={() => requireAuth("Crée un compte gratuit pour lancer des séries de plusieurs profils et conserver ton historique.")}>
          <div className="report-icon"><Lock size={13} /></div>
          <div><strong>Séries multi-profils & historique</strong><span>Crée un compte gratuit pour analyser plusieurs profils d'un coup et garder tes rapports.</span></div>
        </div>
      ) : loading ? (
        <div className="sk-list" style={{ display: "grid", gap: 8, maxWidth: 720 }}>
          <Sk h={44} w="100%" r={10} />
          <Sk h={44} w="100%" r={10} />
        </div>
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
      </>
      )}
    </div>
  );
}

/* ── Instagram analyse hub ─────────────────────────────────────────────── */

function InstagramAnalyzeHub({ jobs, loading, isAuthed, onCreated, onOpenReport, requireAuth, onJobUpdated, part = "full" }: {
  jobs: Job[];
  loading: boolean;
  isAuthed: boolean;
  onCreated: (job: Job) => void;
  onOpenReport: (markdown: string, name: string) => void;
  requireAuth: (reason?: string, mode?: AuthMode) => void;
  onJobUpdated: (job: Job) => void;
  // ALE-257 : "launch" = bloc de lancement, "series" = liste des séries (tiroir), "full" = les deux.
  part?: "launch" | "series" | "full";
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
      {part !== "series" && (
      <>
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
      </>
      )}

      {error ? <div className="error">{error}</div> : null}

      {part !== "launch" && (
      <>
      {!isAuthed ? (
        <div className="report-card" style={{ maxWidth: 720, cursor: "pointer" }} onClick={() => requireAuth("Crée un compte gratuit pour analyser des profils Instagram et conserver ton historique.")}>
          <div className="report-icon"><Lock size={13} /></div>
          <div><strong>Historique & séries multi-profils</strong><span>Crée un compte gratuit pour garder tes rapports et analyser plusieurs comptes d'un coup.</span></div>
        </div>
      ) : loading ? (
        <div className="sk-list" style={{ display: "grid", gap: 8, maxWidth: 720 }}>
          <Sk h={44} w="100%" r={10} />
          <Sk h={44} w="100%" r={10} />
        </div>
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
      </>
      )}
    </div>
  );
}

/* ── ALE-257 : tiroir « Séries en cours & historique » ─────────────────────
   Replié par défaut, s'ouvre automatiquement dès qu'une série tourne ou vient
   d'échouer. Réutilisé pour LinkedIn et Instagram (filtre sur `platform`). */
function SeriesDrawer({ jobs, platform, children }: {
  jobs: Job[];
  platform: Platform;
  children: React.ReactNode;
}) {
  const relevant = jobs.filter((j) =>
    platform === "instagram" ? j.platform === "instagram" : (j.platform ?? "linkedin") !== "instagram",
  );
  const hasActive = relevant.some((j) => jobIsActive(j));
  const activeCount = relevant.filter((j) => jobIsActive(j)).length;
  // Signature stable pour ne réagir qu'aux vrais changements d'état des séries.
  const sig = relevant.map((j) => `${j.id}:${j.status}:${j.failed}:${j.completed}`).join("|");
  const [open, setOpen] = useState(false);
  const prevFailedRef = useRef<Record<string, number> | null>(null);

  useEffect(() => {
    const seeded = prevFailedRef.current !== null;
    let newlyFailed = false;
    const snapshot: Record<string, number> = {};
    for (const j of relevant) {
      snapshot[j.id] = j.failed;
      // Au 1er passage on ne fait qu'amorcer le snapshot : un échec HISTORIQUE ne
      // doit pas rouvrir le tiroir à chaque chargement. Seule une série qui échoue
      // PENDANT la session compte comme « vient d'échouer ».
      if (seeded && j.failed > (prevFailedRef.current?.[j.id] ?? 0)) newlyFailed = true;
    }
    prevFailedRef.current = snapshot;
    // Auto-ouverture : une série tourne, ou une série vient d'accumuler un échec.
    if (hasActive || newlyFailed) setOpen(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig]);

  return (
    <div className="card" style={{ padding: 0, overflow: "hidden", marginBottom: 20 }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 10,
          padding: "14px 16px",
          background: "transparent",
          border: "none",
          cursor: "pointer",
          color: "var(--ink)",
          font: "inherit",
        }}
      >
        <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
          <Activity size={16} />
          <strong style={{ fontSize: 15 }}>Séries en cours &amp; historique</strong>
          {activeCount > 0 ? (
            <span className="badge"><Loader2 size={11} className="spinning" /> {activeCount} en cours</span>
          ) : null}
        </span>
        <ChevronRight size={18} style={{ flexShrink: 0, transform: open ? "rotate(90deg)" : "none", transition: "transform 0.15s" }} />
      </button>
      {open ? <div style={{ padding: "0 16px 16px" }}>{children}</div> : null}
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
  igUnread,
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
  igUnread: number;
  platform: Platform;
  onNavigate: (v: MainView) => void;
  onLoadReport: (report: Report) => void;
  onPlatformChange: (p: Platform) => void;
  requireAuth: (reason?: string, mode?: AuthMode) => void;

}) {
  const [collapsed, setCollapsed] = useState(false);
  const [collapsedPreferenceLoaded, setCollapsedPreferenceLoaded] = useState(false);
  const billing = useBilling(isAuthed);
  // ALE-246 : ouverture par réseau, découplée du réseau actif → LinkedIn et
  // Instagram peuvent rester déployés en même temps (fin de l'accordéon).
  const [openNets, setOpenNets] = useState<Record<Platform, boolean>>(() => ({
    linkedin: platform === "linkedin",
    instagram: platform === "instagram",
  }));
  // Le réseau qui devient actif s'ouvre toujours (changement de platform
  // déclenché ailleurs) → son onglet actif reste visible.
  useEffect(() => {
    setOpenNets((o) => (o[platform] ? o : { ...o, [platform]: true }));
  }, [platform]);

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
        // `soon` : réseau visible mais grisé (pas encore ouvert aux clients).
        const networks: { key: Platform; label: string; icon: React.ReactNode; soon?: boolean }[] = [
          { key: "linkedin", label: "LinkedIn", icon: <Linkedin size={14} /> },
          { key: "instagram", label: "Instagram", icon: <InstagramIcon size={14} />, soon: true },
        ];
        // ALE-257 : « Veille » retirée — l'analyse (profils, classement, tendances,
        // monitoring) vit désormais dans « Contenu » › sous-onglet « Analyses ».
        const subTabs: { key: MainView; label: string; icon: React.ReactNode; premium?: boolean }[] = [
          { key: "content", label: "Contenu", icon: <PenTool size={14} />, premium: true },
        ];
        return (
          <section className="sidebar-section sidebar-nav-tree">
            <div className="nav-list">
              {networks.map((net) => {
                // Réseau grisé : entête inerte + badge « Bientôt », aucun sous-onglet.
                if (net.soon) {
                  return (
                    <button
                      key={net.key}
                      className={`nav-item locked${collapsed ? " nav-item-collapsed" : ""}`}
                      title={`${net.label} arrive bientôt`}
                      disabled
                      style={{ cursor: "default", opacity: 0.55 }}
                    >
                      {net.icon}
                      {!collapsed && <span>{net.label}</span>}
                      {!collapsed && (
                        <span style={{ marginLeft: "auto", fontSize: 10, fontWeight: 600, color: "var(--muted)", border: "1px solid var(--border)", borderRadius: 99, padding: "1px 7px" }}>Bientôt</span>
                      )}
                    </button>
                  );
                }
                // ALE-246 : ouverture indépendante par réseau (plus d'accordéon).
                const expanded = openNets[net.key];
                const isActiveNet = platform === net.key;
                return (
                  <React.Fragment key={net.key}>
                    <button
                      className={`nav-item ${expanded ? "nav-item-open" : ""}${isActiveNet ? " nav-item-active-net" : ""}${collapsed ? " nav-item-collapsed" : ""}`}
                      title={collapsed ? net.label : undefined}
                      aria-expanded={expanded}
                      onClick={() => setOpenNets((o) => ({ ...o, [net.key]: !o[net.key] }))}
                    >
                      {net.icon}
                      {!collapsed && <span>{net.label}</span>}
                    </button>
                    {expanded && subTabs.map((tab) => {
                      const locked = !!tab.premium && !isAuthed;
                      const badge = jobBadges[net.key];
                      // ALE-257 : la progression des séries s'affiche sur « Contenu »
                      // (la Veille n'a plus d'entrée de nav dédiée).
                      const showBadge = tab.key === "content" && badge;
                      return (
                        <button
                          key={tab.key}
                          className={`nav-item nav-item-sub ${isActiveNet && view === tab.key ? "active" : ""} ${locked ? "locked" : ""}${collapsed ? " nav-item-collapsed" : ""}`}
                          title={collapsed ? tab.label : undefined}
                          onClick={() => {
                            if (locked) {
                              requireAuth("Crée un compte gratuit pour débloquer le générateur de contenu.");
                              return;
                            }
                            onPlatformChange(net.key);
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
                    {/* ALE-229 : Prospection — sous LinkedIn (Instagram est grisé en amont) */}
                    {expanded && net.key === "linkedin" && (
                      <button
                        className={`nav-item nav-item-sub ${isActiveNet && view === "prospecting" ? "active" : ""} ${!isAuthed ? "locked" : ""}${collapsed ? " nav-item-collapsed" : ""}`}
                        title={collapsed ? "Prospection" : undefined}
                        onClick={() => {
                          if (!isAuthed) {
                            requireAuth("Crée un compte gratuit pour débloquer la prospection.");
                            return;
                          }
                          onPlatformChange("linkedin");
                          onNavigate("prospecting");
                        }}
                      >
                        <Target size={14} />
                        {!collapsed && <span>Prospection</span>}
                        {!isAuthed ? <Lock size={12} className="lock-ico" /> : null}
                      </button>
                    )}
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
                    className={`nav-item ${view === "inbox" ? "active" : ""} ${locked ? "locked" : ""}${collapsed ? " nav-item-collapsed" : ""}`}
                    title={collapsed ? "Inbox" : undefined}
                    onClick={() => {
                      if (locked) {
                        requireAuth("Crée un compte gratuit pour débloquer l'inbox.");
                        return;
                      }
                      onNavigate("inbox");
                    }}
                  >
                    <InboxIcon size={14} />
                    {!collapsed && <span>Inbox</span>}
                    {!locked && igUnread > 0 ? (
                      collapsed
                        ? <span className="nav-alert-badge nav-alert-badge-dot" aria-label={`${igUnread} nouveau(x) message(s)`} />
                        : <span className="nav-alert-badge">{igUnread > 9 ? "9+" : igUnread}</span>
                    ) : null}
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
        {/* Solde + abonnement au même endroit : le solde est la conséquence de
            l'abonnement, et c'est ici qu'on vient le regarder. La carte qui vivait
            dans « Mon profil » n'avait rien à y faire (ce n'est pas un réglage). */}
        {!collapsed && isAuthed && (
          <div style={{ marginBottom: 8, display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 6 }}>
            {credits !== null && (
              <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 12, color: credits <= 5 ? "#ef4444" : "var(--muted)", border: "1px solid var(--border)", borderRadius: 20, padding: "3px 10px" }}>
                ✦ {credits} crédit{credits !== 1 ? "s" : ""}
              </span>
            )}
            {billing.status?.enabled && (
              billing.status.subscribed ? (
                <button
                  className="link-button"
                  onClick={billing.manage}
                  disabled={billing.busy}
                  style={{ fontSize: 11.5, color: "var(--muted)", textAlign: "left" }}
                  title={
                    billing.status.current_period_end
                      ? billing.status.cancel_at_period_end
                        ? `Résiliation programmée : accès jusqu'au ${formatBillingDate(billing.status.current_period_end)}.`
                        : `Prochain rechargement le ${formatBillingDate(billing.status.current_period_end)}.`
                      : "Gérer mon abonnement (carte, factures, résiliation)"
                  }
                >
                  {billing.busy ? <Loader2 size={11} className="spinning" /> : null}
                  {billing.status.cancel_at_period_end ? "Abonnement : se termine bientôt" : "Abonnement actif"} · Gérer
                </button>
              ) : (
                <button
                  className="secondary-button"
                  onClick={billing.subscribe}
                  disabled={billing.busy}
                  style={{ fontSize: 11.5, minHeight: 28, padding: "0 10px" }}
                  title={`${billing.status.plan?.credits ?? 1000} crédits rechargés ${planPeriodLabel(billing.status.plan)}. Paiement et résiliation gérés par Stripe.`}
                >
                  {billing.busy ? <Loader2 size={12} className="spinning" /> : <CreditCard size={12} />}
                  {billing.busy ? "Redirection…" : `S'abonner — ${planPriceLabel(billing.status.plan)}`}
                </button>
              )
            )}
            {billing.error ? <span style={{ fontSize: 11, color: "#ef4444" }}>{billing.error}</span> : null}
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
  // ALE-257 : Veille Instagram fusionnée dans Contenu (lancement + tiroir séries).
  loadedReport,
  onCloseReport,
  jobs,
  jobsLoading,
  onJobCreated,
  onJobUpdated,
  onOpenReport,
}: {
  tab: ContentTab;
  onTab: (t: ContentTab) => void;
  isAuthed: boolean;
  requireAuth: (reason?: string, mode?: AuthMode) => void;
  loadedReport: Report | null;
  onCloseReport: () => void;
  jobs: Job[];
  jobsLoading: boolean;
  onJobCreated: (job: Job) => void;
  onJobUpdated: (job: Job) => void;
  onOpenReport: (markdown: string, name: string) => void;
}) {
  const subTabs: { key: ContentTab; label: string; icon: React.ReactNode }[] = [
    // ALE-257 : « Analyses » en tête (Veille IG = lancement + tiroir séries).
    { key: "analyses", label: "Analyses", icon: <BarChart3 size={14} /> },
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
      {tab === "analyses" ? (
        loadedReport ? (
          <>
            <button className="secondary-button" style={{ marginBottom: 12 }} onClick={onCloseReport}>
              ← Retour aux analyses
            </button>
            <div className="markdown card"><ReactMarkdown remarkPlugins={[remarkGfm]}>{loadedReport.content}</ReactMarkdown></div>
          </>
        ) : (
          <InstagramAnalysesView
            jobs={jobs}
            jobsLoading={jobsLoading}
            onJobCreated={onJobCreated}
            onJobUpdated={onJobUpdated}
            onOpenReport={onOpenReport}
            isAuthed={isAuthed}
            requireAuth={requireAuth}
          />
        )
      ) : tab === "generator" ? (
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
    inbox: "Inbox",
    prospecting: "Prospection LinkedIn",
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
            {safeHttpUrl(post.url) ? <a className="secondary-button" href={safeHttpUrl(post.url)} target="_blank" rel="noopener noreferrer" style={{ fontSize: 12, minHeight: 28 }}>Voir sur LinkedIn</a> : null}
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
  account_name?: string | null;
  account_type?: string | null;
  connected_at?: string | null;
};

/** Libellé grand public du type de compte LinkedIn (si Zernio l'expose). */
function linkedinAccountTypeLabel(type?: string | null): string | null {
  if (!type) return null;
  const t = type.toLowerCase();
  if (/(organization|organisation|company|entreprise|page|business)/.test(t)) return "page professionnelle";
  if (/(person|personal|perso|profile|profil|member|individual)/.test(t)) return "profil personnel";
  return null;
}

/** Détail du compte LinkedIn connecté : « page professionnelle Clareo Solutions ». */
function linkedinAccountDetail(status?: LinkedInStatus | null): string | null {
  const name = status?.account_name;
  if (!name) return null;
  const label = linkedinAccountTypeLabel(status?.account_type);
  return label ? `${label} ${name}` : name;
}

/** Statut de connexion LinkedIn (via Zernio) + lancement du flux OAuth. */
// ─── ALE-274 : abonnement Stripe (49 €/mois = 1000 crédits) ───
type BillingPlan = {
  amount: number | null;
  currency: string | null;
  interval: string | null;
  credits: number;
};

type BillingStatus = {
  enabled: boolean;          // clés Stripe posées côté serveur
  subscribed: boolean;       // abonnement en cours (actif / essai / impayé en cours de relance)
  status: string | null;
  cancel_at_period_end: boolean;
  current_period_end: string | null;
  has_customer: boolean;
  plan: BillingPlan | null;
};

const BILLING_INTERVALS: Record<string, { price: string; period: string }> = {
  month: { price: "par mois", period: "chaque mois" },
  year: { price: "par an", period: "chaque année" },
  week: { price: "par semaine", period: "chaque semaine" },
};

/** « 49 € par mois » — le montant vient de Stripe, jamais codé en dur ici. */
function planPriceLabel(plan: BillingPlan | null | undefined): string {
  if (!plan || plan.amount === null) return "Abonnement";
  const amount = new Intl.NumberFormat("fr-FR", {
    style: "currency",
    currency: (plan.currency || "eur").toUpperCase(),
    maximumFractionDigits: plan.amount % 1 === 0 ? 0 : 2,
  }).format(plan.amount);
  const interval = BILLING_INTERVALS[plan.interval || ""]?.price;
  return interval ? `${amount} ${interval}` : amount;
}

function planPeriodLabel(plan: BillingPlan | null | undefined): string {
  return BILLING_INTERVALS[plan?.interval || ""]?.period || "à chaque période";
}

function formatBillingDate(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });
}

/** Abonnement Stripe : lecture de l'état + redirection vers Checkout / Customer Portal. */
function useBilling(isAuthed: boolean) {
  const [status, setStatus] = useState<BillingStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isAuthed) { setStatus(null); return; }
    (async () => {
      try {
        const res = await fetch(`${DIRECT_API_URL}/me/billing`, { headers: await authHeaders() });
        if (!res.ok) return;
        setStatus(await res.json());
      } catch { /* ignore */ }
    })();
  }, [isAuthed]);

  /** Ouvre la page de paiement hébergée par Stripe. Le crédit arrive par webhook. */
  async function subscribe() {
    setError("");
    setBusy(true);
    try {
      const base = `${window.location.origin}${window.location.pathname}`;
      const res = await fetch(`${DIRECT_API_URL}/me/billing/checkout`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ success_url: `${base}?billing=success`, cancel_url: `${base}?billing=cancelled` }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Paiement indisponible");
      window.location.href = data.url;
    } catch (err: any) {
      setError(err.message);
      setBusy(false);
    }
  }

  /** Customer Portal Stripe : carte, factures, résiliation. */
  async function manage() {
    setError("");
    setBusy(true);
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/billing/portal`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ return_url: `${window.location.origin}${window.location.pathname}` }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Gestion de l'abonnement indisponible");
      window.location.href = data.url;
    } catch (err: any) {
      setError(err.message);
      setBusy(false);
    }
  }

  return { status, busy, error, subscribe, manage };
}

function useLinkedIn(isAuthed: boolean) {
  const [status, setStatus] = useState<LinkedInStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isAuthed) { setStatus(null); return; }
    (async () => {
      try {
        const res = await fetch(`${DIRECT_API_URL}/me/linkedin/status`, { headers: await authHeaders() });
        if (!res.ok) return;
        const st: LinkedInStatus = await res.json();
        setStatus(st);
        // Backfill : les comptes connectés avant ALE-211 n'ont pas de nom stocké.
        // On récupère alors le nom depuis Zernio une seule fois (puis il est persisté).
        if (st.connected && !st.account_name) {
          try {
            const r2 = await fetch(`${DIRECT_API_URL}/me/linkedin/refresh`, { method: "POST", headers: await authHeaders() });
            if (r2.ok) setStatus(await r2.json());
          } catch { /* ignore */ }
        }
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

// ─── ALE-230 : messagerie LinkedIn (prospection) via Unipile + quotas ───
type OutreachQuota = {
  daily_cap: number;
  weekly_invite_cap: number;
  invites_today: number;
  messages_today: number;
  invites_week: number;
  can_invite: boolean;
  can_message: boolean;
  invite_blocked_reason?: string | null;
  message_blocked_reason?: string | null;
};

// ALE-174 — état du moteur d'envoi cadencé (file d'attente + warm-up + gel).
type OutreachEngine = {
  pending: number;
  last_run_at?: string | null;
  last_run_error?: string | null;
  stalled: boolean;              // le moteur ne passe plus alors qu'il reste du travail
  frozen: boolean;               // gel de sécurité (posé par le moteur, non levable ici)
  freeze_reason?: string | null;
  frozen_until?: string | null;
  warmup_week: number;
  warmup_cap: number;
  warmup_weeks_total: number;
  next_send_estimate: string;
  immediate_left: number;        // soupape « envoyer maintenant » restante sur 24 h
  immediate_cap: number;
  window: { timezone: string; hour_start: number; hour_end: number; days: number[] };
};

type OutreachQueueItem = {
  id: string;
  lead_id: string;
  action_type: "invite" | "message";
  body?: string | null;
  not_before: string;
  created_at?: string | null;
};

type OutreachStatus = {
  configured: boolean;
  connected: boolean;
  account_name?: string | null;
  connected_at?: string | null;
  quota: OutreachQuota;
  engine?: OutreachEngine | null;
};

type OutreachChat = { id: string; name?: string | null; last_message_at?: string | null; provider_url?: string | null };
type OutreachMessage = { id: string; text: string; from_me: boolean; created_at?: string | null };

const WEEKDAY_LABELS = ["L", "M", "M", "J", "V", "S", "D"]; // ISO 1..7

/** « aujourd'hui vers 14 h », « demain vers 9 h », sinon la date — pour dire au
 *  client QUAND son action partira, plutôt que de le laisser deviner. */
function formatEta(iso?: string | null): string {
  if (!iso) return "au prochain créneau";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "au prochain créneau";
  const now = new Date();
  const hour = `${at.getHours()} h${at.getMinutes() >= 30 ? "30" : ""}`;
  const sameDay = at.toDateString() === now.toDateString();
  const tomorrow = new Date(now); tomorrow.setDate(now.getDate() + 1);
  if (sameDay) return at.getTime() - now.getTime() < 90_000 ? "dans un instant" : `aujourd'hui vers ${hour}`;
  if (at.toDateString() === tomorrow.toDateString()) return `demain vers ${hour}`;
  return `${at.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" })} vers ${hour}`;
}

/** « il y a 8 min » — fraîcheur du dernier passage du moteur. */
function formatAgo(iso?: string | null): string {
  if (!iso) return "jamais";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "jamais";
  const mins = Math.max(0, Math.round((Date.now() - at.getTime()) / 60_000));
  if (mins < 1) return "à l'instant";
  if (mins < 60) return `il y a ${mins} min`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `il y a ${hours} h`;
  return `il y a ${Math.round(hours / 24)} j`;
}

/** Statut de connexion Unipile (compte LinkedIn de prospection) + quotas + file d'envoi. */
function useLinkedInOutreach(isAuthed: boolean) {
  const [status, setStatus] = useState<OutreachStatus | null>(null);
  const [queue, setQueue] = useState<OutreachQueueItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const reload = useCallback(async () => {
    if (!isAuthed) { setStatus(null); setQueue([]); return; }
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/linkedin/outreach/status`, { headers: await authHeaders() });
      if (res.ok) setStatus(await res.json());
    } catch { /* non bloquant */ }
  }, [isAuthed]);

  const reloadQueue = useCallback(async () => {
    if (!isAuthed) { setQueue([]); return; }
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/linkedin/outreach/queue`, { headers: await authHeaders() });
      if (res.ok) { const data = await res.json(); setQueue(data.items || []); }
    } catch { /* non bloquant */ }
  }, [isAuthed]);

  useEffect(() => { void reload(); }, [reload]);

  async function connect() {
    setError(""); setBusy(true);
    try {
      const redirect = `${window.location.origin}${window.location.pathname}?linkedin_outreach=connected`;
      const res = await fetch(`${DIRECT_API_URL}/me/linkedin/outreach/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ redirect_url: redirect }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Connexion impossible");
      window.location.href = data.auth_url; // Unipile gère l'auth LinkedIn puis renvoie vers l'app
    } catch (err: any) {
      setError(err.message); setBusy(false);
    }
  }

  async function disconnect() {
    if (!window.confirm("Délier le compte LinkedIn de prospection ?")) return;
    setError(""); setBusy(true);
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/linkedin/outreach`, { method: "DELETE", headers: await authHeaders() });
      if (res.ok) setStatus(await res.json());
    } catch (err: any) { setError(err.message); }
    finally { setBusy(false); }
  }

  /** Plafond quotidien + fenêtre d'envoi du moteur (fuseau, heures, jours). */
  async function saveSettings(patch: Record<string, unknown>) {
    setError(""); setBusy(true);
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/linkedin/outreach/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify(patch),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Enregistrement impossible");
      setStatus(data);
    } catch (err: any) { setError(err.message); }
    finally { setBusy(false); }
  }

  /** Retire une action de la file, tant qu'elle n'est pas partie. */
  async function cancelQueued(itemId: string) {
    setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/linkedin/outreach/queue/${itemId}`, {
        method: "DELETE", headers: await authHeaders(),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Retrait impossible");
      setQueue(data.items || []);
      void reload();
      return true;
    } catch (err: any) { setError(err.message); return false; }
  }

  return { status, queue, busy, error, reload, reloadQueue, connect, disconnect, saveSettings, cancelQueued, setStatus, setQueue };
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

// ALE-261 : génération d'image IA en file d'attente. La pop-up ne fait que
// lancer le job (`POST /generate-image/jobs`) puis affiche sa progression via
// les jobs polled par Home (`imageJobs`, passés en prop) — elle peut donc être
// fermée à tout moment sans rien perdre : le job continue côté serveur et
// l'image rejoint le bloc de post via `targetKey`, appliquée par l'écran
// appelant (pas par cette pop-up, qui peut ne plus être montée à la fin).
function ImageGenModal({
  postText,
  targetKey,
  imageJobs,
  onImageJobCreated,
  onClose,
}: {
  postText: string;
  targetKey: string;
  imageJobs: ImageJob[];
  onImageJobCreated: (job: ImageJob) => void;
  onClose: () => void;
}) {
  const [prompt, setPrompt] = useState("");
  const [loadingPrompt, setLoadingPrompt] = useState(true);
  const [launching, setLaunching] = useState(false);
  const [error, setError] = useState("");
  const postBoxRef = useRef<HTMLDivElement | null>(null);
  // Banque de templates (ALE-216) proposée comme référence visuelle optionnelle (ALE-221) :
  // fetch local à la pop-up plutôt qu'un prop threadé depuis les 4 écrans appelants.
  const [templates, setTemplates] = useState<PostTemplate[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  // Le job qu'on suit dans cette pop-up : celui qu'on vient de créer, ou — si la
  // pop-up est rouverte pendant qu'un job pour ce post tourne encore — celui déjà
  // en cours. Un job déjà terminé pour ce post n'est PAS repris : rouvrir propose
  // une génération fraîche.
  const [createdJobId, setCreatedJobId] = useState<string | null>(() => {
    const latest = latestImageJobFor(imageJobs, targetKey);
    return latest && imageJobIsActive(latest) ? latest.id : null;
  });
  const job = imageJobs.find((j) => j.id === createdJobId) ?? null;
  const active = !!job && imageJobIsActive(job);
  const done = job?.status === "done";
  const notifiedCreditsRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    authHeaders().then((h) =>
      fetch(`${DIRECT_API_URL}/me/post-templates`, { headers: h })
        .then((r) => (r.ok ? r.json() : []))
        .then((data) => { if (!cancelled) setTemplates(Array.isArray(data) ? data : []); })
        .catch(() => {})
    );
    return () => { cancelled = true; };
  }, []);
  const templatesWithImage = templates.filter((t) => !!t.image_url);
  const selectedTemplate = templatesWithImage.find((t) => t.id === selectedTemplateId) ?? null;

  // Reprend le texte du post (ou le passage sélectionné à la souris dans le bloc
  // ci-dessous) à la suite du prompt (ALE-192).
  function insertPostText() {
    const sel = window.getSelection();
    const selected =
      sel && !sel.isCollapsed && postBoxRef.current && sel.anchorNode && postBoxRef.current.contains(sel.anchorNode)
        ? sel.toString().trim()
        : "";
    const toInsert = selected || postText.trim();
    if (!toInsert) return;
    setPrompt((p) => (p.trim() ? `${p.trimEnd()}\n\n${toInsert}` : toInsert));
  }

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

  // Rafraîchit le solde affiché une seule fois par job terminé (l'attache de
  // l'image au post, elle, est faite par l'écran appelant — pas ici — pour
  // fonctionner même si cette pop-up a été fermée entre-temps).
  useEffect(() => {
    if (job?.status === "done" && notifiedCreditsRef.current !== job.id) {
      notifiedCreditsRef.current = job.id;
      emitCredits(job.result?.credits);
    }
  }, [job?.status, job?.id, job?.result?.credits]);

  async function generate() {
    setError("");
    setLaunching(true);
    try {
      const res = await fetch(`${DIRECT_API_URL}/generate-image/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({
          post_text: postText,
          prompt: prompt.trim() || undefined,
          reference_template_id: selectedTemplateId || undefined,
          target_key: targetKey,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Lancement de la génération impossible.");
      onImageJobCreated(data as ImageJob);
      setCreatedJobId(data.id);
    } catch (err: any) {
      setError(err.message || "Lancement de la génération impossible.");
    } finally {
      setLaunching(false);
    }
  }

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 1000,
      display: "flex", alignItems: "center", justifyContent: "center", padding: 16,
    }}>
      <div className="card" style={{ maxWidth: 560, width: "100%", padding: 24 }}>
        <h3 style={{ marginTop: 0, marginBottom: 2, display: "flex", alignItems: "center", gap: 8 }}>
          <ImageIcon size={16} /> {done ? "Image générée" : job?.status === "error" ? "Échec de la génération" : "Générer une image IA"}
        </h3>
        <p style={{ fontSize: 11, color: "var(--muted)", margin: "0 0 10px" }}>
          Générée avec GPT Image 2 — le dernier modèle d&apos;image d&apos;OpenAI
        </p>
        {done ? (
          <>
            <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 12 }}>
              Image jointe au post ✓ — tu la retrouves dans les miniatures sous le post
              (avec télécharger / retirer).
            </p>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={job?.result?.image_data}
              alt="Image générée"
              style={{ width: "100%", maxHeight: 380, objectFit: "contain", borderRadius: 8, border: "1px solid var(--border)", display: "block" }}
            />
            <div style={{ display: "flex", gap: 8, marginTop: 14, justifyContent: "flex-end" }}>
              <button className="primary-button" onClick={onClose}>Fermer</button>
            </div>
          </>
        ) : active ? (
          <>
            <div style={{
              display: "flex", gap: 10, alignItems: "flex-start", marginBottom: 12,
              border: "1px solid var(--border)", background: "var(--surface)",
              borderRadius: 8, padding: "10px 12px", fontSize: 13,
            }}>
              <Loader2 size={16} className="spinning" style={{ flexShrink: 0, marginTop: 1 }} />
              <span>
                <strong>Génération en cours (2 à 3 min).</strong> Tu peux fermer cette fenêtre ou
                changer d&apos;onglet : la génération continue côté serveur et l&apos;image rejoindra
                ce post automatiquement dès qu&apos;elle sera prête.
              </span>
            </div>
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button className="secondary-button" onClick={onClose}>Fermer</button>
            </div>
          </>
        ) : (
          <>
            {job?.status === "error" && (
              <div className="error" style={{ marginBottom: 12, fontSize: 13 }}>
                {job.error || "Génération d'image échouée."}
              </div>
            )}
            <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 12 }}>
              Voici le prompt préparé à partir de ton post. Ajuste-le si besoin, puis valide pour
              générer l&apos;image (5 crédits). L&apos;image sera jointe au post — tu peux fermer
              cette fenêtre pendant la génération (2 à 3 min), elle continue en arrière-plan.
            </p>
            {templatesWithImage.length > 0 && (
              <div style={{ marginBottom: 14 }}>
                <p style={{ fontSize: 12, margin: "0 0 2px", fontWeight: 600 }}>
                  Image de référence (optionnel)
                </p>
                <p style={{ fontSize: 11, color: "var(--muted)", margin: "0 0 8px", lineHeight: 1.45 }}>
                  Clique sur une image de ta bibliothèque : l&apos;IA s&apos;en inspirera pour le
                  <strong> style et la composition</strong> (couleurs, cadrage, ambiance). Elle ne
                  copiera pas son contenu.
                </p>
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                  {templatesWithImage.map((t) => {
                    const selected = selectedTemplateId === t.id;
                    const dimmed = !!selectedTemplateId && !selected;
                    const title = libraryEntryTitle(t);
                    return (
                      <button
                        key={t.id}
                        type="button"
                        aria-pressed={selected}
                        // Nom accessible stable (le libellé sous la vignette bascule sur
                        // « ✓ Sélectionnée », et l'alt de l'image le dupliquerait sinon).
                        aria-label={title}
                        title={selected ? `${title} — cliquer pour retirer` : `S'inspirer de « ${title} »`}
                        onClick={() => setSelectedTemplateId(selected ? "" : t.id)}
                        style={{
                          // Bordure toujours 2px (couleur seule qui change) : sinon la vignette
                          // change de taille à la sélection au lieu de s'entourer d'un liseré.
                          width: 92, padding: 5, borderRadius: 10, flex: "0 0 auto", cursor: "pointer",
                          border: `2px solid ${selected ? "var(--primary)" : "var(--border)"}`,
                          background: selected
                            ? "color-mix(in srgb, var(--primary) 7%, var(--surface))"
                            : "var(--surface)",
                          boxShadow: selected
                            ? "0 0 0 3px color-mix(in srgb, var(--primary) 18%, transparent)"
                            : "none",
                          opacity: dimmed ? 0.5 : 1,
                          filter: dimmed ? "grayscale(0.5)" : "none",
                          transition: "opacity 120ms ease, box-shadow 120ms ease, filter 120ms ease",
                        }}
                      >
                        <span style={{ position: "relative", display: "block" }}>
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img
                            src={t.image_url || ""}
                            alt=""
                            style={{ width: "100%", height: 76, objectFit: "cover", borderRadius: 6, display: "block" }}
                          />
                          {selected && (
                            <span style={{
                              position: "absolute", top: -7, right: -7, width: 20, height: 20,
                              borderRadius: "50%", background: "var(--primary)", color: "#fff",
                              display: "flex", alignItems: "center", justifyContent: "center",
                              boxShadow: "0 1px 4px rgba(0,0,0,0.25)",
                            }}>
                              <Check size={13} strokeWidth={3} />
                            </span>
                          )}
                        </span>
                        <span style={{
                          display: "block", marginTop: 5, fontSize: 10, lineHeight: 1.3,
                          color: selected ? "var(--primary)" : "var(--muted)",
                          fontWeight: selected ? 700 : 400,
                          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                        }}>
                          {selected ? "✓ Sélectionnée" : title}
                        </span>
                      </button>
                    );
                  })}
                </div>
                {selectedTemplate && (
                  <div style={{
                    display: "flex", gap: 10, alignItems: "center", marginTop: 10,
                    padding: "9px 11px", borderRadius: 8, fontSize: 12, lineHeight: 1.45,
                    border: "1px solid color-mix(in srgb, var(--primary) 28%, transparent)",
                    background: "color-mix(in srgb, var(--primary) 7%, var(--surface))",
                  }}>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={selectedTemplate.image_url || ""}
                      alt=""
                      style={{ width: 38, height: 38, objectFit: "cover", borderRadius: 6, flexShrink: 0, display: "block" }}
                    />
                    <span style={{ flex: 1 }}>
                      <strong>Inspiration : « {libraryEntryTitle(selectedTemplate)} »</strong><br />
                      L&apos;image sera générée dans le style et la composition de cette référence.
                    </span>
                    <button
                      type="button"
                      className="ghost-button"
                      onClick={() => setSelectedTemplateId("")}
                      style={{ fontSize: 11, flexShrink: 0 }}
                    >
                      Retirer
                    </button>
                  </div>
                )}
              </div>
            )}
            {loadingPrompt ? (
              <p style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 8 }}>
                <Loader2 size={14} className="spinning" /> Préparation du prompt…
              </p>
            ) : (
              <textarea
                className="variant-text"
                value={prompt}
                rows={5}
                onChange={(e) => setPrompt(e.target.value)}
                style={{ width: "100%", boxSizing: "border-box" }}
              />
            )}
            {!loadingPrompt && (
              <details style={{ marginTop: 10 }}>
                <summary style={{ fontSize: 12, color: "var(--muted)", cursor: "pointer" }}>
                  Reprendre des éléments du post
                </summary>
                <div
                  ref={postBoxRef}
                  style={{
                    maxHeight: 160, overflowY: "auto", fontSize: 12, whiteSpace: "pre-wrap",
                    border: "1px solid var(--border)", borderRadius: 8, padding: 10, marginTop: 8,
                  }}
                >
                  {postText}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8, flexWrap: "wrap" }}>
                  <button
                    type="button"
                    className="secondary-button"
                    // preventDefault sur mousedown : sans ça, le clic effacerait la
                    // sélection dans le bloc de post avant qu'on puisse la lire.
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={insertPostText}
                    style={{ fontSize: 12 }}
                  >
                    Insérer dans le prompt
                  </button>
                  <span style={{ fontSize: 11, color: "var(--muted)" }}>
                    Sélectionne un passage pour n&apos;insérer que lui, sinon tout le post est ajouté.
                  </span>
                </div>
              </details>
            )}
            {error && <div className="error" style={{ marginTop: 8, fontSize: 13 }}>{error}</div>}
            <div style={{ display: "flex", gap: 8, marginTop: 14, justifyContent: "flex-end", flexWrap: "wrap" }}>
              <button className="secondary-button" onClick={onClose}>Annuler</button>
              <button className="primary-button" disabled={loadingPrompt || launching || !prompt.trim()} onClick={generate}>
                {launching
                  ? <><Loader2 size={13} className="spinning" /> Lancement…</>
                  : <><Sparkles size={13} /> Générer l&apos;image</>}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ── Rôles éditoriaux (ALE-286) ──
// Partagés par le parcours guidé (où l'IA en recommande un) et par la file
// d'attente (qui en affiche le badge). Les codes doivent rester alignés sur
// ROLE_SPECS côté serveur : un code inconnu ferait échouer la génération.
const ROLE_OPTIONS: { value: string; label: string; goal: string }[] = [
  { value: "performance", label: "Performance", goal: "Maximiser l'engagement" },
  { value: "methodologie", label: "Méthodologie", goal: "Être utile, étape par étape" },
  { value: "autorite", label: "Autorité", goal: "Asseoir ton expertise" },
  { value: "story", label: "Story", goal: "Raconter une expérience vécue" },
  { value: "quotidien", label: "Quotidien", goal: "Ancrer dans le réel, sans vendre" },
  { value: "opinion", label: "Opinion", goal: "Prendre position, faire réagir" },
  { value: "relationnel", label: "Relationnel", goal: "Créer du lien, ouvrir la conversation" },
];
const ROLE_COLORS: Record<string, string> = {
  performance: "#f97316",
  methodologie: "#0ea5e9",
  autorite: "#8b5cf6",
  story: "#10b981",
  quotidien: "#14b8a6",
  opinion: "#ef4444",
  relationnel: "#ec4899",
};
function roleLabelOf(role?: string | null): string {
  return ROLE_OPTIONS.find((o) => o.value === role)?.label || role || "";
}
function roleColorOf(role?: string | null): string {
  return (role && ROLE_COLORS[role]) || "var(--primary)";
}

// Coûts affichés dans le parcours — doivent rester alignés sur CREDIT_COSTS
// (serveur). Ils ne sont qu'informatifs : c'est le serveur qui débite.
const WIZARD_IDEAS_CREDITS = 3;
const WIZARD_POST_CREDITS = 5;
// Nombre de posts affichés d'emblée dans la file (« Tout voir » montre le reste).
const QUEUE_PREVIEW_COUNT = 3;

// Une structure de la bibliothèque proposée au client à l'avant-dernière étape.
type StructureChoice = {
  id: string;
  label: string | null;
  structure_text: string | null;
  post_text: string | null;
};

function structureName(s: StructureChoice): string {
  return s.label || (s.post_text || "").slice(0, 60) || "Structure sans nom";
}

// Cache module-level : survit aux changements d'onglet dans la même session
// (ALE-145). Depuis ALE-286, les posts eux-mêmes viennent des jobs (persistés en
// base, servis par le polling de Home) : il ne reste ici que ce qui n'existe pas
// côté serveur — le texte en cours d'édition, les images jointes pas encore
// sauvegardées, et la ligne ouverte.
const _genCache: {
  appliedImageJobIds: Set<string>;
  edited: Record<string, string>;
  images: Record<string, LinkedInImageAttachment[]>;
  expanded: string | null;
} = {
  // ALE-261 : jobs d'image déjà rattachés, pour ne les appliquer qu'une fois même
  // si le job termine pendant qu'on est sur un autre onglet.
  appliedImageJobIds: new Set(),
  edited: {},
  images: {},
  expanded: null,
};

// ALE-286 : une ligne = un post. Un job terminé rend une ligne par post produit
// (le parcours n'en produit qu'un par job, mais d'anciens jobs peuvent en porter
// plusieurs) ; un job encore en vol rend une ligne d'attente. La clé est stable
// d'un rendu à l'autre : c'est elle qui porte le texte édité, les images jointes
// et la cible des images IA.
type PostLine = {
  key: string;
  job: GenerationJob;
  variant: Variant | null;
};

function buildPostLines(jobs: GenerationJob[]): PostLine[] {
  const lines: PostLine[] = [];
  for (const job of jobs) {
    const variants = job.result?.variants || [];
    if (job.status === "done" && variants.length > 0) {
      variants.forEach((variant, index) => lines.push({ key: `${job.id}:${index}`, job, variant }));
    } else {
      lines.push({ key: `${job.id}:0`, job, variant: null });
    }
  }
  return lines;
}

/** Réservoir d'idées : ajout, édition, suppression, réordonnancement (ALE-287).
 *
 * Extrait de DailyIdeasView pour être affiché AUSSI sous la file du Générateur.
 * Une seule implémentation, deux écrans : la vue client (compte `ideas_only`,
 * qui n'a que ça) et la page Générateur côté agence. Dupliquer aurait garanti
 * que les deux divergent à la première évolution.
 *
 * L'ordre compte : le cron (idée du jour, posts hebdo) pioche dedans du haut
 * vers le bas — d'où le glisser-déposer.
 */
function IdeaReservoir({
  isAuthed,
  onGenerate,
  desc = "Ajoute tes idées : l'idée du jour piochera dedans en priorité.",
}: {
  isAuthed: boolean;
  /** Fourni = un bouton « Générer un post » apparaît sur chaque idée. */
  onGenerate?: (text: string) => void;
  desc?: string;
}) {
  const [seeds, setSeeds] = useState<IdeaSeed[]>([]);
  const [draft, setDraft] = useState("");
  const [draftComment, setDraftComment] = useState("");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const [dragId, setDragId] = useState<string | null>(null);
  // Drag armé uniquement quand on saisit la poignée (le texte reste sélectionnable).
  const [dragArmedId, setDragArmedId] = useState<string | null>(null);
  const [editingSeedId, setEditingSeedId] = useState<string | null>(null);
  const [editSeedText, setEditSeedText] = useState("");
  const [editSeedComment, setEditSeedComment] = useState("");
  const [savingSeedEdit, setSavingSeedEdit] = useState(false);

  const load = useCallback(async () => {
    if (!isAuthed) { setSeeds([]); return; }
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/idea-seeds`, { headers: await authHeaders() });
      const data = await res.json();
      if (res.ok) setSeeds(Array.isArray(data) ? data : []);
    } catch { /* le réservoir est un plus : un échec de lecture n'affiche pas d'alarme */ }
  }, [isAuthed]);

  useEffect(() => { void load(); }, [load]);

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
    } catch { void load(); }
  }

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
    } catch { void load(); }
  }

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
    // "" = effacer le commentaire côté backend.
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

  return (
    <div className="card daily-reservoir">
      <div className="daily-reservoir-head">
        <div>
          <h3 className="daily-subtitle" style={{ margin: 0 }}><Lightbulb size={16} /> Mes idées de posts</h3>
          <p className="section-desc" style={{ margin: "4px 0 0" }}>{desc}</p>
        </div>
      </div>

      {error && <div className="error" style={{ marginTop: 12 }}>{error}</div>}

      <div className="daily-add">
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void addSeed(); } }}
          placeholder="Une idée de post…"
          aria-label="Une idée de post"
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
        <p style={{ color: "var(--muted)", margin: "12px 0 0", fontSize: 13 }}>
          Aucune idée en réserve — note-les ici quand elles te viennent.
        </p>
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
                {/* Libellé volontairement court : « Générer un post » porterait le même
                    nom que le gros bouton de la page — deux boutons homonymes, illisibles
                    pour un lecteur d'écran. */}
                {!isEditing && onGenerate && (
                  <button
                    className="secondary-button"
                    style={{ fontSize: 12, minHeight: 28, padding: "0 10px", flexShrink: 0 }}
                    title="Générer un post à partir de cette idée"
                    onClick={() => onGenerate(s.text)}
                  >
                    <Sparkles size={12} /> Générer
                  </button>
                )}
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
  );
}

/** Pop-up du parcours guidé : départ → idée → profil éditorial → structure → 1 post (ALE-286). */
type WizardStep = "start" | "idea" | "ideas" | "inspiration" | "role" | "structure";

/** L'état complet d'un parcours guidé, tel qu'il survit à une fermeture. */
type WizardDraft = {
  id: string;
  step: WizardStep;
  idea: string;
  inspiration: InspirationPost | null;
  ideaLines: IdeaLine[];
  pickedLine: string;
  role: string;
  reco: { editorial_role: string; reason: string } | null;
  structures: StructureChoice[];
  // "" = structure libre (aucune imposée) — c'est aussi le repli quand la
  // bibliothèque est vide, pour qu'un compte neuf ne reste pas coincé là.
  templateId: string;
  recommendedId: string | null;
  url: string;
  pasteMode: boolean;
  pasted: string;
};

function newWizardDraft(idea = ""): WizardDraft {
  return {
    id: `draft-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    step: idea ? "idea" : "start",
    idea,
    inspiration: null,
    ideaLines: [],
    pickedLine: "",
    role: "",
    reco: null,
    structures: [],
    templateId: "",
    recommendedId: null,
    url: "",
    pasteMode: false,
    pasted: "",
  };
}

// « Fermer » ne jette pas le parcours : il le laisse EN LIGNE dans la file, au
// statut « à terminer ». Le parcours coûte des crédits (les 3 idées) et de
// l'attente (lecture du post d'inspiration, reco d'angle, structures) — le
// refermer ne doit pas revenir à tout repayer. Plusieurs parcours peuvent
// coexister : le gros bouton en démarre toujours un NOUVEAU, on reprend un
// ancien en cliquant sa ligne. Store module-level (même patron que `_genCache`)
// : il survit à un changement d'onglet, pas à un rechargement de page.
let _wizardDrafts: WizardDraft[] = [];
// Chaque ouverture prend un numéro. Une réponse réseau qui arrive après une
// fermeture n'écrit dans le brouillon que si personne ne l'a rouvert entre-temps
// — sinon elle écraserait l'état courant par celui d'avant.
let _wizardOpenSeq = 0;

function upsertWizardDraft(draft: WizardDraft) {
  const i = _wizardDrafts.findIndex((d) => d.id === draft.id);
  if (i === -1) _wizardDrafts = [draft, ..._wizardDrafts];
  else _wizardDrafts = _wizardDrafts.map((d) => (d.id === draft.id ? draft : d));
}

/** Un parcours ouvert puis refermé aussitôt ne mérite pas de ligne. */
function wizardDraftHasContent(d: WizardDraft): boolean {
  return d.step !== "start" || d.idea.trim().length > 0;
}

/** Ce qui nomme la ligne : l'idée si elle est écrite, sinon celle qu'on a cochée. */
function wizardDraftTitle(d: WizardDraft): string {
  return d.idea.trim() || d.pickedLine.trim() || (d.inspiration ? `D'après le post de ${d.inspiration.author || "LinkedIn"}` : "") || "Post en préparation";
}

/** Où en est le parcours — dit au client ce qu'il lui reste à faire. */
function wizardDraftStepLabel(d: WizardDraft): string {
  if (d.step === "structure") return "il reste à choisir la structure";
  if (d.step === "role") return "il reste à choisir l'angle";
  if (d.step === "ideas") return d.pickedLine ? "idée choisie, à continuer" : "il reste à choisir une idée";
  if (d.step === "inspiration") return d.inspiration ? "post lu, à continuer" : "il reste à coller le lien du post";
  return "à continuer";
}

function PostWizardModal({
  draftId,
  onClose,
  onLaunched,
}: {
  draftId: string;
  onClose: () => void;
  onLaunched: (job: GenerationJob) => void;
}) {
  type Step = WizardStep;
  const initial = useRef(_wizardDrafts.find((d) => d.id === draftId) || newWizardDraft()).current;
  const openSeq = useRef(0);
  if (openSeq.current === 0) openSeq.current = ++_wizardOpenSeq;
  const done = useRef(false);

  const [step, setStep] = useState<Step>(initial.step);
  const [idea, setIdea] = useState(initial.idea);
  const [inspiration, setInspiration] = useState<InspirationPost | null>(initial.inspiration);
  const [seeds, setSeeds] = useState<IdeaSeed[]>([]);
  const [ideaLines, setIdeaLines] = useState<IdeaLine[]>(initial.ideaLines);
  const [pickedLine, setPickedLine] = useState<string>(initial.pickedLine);
  const [role, setRole] = useState(initial.role);
  const [reco, setReco] = useState<{ editorial_role: string; reason: string } | null>(initial.reco);
  const [structures, setStructures] = useState<StructureChoice[]>(initial.structures);
  const [templateId, setTemplateId] = useState(initial.templateId);
  const [recommendedId, setRecommendedId] = useState<string | null>(initial.recommendedId);
  const [url, setUrl] = useState(initial.url);
  const [pasteMode, setPasteMode] = useState(initial.pasteMode);
  const [pasted, setPasted] = useState(initial.pasted);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [seedSaved, setSeedSaved] = useState(false);

  // Le brouillon suit l'état à chaque frappe : au moment où le client ferme, sa
  // ligne est déjà à jour — rien à sauver dans le gestionnaire de fermeture.
  useEffect(() => {
    if (done.current) return;
    upsertWizardDraft({ id: initial.id, step, idea, inspiration, ideaLines, pickedLine, role, reco, structures, templateId, recommendedId, url, pasteMode, pasted });
  }, [initial.id, step, idea, inspiration, ideaLines, pickedLine, role, reco, structures, templateId, recommendedId, url, pasteMode, pasted]);

  /** Écrit dans le brouillon une réponse arrivée APRÈS une fermeture (fermer
   *  pendant que les 3 idées se génèrent ne doit pas les perdre : elles sont
   *  déjà payées). Sans effet si le parcours a été rouvert entre-temps. */
  function patchDraft(patch: Partial<WizardDraft>) {
    if (done.current || _wizardOpenSeq !== openSeq.current) return;
    const current = _wizardDrafts.find((d) => d.id === initial.id);
    if (!current) return;
    upsertWizardDraft({ ...current, ...patch });
  }

  /** Post lancé (ou idée rangée au réservoir) : le parcours est consommé, sa
   *  ligne disparaît. Le drapeau empêche l'effet ci-dessus de la ressusciter. */
  function clearDraft() {
    done.current = true;
    _wizardDrafts = _wizardDrafts.filter((d) => d.id !== initial.id);
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Réservoir d'idées : il vivait dans l'onglet « Idée du jour » (retiré côté
  // agence). Sans lui ici, « Enregistrer pour plus tard » n'aurait plus aucune
  // destination visible — l'idée partirait dans un trou noir.
  useEffect(() => {
    if (step !== "idea") return;
    let cancelled = false;
    authHeaders()
      .then((h) => fetch(`${DIRECT_API_URL}/me/idea-seeds`, { headers: h }))
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => { if (!cancelled) setSeeds(Array.isArray(data) ? data.filter((s: IdeaSeed) => !s.used_at) : []); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [step]);

  async function generateIdeas() {
    setBusy("ideas");
    setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/ideas`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ count: 3 }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Génération des idées impossible");
      if (typeof data.credits === "number") emitCredits(data.credits);
      const list: IdeaLine[] = Array.isArray(data.ideas) ? data.ideas : [];
      setIdeaLines(list);
      setPickedLine("");
      // Les idées sont payées : elles doivent être là au retour, même si le
      // client a fermé la pop-up pendant la génération.
      patchDraft({ step: "ideas", ideaLines: list, pickedLine: "" });
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function readInspiration() {
    setBusy("inspiration");
    setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/generate/inspiration`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ url: url.trim() }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Lecture du post impossible");
      const insp: InspirationPost = { text: data.text, author: data.author, url: data.url, image_url: data.image_url };
      setInspiration(insp);
      setIdea(data.angle || "");
      patchDraft({ step: "inspiration", inspiration: insp, idea: data.angle || "" });
    } catch (err: any) {
      setError(err.message);
      setPasteMode(true);
      patchDraft({ pasteMode: true });
    } finally {
      setBusy("");
    }
  }

  /** Le post collé à la main quand le lien est illisible : même valeur, autre porte d'entrée. */
  function applyPastedInspiration() {
    const text = pasted.trim();
    if (text.length < 20) { setError("Colle le texte du post (20 caractères minimum)."); return; }
    setError("");
    setInspiration({ text, author: null, url: url.trim() || null, image_url: null });
  }

  /** Convergence des 3 chemins : on tient l'idée, on demande le rôle recommandé. */
  async function goToRole(chosen: string) {
    const text = chosen.trim();
    if (!text) return;
    setIdea(text);
    setStep("role");
    setBusy("role");
    setError("");
    setReco(null);
    try {
      const res = await fetch(`${DIRECT_API_URL}/generate/editorial-role`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ idea: text }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Recommandation indisponible");
      const nextReco = { editorial_role: data.editorial_role as string, reason: (data.reason as string) || "" };
      setReco(nextReco);
      setRole(data.editorial_role);
      patchDraft({ step: "role", idea: text, reco: nextReco, role: data.editorial_role });
    } catch (err: any) {
      // La reco n'est qu'un confort : sans elle, le client choisit lui-même son
      // rôle plutôt que de voir le parcours s'arrêter là.
      setError(`Recommandation indisponible (${err.message}) — choisis toi-même le profil.`);
      const fallback = role || "performance";
      setRole(fallback);
      patchDraft({ step: "role", idea: text, role: fallback });
    } finally {
      setBusy("");
    }
  }

  async function saveForLater() {
    const text = idea.trim();
    if (text.length < 3) { setError("Écris ton idée d'abord."); return; }
    setBusy("seed");
    setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/idea-seeds`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ text }),
      });
      if (!res.ok) throw new Error("Enregistrement impossible");
      setSeedSaved(true);
      // L'idée est au chaud dans le réservoir : plus rien à reprendre ici.
      clearDraft();
      setTimeout(onClose, 900);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  /** Avant-dernière étape : l'IA propose les structures de la bibliothèque qui
   *  collent le mieux à l'idée + au rôle. Le client en choisit UNE. */
  async function goToStructures() {
    setStep("structure");
    setBusy("structure");
    setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/generate/structures`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ idea: idea.trim(), editorial_role: role }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Structures indisponibles");
      const list: StructureChoice[] = Array.isArray(data.structures) ? data.structures : [];
      setStructures(list);
      setRecommendedId(data.recommended_id ?? null);
      // Pré-cochée : la plus adaptée selon l'IA. Bibliothèque vide → structure libre.
      setTemplateId(data.recommended_id ?? "");
      patchDraft({ step: "structure", structures: list, recommendedId: data.recommended_id ?? null, templateId: data.recommended_id ?? "" });
    } catch (err: any) {
      // La proposition n'est qu'un confort : sans elle, on écrit le post en
      // structure libre plutôt que d'arrêter le client au bord de l'arrivée.
      setError(`Structures indisponibles (${err.message}) — le post sera écrit en structure libre.`);
      setStructures([]);
      setRecommendedId(null);
      setTemplateId("");
      patchDraft({ step: "structure", structures: [], recommendedId: null, templateId: "" });
    } finally {
      setBusy("");
    }
  }

  async function launch() {
    setBusy("launch");
    setError("");
    try {
      // Un post = un job : on passe par la file d'attente existante, qui sait
      // déjà débiter, créer le job, le suivre et l'annuler.
      const res = await fetch(`${DIRECT_API_URL}/generate/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({
          topic: idea.trim(),
          editorial_role: role,
          count: 1,
          ...(templateId ? { template_id: templateId } : {}),
          ...(inspiration
            ? { inspiration: { text: inspiration.text, author: inspiration.author, url: inspiration.url } }
            : {}),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Lancement de la génération impossible");
      if (typeof data.credits === "number") emitCredits(data.credits);
      // Le post est parti en file : le brouillon est consommé, la prochaine
      // ouverture repart de « Par où on commence ? ».
      clearDraft();
      onLaunched(data as GenerationJob);
      onClose();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  const startCards: { key: Step; icon: React.ReactNode; title: string; desc: string }[] = [
    { key: "idea", icon: <PenTool size={22} />, title: "J'ai une idée", desc: "Écris-la : on la garde pour plus tard, ou on en fait un post tout de suite." },
    { key: "ideas", icon: <Sparkles size={22} />, title: "Je n'ai pas d'idée", desc: `On t'en propose 3, tirées de ta veille et de ton positionnement (${WIZARD_IDEAS_CREDITS} crédits).` },
    { key: "inspiration", icon: <Link2 size={22} />, title: "J'ai une inspiration", desc: "Colle le lien d'un post LinkedIn qui t'a plu : on le lit et on le transpose à ton métier." },
  ];

  const stepTitle: Record<Step, string> = {
    start: "Par où on commence ?",
    idea: "Ton idée",
    ideas: "Trois idées pour toi",
    inspiration: "Le post qui t'a inspiré",
    role: "Quel angle pour ce post ?",
    structure: "Sur quelle structure ?",
  };

  return (
    <div
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      role="dialog"
      aria-modal="true"
      aria-label="Générer un post"
    >
      <div className="card" style={{ maxWidth: 720, width: "100%", padding: 24, maxHeight: "88vh", overflowY: "auto" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 4 }}>
          <h3 style={{ margin: 0 }}>{stepTitle[step]}</h3>
          <button
            className="secondary-button"
            style={{ minHeight: 30, padding: "0 10px", fontSize: 12 }}
            title="Ferme la fenêtre — ton post reste dans la file, à terminer quand tu veux."
            onClick={onClose}
          >
            Fermer
          </button>
        </div>

        {step !== "start" && (
          <button
            className="secondary-button"
            style={{ minHeight: 28, padding: "0 10px", fontSize: 12, marginBottom: 12 }}
            onClick={() => {
              // Depuis le profil éditorial, on revient au chemin qu'on avait pris.
              if (step === "structure") setStep("role");
              else if (step === "role") setStep(inspiration ? "inspiration" : ideaLines.length ? "ideas" : "idea");
              else setStep("start");
              setError("");
            }}
          >
            ← Retour
          </button>
        )}

        {error && <div className="error" style={{ marginBottom: 12 }}>{error}</div>}

        {step === "start" && (
          <div style={{ display: "grid", gap: 10, marginTop: 12 }}>
            {startCards.map((c) => (
              <button
                key={c.key}
                className="wizard-start-card"
                onClick={() => {
                  setStep(c.key);
                  setError("");
                  if (c.key === "ideas" && ideaLines.length === 0) void generateIdeas();
                }}
              >
                <span className="wizard-start-icon">{c.icon}</span>
                <span>
                  <strong>{c.title}</strong>
                  <span className="wizard-start-desc">{c.desc}</span>
                </span>
              </button>
            ))}
          </div>
        )}

        {step === "idea" && (
          <div>
            <label className="role-picker-label" htmlFor="wizard-idea">De quoi veux-tu parler ?</label>
            <textarea
              id="wizard-idea"
              className="variant-text"
              value={idea}
              onChange={(e) => setIdea(e.target.value)}
              rows={4}
              placeholder="Ex. : pourquoi la plupart des PME ratent leur premier projet IA sur le cadrage, pas sur l'outil"
              style={{ width: "100%", boxSizing: "border-box", marginTop: 6 }}
            />
            {seeds.length > 0 && (
              <div style={{ marginTop: 14 }}>
                <p className="role-picker-hint" style={{ marginBottom: 6 }}>Ou reprends une idée que tu avais mise de côté :</p>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {seeds.slice(0, 12).map((s) => (
                    <button
                      key={s.id}
                      className="secondary-button"
                      style={{ minHeight: 30, padding: "0 10px", fontSize: 12, maxWidth: "100%" }}
                      title={s.text}
                      onClick={() => setIdea(s.text)}
                    >
                      <Bookmark size={12} /> <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.text}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
            <div style={{ display: "flex", gap: 8, marginTop: 16, flexWrap: "wrap", justifyContent: "flex-end" }}>
              <button className="secondary-button" disabled={busy === "seed" || seedSaved || idea.trim().length < 3} onClick={saveForLater}>
                {busy === "seed" ? <Loader2 size={14} className="spinning" /> : <Bookmark size={14} />}
                {seedSaved ? "Gardée ✓" : "Enregistrer pour plus tard"}
              </button>
              <button className="primary-button" disabled={idea.trim().length < 3} onClick={() => goToRole(idea)}>
                Continuer <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}

        {step === "ideas" && (
          <div>
            {busy === "ideas" ? (
              <div className="web-search-status" role="status" aria-live="polite">
                <Loader2 size={16} className="spinning" />
                <span><strong>On cherche 3 idées…</strong><span>À partir de ta veille et de ton positionnement.</span></span>
              </div>
            ) : ideaLines.length === 0 ? (
              <p className="role-picker-hint">Aucune idée générée. Réessaie — ou vérifie que tu as bien analysé au moins un influenceur.</p>
            ) : (
              <div style={{ display: "grid", gap: 8 }}>
                {ideaLines.map((line, i) => {
                  const selected = pickedLine === line.line;
                  return (
                    <button
                      key={line.id || i}
                      className={`wizard-idea-line ${selected ? "selected" : ""}`}
                      aria-pressed={selected}
                      onClick={() => setPickedLine(line.line)}
                    >
                      <span className="wizard-idea-check">{selected ? <CheckCircle2 size={16} /> : <span className="wizard-idea-dot" />}</span>
                      <span>
                        <strong>{line.line}</strong>
                        {line.source_ref && <span className="wizard-idea-source">D&apos;après {line.source_ref}</span>}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
            <div style={{ display: "flex", gap: 8, marginTop: 16, flexWrap: "wrap", justifyContent: "flex-end" }}>
              <button className="secondary-button" disabled={busy === "ideas"} onClick={generateIdeas}>
                {busy === "ideas" ? <Loader2 size={14} className="spinning" /> : <RefreshCw size={14} />} Regénérer ({WIZARD_IDEAS_CREDITS} crédits)
              </button>
              <button className="primary-button" disabled={!pickedLine} onClick={() => goToRole(pickedLine)}>
                Continuer <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}

        {step === "inspiration" && (
          <div>
            {!inspiration ? (
              <>
                <label className="role-picker-label" htmlFor="wizard-url">Lien du post LinkedIn</label>
                <div className="url-input" style={{ marginTop: 6 }}>
                  <Link2 size={16} color="var(--primary)" style={{ flexShrink: 0 }} />
                  <input
                    id="wizard-url"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder="https://www.linkedin.com/posts/…"
                    onKeyDown={(e) => { if (e.key === "Enter" && url.trim() && busy !== "inspiration") void readInspiration(); }}
                  />
                  <button className="primary-button" style={{ flexShrink: 0 }} disabled={!url.trim() || busy === "inspiration"} onClick={readInspiration}>
                    {busy === "inspiration" ? <Loader2 size={14} className="spinning" /> : <Sparkles size={14} />} Lire le post
                  </button>
                </div>
                <p className="role-picker-hint" style={{ marginTop: 8 }}>
                  Le post sert de référence : l&apos;IA en reprend l&apos;angle et la forme, mais réécrit tout pour ton métier — jamais de copier-coller.
                </p>
                {pasteMode && (
                  <div style={{ marginTop: 16 }}>
                    <label className="role-picker-label" htmlFor="wizard-paste">Ou colle le texte du post</label>
                    <textarea
                      id="wizard-paste"
                      className="variant-text"
                      value={pasted}
                      onChange={(e) => setPasted(e.target.value)}
                      rows={6}
                      style={{ width: "100%", boxSizing: "border-box", marginTop: 6 }}
                    />
                    <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
                      <button className="primary-button" disabled={pasted.trim().length < 20} onClick={applyPastedInspiration}>
                        Utiliser ce texte <ChevronRight size={14} />
                      </button>
                    </div>
                  </div>
                )}
              </>
            ) : (
              <>
                <div className="card" style={{ padding: 12, background: "var(--surface)", marginBottom: 14 }}>
                  <p className="role-picker-hint" style={{ margin: "0 0 6px" }}>
                    Post lu{inspiration.author ? ` — ${inspiration.author}` : ""} :
                  </p>
                  <p style={{ margin: 0, fontSize: 13, whiteSpace: "pre-wrap", maxHeight: 160, overflowY: "auto" }}>{inspiration.text}</p>
                </div>
                <label className="role-picker-label" htmlFor="wizard-angle">L&apos;angle qu&apos;on en tire pour toi (ajuste-le si besoin)</label>
                <textarea
                  id="wizard-angle"
                  className="variant-text"
                  value={idea}
                  onChange={(e) => setIdea(e.target.value)}
                  rows={3}
                  placeholder="L'angle de ton post, en une phrase"
                  style={{ width: "100%", boxSizing: "border-box", marginTop: 6 }}
                />
                <div style={{ display: "flex", gap: 8, marginTop: 16, flexWrap: "wrap", justifyContent: "flex-end" }}>
                  <button className="secondary-button" onClick={() => { setInspiration(null); setPasteMode(false); }}>Changer de post</button>
                  <button className="primary-button" disabled={idea.trim().length < 3} onClick={() => goToRole(idea)}>
                    Continuer <ChevronRight size={14} />
                  </button>
                </div>
              </>
            )}
          </div>
        )}

        {step === "role" && (
          <div>
            <p className="role-picker-hint" style={{ marginTop: 0 }}>
              Ton idée : <strong style={{ color: "var(--ink)" }}>{idea}</strong>
            </p>
            {busy === "role" ? (
              <div className="web-search-status" role="status" aria-live="polite">
                <Loader2 size={16} className="spinning" />
                <span><strong>On cherche l&apos;angle le plus adapté…</strong></span>
              </div>
            ) : (
              <div style={{ display: "grid", gap: 8, marginTop: 12 }}>
                {ROLE_OPTIONS.map((o) => {
                  const selected = role === o.value;
                  const recommended = reco?.editorial_role === o.value;
                  return (
                    <button
                      key={o.value}
                      className={`wizard-role-card ${selected ? "selected" : ""}`}
                      aria-pressed={selected}
                      onClick={() => setRole(o.value)}
                      style={selected ? { borderColor: roleColorOf(o.value), boxShadow: `0 0 0 3px ${roleColorOf(o.value)}22` } : undefined}
                    >
                      <span className="wizard-role-main">
                        <span className="badge" style={{ borderColor: roleColorOf(o.value), color: roleColorOf(o.value) }}>{o.label}</span>
                        <span className="wizard-role-goal">{o.goal}</span>
                      </span>
                      {recommended && (
                        <span className="wizard-role-reco">
                          <Sparkles size={12} /> Recommandé{reco?.reason ? ` — ${reco.reason}` : ""}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
            <div style={{ display: "flex", gap: 8, marginTop: 16, justifyContent: "flex-end" }}>
              <button className="primary-button" disabled={!role || busy === "role"} onClick={goToStructures}>
                Continuer <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}

        {step === "structure" && (
          <div>
            <p className="role-picker-hint" style={{ marginTop: 0 }}>
              Ton idée : <strong style={{ color: "var(--ink)" }}>{idea}</strong> · Angle :{" "}
              <strong style={{ color: roleColorOf(role) }}>{roleLabelOf(role)}</strong>
            </p>
            {busy === "structure" ? (
              <div className="web-search-status" role="status" aria-live="polite">
                <Loader2 size={16} className="spinning" />
                <span><strong>On cherche les structures les plus adaptées…</strong><span>Dans ta bibliothèque.</span></span>
              </div>
            ) : (
              <div style={{ display: "grid", gap: 8, marginTop: 12 }}>
                {structures.map((s) => {
                  const selected = templateId === s.id;
                  const recommended = recommendedId === s.id;
                  const preview = (s.structure_text || s.post_text || "").replace(/\s*\n\s*/g, " → ").slice(0, 110);
                  return (
                    <button
                      key={s.id}
                      className={`wizard-role-card ${selected ? "selected" : ""}`}
                      aria-pressed={selected}
                      onClick={() => setTemplateId(s.id)}
                      style={selected ? { borderColor: "var(--primary)", boxShadow: "0 0 0 3px rgba(70, 72, 212, 0.15)" } : undefined}
                    >
                      <span className="wizard-role-main">
                        <span className="wizard-idea-check">
                          {selected ? <CheckCircle2 size={16} /> : <span className="wizard-idea-dot" />}
                        </span>
                        <strong>{structureName(s)}</strong>
                      </span>
                      {preview && <span className="wizard-role-goal">{preview}</span>}
                      {recommended && (
                        <span className="wizard-role-reco"><Sparkles size={12} /> La plus adaptée à ton idée</span>
                      )}
                    </button>
                  );
                })}

                {/* Toujours proposée : le client doit pouvoir refuser toute structure.
                    Et quand la bibliothèque est vide, c'est la seule option — le
                    parcours ne s'arrête pas là pour autant. */}
                <button
                  className={`wizard-role-card ${templateId === "" ? "selected" : ""}`}
                  aria-pressed={templateId === ""}
                  onClick={() => setTemplateId("")}
                  style={templateId === "" ? { borderColor: "var(--primary)", boxShadow: "0 0 0 3px rgba(70, 72, 212, 0.15)" } : undefined}
                >
                  <span className="wizard-role-main">
                    <span className="wizard-idea-check">
                      {templateId === "" ? <CheckCircle2 size={16} /> : <span className="wizard-idea-dot" />}
                    </span>
                    <strong>Structure libre</strong>
                  </span>
                  <span className="wizard-role-goal">
                    {structures.length === 0
                      ? "Ta bibliothèque est vide — ajoute des posts dans Ma bibliothèque pour qu'on te propose des structures."
                      : "Aucune structure imposée : l'IA écrit la forme qu'elle juge la meilleure."}
                  </span>
                </button>
              </div>
            )}
            <div style={{ display: "flex", gap: 8, marginTop: 16, flexWrap: "wrap", justifyContent: "flex-end", alignItems: "center" }}>
              <span className="role-picker-hint" style={{ marginRight: "auto" }}>
                1 post — {WIZARD_POST_CREDITS} crédits.
              </span>
              <button className="primary-button" disabled={busy === "launch" || busy === "structure"} onClick={launch}>
                {busy === "launch" ? <Loader2 size={14} className="spinning" /> : <Sparkles size={14} />}
                {busy === "launch" ? "Lancement…" : "Générer le post"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Generator({ isAuthed, requireAuth, seed, generationJobs, onGenerationJobCreated, imageJobs, onImageJobCreated, onRework }: { isAuthed: boolean; requireAuth: (reason?: string) => void; seed?: { topic: string; nonce: number } | null; generationJobs: GenerationJob[]; onGenerationJobCreated: (job: GenerationJob) => void; imageJobs: ImageJob[]; onImageJobCreated: (job: ImageJob) => void; onRework?: (post: string) => void }) {
  // Les parcours inachevés vivent dans `_wizardDrafts` (module-level) : ils
  // s'affichent en lignes dans la file, au-dessus des posts. `wizardId` ne dit
  // que lequel est ouvert dans la pop-up (null = aucune pop-up).
  const [drafts, setDrafts] = useState<WizardDraft[]>(_wizardDrafts);
  const [wizardId, setWizardId] = useState<string | null>(null);
  const [templates, setTemplates] = useState<PostTemplate[]>([]);
  const [expanded, setExpanded] = useState<string | null>(_genCache.expanded);
  const [cancelling, setCancelling] = useState<string | null>(null);
  const [error, setError] = useState("");

  // État par post, indexé par la clé de ligne (stable au remontage).
  const [edited, setEdited] = useState<Record<string, string>>(_genCache.edited);
  const [images, setImages] = useState<Record<string, LinkedInImageAttachment[]>>(_genCache.images);
  const [publishing, setPublishing] = useState<string | null>(null);
  const [published, setPublished] = useState<string | null>(null);
  const [drafted, setDrafted] = useState<string | null>(null);
  const [publishingX, setPublishingX] = useState<string | null>(null);
  const [publishedX, setPublishedX] = useState<string | null>(null);
  const [savingPost, setSavingPost] = useState<string | null>(null);
  const [savedPost, setSavedPost] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [scheduled, setScheduled] = useState<Record<string, "direct" | "slack">>({});
  const [slackSent, setSlackSent] = useState<Record<string, boolean>>({});
  const [slackSending, setSlackSending] = useState<Record<string, boolean>>({});
  const [confirmSlack, setConfirmSlack] = useState<string | null>(null);
  const [confirmPublish, setConfirmPublish] = useState<string | null>(null);
  const [confirmX, setConfirmX] = useState<string | null>(null);
  const [imageModal, setImageModal] = useState<{ key: string; text: string } | null>(null);
  const [scheduleModal, setScheduleModal] = useState<{ key: string; text: string; images: LinkedInImageAttachment[] } | null>(null);
  const [publishError, setPublishError] = useState("");
  const [imageError, setImageError] = useState("");

  const linkedin = useLinkedIn(isAuthed);
  const twitter = useTwitter(isAuthed);
  const slack = useSlack(isAuthed);

  const lines = useMemo(() => buildPostLines(generationJobs), [generationJobs]);
  // ALE-287 : la file montre les 3 derniers posts ; « Tout voir » déplie le reste.
  // Une ligne dépliée hors des 3 premiers doit rester visible, sinon le clic
  // « Réduire » ferait disparaître le post qu'on est en train de lire.
  const [showAllLines, setShowAllLines] = useState(false);
  const shownLines = showAllLines
    ? lines
    : lines.filter((l, i) => i < QUEUE_PREVIEW_COUNT || l.key === expanded);
  const hiddenCount = lines.length - shownLines.length;
  const activeCount = generationJobs.filter(generationJobIsActive).length;

  useEffect(() => { _genCache.edited = edited; }, [edited]);
  useEffect(() => { _genCache.images = images; }, [images]);
  useEffect(() => { _genCache.expanded = expanded; }, [expanded]);

  // Noms des templates : la file affiche « d'après <structure> » sur chaque ligne,
  // et le job ne porte que l'identifiant.
  useEffect(() => {
    if (!isAuthed) { setTemplates([]); return; }
    let cancelled = false;
    authHeaders()
      .then((h) => fetch(`${DIRECT_API_URL}/me/post-templates`, { headers: h }))
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => { if (!cancelled) setTemplates(Array.isArray(data) ? data : []); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [isAuthed]);

  // « Réutiliser » / « M'en inspirer » depuis un autre écran : ouvre le parcours
  // avec le sujet déjà écrit, plutôt que de lancer une génération à l'aveugle.
  useEffect(() => {
    if (!seed?.topic) return;
    const draft = newWizardDraft(seed.topic);
    upsertWizardDraft(draft);
    setWizardId(draft.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed?.nonce]);

  function templateName(templateId?: string | null): string | null {
    if (!templateId) return null;
    const t = templates.find((x) => x.id === templateId);
    return t ? libraryEntryTitle(t) : null;
  }

  function textOf(line: PostLine): string {
    return edited[line.key] ?? line.variant?.post ?? "";
  }

  function imagePayload(key: string) {
    return (images[key] || []).map((image) => ({
      ...(image.url.startsWith("data:") ? { data_url: image.url } : { url: image.url }),
      filename: image.filename,
    }));
  }

  function attachImage(key: string, url: string, source: "upload" | "generated", filename: string, id: string) {
    setImages((prev) => {
      const current = prev[key] || [];
      if (current.some((im) => im.id === id)) return prev;   // rattachement idempotent
      return { ...prev, [key]: [...current, { id, url, filename, source }].slice(0, 20) };
    });
  }

  // ALE-261/286 : l'image IA rejoint sa ligne dès que le job termine, même si la
  // pop-up a été fermée ou l'onglet quitté. La cible est la clé de ligne.
  useEffect(() => {
    for (const job of imageJobs) {
      if (job.status !== "done" || !job.result?.image_data) continue;
      if (_genCache.appliedImageJobIds.has(job.id)) continue;
      const match = /^variant:(.+)$/.exec(job.target_key);
      if (!match) continue;
      _genCache.appliedImageJobIds.add(job.id);
      attachImage(match[1], job.result.image_data, "generated", "image-generee.png", `generated-${job.id}`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imageJobs]);

  function activeImageJobFor(key: string): ImageJob | null {
    const job = latestImageJobFor(imageJobs, `variant:${key}`);
    return job && imageJobIsActive(job) ? job : null;
  }

  function addUploadedImages(key: string, files: FileList | null) {
    if (!files?.length) return;
    setImageError("");
    const imageFiles = Array.from(files).filter((file) => file.type.startsWith("image/"));
    if (imageFiles.length !== files.length) setImageError("Seuls les fichiers image sont acceptés.");
    for (const file of imageFiles) {
      if (file.size > 8 * 1024 * 1024) {
        setImageError("LinkedIn limite chaque image à 8 Mo.");
        continue;
      }
      const reader = new FileReader();
      reader.onload = () => {
        const result = typeof reader.result === "string" ? reader.result : "";
        if (!result) return;
        attachImage(key, result, "upload", file.name, `upload-${Date.now()}-${file.name}`);
      };
      reader.onerror = () => setImageError(`Lecture impossible pour ${file.name}.`);
      reader.readAsDataURL(file);
    }
  }

  function removeImage(key: string, imageId: string) {
    setImages((prev) => ({ ...prev, [key]: (prev[key] || []).filter((im) => im.id !== imageId) }));
  }

  async function cancelJob(jobId: string) {
    setCancelling(jobId);
    try {
      await fetch(`${DIRECT_API_URL}/generate/jobs/${jobId}/cancel`, {
        method: "POST",
        headers: await authHeaders(),
      });
    } catch { /* le polling de Home rattrapera l'état réel */ }
    finally { setCancelling(null); }
  }

  async function savePost(line: PostLine) {
    const id = line.variant?.id;
    if (!id) return;
    setSavingPost(line.key);
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/generated-posts/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ post: textOf(line), saved: true, images: imagePayload(line.key) }),
      });
      if (res.ok) {
        setSavedPost(line.key);
        setTimeout(() => setSavedPost((s) => (s === line.key ? null : s)), 1500);
      }
    } finally {
      setSavingPost(null);
    }
  }

  function publishPost(key: string, draft: boolean = false) {
    if (!isAuthed) { requireAuth("Connecte-toi pour publier sur LinkedIn."); return; }
    if (!linkedin.status?.connected) {
      setPublishError("Connecte d'abord ton compte LinkedIn dans l'onglet Profil.");
      return;
    }
    if (!draft) { setConfirmPublish(key); return; }
    void doPublish(key, edited[key] ?? "", true);
  }

  async function doPublish(key: string, text: string, draft: boolean = false) {
    setPublishError("");
    setPublished(null);
    setDrafted(null);
    setPublishing(key);
    setConfirmPublish(null);
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/linkedin/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ content: text, draft, images: imagePayload(key) }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || (draft ? "Enregistrement du brouillon impossible" : "Publication impossible"));
      if (draft) setDrafted(key); else setPublished(key);
    } catch (err: any) {
      setPublishError(err.message);
    } finally {
      setPublishing(null);
    }
  }

  async function doPublishX(key: string, text: string) {
    setPublishError("");
    setPublishedX(null);
    setPublishingX(key);
    setConfirmX(null);
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/x/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ content: text, draft: false }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Publication sur X impossible");
      setPublishedX(key);
    } catch (err: any) {
      setPublishError(err.message);
    } finally {
      setPublishingX(null);
    }
  }

  function openScheduleModal(line: PostLine) {
    if (!isAuthed) { requireAuth("Connecte-toi pour programmer une publication LinkedIn."); return; }
    if (!linkedin.status?.connected) {
      setPublishError("Connecte d'abord ton compte LinkedIn dans l'onglet Profil.");
      return;
    }
    setPublishError("");
    setScheduleModal({ key: line.key, text: textOf(line), images: images[line.key] || [] });
  }

  function copyPost(line: PostLine) {
    void navigator.clipboard.writeText(textOf(line));
    setCopied(line.key);
    setTimeout(() => setCopied((c) => (c === line.key ? null : c)), 1500);
  }

  /** Le gros bouton démarre TOUJOURS un nouveau post : les parcours déjà entamés
   *  se reprennent depuis leur ligne dans la file, pas depuis ce bouton. */
  function startWizard(idea = "") {
    if (!isAuthed) { requireAuth("Connecte-toi pour générer des posts."); return; }
    setError("");
    const draft = newWizardDraft(idea);
    upsertWizardDraft(draft);
    setWizardId(draft.id);
  }

  /** Fermeture : le parcours entamé reste en ligne dans la file. Celui qu'on a
   *  ouvert sans rien y faire, lui, ne laisse pas de trace. */
  function closeWizard() {
    _wizardDrafts = _wizardDrafts.filter(wizardDraftHasContent);
    setDrafts(_wizardDrafts);
    setWizardId(null);
  }

  function discardDraft(id: string) {
    _wizardDrafts = _wizardDrafts.filter((d) => d.id !== id);
    setDrafts(_wizardDrafts);
  }

  return (
    <div>
      {error && <div className="error">{error}</div>}

      {/* ALE-286 : un seul point d'entrée. Le formulaire (sujet + rôle + template
          + nombre de variants) est passé dans le parcours guidé de la pop-up. */}
      <div className="gen-hero">
        <div>
          <h2 className="section-title" style={{ margin: 0 }}><PenTool size={20} /> Générateur de posts</h2>
          <p className="section-desc" style={{ margin: "6px 0 0" }}>
            Une idée, un angle, une structure de ta bibliothèque — et ton post s&apos;écrit.
          </p>
        </div>
        <button className="primary-button gen-hero-button" onClick={() => startWizard()}>
          <Sparkles size={18} /> Générer un post
        </button>
      </div>

      <div style={{ marginTop: 24 }}>
        <h3 className="section-title" style={{ fontSize: 16 }}>
          <ListChecks size={18} /> Mes posts
          {activeCount + drafts.length > 0 && (
            <span className="badge" style={{ marginLeft: 8 }}>{activeCount + drafts.length} en cours</span>
          )}
        </h3>
        {lines.length === 0 && drafts.length === 0 ? (
          <p className="role-picker-hint">
            Aucun post pour l&apos;instant. Clique sur « Générer un post » : les posts apparaîtront ici, un par ligne, au fur et à mesure.
          </p>
        ) : (
          <div className="post-queue">
            {/* Un parcours refermé avant la fin garde SA ligne : c'est là qu'on le
                reprend. Toujours en tête — c'est ce qui attend une action. */}
            {drafts.map((d) => (
              <div key={d.id} className="post-queue-row">
                <div
                  className="post-queue-line"
                  role="button"
                  tabIndex={0}
                  onClick={() => setWizardId(d.id)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setWizardId(d.id); } }}
                >
                  <span className="post-queue-status"><PenTool size={16} color="var(--primary)" /></span>
                  <span className="post-queue-main">
                    <span className="post-queue-topic">{wizardDraftTitle(d)}</span>
                    <span className="post-queue-meta">
                      <span className="badge">En cours</span>
                      <span>· {wizardDraftStepLabel(d)}</span>
                    </span>
                  </span>
                  <button
                    className="secondary-button"
                    style={{ minHeight: 30, padding: "0 10px", fontSize: 12 }}
                    onClick={(e) => { e.stopPropagation(); discardDraft(d.id); }}
                  >
                    Supprimer
                  </button>
                  <span className="post-queue-chevron"><ChevronRight size={18} /></span>
                </div>
              </div>
            ))}
            {shownLines.map((line) => {
              const { job, key, variant } = line;
              const open = expanded === key;
              const active = generationJobIsActive(job);
              const tplName = templateName(job.template_id);
              const roleColor = roleColorOf(variant?.editorial_role || job.editorial_role);
              return (
                <div key={key} className={`post-queue-row ${open ? "open" : ""}`}>
                  <div
                    className="post-queue-line"
                    role={variant ? "button" : undefined}
                    tabIndex={variant ? 0 : undefined}
                    aria-expanded={variant ? open : undefined}
                    onClick={() => { if (variant) setExpanded(open ? null : key); }}
                    onKeyDown={(e) => {
                      if (!variant) return;
                      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setExpanded(open ? null : key); }
                    }}
                  >
                    <span className="post-queue-status">
                      {active ? <Loader2 size={16} className="spinning" /> :
                       job.status === "done" ? <CheckCircle2 size={16} color="#10b981" /> :
                       job.status === "error" ? <AlertCircle size={16} color="#ef4444" /> :
                       <XCircle size={16} color="var(--muted)" />}
                    </span>
                    <span className="post-queue-main">
                      <span className="post-queue-topic">{job.topic || "Sujet libre"}</span>
                      {/* L'angle et la structure s'affichent DÈS le lancement, pas
                          seulement une fois le post écrit : sans eux, les trois lignes
                          du parcours seraient trois « En attente… » identiques, et rien
                          ne dirait au client pourquoi il y en a trois. */}
                      <span className="post-queue-meta">
                        <span className="badge" style={{ borderColor: roleColor, color: roleColor }}>
                          {roleLabelOf(variant?.editorial_role || job.editorial_role) || "Mix auto"}
                        </span>
                        {tplName ? <span>d&apos;après <strong>{tplName}</strong></span> : <span>structure libre</span>}
                        {active && <span>· {job.status === "queued" ? "en attente…" : "écriture en cours…"}</span>}
                        {job.status === "cancelled" && <span>· annulé</span>}
                        {job.status === "error" && (
                          <span style={{ color: "var(--danger)" }}>· {job.error || "échec de la génération"}</span>
                        )}
                      </span>
                    </span>
                    {active ? (
                      <button
                        className="secondary-button"
                        style={{ minHeight: 30, padding: "0 10px", fontSize: 12 }}
                        disabled={cancelling === job.id}
                        onClick={(e) => { e.stopPropagation(); void cancelJob(job.id); }}
                      >
                        {cancelling === job.id ? <Loader2 size={12} className="spinning" /> : null} Annuler
                      </button>
                    ) : variant ? (
                      <span className="post-queue-chevron">{open ? <ChevronDown size={18} /> : <ChevronRight size={18} />}</span>
                    ) : null}
                  </div>

                  {open && variant && (
                    <div className="post-queue-body">
                      {variant.strategy && <p className="variant-strategy">{variant.strategy}</p>}
                      <div className="variant-text-wrap">
                        <textarea
                          className="variant-text"
                          value={textOf(line)}
                          rows={14}
                          onChange={(e) => setEdited((prev) => ({ ...prev, [key]: e.target.value }))}
                        />
                        <button
                          type="button"
                          className="variant-copy-button"
                          aria-label={copied === key ? "Post copié" : "Copier le post"}
                          title={copied === key ? "Copié ✓" : "Copier le post"}
                          onClick={() => copyPost(line)}
                        >
                          {copied === key ? <CheckCircle2 size={16} /> : <Copy size={16} />}
                        </button>
                      </div>
                      {edited[key] !== undefined && edited[key] !== variant.post && (
                        <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 4 }}>
                          <span style={{ fontSize: 12, color: "var(--muted)" }}>✏️ Modifié</span>
                          <button
                            className="secondary-button"
                            style={{ fontSize: 12, minHeight: 28, padding: "0 10px" }}
                            onClick={() => setEdited((prev) => { const n = { ...prev }; delete n[key]; return n; })}
                          >
                            Revenir à l&apos;original
                          </button>
                        </div>
                      )}
                      <PostActionsBar
                        publishBusy={publishing === key && published !== key}
                        publishLabel={published === key ? "Publié ✓" : publishing === key ? "Publication…" : "Publier"}
                        publishActions={[
                          {
                            key: "linkedin",
                            icon: <Linkedin size={14} />,
                            label: published === key ? "Publié sur LinkedIn ✓" : "Publier maintenant sur LinkedIn",
                            disabled: publishing === key,
                            title: linkedin.status?.connected ? "Publier maintenant sur LinkedIn" : "Connecte ton compte LinkedIn dans l'onglet Profil",
                            onClick: () => publishPost(key),
                          },
                          {
                            key: "schedule",
                            icon: <Clock3 size={14} />,
                            label: scheduled[key] ? "Programmé ✓" : "Programmer…",
                            disabled: publishing === key || !!scheduled[key],
                            title: linkedin.status?.connected
                              ? "Programmer : publication directe à une date, ou validation Slack au préalable"
                              : "Connecte ton compte LinkedIn dans l'onglet Profil",
                            onClick: () => openScheduleModal(line),
                          },
                          ...(slack.status?.connected && variant.id
                            ? [{
                                key: "slack",
                                icon: <Send size={14} />,
                                label: slackSent[key] ? "Sur Slack ✓" : "Envoyer sur Slack pour validation",
                                disabled: !!slackSending[key] || !!slackSent[key],
                                onClick: () => setConfirmSlack(key),
                              } satisfies PostAction]
                            : []),
                          ...(twitter.status?.connected
                            ? [{
                                key: "x",
                                icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.742l7.734-8.842L1.254 2.25H8.08l4.253 5.622L18.244 2.25zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>,
                                label: publishingX === key ? "Publication…" : publishedX === key ? "Publié sur X ✓" : "Publier sur X",
                                disabled: publishingX === key,
                                onClick: () => {
                                  if (!isAuthed) { requireAuth("Connecte-toi pour publier sur X."); return; }
                                  if (!twitter.status?.connected) { setPublishError("Connecte d'abord ton compte X dans l'onglet Profil."); return; }
                                  setConfirmX(key);
                                },
                              } satisfies PostAction]
                            : []),
                        ]}
                        moreActions={[
                          ...(variant.id
                            ? [{
                                key: "save",
                                icon: <Bookmark size={14} />,
                                label: savedPost === key ? "Sauvegardé ✓" : "Sauvegarder",
                                disabled: savingPost === key,
                                title: "Sauvegarder ce post dans « Mes contenus »",
                                onClick: () => savePost(line),
                              } satisfies PostAction]
                            : []),
                          {
                            key: "attach",
                            icon: <ImagePlus size={14} />,
                            label: "Joindre des images",
                            filePicker: {
                              accept: "image/png,image/jpeg,image/jpg,image/webp,image/gif",
                              multiple: true,
                              onFiles: (files) => addUploadedImages(key, files),
                            },
                          },
                          {
                            key: "image-ia",
                            icon: <ImageIcon size={14} />,
                            label: "Générer une image IA",
                            title: "Prépare un prompt d'illustration à valider, puis génère l'image (5 crédits)",
                            onClick: () => setImageModal({ key, text: textOf(line) }),
                          },
                          ...(onRework
                            ? [{
                                key: "rework",
                                icon: <MessageSquare size={14} />,
                                label: "Retravailler avec l'Agent IA",
                                title: "Ouvrir ce post dans l'Agent IA pour le retravailler",
                                onClick: () => onRework(textOf(line)),
                              } satisfies PostAction]
                            : []),
                        ]}
                      />
                      {confirmSlack === key && (
                        <div className="idea-footer" style={{ gap: 8, marginTop: 8, alignItems: "center", flexWrap: "wrap" }}>
                          <span style={{ fontSize: 13 }}>Envoyer ce post sur Slack pour validation ?</span>
                          <DevSlackNote />
                          <button
                            className="primary-button"
                            style={{ fontSize: 12, minHeight: 30, padding: "0 10px" }}
                            disabled={!!slackSending[key]}
                            onClick={async () => {
                              setSlackSending((p) => ({ ...p, [key]: true }));
                              try {
                                await fetch(`${DIRECT_API_URL}/me/integrations/slack/send-posts`, {
                                  method: "POST",
                                  headers: { "Content-Type": "application/json", ...(await authHeaders()) },
                                  body: JSON.stringify({ post_id: variant.id, content: textOf(line), images: imagePayload(key) }),
                                });
                                setSlackSent((p) => ({ ...p, [key]: true }));
                              } finally {
                                setSlackSending((p) => ({ ...p, [key]: false }));
                                setConfirmSlack(null);
                              }
                            }}
                          >
                            {slackSending[key] ? <Loader2 size={12} className="spinning" /> : null} Confirmer l&apos;envoi
                          </button>
                          <button className="secondary-button" style={{ fontSize: 12, minHeight: 30, padding: "0 10px" }} onClick={() => setConfirmSlack(null)}>Annuler</button>
                        </div>
                      )}
                      {published === key && <p className="role-picker-hint" style={{ marginTop: 6 }}>Post publié sur LinkedIn ✓</p>}
                      {drafted === key && <p className="role-picker-hint" style={{ marginTop: 6 }}>Brouillon enregistré ✓</p>}
                      {publishedX === key && <p className="role-picker-hint" style={{ marginTop: 6 }}>Post publié sur X ✓</p>}
                      {scheduled[key] && (
                        <p className="role-picker-hint" style={{ marginTop: 6 }}>
                          {scheduled[key] === "slack" ? "Post programmé ✓ — demande de validation envoyée sur Slack." : "Post programmé sur LinkedIn ✓"}
                        </p>
                      )}
                      {activeImageJobFor(key) && (
                        <p className="role-picker-hint" style={{ marginTop: 6, display: "flex", alignItems: "center", gap: 6 }}>
                          <Loader2 size={12} className="spinning" /> Image IA en cours de génération… elle rejoindra ce post automatiquement.
                        </p>
                      )}
                      {(images[key] || []).length > 0 && (
                        <div style={{ marginTop: 12 }}>
                          <p className="role-picker-hint" style={{ marginBottom: 8 }}>
                            {(images[key] || []).length} image{(images[key] || []).length > 1 ? "s" : ""} jointe{(images[key] || []).length > 1 ? "s" : ""} au post LinkedIn.
                          </p>
                          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 10, maxWidth: 640 }}>
                            {(images[key] || []).map((image, imageIndex) => (
                              <div key={image.id} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 8, background: "var(--surface)" }}>
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
                                    onClick={() => removeImage(key, image.id)}
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
                  )}
                </div>
              );
            })}
          </div>
        )}

        {(hiddenCount > 0 || showAllLines) && (
          <button
            className="secondary-button"
            style={{ marginTop: 10 }}
            onClick={() => setShowAllLines((v) => !v)}
          >
            {showAllLines
              ? <>Réduire <ChevronDown size={14} style={{ transform: "rotate(180deg)" }} /></>
              : <>Tout voir ({lines.length}) <ChevronDown size={14} /></>}
          </button>
        )}
      </div>

      {/* ALE-287 : le réservoir a sa place ICI. Il ne vivait plus que dans la
          pop-up, où l'on ne pouvait ni en ajouter plusieurs, ni en supprimer, ni
          les réordonner — alors que l'ordre décide de ce que le cron pioche. */}
      <div style={{ marginTop: 28 }}>
        <IdeaReservoir
          isAuthed={isAuthed}
          desc="Note tes idées quand elles viennent. Génère le post quand tu veux — l'idée du jour pioche aussi dedans, de haut en bas."
          onGenerate={(text) => startWizard(text)}
        />
      </div>

      {publishError && <div className="error" style={{ marginTop: 12 }}>{publishError}</div>}
      {imageError && <div className="error" style={{ marginTop: 12 }}>{imageError}</div>}

      {wizardId && (
        <PostWizardModal
          draftId={wizardId}
          onClose={closeWizard}
          onLaunched={(job) => {
            // Le post apparaît aussitôt en file, sans attendre le prochain tour
            // de polling — sinon le client croirait que son clic n'a rien fait.
            onGenerationJobCreated(job);
            setExpanded(null);
          }}
        />
      )}

      {imageModal && (
        <ImageGenModal
          postText={imageModal.text}
          targetKey={`variant:${imageModal.key}`}
          imageJobs={imageJobs}
          onImageJobCreated={onImageJobCreated}
          onClose={() => setImageModal(null)}
        />
      )}

      {confirmPublish !== null && (
        <PublishConfirmModal
          text={edited[confirmPublish] ?? lines.find((l) => l.key === confirmPublish)?.variant?.post ?? ""}
          images={(images[confirmPublish] || []).map((im) => ({ url: im.url, filename: im.filename }))}
          busy={publishing !== null}
          onClose={() => setConfirmPublish(null)}
          onConfirm={(t) => {
            const key = confirmPublish;
            setEdited((prev) => ({ ...prev, [key]: t }));
            void doPublish(key, t);
          }}
        />
      )}

      {confirmX !== null && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}>
          <div className="card" style={{ maxWidth: 560, width: "100%", padding: 24 }}>
            <h3 style={{ marginTop: 0, marginBottom: 8 }}>Publier ce post sur X ?</h3>
            <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 12 }}>
              Le post sera publié <strong>immédiatement</strong> sur ton compte X (Twitter).
            </p>
            <textarea
              readOnly
              value={edited[confirmX] ?? lines.find((l) => l.key === confirmX)?.variant?.post ?? ""}
              rows={8}
              className="variant-text"
              style={{ width: "100%", boxSizing: "border-box", marginBottom: 16 }}
            />
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button className="secondary-button" onClick={() => setConfirmX(null)}>Annuler</button>
              <button
                className="primary-button"
                disabled={publishingX !== null}
                onClick={() => doPublishX(confirmX, edited[confirmX] ?? lines.find((l) => l.key === confirmX)?.variant?.post ?? "")}
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
            setScheduled((prev) => ({ ...prev, [scheduleModal.key]: viaSlack ? "slack" : "direct" }));
            setScheduleModal(null);
          }}
        />
      )}
    </div>
  );
}


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

// ALE-261 : cache module-level pour les images IA jointes aux idées du jour —
// même rationale que `_genCache` (ALE-145) : sans lui, une image attachée
// pendant qu'on est sur un autre onglet serait perdue au remontage du composant.
const _dailyIdeaCache: { ideaImages: Record<string, string[]>; appliedImageJobIds: Set<string> } = {
  ideaImages: {},
  appliedImageJobIds: new Set(),
};

function DailyIdeasView({
  isAuthed,
  requireAuth,
  onReuse,
  onRework,
  reservoirOnly = false,
  imageJobs,
  onImageJobCreated,
}: {
  isAuthed: boolean;
  requireAuth: (reason?: string) => void;
  onReuse: (topic: string) => void;
  onRework?: (post: string) => void;
  reservoirOnly?: boolean;
  imageJobs: ImageJob[];
  onImageJobCreated: (job: ImageJob) => void;
}) {
  const [ideas, setIdeas] = useState<DailyIdea[]>([]);
  const [loading, setLoading] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [error, setError] = useState("");

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
        body: JSON.stringify({ count: 3, web_search: batchWebSearch }),
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
  const [ideaImages, setIdeaImages] = useState<Record<string, string[]>>(_dailyIdeaCache.ideaImages);
  useEffect(() => { _dailyIdeaCache.ideaImages = ideaImages; }, [ideaImages]);

  // ALE-261 : rattache l'image dès qu'un job `idea:{id}` termine, même si la
  // pop-up a été fermée ou l'onglet quitté entre-temps (le job continue en fond).
  useEffect(() => {
    for (const job of imageJobs) {
      if (job.status !== "done" || !job.result?.image_data) continue;
      if (_dailyIdeaCache.appliedImageJobIds.has(job.id)) continue;
      const match = /^idea:(.+)$/.exec(job.target_key);
      if (!match) continue;
      _dailyIdeaCache.appliedImageJobIds.add(job.id);
      const ideaId = match[1];
      const dataUrl = job.result.image_data;
      setIdeaImages((prev) => ({ ...prev, [ideaId]: [...(prev[ideaId] || []), dataUrl] }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imageJobs]);

  function activeImageJobForIdea(id: string): ImageJob | null {
    const job = latestImageJobFor(imageJobs, `idea:${id}`);
    return job && imageJobIsActive(job) ? job : null;
  }

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

  async function publishPost(it: DailyIdea, overrideText?: string) {
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
          content: overrideText ?? postTextOf(it),
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
  const todayIso = new Date().toLocaleDateString("en-CA");

  async function loadAll() {
    if (!isAuthed) return;
    setLoading(true);
    setError("");
    try {
      const headers = await authHeaders();
      // Le réservoir se charge lui-même (IdeaReservoir). Compte restreint : pas de
      // corpus, donc rien d'autre à aller chercher.
      if (!reservoirOnly) {
        const dRes = await fetch(`${DIRECT_API_URL}/me/daily-ideas`, { headers });
        const dData = await dRes.json();
        if (!dRes.ok) throw new Error(dData.detail || "Chargement des idées impossible");
        setIdeas(Array.isArray(dData?.ideas) ? dData.ideas : []);
      }
    } catch (err: any) {
      setError(err.message || "Chargement impossible");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (isAuthed) void loadAll();
    else setIdeas([]);
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
              Un lot de 3 idées en une ligne, ancrées dans tes vrais posts performants. 3 crédits/lot.
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
                    {safeHttpUrl(idea.source_url) ? (
                      <a href={safeHttpUrl(idea.source_url)} target="_blank" rel="noopener noreferrer">{idea.source_ref}</a>
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
            <div className="sk-list" style={{ display: "grid", gap: 8, textAlign: "left" }}>
              <Sk h={12} w="45%" r={6} />
              <Sk h={10} w="100%" />
              <Sk h={10} w="92%" />
              <Sk h={10} w="68%" />
            </div>
          ) : (
            <p style={{ margin: 0 }}>
              Pas encore d'idée générée. Active « Recevoir une idée chaque matin » dans <strong>Mon profil</strong> et
              ajoute des idées à ton réservoir — la première arrivera demain matin.
            </p>
          )}
        </div>
      ) : (
        <div className="daily-ideas-lines">
          {ideas.map((it) => {
            const isPost = !!it.post_text;
            const idea = isPost ? null : parseDailyIdeaMarkdown(it.idea_markdown);
            const isToday = it.idea_date === todayIso;
            return (
              <details className="card daily-idea-line" key={it.id}>
                {/* Ligne fermée par défaut, tag "Aujourd'hui" seulement si la date correspond (demande Alex 2026-07-08). */}
                <summary>
                  <span className="daily-line-date">{fmtDate(it.idea_date)}</span>
                  {isToday ? <span className="daily-today-tag">Aujourd'hui</span> : null}
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
                            {safeHttpUrl(it.source_url) && <> · <a href={safeHttpUrl(it.source_url)} target="_blank" rel="noreferrer">voir l'annonce</a></>}
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
                      {activeImageJobForIdea(it.id) && (
                        <p className="role-picker-hint" style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 6 }}>
                          <Loader2 size={12} className="spinning" /> Image IA en cours de génération… elle rejoindra ce post automatiquement.
                        </p>
                      )}
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
                        <PublishConfirmModal
                          text={postTextOf(it)}
                          images={ideaImagePayload(it).map((im) => ({ url: im.url }))}
                          busy={publishingId === it.id}
                          onClose={() => setConfirmPublishId(null)}
                          onConfirm={(t) => { setEditedPost((prev) => ({ ...prev, [it.id]: t })); publishPost(it, t); }}
                        />
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
          targetKey={`idea:${imageModalIdea.id}`}
          imageJobs={imageJobs}
          onImageJobCreated={onImageJobCreated}
          onClose={() => setImageModalIdea(null)}
        />
      )}
      </>
      )}

      <IdeaReservoir isAuthed={isAuthed} />
    </div>
  );
}

// ALE-223 : tiroir repliable réutilisable pour l'onglet « Ma bibliothèque »
// (contenus sauvegardés / posts programmés / références & templates).
function LibDrawer({
  icon,
  title,
  desc,
  open,
  onToggle,
  right,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  desc?: string;
  open: boolean;
  onToggle: () => void;
  right?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section style={{ marginBottom: 24 }}>
      <div className="section-header" style={{ marginBottom: open ? 16 : 0 }}>
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          title={open ? "Replier" : "Déplier"}
          style={{ display: "flex", alignItems: "flex-start", gap: 8, background: "none", border: "none", padding: 0, cursor: "pointer", textAlign: "left", color: "inherit", flex: 1, minWidth: 0 }}
        >
          <ChevronRight size={20} style={{ marginTop: 2, flexShrink: 0, transform: open ? "rotate(90deg)" : "none", transition: "transform 0.15s" }} />
          <div>
            <h2 className="section-title">{icon} {title}</h2>
            {desc && <p className="section-desc">{desc}</p>}
          </div>
        </button>
        {right}
      </div>
      {open && children}
    </section>
  );
}

// ALE-261 : applied-tracking module-level pour les jobs d'image de « Mes contenus » —
// l'image elle-même est persistée côté serveur (persistSavedPostImages), seule
// l'idempotence (ne pas la joindre deux fois) doit survivre au remontage du composant.
const _libraryAppliedImageJobIds = new Set<string>();

function LibraryView({
  isAuthed,
  requireAuth,
  onReuse,
  onRework,
  imageJobs,
  onImageJobCreated,
}: {
  isAuthed: boolean;
  requireAuth: (reason?: string) => void;
  onReuse: (topic: string) => void;
  onRework?: (post: string) => void;
  imageJobs: ImageJob[];
  onImageJobCreated: (job: ImageJob) => void;
}) {
  const [posts, setPosts] = useState<SavedPost[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState<string | null>(null);
  const [editedPosts, setEditedPosts] = useState<Record<string, string>>({});
  const [savingPost, setSavingPost] = useState<string | null>(null);
  const [savedPost, setSavedPost] = useState<string | null>(null);
  // Tiroirs repliables (ALE-223) : les contenus sauvegardés sont ouverts par défaut,
  // les posts programmés repliés.
  const [savedOpen, setSavedOpen] = useState(true);
  const [scheduledOpen, setScheduledOpen] = useState(false);
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

  async function publishSavedPost(p: SavedPost, overrideText?: string) {
    setConfirmPublishPostId(null);
    if (!linkedin.status?.connected) {
      setPublishError("Connecte d'abord ton compte LinkedIn dans l'onglet Profil.");
      return;
    }
    setPublishError("");
    setPublishingPost(p.id);
    try {
      const text = overrideText ?? editedPosts[p.id] ?? p.post;
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

  // ALE-261 : rattache l'image dès qu'un job `saved:{id}` termine, même si la
  // pop-up a été fermée ou l'onglet quitté entre-temps. On relit `posts` (pas le
  // post capturé à l'ouverture de la pop-up) pour ne pas écraser des images
  // jointes entre-temps par ailleurs.
  useEffect(() => {
    for (const job of imageJobs) {
      if (job.status !== "done" || !job.result?.image_data) continue;
      if (_libraryAppliedImageJobIds.has(job.id)) continue;
      const match = /^saved:(.+)$/.exec(job.target_key);
      if (!match) continue;
      const post = posts.find((pp) => pp.id === match[1]);
      if (!post) continue;
      _libraryAppliedImageJobIds.add(job.id);
      void persistSavedPostImages(post, [...savedPostImagePayload(post), { data_url: job.result.image_data, filename: "image-ia.png" }]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imageJobs, posts]);

  function activeImageJobForSavedPost(id: string): ImageJob | null {
    const job = latestImageJobFor(imageJobs, `saved:${id}`);
    return job && imageJobIsActive(job) ? job : null;
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
        <PostCardsSkeleton cards={3} />
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
                  <PublishConfirmModal
                    text={editedPosts[p.id] ?? p.post}
                    images={savedPostImagePayload(p).map((im) => ({ url: im.url, filename: im.filename }))}
                    busy={publishingPost === p.id}
                    onClose={() => setConfirmPublishPostId(null)}
                    onConfirm={(t) => { setEditedPosts((prev) => ({ ...prev, [p.id]: t })); publishSavedPost(p, t); }}
                  />
                )}
                {activeImageJobForSavedPost(p.id) && (
                  <p className="role-picker-hint" style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 6 }}>
                    <Loader2 size={12} className="spinning" /> Image IA en cours de génération… elle rejoindra ce post automatiquement.
                  </p>
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
        <LibDrawer
          icon={<Clock3 size={20} />}
          title={`Posts programmés${scheduledPosts.length ? ` (${scheduledPosts.length})` : ""}`}
          desc="Posts en attente de publication ou déjà publiés via la programmation LinkedIn."
          open={scheduledOpen}
          onToggle={() => setScheduledOpen((v) => !v)}
        >
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
        </LibDrawer>
      )}

      {imageModalSaved && (
        <ImageGenModal
          postText={editedPosts[imageModalSaved.id] ?? imageModalSaved.post}
          targetKey={`saved:${imageModalSaved.id}`}
          imageJobs={imageJobs}
          onImageJobCreated={onImageJobCreated}
          onClose={() => setImageModalSaved(null)}
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
  targetKey,
  imageJobs,
  onImageJobCreated,
  linkedin,
  twitter,
  slack,
}: {
  text: string;
  targetKey: string;
  imageJobs: ImageJob[];
  onImageJobCreated: (job: ImageJob) => void;
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
  // Édition manuelle du post proposé : la bulle de conversation reste intacte,
  // mais toutes les actions (publier, programmer, Slack, X, sauvegarder, image)
  // opèrent sur la version modifiée, affichée sous la réponse.
  const [editedText, setEditedText] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editDraft, setEditDraft] = useState("");
  const [err, setErr] = useState("");

  const postText = editedText ?? text;

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

  // ALE-261 : rattache l'image dès qu'un job pour ce message termine, même si la
  // pop-up a été fermée entre-temps. Suivi local (pas de cache module-level) :
  // comme les images jointes à une réponse de l'Assistant sont déjà perdues au
  // remontage du composant (pas de persistance tant que le post n'est pas
  // sauvegardé), un `ref` scoppé à cette instance suffit — cohérent avec le
  // reste du comportement de cet écran.
  const appliedImageJobIdsRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    for (const job of imageJobs) {
      if (job.status !== "done" || !job.result?.image_data) continue;
      if (job.target_key !== targetKey) continue;
      if (appliedImageJobIdsRef.current.has(job.id)) continue;
      appliedImageJobIdsRef.current.add(job.id);
      setImages((prev) => [...prev, {
        id: `generated-${job.id}`,
        url: job.result!.image_data!,
        filename: "image-ia.png",
        source: "generated",
      }]);
    }
  }, [imageJobs, targetKey]);
  const activeImageJob = latestImageJobFor(imageJobs, targetKey);
  const generatingImage = !!activeImageJob && imageJobIsActive(activeImageJob);

  async function copy() {
    try {
      await navigator.clipboard.writeText(postText);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { setErr("Copie impossible."); }
  }

  async function publishLinkedIn(overrideText?: string) {
    setConfirmPub(false);
    if (overrideText !== undefined) setEditedText(overrideText);
    if (!linkedin.status?.connected) { setErr("Connecte d'abord ton compte LinkedIn dans l'onglet Profil."); return; }
    setErr(""); setPublishing(true);
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/linkedin/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({
          content: overrideText ?? postText,
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
        body: JSON.stringify({ content: postText, draft: false }),
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
        body: JSON.stringify({ post: postText, images: imagePayload() }),
      });
      const saved = await saveRes.json();
      if (!saveRes.ok) throw new Error(saved.detail || "Sauvegarde impossible.");
      const res = await fetch(`${DIRECT_API_URL}/me/integrations/slack/send-posts`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ post_id: saved.id, content: postText, images: imagePayload() }),
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
        body: JSON.stringify({ post: postText, images: imagePayload() }),
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
            key: "edit",
            icon: <Pencil size={14} />,
            label: editedText !== null ? "Modifier le post (modifié)" : "Modifier le post",
            title: "Retoucher le texte à la main : c'est la version modifiée qui sera publiée, programmée, envoyée ou sauvegardée",
            onClick: () => { setErr(""); setEditDraft(postText); setEditing(true); },
          },
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
      {editing && (
        <div style={{ width: "100%", marginTop: 8 }}>
          <label style={{ fontSize: 13, fontWeight: 500, display: "block", marginBottom: 6 }}>Modifier le post</label>
          <textarea
            value={editDraft}
            rows={10}
            className="variant-text"
            style={{ width: "100%", boxSizing: "border-box", marginBottom: 8 }}
            onChange={(e) => setEditDraft(e.target.value)}
            autoFocus
          />
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              className="primary-button"
              style={btn}
              disabled={!editDraft.trim()}
              onClick={() => { setEditedText(editDraft.trim() === text.trim() ? null : editDraft); setEditing(false); }}
            >
              <CheckCircle2 size={13} /> Enregistrer
            </button>
            <button className="secondary-button" style={btn} onClick={() => setEditing(false)}>Annuler</button>
            {editedText !== null && (
              <button
                className="secondary-button"
                style={btn}
                onClick={() => { setEditedText(null); setEditing(false); }}
              >
                Revenir au texte d&apos;origine
              </button>
            )}
          </div>
        </div>
      )}
      {!editing && editedText !== null && (
        <div style={{ width: "100%", marginTop: 8, border: "1px solid var(--border)", borderRadius: 8, padding: "10px 12px", background: "var(--surface)" }}>
          <p className="role-picker-hint" style={{ marginBottom: 6 }}>
            <Pencil size={12} /> Version modifiée — c&apos;est ce texte qui sera publié, programmé, envoyé ou sauvegardé.
          </p>
          <p style={{ whiteSpace: "pre-wrap", fontSize: 13, margin: 0 }}>{editedText}</p>
        </div>
      )}
      {confirmPub && (
        <PublishConfirmModal
          text={postText}
          images={images.map((im) => ({ url: im.url, filename: im.filename }))}
          busy={publishing}
          onClose={() => setConfirmPub(false)}
          onConfirm={(t) => publishLinkedIn(t)}
        />
      )}
      {scheduleOpen && (
        <SchedulePostModal
          text={postText}
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
          postText={postText}
          targetKey={targetKey}
          imageJobs={imageJobs}
          onImageJobCreated={onImageJobCreated}
          onClose={() => setImageModalOpen(false)}
        />
      )}
      {generatingImage && (
        <p className="role-picker-hint" style={{ width: "100%", marginTop: 4, display: "flex", alignItems: "center", gap: 6 }}>
          <Loader2 size={12} className="spinning" /> Image IA en cours de génération… elle rejoindra cette réponse automatiquement.
        </p>
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

// ---------------------------------------------------------------------------
// Inbox in-app de l'agent de qualification Instagram (ALE-195 / 204)
// ---------------------------------------------------------------------------

type IgConversation = {
  id: string;
  prospect_id: string;
  prospect_name: string | null;
  status: string;
  mode: "supervised" | "autopilot";
  last_message_at: string | null;
  window_expires_at: string | null;
};
type IgMessage = {
  id: string;
  role: "in" | "out";
  source: string;
  text: string;
  kind: string;
  created_at: string;
};
type IgDraft = {
  id: string;
  conversation_id: string;
  message_id: string;
  reply: string;
  confidence: number | null;
  needs_human: boolean;
  reason: string | null;
  status: string;
  created_at: string;
};
type IgManychatStatus = {
  connected: boolean;
  api_token_masked?: string | null;
  webhook_url?: string;
  webhook_secret?: string;
  connected_at?: string | null;
};

// ALE-224 : pastille du mode d'une conversation (auto vs supervisé), stylée
// via .mode-badge (globals.css) — remplace les anciens emojis 🤖 / 🙋.
function ConversationModeBadge({ mode }: { mode: IgConversation["mode"] }) {
  const isAuto = mode === "autopilot";
  return (
    <span
      className={`mode-badge ${isAuto ? "auto" : "supervised"}`}
      title={isAuto
        ? "Autopilot — les réponses partent automatiquement"
        : "Supervisé — chaque réponse est validée à la main avant envoi"}
    >
      {isAuto ? "Auto" : "Supervisé"}
    </span>
  );
}

// Corps JSON à coller dans l'action « External Request » ManyChat. Les valeurs
// sont des libellés à remplacer par les champs système ManyChat (Contact ID, etc.).
const MANYCHAT_BODY_TEMPLATE = `{
  "subscriber_id": "{{Contact ID}}",
  "name": "{{Full Name}}",
  "text": "{{Last Text Input}}"
}`;

// ALE-230 : connexion du compte LinkedIn de PROSPECTION via Unipile (envoi de
// demandes de connexion + messages aux leads). Modèle multi-client comme ManyChat :
// chaque client relie SON compte LinkedIn. Porte aussi le plafond quotidien de
// quota (garde-fou anti-restriction). Distinct de la connexion « Publier sur
// LinkedIn » (Zernio) : Zernio publie des posts, Unipile fait la messagerie.
/* ─── Ligne de réglage repliable (onglets Connexions / Automatisations du profil).
   Le profil empilait une carte pleine largeur par connexion : à cinq connexions,
   la page ne tenait plus à l'écran. Une ligne ne dit que l'essentiel (ce que ça
   débloque, l'état, l'action) ; les réglages ne se déplient qu'au clic. ─── */
function SettingRow({
  icon,
  name,
  why,
  right,
  open,
  onToggle,
  children,
}: {
  icon: React.ReactNode;
  name: string;
  why: React.ReactNode;
  right?: React.ReactNode;
  open?: boolean;
  onToggle?: () => void;
  children?: React.ReactNode;
}) {
  const expandable = !!onToggle;
  return (
    <section className="card" style={{ marginBottom: 10, padding: 0, overflow: "hidden" }}>
      <div
        role={expandable ? "button" : undefined}
        tabIndex={expandable ? 0 : undefined}
        aria-expanded={expandable ? !!open : undefined}
        onClick={expandable ? onToggle : undefined}
        onKeyDown={
          expandable
            ? (e) => {
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle!(); }
              }
            : undefined
        }
        style={{
          display: "flex", alignItems: "center", gap: 12, padding: "12px 14px",
          cursor: expandable ? "pointer" : "default",
        }}
      >
        <span style={{ flexShrink: 0, display: "grid", placeItems: "center", width: 24 }}>{icon}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <strong style={{ fontSize: 13.5 }}>{name}</strong>
          <p className="section-desc" style={{ margin: 0, fontSize: 12 }}>{why}</p>
        </div>
        {/* Les contrôles ne doivent pas déplier la ligne au passage. */}
        <div
          style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}
          onClick={(e) => e.stopPropagation()}
        >
          {right}
        </div>
        {expandable && (
          <ChevronRight
            size={16}
            style={{
              flexShrink: 0, color: "var(--muted)",
              transform: open ? "rotate(90deg)" : "none", transition: "transform 0.15s",
            }}
          />
        )}
      </div>
      {expandable && open && (
        <div style={{ padding: 14, borderTop: "1px solid var(--border)" }}>{children}</div>
      )}
    </section>
  );
}

/* État ManyChat remonté au profil : la ligne « Instagram » (Connexions) et la ligne
   « Réponses aux DM » (Automatisations) parlent du même compte — sans ça, chacune
   irait le chercher de son côté et elles pourraient se contredire à l'écran. */
function useManychat(isAuthed: boolean) {
  const [status, setStatus] = useState<IgManychatStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (!isAuthed) { setStatus(null); return; }
    (async () => {
      try {
        const res = await fetch(`${DIRECT_API_URL}/me/ig/manychat`, { headers: await authHeaders() });
        const data = await res.json();
        if (res.ok) setStatus(data);
      } catch { /* non bloquant */ }
    })();
  }, [isAuthed]);

  async function connect(apiKey: string) {
    if (!apiKey.trim()) return false;
    setBusy(true); setNotice("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/ig/manychat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ api_token: apiKey.trim() }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Connexion impossible");
      setStatus(data);
      setNotice("✓ Compte ManyChat relié. Copie l'URL et le secret ci-dessous dans ton flow ManyChat.");
      return true;
    } catch (err: any) {
      setNotice(`Erreur : ${err.message}`);
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    if (!window.confirm("Délier le compte ManyChat ?")) return false;
    setBusy(true); setNotice("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/ig/manychat`, { method: "DELETE", headers: await authHeaders() });
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || "Déconnexion impossible"); }
      setStatus({ connected: false });
      setNotice("Compte ManyChat délié.");
      return true;
    } catch (err: any) {
      setNotice(`Erreur : ${err.message}`);
      return false;
    } finally {
      setBusy(false);
    }
  }

  return { status, busy, notice, setNotice, connect, disconnect };
}

function UnipileOutreachConnect({
  outreach,
  open,
  onToggle,
}: {
  outreach: ReturnType<typeof useLinkedInOutreach>;
  open: boolean;
  onToggle: () => void;
}) {
  const [capDraft, setCapDraft] = useState<number>(25);
  // ALE-174 — fenêtre d'envoi du moteur (heures de bureau du client).
  const [hoursDraft, setHoursDraft] = useState<[number, number]>([9, 18]);
  const [daysDraft, setDaysDraft] = useState<number[]>([1, 2, 3, 4, 5]);

  const st = outreach.status;
  const connected = !!st?.connected;
  const q = st?.quota;
  const eng = st?.engine;

  useEffect(() => { if (q?.daily_cap) setCapDraft(q.daily_cap); }, [q?.daily_cap]);
  useEffect(() => {
    if (eng?.window) {
      setHoursDraft([eng.window.hour_start, eng.window.hour_end]);
      setDaysDraft(eng.window.days);
    }
  }, [eng?.window?.hour_start, eng?.window?.hour_end, eng?.window?.days?.join(",")]);

  const toggleDay = (d: number) =>
    setDaysDraft((prev) => (prev.includes(d) ? prev.filter((x) => x !== d) : [...prev, d].sort()));

  return (
    <>
      {/* ALE-174 — un moteur qui plante en silence est pire qu'un moteur absent : le
          client croirait que sa prospection tourne. Un cron mort ne peut pas alerter
          sur sa propre mort, donc c'est l'app qui le dit, ici, en rouge. Ces deux
          bandeaux restent HORS de la ligne repliable : une alerte qui exige un clic
          pour être lue n'est plus une alerte. */}
      {connected && eng?.stalled && (
        <div className="error" style={{ marginBottom: 12 }}>
          <strong>Ta prospection est à l&apos;arrêt.</strong> {eng.pending} action(s) attendent en file mais le
          moteur d&apos;envoi n&apos;est pas passé depuis {formatAgo(eng.last_run_at)}. Rien ne part.
          {eng.last_run_error ? <> Dernière erreur : {eng.last_run_error}</> : null}
        </div>
      )}
      {connected && eng?.frozen && (
        <div className="card" style={{ marginBottom: 12, padding: 12, borderColor: "var(--warning, #b8860b)" }}>
          <strong>⏸ Envois en pause de sécurité.</strong>{" "}
          {eng.freeze_reason || "LinkedIn a signalé une limite."}{" "}
          {eng.frozen_until ? `Reprise automatique ${formatEta(eng.frozen_until)}.` : ""}
          <p style={{ margin: "6px 0 0", fontSize: 12, color: "var(--muted)" }}>
            La pause n&apos;est pas levable à la main : c&apos;est elle qui protège ton compte d&apos;une restriction.
            Tes actions restent en file et repartiront toutes seules.
          </p>
        </div>
      )}

      <SettingRow
        icon={<Send size={18} style={{ color: "#0a66c2" }} />}
        name="Prospection LinkedIn"
        why={
          !st?.configured
            ? "Messagerie LinkedIn non configurée sur le serveur."
            : connected
              ? `Envoyer invitations et messages à tes leads${q ? ` · ${q.invites_today}/${q.daily_cap} invitations aujourd'hui` : ""}`
              : "Envoyer invitations et messages à tes leads, sans quitter l'app"
        }
        open={open}
        onToggle={connected && q ? onToggle : undefined}
        right={
          connected ? (
            <>
              <span className="status-pill ok"><CheckCircle2 size={14} /> Connecté</span>
              <button className="secondary-button" onClick={outreach.disconnect} disabled={outreach.busy} style={{ fontSize: 12 }}>
                {outreach.busy ? <Loader2 size={12} className="spinning" /> : null} Délier
              </button>
            </>
          ) : st?.configured ? (
            <button className="primary-button" onClick={outreach.connect} disabled={outreach.busy}>
              {outreach.busy ? <Loader2 size={14} className="spinning" /> : <Linkedin size={14} />}
              {outreach.busy ? "Redirection…" : "Connecter"}
            </button>
          ) : (
            <span className="status-pill">Non configuré</span>
          )
        }
      >
        {connected && q && (
          <>
          <p style={{ fontSize: 13, margin: "0 0 10px" }}>
            <strong>Rythme d&apos;envoi</strong> — tes actions ne partent pas au clic : elles entrent dans une
            file, et le moteur les envoie une par une, dans ta plage horaire, avec un délai variable entre
            chacune. C&apos;est ce qui te fait ressembler à quelqu&apos;un qui prospecte, et pas à un robot.
          </p>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10, marginBottom: 12 }}>
            <div className="card" style={{ padding: "10px 12px" }}>
              <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: ".05em", color: "var(--muted)", fontWeight: 700 }}>Invitations aujourd&apos;hui</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{q.invites_today}<span style={{ fontSize: 13, color: "var(--muted)", fontWeight: 500 }}> / {q.daily_cap}</span></div>
              <div style={{ fontSize: 11.5, color: "var(--muted)" }}>{q.invites_week}/{q.weekly_invite_cap} sur 7 jours</div>
            </div>
            <div className="card" style={{ padding: "10px 12px" }}>
              <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: ".05em", color: "var(--muted)", fontWeight: 700 }}>Messages aujourd&apos;hui</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{q.messages_today}<span style={{ fontSize: 13, color: "var(--muted)", fontWeight: 500 }}> / {q.daily_cap}</span></div>
            </div>
            {eng && (
              <div className="card" style={{ padding: "10px 12px" }}>
                <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: ".05em", color: "var(--muted)", fontWeight: 700 }}>En file</div>
                <div style={{ fontSize: 20, fontWeight: 700 }}>{eng.pending}</div>
                <div style={{ fontSize: 11.5, color: "var(--muted)" }}>Moteur passé {formatAgo(eng.last_run_at)}</div>
              </div>
            )}
          </div>

          {eng && eng.warmup_week <= eng.warmup_weeks_total && (
            <p style={{ fontSize: 12.5, margin: "0 0 12px", padding: "8px 10px", background: "var(--surface-2, rgba(0,0,0,.03))", borderRadius: 8 }}>
              🌱 <strong>Mise en route — semaine {eng.warmup_week}/{eng.warmup_weeks_total}</strong> : {eng.warmup_cap} actions
              par jour maximum pour l&apos;instant. Un compte qui se met à envoyer beaucoup du jour au lendemain est
              exactement ce que LinkedIn repère — on monte progressivement, tu n&apos;as rien à faire.
            </p>
          )}

          <label style={{ display: "flex", gap: 10, alignItems: "center", fontSize: 13, fontWeight: 600, flexWrap: "wrap", marginBottom: 10 }}>
            Plafond quotidien
            <input
              type="number" min={1} max={100} value={capDraft}
              onChange={(e) => setCapDraft(Math.max(1, Math.min(100, Number(e.target.value) || 1)))}
              style={{ width: 80, padding: 8, fontSize: 13, fontWeight: 400 }}
            />
            <button className="primary-button" onClick={() => outreach.saveSettings({ daily_cap: capDraft })} disabled={outreach.busy || capDraft === q.daily_cap} style={{ fontSize: 13 }}>
              {outreach.busy ? <Loader2 size={13} className="spinning" /> : <CheckCircle2 size={13} />} Enregistrer
            </button>
          </label>

          <div style={{ display: "grid", gap: 8, borderTop: "1px solid var(--border)", paddingTop: 10 }}>
            <div style={{ fontSize: 13, fontWeight: 600 }}>Quand tes actions peuvent partir</div>
            <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, flexWrap: "wrap" }}>
              Entre
              <input type="number" min={0} max={23} value={hoursDraft[0]}
                onChange={(e) => setHoursDraft(([, end]) => [Math.max(0, Math.min(23, Number(e.target.value) || 0)), end])}
                style={{ width: 64, padding: 8, fontSize: 13 }} />
              h et
              <input type="number" min={1} max={24} value={hoursDraft[1]}
                onChange={(e) => setHoursDraft(([start]) => [start, Math.max(1, Math.min(24, Number(e.target.value) || 1))])}
                style={{ width: 64, padding: 8, fontSize: 13 }} />
              h ({eng?.window.timezone || "Europe/Paris"})
            </label>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
              {WEEKDAY_LABELS.map((label, i) => {
                const day = i + 1;
                const on = daysDraft.includes(day);
                return (
                  <button
                    key={day}
                    className={on ? "primary-button" : "secondary-button"}
                    onClick={() => toggleDay(day)}
                    style={{ width: 36, padding: "6px 0", fontSize: 12, justifyContent: "center" }}
                    title={on ? "Jour d'envoi" : "Aucun envoi ce jour"}
                  >
                    {label}
                  </button>
                );
              })}
              <button
                className="primary-button"
                disabled={outreach.busy || !daysDraft.length}
                onClick={() => outreach.saveSettings({ send_hour_start: hoursDraft[0], send_hour_end: hoursDraft[1], send_days: daysDraft })}
                style={{ fontSize: 13, marginLeft: "auto" }}
              >
                {outreach.busy ? <Loader2 size={13} className="spinning" /> : <CheckCircle2 size={13} />} Enregistrer
              </button>
            </div>
            <p style={{ fontSize: 11.5, color: "var(--muted)", margin: 0 }}>
              Recommandé : heures de bureau, jours ouvrés. Des invitations qui partent à 3 h du matin, un
              dimanche, c&apos;est le signal le plus facile à repérer pour LinkedIn.
            </p>
          </div>
          </>
        )}
      </SettingRow>
      {outreach.error && <div className="error" style={{ marginBottom: 12 }}>{outreach.error}</div>}
    </>
  );
}

// Connexion ManyChat (par client), affichée dans le profil à côté des autres
// connexions (LinkedIn/X/Slack). ManyChat est le pont d'envoi vers les DM
// Instagram : clé API + webhook à coller côté ManyChat. C'est une étape de
// paramétrage ponctuel, d'où sa place dans le profil plutôt que l'Inbox.
function ManychatConnect({
  manychat,
  open,
  onToggle,
}: {
  manychat: ReturnType<typeof useManychat>;
  open: boolean;
  onToggle: () => void;
}) {
  const { status, busy, notice, setNotice } = manychat;
  const [apiKey, setApiKey] = useState("");
  const [copied, setCopied] = useState("");
  // Vrai quand l'utilisateur veut ressaisir une clé alors qu'un compte est déjà
  // relié : on repasse en mode saisie sans perdre le status côté serveur.
  const [editingKey, setEditingKey] = useState(false);

  async function connect() {
    const ok = await manychat.connect(apiKey);
    if (ok) { setApiKey(""); setEditingKey(false); }
  }

  async function disconnect() {
    const ok = await manychat.disconnect();
    if (ok) setEditingKey(false);
  }

  async function copy(value: string, label: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(label);
      setTimeout(() => setCopied(""), 1500);
    } catch { /* clipboard indisponible */ }
  }

  const connected = !!status?.connected && !editingKey;

  return (
    <SettingRow
      icon={<MessageSquare size={18} style={{ color: "#2563eb" }} />}
      name="Instagram (ManyChat)"
      why={
        connected
          ? "Recevoir les DM dans l'Inbox et laisser l'agent y répondre"
          : "Connecte ManyChat pour recevoir tes DM Instagram dans l'Inbox"
      }
      open={open}
      onToggle={onToggle}
      right={
        <>
          <a href="/manychat-test" className="secondary-button" style={{ fontSize: 12, whiteSpace: "nowrap", textDecoration: "none" }} title="Tester l'agent avec un faux DM entrant">
            🧪 Simulateur
          </a>
          {connected ? (
            <>
              <span className="status-pill ok"><CheckCircle2 size={14} /> Connecté</span>
              <button className="secondary-button" onClick={disconnect} disabled={busy} style={{ fontSize: 12 }}>
                {busy ? <Loader2 size={12} className="spinning" /> : null}
                Délier
              </button>
            </>
          ) : (
            <span className="status-pill">Non connecté</span>
          )}
        </>
      }
    >
      {!connected && (
        <>
          <p style={{ fontSize: 13, marginTop: 0, marginBottom: 8 }}>
            <strong>Connecter ton compte ManyChat.</strong> Colle ta clé API ManyChat
            (ManyChat → Settings → API → Generate your token). Elle sert à envoyer les
            réponses de l'agent à tes prospects. Après connexion, tu recevras une URL de
            webhook et un secret à coller dans un flow ManyChat pour recevoir les DM.
          </p>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Clé API ManyChat (0123456789:abcdef…)"
              style={{ flex: 1, padding: 10, borderRadius: 8, border: "1px solid rgba(128,128,128,0.3)", fontSize: 13 }}
            />
            <button className="primary-button" onClick={connect} disabled={busy || !apiKey.trim()} style={{ fontSize: 13, whiteSpace: "nowrap" }}>
              {busy ? "Vérification…" : "Connecter"}
            </button>
            {status?.connected && (
              <button className="secondary-button" onClick={() => { setEditingKey(false); setApiKey(""); setNotice(""); }} disabled={busy} style={{ fontSize: 13, whiteSpace: "nowrap" }}>
                Annuler
              </button>
            )}
          </div>
          {notice && <div style={{ fontSize: 12, marginTop: 10, opacity: 0.85 }}>{notice}</div>}
        </>
      )}

      {connected && (
        <>
          <p style={{ fontSize: 13, marginTop: 0, marginBottom: 6 }}>
            <strong>✓ Compte ManyChat relié</strong>
            {status?.api_token_masked && <span style={{ opacity: 0.7 }}> (clé {status.api_token_masked})</span>}.
          </p>
          <p style={{ fontSize: 12, opacity: 0.8, marginBottom: 10 }}>
            Dans ManyChat (plan <strong>Pro</strong> requis), crée une automatisation
            déclenchée par <strong>Instagram → « Default Reply »</strong> (attrape tous les DM),
            avec une action <strong>« External Request »</strong> configurée avec l'URL, l'en-tête
            et le corps ci-dessous. Pas besoin de mapper la réponse : l'agent répond via l'API.
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div>
              <div style={{ fontSize: 11, textTransform: "uppercase", opacity: 0.6, marginBottom: 3 }}>Méthode & URL (POST)</div>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <code style={{ flex: 1, padding: "8px 10px", borderRadius: 8, background: "rgba(128,128,128,0.12)", fontSize: 12, wordBreak: "break-all" }}>{status?.webhook_url}</code>
                <button className="secondary-button" onClick={() => copy(status?.webhook_url || "", "url")} style={{ fontSize: 12, whiteSpace: "nowrap" }}>
                  {copied === "url" ? "Copié ✓" : "Copier"}
                </button>
              </div>
            </div>
            <div>
              <div style={{ fontSize: 11, textTransform: "uppercase", opacity: 0.6, marginBottom: 3 }}>En-tête <code>X-ManyChat-Secret</code></div>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <code style={{ flex: 1, padding: "8px 10px", borderRadius: 8, background: "rgba(128,128,128,0.12)", fontSize: 12, wordBreak: "break-all" }}>{status?.webhook_secret}</code>
                <button className="secondary-button" onClick={() => copy(status?.webhook_secret || "", "secret")} style={{ fontSize: 12, whiteSpace: "nowrap" }}>
                  {copied === "secret" ? "Copié ✓" : "Copier"}
                </button>
              </div>
            </div>
            <div>
              <div style={{ fontSize: 11, textTransform: "uppercase", opacity: 0.6, marginBottom: 3 }}>Corps (JSON, Content-Type application/json)</div>
              <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                <pre style={{ flex: 1, margin: 0, padding: "8px 10px", borderRadius: 8, background: "rgba(128,128,128,0.12)", fontSize: 12, whiteSpace: "pre-wrap", fontFamily: "inherit" }}>{MANYCHAT_BODY_TEMPLATE}</pre>
                <button className="secondary-button" onClick={() => copy(MANYCHAT_BODY_TEMPLATE, "body")} style={{ fontSize: 12, whiteSpace: "nowrap" }}>
                  {copied === "body" ? "Copié ✓" : "Copier"}
                </button>
              </div>
              <p style={{ fontSize: 11, opacity: 0.65, margin: "4px 0 0" }}>
                Remplace les valeurs par les champs système ManyChat correspondants
                (Contact ID, Full Name, Last Text Input) via le sélecteur de champs.
              </p>
            </div>
            <div>
              <button className="secondary-button" onClick={() => { setEditingKey(true); setNotice(""); }} disabled={busy} style={{ fontSize: 12 }}>
                Changer la clé API
              </button>
            </div>
          </div>
          {notice && <div style={{ fontSize: 12, marginTop: 10, opacity: 0.85 }}>{notice}</div>}
        </>
      )}
    </SettingRow>
  );
}

// Cerveau de l'agent DM (FAQ + objectif) : la seule source de vérité utilisée
// par l'agent Instagram. Édité ponctuellement → placé dans le profil, à côté de
// la config ManyChat, plutôt que dans le header de l'Inbox.
function AgentFaqEditor({ isAuthed, active }: { isAuthed: boolean; active: boolean }) {
  const [text, setText] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");

  // Chargée seulement quand la ligne est dépliée : inutile d'aller chercher la
  // FAQ de tous ceux qui ouvrent leur profil sans toucher à l'agent.
  useEffect(() => {
    if (!isAuthed || loaded || !active) return;
    (async () => {
      try {
        const res = await fetch(`${DIRECT_API_URL}/me/ig/faq`, { headers: await authHeaders() });
        const data = await res.json();
        if (res.ok) { setText(data.content || ""); setLoaded(true); }
      } catch { /* non bloquant */ }
    })();
  }, [isAuthed, active, loaded]);

  async function save() {
    setSaving(true); setNotice("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/ig/faq`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ content: text }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Enregistrement impossible");
      setNotice("✓ FAQ enregistrée — l'agent l'utilise dès le prochain message.");
    } catch (err: any) {
      setNotice(`Erreur : ${err.message}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <p style={{ fontSize: 12, opacity: 0.8, marginTop: 0, marginBottom: 8 }}>
        C&apos;est la seule source de vérité de l&apos;agent : il ne répond seul que si la réponse est couverte
        ici, sinon il te passe la main. Décris ton offre, tes prix, tes questions/réponses fréquentes et
        l&apos;objectif de la conversation (ex. proposer un appel découverte).
      </p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={loaded ? "Ex. : Qui es-tu ? / Quels sont tes tarifs ? / Objectif : qualifier puis proposer un appel…" : "Chargement…"}
        rows={10}
        style={{ width: "100%", resize: "vertical", padding: 10, borderRadius: 8, border: "1px solid rgba(128,128,128,0.3)", fontSize: 13, fontFamily: "inherit" }}
      />
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 8 }}>
        <button className="primary-button" onClick={save} disabled={saving || !loaded} style={{ fontSize: 13 }}>
          {saving ? "Enregistrement…" : "Enregistrer la FAQ"}
        </button>
        {notice && <span style={{ fontSize: 12, opacity: 0.8 }}>{notice}</span>}
      </div>
    </div>
  );
}

function IgInbox({ isAuthed, requireAuth, userId, hideChrome = false, externalActiveId = null }: { isAuthed: boolean; requireAuth: (reason?: string) => void; userId: string | null; hideChrome?: boolean; externalActiveId?: string | null }) {
  const [conversations, setConversations] = useState<IgConversation[]>([]);
  // Faux tant que le premier /me/ig/conversations n'a pas répondu : évite d'afficher
  // « Aucune conversation » pendant le chargement initial (backend dev lent).
  const [convLoaded, setConvLoaded] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<IgMessage[]>([]);
  const [drafts, setDrafts] = useState<IgDraft[]>([]);
  const [replyText, setReplyText] = useState("");
  const [draftText, setDraftText] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [killSwitch, setKillSwitch] = useState(false);
  // La FAQ/objectif de l'agent et la connexion ManyChat ont été déplacées dans
  // le profil (composants AgentFaqEditor + ManychatConnect) — l'Inbox reste
  // focalisée sur les conversations.
  const endRef = useRef<HTMLDivElement | null>(null);
  // Conversation réellement affichée : sert à ignorer les réponses de chargement
  // de fil arrivées hors-séquence (l'utilisateur a changé de conversation entre
  // la requête et sa réponse — fréquent sur le backend dev lent).
  const selectedConvRef = useRef<string | null>(null);

  const active = conversations.find((c) => c.id === activeId) || null;
  // La suggestion à traiter = le draft pending le plus récent (créé après le dernier DM prospect).
  const pendingDraft = drafts.find((d) => d.status === "pending") || null;
  // Échec de génération : le dernier message du prospect n'a produit aucune
  // suggestion (aucun draft ne le référence) alors qu'elle aurait dû aboutir.
  // Cause typique en dev : thread de fond tué (Render free) ou hoquet LLM —
  // l'erreur est avalée côté serveur, on la rend au moins visible ici. Délai de
  // grâce (25 s) pour ne pas alerter pendant la génération encore en cours.
  const lastInbound = [...messages].reverse().find((m) => m.role === "in") || null;
  const lastInboundHasDraft = lastInbound ? drafts.some((d) => d.message_id === lastInbound.id) : true;
  const lastInboundAgeMs = lastInbound?.created_at ? Date.now() - new Date(lastInbound.created_at).getTime() : 0;
  const suggestionFailed = !!lastInbound && !lastInboundHasDraft && !pendingDraft && lastInboundAgeMs > 25000;

  // Pastille « nouveau message » par conversation : une conversation est non lue
  // tant que son dernier message est plus récent que la dernière fois qu'on l'a
  // ouverte. Le repère est stocké par conversation dans localStorage, keyé par
  // utilisateur (pas de fuite cross-user). Indépendant de la pastille globale de
  // l'onglet Inbox : ici on veut voir QUELLE conversation a le nouveau message,
  // même en restant sur l'écran Inbox.
  const readKey = userId ? `ig_conv_read:${userId}` : null;
  const [readMap, setReadMap] = useState<Record<string, number>>({});
  const seededRef = useRef(false);
  const convTs = (c: IgConversation) => (c.last_message_at ? new Date(c.last_message_at).getTime() : 0);
  const markRead = (id: string, ts: number) => {
    setReadMap((prev) => {
      if ((prev[id] || 0) >= ts) return prev;
      const next = { ...prev, [id]: ts };
      if (readKey) { try { localStorage.setItem(readKey, JSON.stringify(next)); } catch { /* ignore */ } }
      return next;
    });
  };
  const isUnread = (c: IgConversation) => c.id !== activeId && convTs(c) > (readMap[c.id] || 0);

  // Charge les repères de lecture au montage / changement d'utilisateur.
  useEffect(() => {
    seededRef.current = false;
    if (!readKey) { setReadMap({}); return; }
    try {
      const raw = localStorage.getItem(readKey);
      if (raw !== null) { setReadMap(JSON.parse(raw) || {}); seededRef.current = true; }
      else setReadMap({});
    } catch { setReadMap({}); }
  }, [readKey]);

  // Premier chargement pour cet utilisateur : on considère les conversations déjà
  // présentes comme lues (sinon toutes seraient pastillées d'un coup). Seuls les
  // messages arrivant après ce repère, ou les nouvelles conversations, alertent.
  useEffect(() => {
    if (!readKey || seededRef.current || !convLoaded) return;
    const seed: Record<string, number> = {};
    conversations.forEach((c) => { seed[c.id] = convTs(c); });
    seededRef.current = true;
    try { localStorage.setItem(readKey, JSON.stringify(seed)); } catch { /* ignore */ }
    setReadMap(seed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readKey, convLoaded, conversations]);

  // La conversation ouverte est toujours considérée lue, même si de nouveaux
  // messages y arrivent pendant qu'elle est affichée (le fil se rafraîchit).
  useEffect(() => {
    if (!activeId) return;
    const c = conversations.find((x) => x.id === activeId);
    if (c) markRead(activeId, convTs(c));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId, conversations]);

  async function loadConversations() {
    if (!isAuthed) return;
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/ig/conversations`, { headers: await authHeaders() });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Chargement des conversations impossible");
      setConversations(Array.isArray(data) ? data : []);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setConvLoaded(true);
    }
  }

  async function loadKillSwitch() {
    if (!isAuthed) return;
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/ig/autopilot/kill-switch`, { headers: await authHeaders() });
      const data = await res.json();
      if (res.ok) setKillSwitch(!!data.active);
    } catch { /* non bloquant */ }
  }

  // toggleKillSwitch retiré : le bouton « Désactiver l'autopilot partout » est
  // grisé tant que la feature n'est pas disponible (l'endpoint reste en place).

  async function loadThread(conversationId: string) {
    setLoading(true);
    setError("");
    try {
      const [mRes, dRes] = await Promise.all([
        fetch(`${DIRECT_API_URL}/me/ig/conversations/${conversationId}/messages`, { headers: await authHeaders() }),
        fetch(`${DIRECT_API_URL}/me/ig/conversations/${conversationId}/drafts`, { headers: await authHeaders() }),
      ]);
      const mData = await mRes.json();
      const dData = await dRes.json();
      // L'utilisateur a changé de conversation entre-temps : cette réponse est
      // périmée, ne pas écraser le fil affiché avec le mauvais contenu.
      if (selectedConvRef.current !== conversationId) return;
      if (!mRes.ok) throw new Error(mData.detail || "Messages introuvables");
      setMessages(Array.isArray(mData) ? mData : []);
      setDrafts(Array.isArray(dData) ? dData : []);
    } catch (err: any) {
      if (selectedConvRef.current === conversationId) setError(err.message);
    } finally {
      if (selectedConvRef.current === conversationId) setLoading(false);
    }
  }

  function selectConversation(id: string) {
    selectedConvRef.current = id;
    setActiveId(id);
    setReplyText("");
    setDraftText("");
    // Vider immédiatement le fil précédent → on affiche « Chargement… » au lieu
    // de laisser le fil de la conversation d'avant tant que le fetch n'a pas fini.
    setMessages([]);
    setDrafts([]);
    loadThread(id);
  }

  // Inbox unifiée (ALE-244) : quand le parent pilote la sélection (mode headless),
  // on ouvre la conversation demandée.
  useEffect(() => {
    if (externalActiveId && externalActiveId !== activeId) selectConversation(externalActiveId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalActiveId]);

  useEffect(() => {
    if (!isAuthed) {
      selectedConvRef.current = null;
      setConversations([]); setConvLoaded(false); setActiveId(null); setMessages([]); setDrafts([]);
      return;
    }
    loadConversations();
    loadKillSwitch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed]);

  // La liste des conversations se rafraîchit en continu tant qu'on est connecté,
  // même quand l'Inbox est vide : une nouvelle conversation créée côté serveur
  // (DM entrant via le webhook ManyChat, ou Simulateur) doit apparaître sans
  // recharger la page. Ce composant n'est monté que sur l'écran Inbox.
  // Polling NON-CHEVAUCHANT (setTimeout récursif) : on ne relance qu'après la
  // fin de la requête précédente. Sur backend lent (dev free), un setInterval
  // fixe empilait les requêtes plus vite qu'elles n'étaient servies → file qui
  // gonfle, ~6 connexions/hôte du navigateur saturées, et les écritures de
  // l'utilisateur (FAQ / envoi) starvées → « Failed to fetch ».
  useEffect(() => {
    if (!isAuthed) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const loop = async () => {
      await loadConversations();
      if (!stop) timer = setTimeout(loop, 6000);
    };
    timer = setTimeout(loop, 6000);
    return () => { stop = true; clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed]);

  // Le webhook persiste messages/drafts de façon asynchrone → on rafraîchit le
  // fil ouvert pour voir arriver les nouveaux DM et suggestions (non-chevauchant).
  useEffect(() => {
    if (!activeId) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const loop = async () => {
      await loadThread(activeId);
      if (!stop) timer = setTimeout(loop, 6000);
    };
    timer = setTimeout(loop, 6000);
    return () => { stop = true; clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId]);

  useEffect(() => {
    if (pendingDraft) setDraftText(pendingDraft.reply || "");
  }, [pendingDraft?.id]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages.length, pendingDraft?.id]);

  async function sendDraft() {
    if (!pendingDraft || !draftText.trim()) return;
    setBusy(true); setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/ig/drafts/${pendingDraft.id}/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ text: draftText }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Envoi impossible");
      setDraftText("");
      if (activeId) await loadThread(activeId);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function rejectDraft() {
    if (!pendingDraft) return;
    setBusy(true); setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/ig/drafts/${pendingDraft.id}/reject`, {
        method: "POST", headers: await authHeaders(),
      });
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || "Refus impossible"); }
      if (activeId) await loadThread(activeId);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function sendManual() {
    if (!active || !replyText.trim()) return;
    setBusy(true); setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/ig/conversations/${active.id}/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ text: replyText }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Envoi impossible");
      setReplyText("");
      if (activeId) await loadThread(activeId);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function toggleMode() {
    if (!active) return;
    const next = active.mode === "autopilot" ? "supervised" : "autopilot";
    setBusy(true); setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/ig/conversations/${active.id}/mode`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ mode: next }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Bascule impossible");
      await loadConversations();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!isAuthed) {
    return (
      <div className="card" style={{ textAlign: "center", padding: 40 }}>
        <p>Connecte-toi pour accéder à l'inbox de qualification Instagram.</p>
        <button className="primary-button" onClick={() => requireAuth("Crée un compte pour accéder à l'inbox Instagram.")}>Se connecter</button>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: hideChrome ? "100%" : "calc(100vh - var(--header-h) - var(--dev-banner-h) - 40px)", minHeight: hideChrome ? 0 : 420 }}>
    {!hideChrome && (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 12, padding: "10px 14px", borderRadius: 10, background: killSwitch ? "rgba(224,108,0,0.12)" : "rgba(128,128,128,0.08)", flex: "none" }}>
      <span style={{ fontSize: 13 }}>
        {killSwitch
          ? "🛑 Kill-switch actif — tout est en supervisé, aucun envoi automatique."
          : "🙋 Mode supervisé — l'autopilot est temporairement désactivé, chaque réponse est validée à la main avant envoi."}
      </span>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flex: "none" }}>
        {/* Désactive l'autopilot (envoi automatique) sur TOUTES les conversations
            d'un coup. Feature pas encore disponible → bouton grisé. */}
        <button
          className="secondary-button"
          disabled
          title="Bientôt disponible"
          style={{ fontSize: 12, whiteSpace: "nowrap", opacity: 0.5, cursor: "not-allowed" }}
        >
          🛑 Désactiver l'autopilot partout — bientôt
        </button>
      </div>
    </div>
    )}
    <div className="ig-inbox" style={{ display: "grid", gridTemplateColumns: hideChrome ? "1fr" : "280px 1fr", gap: 16, flex: 1, minHeight: 0 }}>
      {!hideChrome && (
      <aside className="card" style={{ padding: 8, overflowY: "auto", minHeight: 0 }}>
        <p className="eyebrow" style={{ padding: "6px 8px" }}>Conversations</p>
        {!convLoaded && conversations.length === 0 && <ConvListSkeleton rows={6} />}
        {convLoaded && conversations.length === 0 && (
          <p style={{ padding: 8, fontSize: 13, opacity: 0.7 }}>
            Aucune conversation pour l&apos;instant. Elles apparaîtront dès qu&apos;un prospect écrit en DM.
          </p>
        )}
        {conversations.map((c) => (
          <button
            key={c.id}
            onClick={() => selectConversation(c.id)}
            className={`ig-conv-item ${activeId === c.id ? "active" : ""}`}
            style={{
              display: "block", width: "100%", textAlign: "left", padding: "8px 10px", marginBottom: 4,
              borderRadius: 8, border: "1px solid transparent", cursor: "pointer",
              background: activeId === c.id ? "rgba(120,120,255,0.12)" : "transparent",
            }}
          >
            <span style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
              <span style={{ fontWeight: isUnread(c) ? 700 : 600, fontSize: 14, display: "inline-flex", alignItems: "center", gap: 6, minWidth: 0 }}>
                {isUnread(c) && (
                  <span
                    aria-label="Nouveau message"
                    title="Nouveau message"
                    style={{ width: 8, height: 8, borderRadius: "50%", background: "#e5484d", flex: "0 0 auto" }}
                  />
                )}
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.prospect_name || c.prospect_id}</span>
              </span>
              <ConversationModeBadge mode={c.mode} />
            </span>
          </button>
        ))}
      </aside>
      )}

      <section className="card" style={{ display: "flex", flexDirection: "column", padding: 0, minHeight: 0 }}>
        {!active ? (
          <div style={{ margin: "auto", opacity: 0.7 }}>Sélectionne une conversation.</div>
        ) : (
          <>
            <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 16px", borderBottom: "1px solid rgba(128,128,128,0.2)" }}>
              <div>
                <strong>{active.prospect_name || active.prospect_id}</strong>
                <span style={{ marginLeft: 10, fontSize: 12, opacity: 0.7 }}>
                  {active.window_expires_at && new Date(active.window_expires_at) < new Date()
                    ? "⏰ fenêtre 24 h expirée"
                    : "fenêtre 24 h ouverte"}
                </span>
              </div>
              {/* Autopilot temporairement grisé : chaque réponse reste validée à la main. */}
              <button
                className="secondary-button"
                onClick={toggleMode}
                disabled
                title="L'autopilot sera bientôt disponible"
                style={{ fontSize: 12, opacity: 0.5, cursor: "not-allowed" }}
              >
                🤖 Autopilot — bientôt
              </button>
            </header>

            <div style={{ flex: 1, overflowY: "auto", padding: 16, display: "flex", flexDirection: "column", gap: 8 }}>
              {loading && messages.length === 0 && <MsgThreadSkeleton />}
              {messages.map((m) => (
                <div key={m.id} style={{ alignSelf: m.role === "in" ? "flex-start" : "flex-end", maxWidth: "78%" }}>
                  <div style={{
                    padding: "8px 12px", borderRadius: 12, whiteSpace: "pre-wrap", fontSize: 14,
                    background: m.role === "in" ? "rgba(128,128,128,0.14)" : "rgba(90,120,255,0.18)",
                  }}>
                    {m.kind === "voice" && <span title="note vocale transcrite" style={{ marginRight: 6 }}>🎤</span>}
                    {m.text}
                  </div>
                  <div style={{ fontSize: 10, opacity: 0.5, textAlign: m.role === "in" ? "left" : "right", marginTop: 2 }}>
                    {m.source}{m.created_at ? ` · ${new Date(m.created_at).toLocaleString("fr-FR")}` : ""}
                  </div>
                </div>
              ))}

              {pendingDraft && (
                <div style={{ alignSelf: "flex-end", width: "78%", maxWidth: "78%" }}>
                  <div style={{
                    padding: "10px 12px", borderRadius: 12,
                    border: "1.5px dashed rgba(90,120,255,0.55)", background: "rgba(90,120,255,0.07)",
                  }}>
                    <div style={{ fontSize: 12, marginBottom: 6 }}>
                      {pendingDraft.needs_human
                        ? <span style={{ color: "#e06c00", fontWeight: 600 }}>⚠️ L'agent ne sait pas — à traiter à la main</span>
                        : <span style={{ color: "#1a8a3a", fontWeight: 600 }}>✨ Réponse proposée par l'agent</span>}
                      {typeof pendingDraft.confidence === "number" && (
                        <span style={{ opacity: 0.7, marginLeft: 8 }}>confiance {Math.round(pendingDraft.confidence * 100)}%</span>
                      )}
                    </div>
                    {pendingDraft.reason && <div style={{ fontSize: 11, opacity: 0.65, marginBottom: 6 }}>{pendingDraft.reason}</div>}
                    <textarea
                      value={draftText}
                      onChange={(e) => setDraftText(e.target.value)}
                      rows={Math.min(8, Math.max(2, draftText.split("\n").length))}
                      style={{ width: "100%", resize: "vertical", padding: 8, borderRadius: 8, border: "1px solid rgba(128,128,128,0.3)", fontSize: 14, fontFamily: "inherit", background: "transparent" }}
                    />
                    <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 8 }}>
                      <button className="secondary-button" onClick={rejectDraft} disabled={busy} style={{ fontSize: 12 }}>
                        ✕ Refuser
                      </button>
                      <button className="primary-button" onClick={sendDraft} disabled={busy || !draftText.trim()} style={{ fontSize: 13 }}>
                        {busy ? "…" : "✓ Accepter & envoyer"}
                      </button>
                    </div>
                  </div>
                  <div style={{ fontSize: 10, opacity: 0.5, textAlign: "right", marginTop: 2 }}>
                    suggestion — modifiable avant envoi
                  </div>
                </div>
              )}

              {suggestionFailed && (
                <div style={{ alignSelf: "flex-end", width: "78%", maxWidth: "78%" }}>
                  <div style={{
                    padding: "10px 12px", borderRadius: 12,
                    border: "1.5px dashed rgba(224,108,0,0.55)", background: "rgba(224,108,0,0.07)",
                  }}>
                    <div style={{ fontSize: 12, color: "#e06c00", fontWeight: 600, marginBottom: 4 }}>
                      ⚠️ Aucune suggestion n'a pu être générée pour ce message
                    </div>
                    <div style={{ fontSize: 11, opacity: 0.7 }}>
                      La génération a échoué (erreur temporaire). Réponds à la main,
                      ou attends le prochain message du prospect pour relancer l'agent.
                    </div>
                  </div>
                </div>
              )}
              <div ref={endRef} />
            </div>

            <div style={{ padding: 12, borderTop: "1px solid rgba(128,128,128,0.2)", display: "flex", gap: 8, alignItems: "flex-end", flex: "none" }}>
              <textarea
                value={replyText}
                onChange={(e) => setReplyText(e.target.value)}
                placeholder="Écris une réponse…"
                rows={2}
                style={{ flex: 1, resize: "vertical", padding: 8, borderRadius: 8, border: "1px solid rgba(128,128,128,0.3)", fontSize: 14 }}
              />
              <button className="primary-button" onClick={sendManual} disabled={busy || !replyText.trim()} style={{ fontSize: 13 }}>
                {busy ? "…" : "Envoyer"}
              </button>
            </div>
            {error && <div style={{ padding: "0 16px 12px", color: "#d33", fontSize: 13 }}>{error}</div>}
          </>
        )}
      </section>
    </div>
    </div>
  );
}

// ALE-244 : fil LinkedIn (messages Unipile lus en direct) pour l'Inbox unifiée.
function LinkedInThread({ chat, quota, onQuota }: { chat: OutreachChat; quota?: OutreachQuota; onQuota: (q: OutreachQuota) => void }) {
  const [messages, setMessages] = useState<OutreachMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef<HTMLDivElement | null>(null);
  const chatId = chat.id;

  async function loadMessages() {
    setLoading(true); setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/linkedin/outreach/chats/${encodeURIComponent(chatId)}/messages`, { headers: await authHeaders() });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Messages introuvables");
      setMessages(Array.isArray(data.messages) ? data.messages : []);
    } catch (err: any) { setError(err.message); }
    finally { setLoading(false); }
  }

  // Monté par conversation (key=chatId) → chargement + rafraîchissement 15 s.
  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const loop = async () => { await loadMessages(); if (!stop) timer = setTimeout(loop, 15000); };
    loop();
    return () => { stop = true; clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages.length]);

  async function sendReply() {
    if (!reply.trim()) return;
    setBusy(true); setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/linkedin/outreach/chats/${encodeURIComponent(chatId)}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ text: reply.trim() }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Envoi impossible");
      if (data.quota) onQuota(data.quota);
      setReply("");
      await loadMessages();
    } catch (err: any) { setError(err.message); }
    finally { setBusy(false); }
  }

  return (
    <section className="card" style={{ display: "flex", flexDirection: "column", minHeight: 0, padding: 0, height: "100%" }}>
      <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)", fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
        <Linkedin size={15} style={{ color: "#0a66c2", flexShrink: 0 }} />
        {chat.name || "Conversation LinkedIn"}
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: 16, display: "flex", flexDirection: "column", gap: 8 }}>
        {loading && messages.length === 0 ? (
          <MsgThreadSkeleton />
        ) : messages.length === 0 ? (
          <div style={{ margin: "auto", opacity: 0.6, fontSize: 13 }}>Aucun message.</div>
        ) : null}
        {messages.map((m) => (
          <div
            key={m.id}
            style={{ alignSelf: m.from_me ? "flex-end" : "flex-start", maxWidth: "78%", padding: "8px 12px", borderRadius: 12, background: m.from_me ? "rgba(10,102,194,0.14)" : "var(--surface-high)", fontSize: 13.5, whiteSpace: "pre-wrap" }}
          >
            {m.text}
          </div>
        ))}
        <div ref={endRef} />
      </div>
      {error && <div className="error" style={{ margin: "0 12px 8px" }}>{error}</div>}
      <div style={{ padding: 12, borderTop: "1px solid var(--border)", display: "flex", gap: 8, alignItems: "flex-end" }}>
        <textarea
          value={reply}
          onChange={(e) => setReply(e.target.value)}
          rows={2}
          placeholder="Écris ta réponse… (Cmd/Ctrl+Entrée pour envoyer)"
          style={{ flex: 1, resize: "none", padding: 8, fontSize: 13 }}
          onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") sendReply(); }}
        />
        <button
          className="primary-button"
          disabled={busy || !reply.trim() || !quota?.can_message}
          title={!quota?.can_message ? (quota?.message_blocked_reason || "") : "Envoyer"}
          onClick={sendReply}
        >
          {busy ? <Loader2 size={14} className="spinning" /> : <Send size={14} />}
        </button>
      </div>
      {!quota?.can_message && quota?.message_blocked_reason && (
        <p style={{ margin: "0 12px 10px", fontSize: 11.5, color: "var(--warning, #b8860b)" }}>{quota.message_blocked_reason}</p>
      )}
    </section>
  );
}

// ALE-244 : Inbox UNIQUE regroupant Instagram (DM ManyChat) + LinkedIn (messagerie
// Unipile). Une seule liste de conversations, chaque ligne taguée par réseau ; à
// l'ouverture le fil et l'envoi s'adaptent au réseau. L'inbox Instagram garde
// toute sa logique d'agent (réutilisée via IgInbox en mode headless `hideChrome`).
type InboxNetwork = "instagram" | "linkedin";

// ALE-248 : réconcilie une liste de conversations fraîchement pollée avec l'état
// courant plutôt que de tout remplacer. Conserve la RÉFÉRENCE des objets
// inchangés (pas de re-render / clignotement inutile), n'ajoute/retire que les
// nouveautés. Comparaison par sérialisation (listes courtes = OK). Renvoie
// `prev` tel quel si rien n'a bougé → référence stable en amont.
function reconcileById<T>(prev: T[], next: T[], keyOf: (x: T) => string): T[] {
  const prevByKey = new Map(prev.map((x) => [keyOf(x), x] as const));
  const merged = next.map((n) => {
    const p = prevByKey.get(keyOf(n));
    return p && JSON.stringify(p) === JSON.stringify(n) ? p : n;
  });
  if (merged.length === prev.length && merged.every((m, i) => m === prev[i])) return prev;
  return merged;
}

function UnifiedInbox({ isAuthed, requireAuth, userId, initialSelect }: { isAuthed: boolean; requireAuth: (reason?: string) => void; userId: string | null; initialSelect?: { network: InboxNetwork; id: string; nonce: number } | null }) {
  const outreach = useLinkedInOutreach(isAuthed);
  const lnConnected = !!outreach.status?.connected;
  const [igConvs, setIgConvs] = useState<IgConversation[]>([]);
  const [lnChats, setLnChats] = useState<OutreachChat[]>([]);
  const [igLoaded, setIgLoaded] = useState(false);
  const [lnLoaded, setLnLoaded] = useState(false);
  const [forceReveal, setForceReveal] = useState(false);
  const [sel, setSel] = useState<{ network: InboxNetwork; id: string } | null>(null);

  // ALE-265 : ne révéler la liste qu'une fois Instagram ET LinkedIn prêts (fini
  // le remplissage en escalier). Gardé sur le statut outreach résolu pour ne pas
  // flicker quand on découvre le compte connecté ; filet de sécurité à 8 s si un
  // fetch reste muet (erreur silencieuse) pour ne jamais bloquer le skeleton.
  const statusReady = outreach.status !== null;
  const loaded = forceReveal || (igLoaded && statusReady && (!lnConnected || lnLoaded));
  useEffect(() => {
    if (!isAuthed) return;
    const t = setTimeout(() => setForceReveal(true), 8000);
    return () => clearTimeout(t);
  }, [isAuthed]);

  async function loadIg() {
    if (!isAuthed) return;
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/ig/conversations`, { headers: await authHeaders() });
      const data = await res.json();
      if (res.ok) setIgConvs((prev) => reconcileById(prev, Array.isArray(data) ? data : [], (c) => c.id));
    } catch { /* non bloquant */ } finally { setIgLoaded(true); }
  }
  async function loadLn() {
    if (!isAuthed || !lnConnected) { setLnChats([]); setLnLoaded(true); return; }
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/linkedin/outreach/chats`, { headers: await authHeaders() });
      const data = await res.json();
      if (res.ok) setLnChats((prev) => reconcileById(prev, Array.isArray(data.chats) ? data.chats : [], (c) => c.id));
    } catch { /* non bloquant */ } finally { setLnLoaded(true); }
  }

  // Poll IG (6 s, non-chevauchant) — nouvelles conversations sans recharger.
  useEffect(() => {
    if (!isAuthed) { setIgConvs([]); setLnChats([]); setSel(null); return; }
    let stop = false; let t: ReturnType<typeof setTimeout>;
    const loop = async () => { await loadIg(); if (!stop) t = setTimeout(loop, 6000); };
    loop();
    return () => { stop = true; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed]);

  // Poll LinkedIn (30 s) uniquement si le compte est connecté.
  useEffect(() => {
    if (!isAuthed || !lnConnected) return;
    let stop = false; let t: ReturnType<typeof setTimeout>;
    const loop = async () => { await loadLn(); if (!stop) t = setTimeout(loop, 30000); };
    loop();
    return () => { stop = true; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed, lnConnected]);

  // ALE-245 : pré-sélection d'une conversation depuis un autre écran (bouton
  // « Inbox » sur une ligne de lead). Le nonce garantit qu'un même chat
  // re-sélectionne même après avoir fermé le fil.
  useEffect(() => {
    if (initialSelect) setSel({ network: initialSelect.network, id: initialSelect.id });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSelect?.nonce]);

  const ts = (v?: string | null) => (v ? new Date(v).getTime() : 0);
  type Row = { network: InboxNetwork; id: string; name: string; time: number; mode?: IgConversation["mode"] };
  const rows: Row[] = [
    ...igConvs.map((c) => ({ network: "instagram" as const, id: c.id, name: c.prospect_name || c.prospect_id, time: ts(c.last_message_at), mode: c.mode })),
    ...lnChats.map((c) => ({ network: "linkedin" as const, id: c.id, name: c.name || "Conversation LinkedIn", time: ts(c.last_message_at) })),
    // ALE-248 : tri stable — départage les temps égaux (ex. chats LinkedIn sans
    // last_message_at, tous à 0) par clé réseau:id pour éviter que les lignes
    // sautent à chaque poll.
  ].sort((a, b) => b.time - a.time || `${a.network}:${a.id}`.localeCompare(`${b.network}:${b.id}`));

  // Pastille « non lu » unifiée (localStorage par utilisateur, clé network:id).
  const readKey = userId ? `inbox_conv_read:${userId}` : null;
  const [readMap, setReadMap] = useState<Record<string, number>>({});
  const seededRef = useRef(false);
  const rowKey = (r: { network: InboxNetwork; id: string }) => `${r.network}:${r.id}`;
  useEffect(() => {
    seededRef.current = false;
    if (!readKey) { setReadMap({}); return; }
    try { const raw = localStorage.getItem(readKey); if (raw !== null) { setReadMap(JSON.parse(raw) || {}); seededRef.current = true; } else setReadMap({}); }
    catch { setReadMap({}); }
  }, [readKey]);
  useEffect(() => {
    if (!readKey || seededRef.current || !loaded) return;
    const seed: Record<string, number> = {};
    rows.forEach((r) => { seed[rowKey(r)] = r.time; });
    seededRef.current = true;
    try { localStorage.setItem(readKey, JSON.stringify(seed)); } catch { /* ignore */ }
    setReadMap(seed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readKey, loaded, igConvs, lnChats]);
  const markRead = (r: { network: InboxNetwork; id: string }, time: number) => {
    setReadMap((prev) => {
      const k = rowKey(r);
      if ((prev[k] || 0) >= time) return prev;
      const next = { ...prev, [k]: time };
      if (readKey) { try { localStorage.setItem(readKey, JSON.stringify(next)); } catch { /* ignore */ } }
      return next;
    });
  };
  const selKey = sel ? `${sel.network}:${sel.id}` : "";
  const isUnread = (r: Row) => rowKey(r) !== selKey && r.time > (readMap[rowKey(r)] || 0);

  function selectRow(r: Row) { setSel({ network: r.network, id: r.id }); markRead(r, r.time); }

  const selectedIg = sel?.network === "instagram" ? igConvs.find((c) => c.id === sel.id) || null : null;
  const selectedLn = sel?.network === "linkedin" ? lnChats.find((c) => c.id === sel.id) || null : null;

  if (!isAuthed) {
    return (
      <div className="card" style={{ textAlign: "center", padding: 40 }}>
        <p>Connecte-toi pour accéder à ton inbox.</p>
        <button className="primary-button" onClick={() => requireAuth("Crée un compte pour accéder à l'inbox.")}>Se connecter</button>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - var(--header-h) - var(--dev-banner-h) - 40px)", minHeight: 420 }}>
      <div className="ig-inbox" style={{ display: "grid", gridTemplateColumns: "300px 1fr", gap: 16, flex: 1, minHeight: 0 }}>
        <aside className="card" style={{ padding: 8, overflowY: "auto", minHeight: 0 }}>
          <p className="eyebrow" style={{ padding: "6px 8px" }}>Conversations</p>
          {!loaded && <ConvListSkeleton rows={6} />}
          {loaded && rows.length === 0 && (
            <p style={{ padding: 8, fontSize: 13, opacity: 0.7 }}>
              Aucune conversation pour l&apos;instant. Elles apparaîtront dès qu&apos;un prospect écrit en DM (Instagram) ou après ton premier message à un lead (LinkedIn).
            </p>
          )}
          {loaded && rows.map((r) => (
            <button
              key={rowKey(r)}
              onClick={() => selectRow(r)}
              className="ig-conv-item"
              style={{ display: "block", width: "100%", textAlign: "left", padding: "8px 10px", marginBottom: 4, borderRadius: 8, border: "1px solid transparent", cursor: "pointer", background: rowKey(r) === selKey ? "rgba(120,120,255,0.12)" : "transparent" }}
            >
              <span style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                <span style={{ fontWeight: isUnread(r) ? 700 : 600, fontSize: 14, display: "inline-flex", alignItems: "center", gap: 6, minWidth: 0 }}>
                  {isUnread(r) && (
                    <span aria-label="Nouveau message" title="Nouveau message" style={{ width: 8, height: 8, borderRadius: "50%", background: "#e5484d", flex: "0 0 auto" }} />
                  )}
                  <span title={r.network === "instagram" ? "Instagram" : "LinkedIn"} style={{ display: "inline-flex", flex: "0 0 auto" }}>
                    {r.network === "instagram"
                      ? <span style={{ display: "inline-flex", color: "#c13584" }}><InstagramIcon size={13} /></span>
                      : <Linkedin size={13} style={{ color: "#0a66c2" }} />}
                  </span>
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.name}</span>
                </span>
                {r.network === "instagram" && r.mode ? <ConversationModeBadge mode={r.mode} /> : null}
              </span>
            </button>
          ))}
        </aside>
        <div style={{ minHeight: 0 }}>
          {selectedIg ? (
            <IgInbox key="ig-thread" isAuthed={isAuthed} requireAuth={requireAuth} userId={userId} hideChrome externalActiveId={selectedIg.id} />
          ) : selectedLn ? (
            <LinkedInThread
              key={`ln:${selectedLn.id}`}
              chat={selectedLn}
              quota={outreach.status?.quota}
              onQuota={(q) => outreach.setStatus((p) => (p ? { ...p, quota: q } : p))}
            />
          ) : (
            <div className="card" style={{ height: "100%", display: "flex" }}>
              <div style={{ margin: "auto", opacity: 0.7 }}>Sélectionne une conversation.</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Assistant({ isAuthed, requireAuth, seed, imageJobs, onImageJobCreated }: { isAuthed: boolean; requireAuth: (reason?: string) => void; seed?: { post: string; nonce: number } | null; imageJobs: ImageJob[]; onImageJobCreated: (job: ImageJob) => void }) {
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
                      <AssistantMessageActions
                        text={m.content}
                        targetKey={`chat:${activeConversationId ?? "new"}:${idx}`}
                        imageJobs={imageJobs}
                        onImageJobCreated={onImageJobCreated}
                        linkedin={linkedin}
                        twitter={twitter}
                        slack={slack}
                      />
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
  const [profile, setProfile] = useState<EditorialProfile>(EMPTY_EDITORIAL_PROFILE);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [aiInput, setAiInput] = useState("");
  const [draftInfo, setDraftInfo] = useState("");
  const linkedin = useLinkedIn(isAuthed);
  const twitter = useTwitter(isAuthed);
  const slack = useSlack(isAuthed);
  const outreach = useLinkedInOutreach(isAuthed);
  const manychat = useManychat(isAuthed);
  // Trois métiers distincts vivaient sur une même page qui défilait : qui je suis,
  // les comptes que je relie, et ce qui tourne sans moi. Un onglet par métier.
  // (L'abonnement, lui, a rejoint le pied de la barre latérale, avec le solde.)
  const [tab, setTab] = useState<ProfileTab>("profile");
  // Une seule ligne dépliée à la fois : c'est ce qui empêche la page de redevenir
  // le mur de réglages qu'on vient de démonter.
  const [openRow, setOpenRow] = useState<string | null>(null);
  const toggleRow = (key: string) => setOpenRow((prev) => (prev === key ? null : key));
  const [weeklyEnabled, setWeeklyEnabled] = useState(false);
  const [weeklySchedule, setWeeklySchedule] = useState<{day_of_week: number; hour: number; timezone: string}[]>([]);
  const [weeklySaving, setWeeklySaving] = useState(false);
  const [weeklyRunning, setWeeklyRunning] = useState(false);
  const [weeklyRunMsg, setWeeklyRunMsg] = useState("");
  const [weeklyRunErr, setWeeklyRunErr] = useState("");
  // ALE-224 : 2ᵉ point d'accès à l'opt-in « idée du jour » (l'autre est dans
  // Contenu › Idée du jour). Les deux tapent les mêmes endpoints → toujours en
  // phase à l'affichage (chaque onglet recharge l'état au montage).
  const [dailyEnabled, setDailyEnabled] = useState(false);
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

  // ALE-224 : opt-in « idée du jour » (mêmes endpoints que Contenu › Idée du jour).
  useEffect(() => {
    if (!isAuthed) { setDailyEnabled(false); return; }
    (async () => {
      try {
        const res = await fetch(`${DIRECT_API_URL}/me/daily-ideas`, { headers: await authHeaders() });
        if (res.ok) setDailyEnabled(!!(await res.json()).enabled);
      } catch { /* silencieux */ }
    })();
  }, [isAuthed]);

  async function toggleDailyEnabled() {
    const next = !dailyEnabled;
    setDailyEnabled(next);
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/daily-ideas/enabled`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ enabled: next }),
      });
      if (!res.ok) throw new Error();
    } catch { setDailyEnabled(!next); }
  }

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

  async function runWeeklyNow() {
    setWeeklyRunning(true);
    setWeeklyRunMsg("");
    setWeeklyRunErr("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/weekly-posts/run`, {
        method: "POST",
        headers: await authHeaders(),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Génération impossible.");
      setWeeklyRunMsg("Génération lancée — les posts de la semaine prochaine arriveront sur Slack à valider dans une minute.");
    } catch (err: any) {
      setWeeklyRunErr(err.message);
    } finally {
      setWeeklyRunning(false);
    }
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
      // (Le tiroir qu'on ouvrait ici n'existe plus : les champs sont toujours visibles.)
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

  const weeklyReady = !!linkedin.status?.connected;
  const igConnected = !!manychat.status?.connected;

  return (
    <div>
      <div className="tabs">
        {PROFILE_TABS.map((t) => (
          <button
            key={t.key}
            className={`tab ${tab === t.key ? "active" : ""}`}
            onClick={() => { setTab(t.key); setOpenRow(null); }}
            style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>

      {tab === "connections" && (
        <div>
          <p className="section-desc" style={{ marginTop: 0, marginBottom: 16 }}>
            Les comptes que tu relies à l&apos;app. Clique une ligne pour ouvrir ses réglages.
          </p>

          <SettingRow
            icon={<Linkedin size={18} style={{ color: "#0a66c2" }} />}
            name="LinkedIn"
            why={linkedinAccountDetail(linkedin.status) || "Publier tes posts en un clic, sans copier-coller"}
            right={
              linkedin.status?.connected ? (
                <>
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
                </>
              ) : (
                <button className="primary-button" onClick={linkedin.connect} disabled={linkedin.busy}>
                  {linkedin.busy ? <Loader2 size={14} className="spinning" /> : <Linkedin size={14} />}
                  {linkedin.busy ? "Redirection…" : "Connecter"}
                </button>
              )
            }
          />
          {linkedin.error ? <div className="error" style={{ marginBottom: 12 }}>{linkedin.error}</div> : null}

          <UnipileOutreachConnect
            outreach={outreach}
            open={openRow === "outreach"}
            onToggle={() => toggleRow("outreach")}
          />

          <SettingRow
            icon={
              <svg width="18" height="18" viewBox="0 0 122.8 122.8" style={{ flexShrink: 0 }}><path d="M0 11.1C0 5 5.1 0 11.3 0h100.2c6.2 0 11.3 5 11.3 11.1v100.6c0 6.1-5.1 11.1-11.3 11.1H11.3C5.1 122.8 0 117.8 0 111.7V11.1zm32.2 12.4a8.6 8.6 0 10.1 17.2 8.6 8.6 0 00-.1-17.2zM25.8 77.6h14.9V51.2H25.8v26.4zm36.1 0h14.9V61.4c0-13-7-19.1-16.3-19.1-7.5 0-11 4.2-12.9 7.1V51.2H57.1c.2-4.1 0-43.6 0-43.6H72v6.3c2-3 5.5-7.4 13.4-7.4 9.8 0 17.2 6.4 17.2 20.3v26.4H61.9z" fill="#4A154B"/></svg>
            }
            name="Slack"
            why={
              slack.status?.connected
                ? `Valider tes posts depuis ton téléphone · ${slack.status.team_name || "Slack"}`
                : !slack.status?.configured
                  ? "Intégration Slack non configurée sur le serveur."
                  : "Valider tes posts et tes idées depuis ton téléphone"
            }
            right={
              slack.status?.connected ? (
                <>
                  <span className="status-pill ok"><CheckCircle2 size={14} /> Connecté</span>
                  <button className="secondary-button" onClick={slack.disconnect} disabled={slack.busy} style={{ fontSize: 12 }}>
                    {slack.busy ? <Loader2 size={14} className="spinning" /> : null}
                    Déconnecter
                  </button>
                </>
              ) : slack.status?.configured ? (
                <button className="primary-button" onClick={slack.connect} disabled={slack.busy}>
                  {slack.busy ? <Loader2 size={14} className="spinning" /> : null}
                  {slack.busy ? "Redirection…" : "Connecter"}
                </button>
              ) : (
                <span className="status-pill">Non configuré</span>
              )
            }
          />
          {slack.error ? <div className="error" style={{ marginBottom: 12 }}>{slack.error}</div> : null}

          <SettingRow
            icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" style={{ flexShrink: 0 }}><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.742l7.734-8.842L1.254 2.25H8.08l4.253 5.622L18.244 2.25zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>}
            name="X (Twitter)"
            why="Republier tes posts sur X en un clic"
            right={
              twitter.status?.connected ? (
                <span className="status-pill ok"><CheckCircle2 size={14} /> Connecté</span>
              ) : (
                <button className="primary-button" onClick={twitter.connect} disabled={twitter.busy}>
                  {twitter.busy ? <Loader2 size={14} className="spinning" /> : null}
                  {twitter.busy ? "Redirection…" : "Connecter"}
                </button>
              )
            }
          />
          {twitter.error ? <div className="error" style={{ marginBottom: 12 }}>{twitter.error}</div> : null}

          <ManychatConnect
            manychat={manychat}
            open={openRow === "manychat"}
            onToggle={() => toggleRow("manychat")}
          />
        </div>
      )}

      {tab === "automations" && (
        <div>
          <p className="section-desc" style={{ marginTop: 0, marginBottom: 16 }}>
            Ce qui tourne pendant que tu n&apos;es pas là. Clique une ligne pour ouvrir ses réglages.
          </p>

          {/* ALE-224 : opt-in « idée du jour ». ALE-286 : c'est le SEUL interrupteur
              côté agence (le sous-onglet a disparu) — les comptes clients, eux,
              continuent de recevoir et de lire leur idée du matin. */}
          <SettingRow
            icon={<Sparkles size={18} style={{ color: "var(--coral)" }} />}
            name="Une idée de post chaque matin"
            why="Générée depuis ta veille et ton réservoir d'idées, puis servie aux comptes clients"
            right={
              <label className="daily-switch">
                <input type="checkbox" checked={dailyEnabled} onChange={toggleDailyEnabled} />
                <span>Activer</span>
              </label>
            }
          />

          <SettingRow
            icon={<CalendarDays size={18} style={{ color: "var(--coral)" }} />}
            name="Les posts de ta semaine"
            why={
              !weeklyReady
                ? "Connecte LinkedIn (onglet Connexions) pour activer"
                : weeklyEnabled && weeklySchedule.length
                  ? `3 posts écrits le vendredi, publiés ${weeklySchedule.map((s) => `${["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."][s.day_of_week]} ${String(s.hour).padStart(2, "0")} h`).join(" · ")}`
                  : "3 posts écrits le vendredi matin pour la semaine suivante"
            }
            open={openRow === "weekly"}
            onToggle={weeklyReady && weeklyEnabled ? () => toggleRow("weekly") : undefined}
            right={
              weeklyReady ? (
                <label className="daily-switch">
                  <input type="checkbox" checked={weeklyEnabled} onChange={toggleWeeklyEnabled} />
                  <span>Activer</span>
                </label>
              ) : (
                <span className="status-pill">LinkedIn requis</span>
              )
            }
          >
            <p style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 0, marginBottom: 10 }}>
              Chaque <strong>vendredi matin (vers 6-7 h, heure de Paris)</strong>, 3 posts sont écrits pour la{" "}
              <strong>semaine suivante</strong>
              {slack.status?.connected
                ? " et envoyés sur Slack pour validation, puis publiés aux créneaux ci-dessous une fois validés."
                : " puis publiés automatiquement aux créneaux ci-dessous. Connecte Slack (onglet Connexions) pour les valider avant publication."}
            </p>
            <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 8 }}>
              Jours de publication (fuseau Europe/Paris) :
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
            <div style={{ marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
              <p style={{ fontSize: 12, color: "var(--muted)", marginBottom: 8 }}>
                Pas envie d&apos;attendre vendredi ? Génère les posts de la semaine prochaine tout de suite.
              </p>
              <button
                className="secondary-button"
                onClick={runWeeklyNow}
                disabled={weeklyRunning || weeklySchedule.length === 0}
                style={{ fontSize: 13 }}
              >
                {weeklyRunning ? <><Loader2 size={14} className="spinning" /> Génération…</> : <><Sparkles size={14} /> Générer les posts de la semaine maintenant</>}
              </button>
              {weeklyRunMsg && <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 8 }}>{weeklyRunMsg}</p>}
              {weeklyRunErr && <p style={{ fontSize: 12, color: "var(--coral)", marginTop: 8 }}>{weeklyRunErr}</p>}
            </div>
          </SettingRow>

          <SettingRow
            icon={<Lightbulb size={18} style={{ color: "var(--coral)" }} />}
            name="Réponses aux messages Instagram"
            why="L'agent répond seul quand la réponse est dans sa FAQ, sinon il te passe la main"
            open={openRow === "faq"}
            onToggle={() => toggleRow("faq")}
            right={
              igConnected ? (
                <span className="status-pill ok"><CheckCircle2 size={14} /> Actif</span>
              ) : (
                <span className="status-pill">Instagram non connecté</span>
              )
            }
          >
            <AgentFaqEditor isAuthed={isAuthed} active={openRow === "faq"} />
          </SettingRow>
        </div>
      )}

      {tab === "profile" && (
      <div>
      <div className="section-header">
        <div>
          <h2 className="section-title"><UserRound size={20} /> Contexte éditorial</h2>
          <p className="section-desc">
            Décris le client qui publie. L&apos;IA s&apos;appuie sur ce contexte pour écrire les idées et les posts.
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

      {error ? <div className="error" style={{ marginBottom: 12 }}>{error}</div> : null}
      {draftInfo ? <div className="auth-info" style={{ marginBottom: 12 }}>{draftInfo}</div> : null}
      {saved ? <div className="auth-info" style={{ marginBottom: 12 }}>Profil éditorial sauvegardé. Les prochaines générations utiliseront ce contexte.</div> : null}
      {loading ? (
        <div className="card sk-list" style={{ padding: 24, display: "grid", gap: 12 }}>
          <Sk h={16} w="40%" r={6} />
          <Sk h={38} w="100%" r={8} />
          <Sk h={38} w="100%" r={8} />
          <Sk h={10} w="90%" />
          <Sk h={10} w="76%" />
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

          {/* Le tiroir « Détails du profil éditorial » a disparu : il n'existait que
              parce que la page portait aussi les connexions et les automatisations.
              L'onglet est maintenant dédié — les champs s'affichent directement. */}
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
      )}
      </div>
      )}
    </div>
  );
}

/* ─── Tendances de la veille : agrégation de tous les rapports (remplace le Dashboard global, ALE-132). ───
   Les chiffres viennent de GET /me/influencer-trends (agrégation pure, aucun coût LLM) ; ce composant
   ne fait que la mise en récit. Chaque « lift » compare une catégorie de posts à la performance
   habituelle de son auteur, pour neutraliser les écarts de taille d'audience. */

function fmtLift(n: number) {
  return n > 0 ? `+${n} %` : n < 0 ? `−${Math.abs(n)} %` : "±0 %";
}
function fmtKAbo(n: number) {
  if (!n) return "—";
  return n >= 1000 ? `${(n / 1000).toFixed(n < 10000 ? 1 : 0).replace(".", ",")} k` : String(n);
}
function fmtRatio(n: number) {
  return `×${String(n).replace(".", ",")}`;
}
function fmtRatePct(n: number | null | undefined) {
  if (n === null || n === undefined) return "—";
  return `${n.toFixed(n >= 1 ? 1 : 2).replace(".", ",")} %`;
}
function initialsOf(name: string) {
  return name.split(/\s+/).map((w) => w[0]).filter(Boolean).slice(0, 2).join("").toUpperCase();
}

function TrendBars({ rows, ariaLabel }: { rows: TrendRow[]; ariaLabel: string }) {
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.lift_pct)));
  return (
    <div className="tr-bars" role="img" aria-label={ariaLabel}>
      {rows.map((r) => (
        <div className="tr-bar-row" key={r.label}>
          <span className="tr-bar-lbl" title={`${r.posts} posts`}>{r.label}</span>
          <span className="tr-bar-track">
            <span
              className={`tr-bar-fill ${r.lift_pct >= 0 ? "pos" : "neg"}`}
              style={{ width: `${Math.round((Math.abs(r.lift_pct) / max) * 50)}%` }}
            />
          </span>
          <span className="tr-bar-val">{fmtLift(r.lift_pct)}</span>
        </div>
      ))}
    </div>
  );
}

function escHtml(s: string) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] as string));
}

/** Document imprimable (→ « Enregistrer en PDF » du navigateur) reprenant toutes les tendances + le classement. */
function trendsPrintHtml(trends: InfluencerTrends): string {
  const updated = trends.updated_at
    ? new Date(trends.updated_at).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" })
    : "";
  const barTable = (title: string, rows?: TrendRow[]) => {
    if (!rows || !rows.length) return "";
    const body = rows.map((r) =>
      `<tr><td>${escHtml(r.label)}</td><td class="num ${r.lift_pct >= 0 ? "pos" : "neg"}">${fmtLift(r.lift_pct)}</td><td class="n">${r.posts} posts</td></tr>`
    ).join("");
    return `<section><h2>${escHtml(title)}</h2><table>${body}</table></section>`;
  };
  const cta = trends.cta;
  const share = trends.comments_share;
  const bench = trends.benchmark;
  const freq = trends.frequency && trends.frequency.buckets.length ? trends.frequency : null;
  const ranking = trends.ranking || [];
  return `<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Tendances de ma veille LinkedIn</title><style>
    body{font-family:-apple-system,"Segoe UI",Roboto,sans-serif;color:#111;margin:40px auto;max-width:720px;padding:0 24px;font-size:13px;line-height:1.55}
    h1{font-size:24px;letter-spacing:-.02em;margin:0 0 4px}.meta{color:#666;font-size:12px;margin:0 0 26px}
    h2{font-size:15px;margin:26px 0 8px}.hero{font-size:40px;font-weight:700;letter-spacing:-.03em;margin:6px 0}
    table{border-collapse:collapse;width:100%}td{padding:5px 8px;border-bottom:1px solid #e5e5e5}
    td.num{text-align:right;font-weight:600;white-space:nowrap}td.n{text-align:right;color:#888;font-size:11px;white-space:nowrap}
    .pos{color:#0b7a55}.neg{color:#b91c1c}.note{color:#777;font-size:11px;margin:6px 0 0}
    section{break-inside:avoid}@media print{body{margin:0 auto}}
  </style></head><body>
  <h1>Tendances de ma veille LinkedIn</h1>
  <p class="meta">${trends.report_count} rapports · ${trends.post_count} posts analysés${updated ? ` · ${escHtml(updated)}` : ""} — chaque écart compare les posts à la performance habituelle de leur auteur.</p>
  ${cta ? `<section><h2>La mécanique des commentaires</h2><div class="hero">${fmtRatio(cta.ratio_median)}</div><p>Les posts « commente et je t&#39;envoie la ressource » multiplient l&#39;engagement médian par ${String(cta.ratio_median).replace(".", ",")} (${cta.winning}/${cta.accounts} comptes gagnants, de ${fmtRatio(cta.ratio_min)} à ${fmtRatio(cta.ratio_max)}).${share ? ` ${share.share_median_pct} % de l&#39;engagement des ${share.top_accounts} comptes les plus performants vient des commentaires.` : ""}</p><p class="note">Basé sur ${cta.posts_with} posts avec appel à commenter vs ${cta.posts_without} sans.</p></section>` : ""}
  ${barTable("Formats", trends.formats)}
  ${barTable("Sujets", trends.stages)}
  ${barTable("Accroches", trends.hooks)}
  ${barTable("Longueur des posts", trends.length_buckets)}
  ${barTable("Jour de publication", trends.weekdays)}
  ${freq ? `<section><h2>Rythme de publication</h2><table>${freq.buckets.map((b) => `<tr><td>${escHtml(b.label)}</td><td class="num">${fmtRatePct(b.median_rate_pct)}</td><td class="n">${b.accounts} comptes</td></tr>`).join("")}</table><p class="note">Taux d'engagement médian par tranche de fréquence (comparaison entre comptes).</p></section>` : ""}
  ${bench ? `<section><h2>Benchmark</h2><p>Meilleur taux d&#39;engagement : <b>${escHtml(bench.best.name)}</b> (${fmtKAbo(bench.best.followers)} abonnés, ${fmtRatePct(bench.best.rate_pct)})${bench.biggest.name !== bench.best.name ? ` — plus gros compte : ${escHtml(bench.biggest.name)} (${fmtKAbo(bench.biggest.followers)}, ${fmtRatePct(bench.biggest.rate_pct)})` : ""}.${bench.high_freq ? ` Au-delà de ${bench.high_freq.threshold} posts/semaine, aucun compte ne dépasse ${fmtRatePct(bench.high_freq.max_rate_pct)} de taux.` : ""}</p></section>` : ""}
  ${ranking.length ? `<section><h2>Classement</h2><table>${ranking.map((r, i) => `<tr><td class="n">${i + 1}</td><td>${escHtml(r.name)}</td><td class="n">${fmtKAbo(r.followers)} abonnés</td></tr>`).join("")}</table></section>` : ""}
  </body></html>`;
}

function exportTrendsPdf(trends: InfluencerTrends) {
  const w = window.open("", "_blank");
  if (!w) return;
  w.document.write(trendsPrintHtml(trends));
  w.document.close();
  w.focus();
  setTimeout(() => {
    try { w.print(); } catch { /* l'utilisateur peut imprimer manuellement (Cmd+P) */ }
  }, 400);
}

function InfluencerTrendsBlock({
  trends,
  loading,
  onRefresh,
}: {
  trends: InfluencerTrends | null;
  loading: boolean;
  onRefresh: () => void;
}) {
  if (loading && !trends) {
    return (
      <div className="card sk-list" style={{ padding: 24, marginBottom: 20, display: "grid", gap: 12 }}>
        <Sk h={16} w="55%" r={6} />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Sk h={64} w="100%" r={10} />
          <Sk h={64} w="100%" r={10} />
        </div>
        <Sk h={10} w="100%" />
        <Sk h={10} w="86%" />
      </div>
    );
  }
  if (!trends) return null;

  const updated = trends.updated_at
    ? new Date(trends.updated_at).toLocaleDateString("fr-FR", { day: "numeric", month: "long" })
    : null;

  if (trends.insufficient) {
    return (
      <div className="card" style={{ padding: 20, marginBottom: 20 }}>
        <span className="tr-eyebrow">Tendances de ta veille</span>
        <p style={{ margin: "8px 0 0", fontSize: 13.5, color: "var(--muted)" }}>
          Analyse au moins {trends.min_reports || 3} influenceurs pour voir les tendances transverses
          ({trends.report_count} analysé{trends.report_count > 1 ? "s" : ""} pour l’instant).
        </p>
      </div>
    );
  }

  const hooks = trends.hooks || [];
  const stages = trends.stages || [];
  const formats = trends.formats || [];
  const lengths = trends.length_buckets || [];
  const weekdays = trends.weekdays || [];
  const cta = trends.cta;
  const share = trends.comments_share;
  const bench = trends.benchmark;
  const freq = trends.frequency && trends.frequency.buckets.length ? trends.frequency : null;
  const maxFreqRate = freq ? Math.max(...freq.buckets.map((b) => b.median_rate_pct)) : 0;

  const worstFormat = formats.length ? formats[formats.length - 1] : null;
  const topStage = stages[0] || null;
  const lastStage = stages.length > 1 ? stages[stages.length - 1] : null;
  const topHook = hooks[0] || null;
  const worstHook = hooks.length > 1 ? hooks[hooks.length - 1] : null;
  const reliableHook = hooks
    .filter((h) => (h.reports || 0) >= 8)
    .sort((a, b) => (b.wins || 0) / (b.reports || 1) - (a.wins || 0) / (a.reports || 1))[0] || null;

  const lenMax = lengths.length ? Math.max(...lengths.map((r) => Math.abs(r.lift_pct))) : 0;
  const sortedDays = [...weekdays].sort((a, b) => b.lift_pct - a.lift_pct);
  const bestDay = sortedDays[0] || null;
  const worstDay = sortedDays.length > 1 ? sortedDays[sortedDays.length - 1] : null;
  const dayMax = Math.max(Math.abs(bestDay?.lift_pct || 0), Math.abs(worstDay?.lift_pct || 0));
  const mythsFlat = lenMax <= 15 && dayMax <= 15;

  const leverCount = (cta ? 1 : 0) + (formats.length ? 1 : 0) + (stages.length ? 1 : 0) + (hooks.length ? 1 : 0);
  let lever = 0;
  const no = () => String(++lever).padStart(2, "0");

  return (
    <section aria-label="Tendances de ta veille">
      <div className="tr-intro">
        <span className="tr-eyebrow">Tendances de ta veille</span>
        <h3>
          {leverCount > 1
            ? `${["Un", "Deux", "Trois", "Quatre"][leverCount - 1]} leviers pèsent vraiment. Le reste est du bruit.`
            : "Ce que tes rapports disent quand on les lit ensemble."}
        </h3>
        <p className="tr-lede">
          Lus ensemble, tes {trends.report_count} rapports racontent une stratégie précise. Chaque chiffre compare
          les posts à la performance habituelle de leur auteur, pour neutraliser les écarts de taille d’audience.
        </p>
        <div className="tr-meta-row">
          <span className="tr-meta">
            {trends.report_count} rapports · {fmt(trends.post_count)} posts{updated ? ` · mise à jour le ${updated}` : ""}
          </span>
          <button type="button" className="tr-pill-btn" onClick={onRefresh} disabled={loading}>
            {loading ? <Loader2 size={13} className="spinning" /> : <RefreshCw size={13} />} Actualiser l’analyse
          </button>
          <button type="button" className="tr-pill-btn" onClick={() => exportTrendsPdf(trends)}>
            <FileText size={13} /> Exporter en PDF
          </button>
        </div>
      </div>

      {cta && (
        <div className="tr-hero" role="group" aria-label="Levier n°1 : la mécanique des commentaires">
          <div className="tr-hero-grid">
            <div>
              <span className="tr-eyebrow"><span className="tr-no">{no()}</span> · La mécanique des commentaires</span>
              <div className="tr-hero-num">{fmtRatio(cta.ratio_median)}</div>
              <p className="tr-hero-title">L’engagement se fabrique dans les commentaires.</p>
              <p className="tr-hero-body">
                Les posts « commente et je t’envoie la ressource » multiplient l’engagement médian par {String(cta.ratio_median).replace(".", ",")}.{" "}
                <b>
                  {cta.winning === cta.accounts
                    ? `Les ${cta.accounts} comptes qui utilisent ce levier y gagnent tous`
                    : `${cta.winning} des ${cta.accounts} comptes qui l’utilisent y gagnent`}
                </b>
                , de {fmtRatio(cta.ratio_min)} à {fmtRatio(cta.ratio_max)} — c’est la mécanique qui fabrique les « gros » chiffres de ta niche.
              </p>
            </div>
            {share && (
              <div className="tr-hero-side">
                <span className="tr-hero-side-num">{share.share_median_pct} %</span>
                <span className="tr-hero-side-lbl">
                  de l’engagement des {share.top_accounts} comptes les plus performants vient des commentaires (jusqu’à {share.share_max_pct} %)
                </span>
              </div>
            )}
            <span className="tr-hero-action">À tester — offrir un guide ou un template contre un commentaire</span>
            <span className="tr-hero-foot">
              Basé sur {cta.posts_with} posts avec appel à commenter vs {cta.posts_without} sans, sur {cta.accounts} comptes.
            </span>
          </div>
        </div>
      )}

      <div className="tr-exhibits">
        {formats.length > 0 && worstFormat && (
          <article className="tr-exhibit">
            <span className="tr-eyebrow"><span className="tr-no">{no()}</span> Formats</span>
            <div className="tr-exhibit-top">
              <span className={`tr-exhibit-num ${worstFormat.lift_pct < 0 ? "neg" : "pos"}`}>{fmtLift(worstFormat.lift_pct)}</span>
              <p className="tr-exhibit-title">
                {worstFormat.lift_pct <= -30 ? "Le contenu natif écrase le contenu partagé." : "Ce que chaque format rapporte."}
              </p>
            </div>
            <TrendBars rows={formats} ariaLabel="Impact de chaque format sur l’engagement" />
            <span className="tr-exhibit-foot">
              {formats.reduce((s, r) => s + r.posts, 0)} posts — écart vs la performance habituelle de chaque compte.
            </span>
          </article>
        )}
        {topStage && (
          <article className="tr-exhibit">
            <span className="tr-eyebrow"><span className="tr-no">{no()}</span> Sujets</span>
            <div className="tr-exhibit-top">
              <span className={`tr-exhibit-num ${topStage.lift_pct >= 0 ? "pos" : "neg"}`}>{fmtLift(topStage.lift_pct)}</span>
              <p className="tr-exhibit-title">
                {topStage.key === "BOFU"
                  ? "Les posts qui proposent quelque chose engagent le plus."
                  : `« ${topStage.label} » : la catégorie qui engage le plus.`}
              </p>
            </div>
            <TrendBars rows={stages} ariaLabel="Impact de chaque catégorie de contenu sur l’engagement" />
            <p className="tr-exhibit-body">
              Chaque post est classé selon son intention : attirer l’attention (opinion, actu), éduquer
              (méthode, tuto) ou proposer quelque chose — un guide à récupérer, une offre, une preuve client.
              {lastStage && (
                <> Les posts « {topStage.label.toLowerCase()} » font <b>{fmtLift(topStage.lift_pct)}</b>,
                quand « {lastStage.label.toLowerCase()} » fait <b>{fmtLift(lastStage.lift_pct)}</b>.</>
              )}
            </p>
            <span className="tr-exhibit-foot">{stages.reduce((s, r) => s + r.posts, 0)} posts classés par catégorie.</span>
          </article>
        )}
        {topHook && (
          <article className="tr-exhibit">
            <span className="tr-eyebrow"><span className="tr-no">{no()}</span> Accroches</span>
            <div className="tr-exhibit-top">
              <span className={`tr-exhibit-num ${topHook.lift_pct >= 0 ? "pos" : "neg"}`}>{fmtLift(topHook.lift_pct)}</span>
              <p className="tr-exhibit-title">« {topHook.label} » : l’accroche qui porte le plus.</p>
            </div>
            <TrendBars rows={hooks} ariaLabel="Impact de chaque type d’accroche sur l’engagement" />
            <p className="tr-exhibit-body">
              {reliableHook
                ? <>La valeur sûre : « {reliableHook.label} », qui gagne ou fait jeu égal dans <b>{reliableHook.wins} rapports sur {reliableHook.reports}</b>.</>
                : null}
              {worstHook && worstHook.lift_pct < 0
                ? <> « {worstHook.label} » sous-performe ({fmtLift(worstHook.lift_pct)}).</>
                : null}
            </p>
            <span className="tr-exhibit-foot">{hooks.reduce((s, r) => s + r.posts, 0)} posts classés par type d’accroche.</span>
          </article>
        )}
        {bench && (
          <article className="tr-exhibit">
            <span className="tr-eyebrow">Benchmark</span>
            <div className="tr-exhibit-top">
              <span className="tr-exhibit-num">{fmtRatePct(bench.best.rate_pct)}</span>
              <p className="tr-exhibit-title">Le taux d’engagement ne suit pas la taille.</p>
            </div>
            <div className="tr-compare">
              <div className="tr-compare-row">
                <span className="tr-compare-dot" style={{ background: "var(--success)" }} />
                <span><b>{bench.best.name}</b> <span style={{ color: "var(--muted)" }}>— {fmtKAbo(bench.best.followers)} abonnés</span></span>
                <span className="tr-compare-num" style={{ color: "var(--success)" }}>{fmtRatePct(bench.best.rate_pct)}</span>
              </div>
              {bench.biggest.name !== bench.best.name && (
                <div className="tr-compare-row">
                  <span className="tr-compare-dot" style={{ background: "var(--muted)" }} />
                  <span><b>{bench.biggest.name}</b> <span style={{ color: "var(--muted)" }}>— {fmtKAbo(bench.biggest.followers)} abonnés, le plus gros compte</span></span>
                  <span className="tr-compare-num" style={{ color: "var(--muted)" }}>{fmtRatePct(bench.biggest.rate_pct)}</span>
                </div>
              )}
            </div>
            {bench.high_freq && (
              <p className="tr-exhibit-body">
                Publier plus ne rattrape rien : au-delà de <b>{bench.high_freq.threshold} posts/semaine</b>{" "}
                ({bench.high_freq.accounts} comptes), aucun ne dépasse {fmtRatePct(bench.high_freq.max_rate_pct)} de taux.
              </p>
            )}
          </article>
        )}
        {freq && (
          <article className="tr-exhibit">
            <span className="tr-eyebrow">Rythme</span>
            <div className="tr-exhibit-top">
              <span className="tr-exhibit-num">
                {freq.ratio ? `÷${String(freq.ratio).replace(".", ",")}` : fmtRatePct(freq.buckets[0].median_rate_pct)}
              </span>
              <p className="tr-exhibit-title">Publier plus dilue chaque post.</p>
            </div>
            <div className="tr-compare">
              {freq.buckets.map((b) => (
                <div className="tr-compare-row" key={b.label}>
                  <span
                    className="tr-compare-dot"
                    style={{ background: b.median_rate_pct === maxFreqRate ? "var(--success)" : "var(--muted)" }}
                  />
                  <span><b>{b.label}</b> <span style={{ color: "var(--muted)" }}>— {b.accounts} comptes</span></span>
                  <span
                    className="tr-compare-num"
                    style={{ color: b.median_rate_pct === maxFreqRate ? "var(--success)" : "var(--muted)" }}
                  >
                    {fmtRatePct(b.median_rate_pct)}
                  </span>
                </div>
              ))}
            </div>
            <p className="tr-exhibit-body">
              {freq.ratio && freq.ratio > 1.5
                ? <>Le taux d’engagement médian est divisé par <b>{String(freq.ratio).replace(".", ",")}</b> entre les comptes
                les moins actifs et les plus actifs. Publier plus peut élargir la portée totale, mais chaque post touche
                proportionnellement moins — la régularité bat le volume.</>
                : <>Sur ton corpus, la fréquence de publication ne change pas nettement le taux d’engagement par post.</>}
            </p>
            <span className="tr-exhibit-foot">Taux d’engagement médian par tranche de fréquence — comparaison entre comptes, à lire comme une tendance.</span>
          </article>
        )}
      </div>

      {(lengths.length > 0 || (bestDay && worstDay)) && (
        <div className="tr-myths" role="group" aria-label="Longueur et jour de publication">
          <div style={{ maxWidth: "22ch", display: "flex", flexDirection: "column", gap: 6 }}>
            <span className="tr-eyebrow">{mythsFlat ? "Mythes cassés" : "Longueur & timing"}</span>
            <p className="tr-exhibit-title" style={{ fontSize: 15 }}>
              {mythsFlat ? "Deux variables qu’on surveille pour rien." : "L’effet mesuré sur ton corpus."}
            </p>
          </div>
          {lengths.length > 0 && (
            <div>
              <span className="tr-myth-num">±{lenMax} %</span>
              <span className="tr-myth-lbl" style={{ display: "block" }}>La longueur du post</span>
              <p className="tr-myth-body">
                De moins de 150 mots à 350 et plus, l’écart d’engagement médian reste dans ±{lenMax} %.
                {mythsFlat ? " Écris la longueur que ton sujet demande." : ""}
              </p>
            </div>
          )}
          {bestDay && worstDay && (
            <div>
              <span className="tr-myth-num">±{dayMax} %</span>
              <span className="tr-myth-lbl" style={{ display: "block" }}>Le jour de publication</span>
              <p className="tr-myth-body">
                {bestDay.label} {fmtLift(bestDay.lift_pct)}, {worstDay.label.toLowerCase()} {fmtLift(worstDay.lift_pct)} —
                aucun jour ne justifie de retenir un bon post.
              </p>
            </div>
          )}
        </div>
      )}
    </section>
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
  const [trends, setTrends] = useState<InfluencerTrends | null>(null);
  const [trendsLoading, setTrendsLoading] = useState(false);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [error, setError] = useState("");

  // ALE-214 : suivi d'influenceurs (veille). handle → id de la ligne de suivi.
  const [followed, setFollowed] = useState<Record<string, string>>({});
  const [followCap, setFollowCap] = useState(5);
  const [togglingHandle, setTogglingHandle] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkMsg, setCheckMsg] = useState("");

  useEffect(() => {
    if (!isAuthed) { setFollowed({}); return; }
    let cancelled = false;
    authHeaders().then((h) =>
      fetch(`${DIRECT_API_URL}/me/followed-influencers`, { headers: h })
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (cancelled || !data) return;
          const map: Record<string, string> = {};
          (data.followed || []).forEach((f: any) => { if (f.handle) map[f.handle] = f.id; });
          setFollowed(map);
          if (data.cap) setFollowCap(data.cap);
        })
        .catch(() => {})
    );
    return () => { cancelled = true; };
  }, [isAuthed]);

  async function loadTrends() {
    setTrendsLoading(true);
    try {
      const res = await fetch(`${API_URL}/me/influencer-trends`, { headers: await authHeaders() });
      if (res.ok) setTrends(await res.json());
    } catch {
      /* best-effort : le classement reste utilisable sans tendances */
    } finally {
      setTrendsLoading(false);
    }
  }

  useEffect(() => {
    if (isAuthed) loadTrends();
    else setTrends(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed]);

  async function toggleFollow(handle: string) {
    setError("");
    setTogglingHandle(handle);
    try {
      const followId = followed[handle];
      if (followId) {
        setFollowed((prev) => { const next = { ...prev }; delete next[handle]; return next; });
        await fetch(`${DIRECT_API_URL}/me/followed-influencers/${followId}`, {
          method: "DELETE",
          headers: await authHeaders(),
        });
      } else {
        const res = await fetch(`${DIRECT_API_URL}/me/followed-influencers`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...(await authHeaders()) },
          body: JSON.stringify({ handle }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Impossible de suivre cet influenceur");
        setFollowed((prev) => ({ ...prev, [handle]: data.id }));
      }
    } catch (err: any) {
      setError(err.message || "Action impossible");
    } finally {
      setTogglingHandle(null);
    }
  }

  async function checkNow() {
    setChecking(true);
    setCheckMsg("");
    setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/influencer-monitor/run`, {
        method: "POST",
        headers: await authHeaders(),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Détection impossible");
      setCheckMsg("Détection lancée ✓ — les nouveaux posts sont enregistrés en arrière-plan (écran de veille à venir).");
    } catch (err: any) {
      setError(err.message || "Détection impossible");
    } finally {
      setChecking(false);
    }
  }

  const followedCount = Object.keys(followed).length;

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

  const statsByInf = new Map<string, TrendsRankingRow>((trends?.ranking || []).map((r) => [r.influencer_id, r]));
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
      const ea = statsByInf.get(a.influencer_id)?.median_engagement ?? -1;
      const eb = statsByInf.get(b.influencer_id)?.median_engagement ?? -1;
      if (eb !== ea) return eb - ea;
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
            Le classement de tes profils analysés, puis les tendances de ta veille.
          </p>
        </div>
      </div>

      {checkMsg && <div className="card" style={{ margin: "12px 0", padding: "10px 14px", fontSize: 13, color: "var(--muted)" }}>{checkMsg}</div>}
      {error && <div className="error" style={{ margin: "12px 0" }}>{error}</div>}

      {loading ? (
        <div className="card sk-list" style={{ padding: "8px 0", marginTop: 20 }}>
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 16px", borderBottom: i < 4 ? "1px solid var(--border)" : "none" }}>
              <Sk circle w={16} h={16} />
              <Sk h={12} w={`${34 - (i % 3) * 6}%`} r={6} />
              <Sk h={10} w={80} style={{ marginLeft: "auto" }} />
              <Sk h={10} w={64} />
            </div>
          ))}
        </div>
      ) : entries.length === 0 ? (
        <div className="card" style={{ textAlign: "center", padding: 32, marginTop: 20 }}>
          <FileText size={24} style={{ opacity: 0.35, marginBottom: 8 }} />
          <p style={{ margin: 0, color: "var(--muted)" }}>
            Aucun profil analysé pour l’instant. Lance une série avec le bloc « Analyser des profils » ci-dessus.
          </p>
        </div>
      ) : (
        <div className="card" style={{ padding: 0, overflow: "hidden", marginTop: 20 }}>
          <div className="tr-table-head">
            <h3 style={{ margin: 0, fontSize: 16 }}>Classement</h3>
            <span style={{ fontSize: 12, color: "var(--muted)" }}>
              Veille : <b style={{ color: "var(--ink)" }}>{followedCount}</b>/{followCap} suivis
            </span>
            {followedCount > 0 && (
              <button
                type="button"
                className="secondary-button"
                style={{ fontSize: 12, whiteSpace: "nowrap", padding: "5px 10px" }}
                disabled={checking}
                title="Scrape les derniers posts de tes influenceurs suivis et enregistre les nouveaux"
                onClick={checkNow}
              >
                {checking ? <Loader2 size={13} className="spinning" /> : <RefreshCw size={13} />} Vérifier les nouveaux posts
              </button>
            )}
            <input
              type="search"
              className="tr-search"
              placeholder="Rechercher un influenceur…"
              aria-label="Rechercher un influenceur"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          {filtered.length === 0 ? (
            <p style={{ margin: 0, padding: 24, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>
              Aucun profil ne correspond à ta recherche.
            </p>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table className="dash-table tr-ranking">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Influenceur</th>
                    <th style={{ textAlign: "center" }}>Veille</th>
                    <th style={{ textAlign: "center" }}>Rapport</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((entry, i) => {
                    const s = statsByInf.get(entry.influencer_id);
                    return (
                      <tr key={entry.influencer_id} className={i < 3 && s ? "tr-top3" : ""}>
                        <td><span className="tr-rank">{i + 1}</span></td>
                        <td>
                          <span className="tr-who">
                            <span className="tr-avatar" aria-hidden="true">{initialsOf(entry.name)}</span>
                            <span>
                              <a
                                href={safeHttpUrl(entry.profile_url)}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="tr-name"
                                title="Voir le profil LinkedIn"
                              >
                                {entry.name}
                              </a>
                              <span className="tr-sub">
                                {entry.follower_count ? `${fmt(entry.follower_count)} abonnés` : decodeHandle(entry.handle)}
                              </span>
                            </span>
                          </span>
                        </td>
                        <td style={{ textAlign: "center" }}>
                          <button
                            type="button"
                            className={followed[entry.handle] ? "primary-button" : "secondary-button"}
                            style={{ padding: "4px 10px", fontSize: 12, whiteSpace: "nowrap" }}
                            disabled={togglingHandle === entry.handle}
                            title={followed[entry.handle]
                              ? "Ne plus surveiller cet influenceur"
                              : `Surveiller ses nouveaux posts (max ${followCap} influenceurs)`}
                            onClick={() => toggleFollow(entry.handle)}
                          >
                            {togglingHandle === entry.handle
                              ? <Loader2 size={12} className="spinning" />
                              : <Eye size={12} />}
                            {followed[entry.handle] ? " Suivi ✓" : " Suivre"}
                          </button>
                        </td>
                        <td style={{ textAlign: "center" }}>
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
                            Rapport
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ALE-257 : les tendances passent SOUS le classement (ordre voulu). */}
      <div style={{ marginTop: 24 }}>
        <InfluencerTrendsBlock trends={trends} loading={trendsLoading} onRefresh={loadTrends} />
      </div>
    </div>
  );
}

/** ALE-215 : fil de veille — nouveaux posts des influenceurs suivis. */
type MonitoredPost = {
  id: string;
  url?: string | null;
  text?: string | null;
  posted_at?: string | null;
  format?: string | null;
  likes: number;
  comments: number;
  reposts: number;
  engagement: number;
  media_items?: { type: string; url: string }[] | null;
  detected_by_monitor?: boolean;
  first_seen_at?: string | null;
  influencer_name?: string | null;
  influencer_handle?: string | null;
};

function MonitoringFeedView({
  isAuthed,
  requireAuth,
  onInspire,
}: {
  isAuthed: boolean;
  requireAuth: (reason?: string, mode?: AuthMode) => void;
  onInspire: (topic: string) => void;
}) {
  const [posts, setPosts] = useState<MonitoredPost[]>([]);
  const [followedCount, setFollowedCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);
  const [checkMsg, setCheckMsg] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);
  const [savedIds, setSavedIds] = useState<Record<string, boolean>>({});
  const [open, setOpen] = useState(false); // tiroir replié par défaut (compact)
  const [showAll, setShowAll] = useState(false); // aperçu 3 posts → « Voir tout »

  async function load() {
    if (!isAuthed) return;
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/monitoring/feed`, { headers: await authHeaders() });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Chargement de la veille impossible");
      setPosts(Array.isArray(data.posts) ? data.posts : []);
      setFollowedCount(data.followed_count || 0);
    } catch (err: any) {
      setError(err.message || "Chargement impossible");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (isAuthed) void load();
    else { setPosts([]); setFollowedCount(0); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed]);

  async function checkNow() {
    setChecking(true);
    setCheckMsg("");
    setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/influencer-monitor/run`, {
        method: "POST",
        headers: await authHeaders(),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Détection impossible");
      setCheckMsg("Détection lancée ✓ — compte ~30 s par influenceur suivi, puis clique « Rafraîchir ».");
    } catch (err: any) {
      setError(err.message || "Détection impossible");
    } finally {
      setChecking(false);
    }
  }

  // ALE-222 : « Garder dans ma bibliothèque » — remplace « Garder pour plus tard »
  // (posts de référence) + « Garder comme template » : une seule entrée avec le
  // texte, l'image et la structure extraite par l'IA (best-effort côté serveur).
  async function keepInLibrary(p: MonitoredPost) {
    if (!p.text) return;
    setSavingId(p.id);
    setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/post-templates`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({
          text: p.text,
          url: p.url || null,
          author: p.influencer_name || p.influencer_handle || null,
          image_url: firstImage(p),
          note: "Repéré via la veille",
          source: "influencer",
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Enregistrement impossible");
      setSavedIds((prev) => ({ ...prev, [p.id]: true }));
    } catch (err: any) {
      setError(err.message || "Enregistrement impossible");
    } finally {
      setSavingId(null);
    }
  }

  function inspire(p: MonitoredPost) {
    const who = p.influencer_name || p.influencer_handle || "un influenceur suivi";
    onInspire(
      `Inspire-toi de ce post de ${who} — reprends l'angle, la structure ou le fond, mais réécris-le entièrement pour moi :\n\n« ${(p.text || "").slice(0, 1200)} »`
    );
  }

  const fmtFeedDate = (s?: string | null) => {
    if (!s) return "";
    try { return new Date(s).toLocaleDateString("fr-FR", { day: "numeric", month: "short" }); }
    catch { return ""; }
  };
  const isNew = (p: MonitoredPost) => {
    if (!p.detected_by_monitor || !p.first_seen_at) return false;
    try { return Date.now() - new Date(p.first_seen_at).getTime() < 7 * 24 * 3600 * 1000; }
    catch { return false; }
  };
  const firstImage = (p: MonitoredPost) =>
    (p.media_items || []).find((m) => m?.type === "image" && m?.url)?.url || null;

  if (!isAuthed) {
    return (
      <div className="card" style={{ textAlign: "center", padding: 40 }}>
        <Lock size={28} style={{ opacity: 0.4, marginBottom: 12 }} />
        <h2 style={{ margin: "0 0 8px" }}>Monitoring d&apos;influenceurs</h2>
        <p style={{ color: "var(--muted)", marginBottom: 16 }}>
          Connecte-toi pour surveiller les nouveaux posts de tes influenceurs et t&apos;en inspirer.
        </p>
        <button type="button" className="primary-button" onClick={() => requireAuth("Crée un compte gratuit pour activer la veille.")}>
          <Sparkles size={14} /> Créer un compte gratuit
        </button>
      </div>
    );
  }

  return (
    <LibDrawer
      icon={<Eye size={20} />}
      title={`Veille des influenceurs suivis${posts.length ? ` (${posts.length})` : ""}`}
      desc="Les derniers posts de tes influenceurs suivis — inspire-t'en en un clic, ou garde-les pour plus tard."
      open={open}
      onToggle={() => setOpen((v) => !v)}
    >
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        <button type="button" className="secondary-button" style={{ fontSize: 13 }} disabled={loading} onClick={() => void load()}>
          {loading ? <Loader2 size={14} className="spinning" /> : <RefreshCw size={14} />} Rafraîchir
        </button>
        {followedCount > 0 && (
          <button
            type="button"
            className="primary-button"
            style={{ fontSize: 13 }}
            disabled={checking}
            title="Scrape les derniers posts de tes influenceurs suivis et enregistre les nouveaux"
            onClick={checkNow}
          >
            {checking ? <Loader2 size={14} className="spinning" /> : <Zap size={14} />} Vérifier les nouveaux posts
          </button>
        )}
      </div>

      {checkMsg && <div className="card" style={{ marginBottom: 12, padding: "10px 14px", fontSize: 13, color: "var(--muted)" }}>{checkMsg}</div>}
      {error && <div className="error" style={{ marginBottom: 12 }}>{error}</div>}

      {followedCount === 0 ? (
        <div className="card" style={{ textAlign: "center", padding: 32 }}>
          <Eye size={24} style={{ opacity: 0.35, marginBottom: 8 }} />
          <p style={{ margin: 0, color: "var(--muted)" }}>
            Tu ne suis encore aucun influenceur. Va dans « Mes influenceurs » et clique « Suivre » (jusqu&apos;à 5) pour activer la veille.
          </p>
        </div>
      ) : loading && posts.length === 0 ? (
        <div className="sk-list" aria-hidden style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
          {Array.from({ length: 3 }).map((_, i) => (
            <div className="card" key={i} style={{ flex: "1 1 220px", display: "grid", gap: 8, padding: 12 }}>
              <Sk h={14} w={120} r={6} />
              <Sk h={90} w="100%" r={6} />
              <Sk h={10} w="94%" />
              <Sk h={10} w="70%" />
            </div>
          ))}
        </div>
      ) : posts.length === 0 ? (
        <div className="card" style={{ textAlign: "center", padding: 32 }}>
          <p style={{ margin: 0, color: "var(--muted)" }}>
            Aucun post récent en stock pour tes influenceurs suivis. Clique « Vérifier les nouveaux posts », attends ~30 s par influenceur, puis « Rafraîchir ».
          </p>
        </div>
      ) : (
        <>
          {/* Aperçu compact : 3 posts côte à côte, « Voir tout » déroule le reste. */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
            {(showAll ? posts : posts.slice(0, 3)).map((p) => {
              const img = firstImage(p);
              const text = p.text || "";
              const preview = text.length > 160 ? `${text.slice(0, 160)}…` : text;
              return (
                <div key={p.id} className="card" style={{ flex: "1 1 220px", minWidth: 0, display: "flex", flexDirection: "column", gap: 8, padding: 12 }}>
                  <div style={{ display: "flex", gap: 6, alignItems: "baseline", flexWrap: "wrap" }}>
                    <strong style={{ fontSize: 13 }}>{p.influencer_name || p.influencer_handle}</strong>
                    <span style={{ fontSize: 11, color: "var(--muted)" }}>{fmtFeedDate(p.posted_at)}</span>
                    {isNew(p) && <span className="daily-seed-tag" style={{ background: "var(--primary)", color: "#fff" }}>Nouveau</span>}
                  </div>
                  <span style={{ fontSize: 11, color: "var(--muted)" }}>👍 {fmt(p.likes)} · 💬 {fmt(p.comments)} · 🔁 {fmt(p.reposts)}</span>
                  {img && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={img} alt="" style={{ width: "100%", height: 90, objectFit: "cover", borderRadius: 6 }} />
                  )}
                  <p style={{ margin: 0, fontSize: 13, whiteSpace: "pre-wrap", color: "var(--muted)" }}>{preview}</p>
                  <div style={{ display: "flex", gap: 6, marginTop: "auto", flexWrap: "wrap", alignItems: "center" }}>
                    <button
                      type="button"
                      className="primary-button"
                      style={{ fontSize: 12, minHeight: 30, padding: "0 10px" }}
                      title="Génère un post pour toi sur le même angle, réécrit selon ton profil"
                      onClick={() => inspire(p)}
                    >
                      <Sparkles size={12} /> M&apos;en inspirer
                    </button>
                    <button
                      type="button"
                      className="secondary-button"
                      style={{ fontSize: 12, minHeight: 30, padding: "0 10px" }}
                      disabled={savingId === p.id || !!savedIds[p.id]}
                      title="Garde ce post (texte, image, structure extraite par l'IA) dans ta bibliothèque"
                      onClick={() => void keepInLibrary(p)}
                    >
                      {savingId === p.id
                        ? <Loader2 size={12} className="spinning" />
                        : savedIds[p.id] ? <CheckCircle2 size={12} /> : <BookmarkPlus size={12} />}
                      {savedIds[p.id] ? " Gardé ✓" : savingId === p.id ? " …" : " Garder"}
                    </button>
                    {safeHttpUrl(p.url) && (
                      <a href={safeHttpUrl(p.url)} target="_blank" rel="noopener noreferrer" style={{ fontSize: 11, color: "var(--muted)" }} title="Voir sur LinkedIn">
                        ↗
                      </a>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          {posts.length > 3 && (
            <button type="button" className="link-button" style={{ marginTop: 12, fontSize: 13 }} onClick={() => setShowAll((v) => !v)}>
              {showAll ? "Voir moins" : `Voir tout (${posts.length})`}
            </button>
          )}
        </>
      )}
    </LibDrawer>
  );
}

/**
 * Vue « Analyser » fusionnée : barre de sous-onglets qui regroupe l'ancien
 * onglet Analyser (séries) et Mes influenceurs. L'ancien Dashboard global (ALE-132)
 * est remplacé par le bloc « Tendances de ta veille » rendu par InfluencersView.
 */
/** ALE-257 : page « Analyses » LinkedIn — tout empilé sur une seule page qui défile
 *  (lancement → tiroir séries → classement « Mes influenceurs » → tendances →
 *  monitoring). Remplace l'ancien AnalyzeHub à sous-onglets. */
function LinkedInAnalysesView({
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
  return (
    <div>
      {/* 1. Lancement d'une série */}
      <JobsView
        part="launch"
        jobs={jobs}
        loading={jobsLoading}
        isAuthed={isAuthed}
        onCreated={onJobCreated}
        onJobUpdated={onJobUpdated}
        onOpenReport={onOpenReport}
        requireAuth={requireAuth}
      />
      {/* 2. Séries d'analyse (logs) — dans un tiroir replié par défaut */}
      {isAuthed && (
        <SeriesDrawer jobs={jobs} platform="linkedin">
          <JobsView
            part="series"
            jobs={jobs}
            loading={jobsLoading}
            isAuthed={isAuthed}
            onCreated={onJobCreated}
            onJobUpdated={onJobUpdated}
            onOpenReport={onOpenReport}
            requireAuth={requireAuth}
          />
        </SeriesDrawer>
      )}
      {/* 3. Mes influenceurs (classement) + 4. Tendances (rendus dans cet ordre par InfluencersView).
          Le fil « Nouveaux posts » (MonitoringFeedView) a été déplacé dans Ma bibliothèque. */}
      <div style={{ marginTop: 8 }}>
        <InfluencersView
          entries={influencers}
          loading={influencersLoading}
          isAuthed={isAuthed}
          requireAuth={requireAuth}
          onOpenReport={onOpenLibraryReport}
        />
      </div>
    </div>
  );
}

/** ALE-257 : page « Analyses » Instagram — lancement + tiroir séries uniquement
 *  (pas de classement / tendances / monitoring : features LinkedIn only). */
function InstagramAnalysesView({
  jobs,
  jobsLoading,
  onJobCreated,
  onJobUpdated,
  onOpenReport,
  isAuthed,
  requireAuth,
}: {
  jobs: Job[];
  jobsLoading: boolean;
  onJobCreated: (job: Job) => void;
  onJobUpdated: (job: Job) => void;
  onOpenReport: (markdown: string, name: string) => void;
  isAuthed: boolean;
  requireAuth: (reason?: string, mode?: AuthMode) => void;
}) {
  return (
    <div>
      <InstagramAnalyzeHub
        part="launch"
        jobs={jobs}
        loading={jobsLoading}
        isAuthed={isAuthed}
        onCreated={onJobCreated}
        onJobUpdated={onJobUpdated}
        onOpenReport={onOpenReport}
        requireAuth={requireAuth}
      />
      {isAuthed && (
        <SeriesDrawer jobs={jobs} platform="instagram">
          <InstagramAnalyzeHub
            part="series"
            jobs={jobs}
            loading={jobsLoading}
            isAuthed={isAuthed}
            onCreated={onJobCreated}
            onJobUpdated={onJobUpdated}
            onOpenReport={onOpenReport}
            requireAuth={requireAuth}
          />
        </SeriesDrawer>
      )}
    </div>
  );
}

/** Onglet « Contenu » : regroupe Idée du jour, Générateur et Mes contenus en sous-onglets. */
/** ALE-222 : « Ma bibliothèque » — fusion posts de référence (ALE-67) + templates (ALE-216).
 *  Une entrée peut porter un texte de post (inspiration à la génération), une
 *  structure (template sélectionnable au Générateur) et/ou une image (référence
 *  visuelle pour l'image IA). */
type PostTemplate = {
  id: string;
  structure_label?: string | null;
  structure_text?: string | null;
  post_text?: string | null;
  note?: string | null;
  format?: string | null;
  image_url?: string | null;
  image_note?: string | null;
  source?: string | null;
  source_author?: string | null;
  source_post_url?: string | null;
  created_at?: string;
};

// ALE-234 : source de prospection rattachée à une entrée de bibliothèque (même post).
type LibraryLeadSource = {
  id: string;
  post_url: string;
  is_lead_magnet?: boolean;
  trigger_keyword?: string | null;
  collected_at?: string | null;
  comments_count?: number | null;
};

function libraryEntryTitle(t: PostTemplate): string {
  if (t.structure_label) return t.structure_label;
  if (t.source_author) return t.source_author;
  const text = (t.post_text || "").trim();
  return text.length > 60 ? `${text.slice(0, 60)}…` : text || "Entrée";
}

function MyLibraryView({
  isAuthed,
  requireAuth,
}: {
  isAuthed: boolean;
  requireAuth: (reason?: string, mode?: AuthMode) => void;
}) {
  // ALE-223 : rendu en tiroir repliable au sein de l'onglet « Ma bibliothèque ».
  const [open, setOpen] = useState(true); // ALE-231 : ouvert par défaut (import rapide en haut)
  const [entries, setEntries] = useState<PostTemplate[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [note, setNote] = useState("");
  const [label, setLabel] = useState("");
  const [structure, setStructure] = useState("");
  const [imageNote, setImageNote] = useState("");
  const [imageUrl, setImageUrl] = useState("");
  const [adding, setAdding] = useState(false);
  // ALE-233 : déplier un post tronqué pour voir le texte complet (chaque post = template).
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  // ALE-234 : sources de prospection croisées avec la bibliothèque par URL de post.
  const [leadSources, setLeadSources] = useState<Record<string, LibraryLeadSource>>({});
  const [collectingId, setCollectingId] = useState<string | null>(null);
  const [collectMsg, setCollectMsg] = useState("");

  async function load() {
    if (!isAuthed) return;
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/post-templates`, { headers: await authHeaders() });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Chargement de la bibliothèque impossible");
      setEntries(Array.isArray(data) ? data : []);
    } catch (err: any) {
      setError(err.message || "Chargement impossible");
    } finally {
      setLoading(false);
    }
    // Best-effort : sans les sources, la bibliothèque reste pleinement utilisable.
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/lead-sources`, { headers: await authHeaders() });
      if (res.ok) {
        const data = await res.json();
        const map: Record<string, LibraryLeadSource> = {};
        for (const s of data.sources || []) {
          if (s.is_lead_magnet && s.post_url) map[s.post_url] = s;
        }
        setLeadSources(map);
      }
    } catch { /* pastilles indisponibles, tant pis */ }
  }

  async function collectCommenters(source: LibraryLeadSource) {
    if (collectingId) return;
    setCollectingId(source.id);
    setError("");
    setCollectMsg("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/lead-sources/${source.id}/collect`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({}),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Collecte impossible");
      setLeadSources((prev) => ({ ...prev, [source.post_url]: { ...source, ...data.source } }));
      const counts = data.leads || {};
      const fresh = counts.inserted ?? 0;
      const enriched = counts.updated ?? 0;
      setCollectMsg(
        `${data.comments_count} commentaire(s) analysé(s) — ${fresh} nouveau(x) lead(s)` +
          (enriched ? `, ${enriched} enrichi(s)` : "") +
          ". Retrouve-les dans l'onglet Prospection."
      );
    } catch (err: any) {
      setError(err.message || "Collecte impossible");
    } finally {
      setCollectingId(null);
    }
  }

  useEffect(() => {
    if (isAuthed) void load();
    else setEntries([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed]);

  // Miroir de la matrice serveur : lien valide OU texte ≥ 10 OU structure ≥ 10.
  const urlOk = /^https?:\/\//i.test(url.trim());
  const canAdd = urlOk || text.trim().length >= 10 || structure.trim().length >= 10;

  async function addEntry() {
    if (!canAdd || adding) return;
    setAdding(true);
    setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/post-templates`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({
          url: url.trim() || null,
          text: text.trim() || null,
          note: note.trim() || null,
          structure_label: label.trim() || null,
          structure_text: structure.trim() || null,
          image_note: imageNote.trim() || null,
          image_url: imageUrl.trim() || null,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Ajout impossible");
      setEntries((prev) => [data, ...prev]);
      // ALE-234 : l'import par lien peut détecter un lead magnet → pastille immédiate.
      if (data.lead_magnet && data.source_post_url) {
        setLeadSources((prev) => ({
          ...prev,
          [data.source_post_url]: {
            id: data.lead_magnet.source_id,
            post_url: data.source_post_url,
            is_lead_magnet: true,
            trigger_keyword: data.lead_magnet.trigger_keyword,
            collected_at: data.lead_magnet.collected_at,
            comments_count: data.lead_magnet.comments_count,
          },
        }));
      }
      setUrl(""); setText(""); setNote(""); setLabel(""); setStructure(""); setImageNote(""); setImageUrl("");
    } catch (err: any) {
      setError(err.message || "Ajout impossible");
    } finally {
      setAdding(false);
    }
  }

  async function deleteEntry(id: string) {
    setEntries((prev) => prev.filter((t) => t.id !== id));
    try {
      await fetch(`${DIRECT_API_URL}/me/post-templates/${id}`, { method: "DELETE", headers: await authHeaders() });
    } catch { void load(); }
  }

  if (!isAuthed) {
    return (
      <div className="card" style={{ textAlign: "center", padding: 40 }}>
        <Lock size={28} style={{ opacity: 0.4, marginBottom: 12 }} />
        <h2 style={{ margin: "0 0 8px" }}>Ma bibliothèque</h2>
        <p style={{ color: "var(--muted)", marginBottom: 16 }}>
          Connecte-toi pour garder les posts qui t&apos;ont plu et tes structures préférées — l&apos;IA s&apos;en inspire à la génération.
        </p>
        <button type="button" className="primary-button" onClick={() => requireAuth("Crée un compte gratuit pour ta bibliothèque.")}>
          <Sparkles size={14} /> Créer un compte gratuit
        </button>
      </div>
    );
  }

  return (
    <LibDrawer
      icon={<ListChecks size={20} />}
      title={`Posts de référence & templates${entries.length ? ` (${entries.length})` : ""}`}
      desc="Garde ici tout ce qui te sert de référence : des posts qui t'ont plu et des structures qui marchent. L'IA s'en inspire à la génération (toujours réécrits, jamais copiés), les structures deviennent des templates dans le Générateur, et les images servent de référence visuelle."
      open={open}
      onToggle={() => setOpen((v) => !v)}
    >
      <div className="card daily-reservoir">
        <h3 className="daily-subtitle" style={{ margin: 0 }}><PlusCircle size={16} /> Ajouter à ma bibliothèque</h3>
        <div className="ref-add" style={{ marginTop: 12, display: "grid", gap: 8 }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void addEntry(); } }}
              placeholder="Colle le lien du post LinkedIn — texte, auteur, image et structure importés automatiquement"
              maxLength={2000}
              style={{ flex: "1 1 320px" }}
            />
            <button className="primary-button" onClick={addEntry} disabled={adding || !canAdd}>
              {adding ? <Loader2 size={14} className="spinning" /> : <PlusCircle size={14} />} Ajouter à ma bibliothèque
            </button>
          </div>
          <details>
            <summary style={{ cursor: "pointer", fontSize: 13, color: "var(--muted)" }}>Plus d&apos;options — texte collé, structure à la main, image</summary>
            <div style={{ marginTop: 10, display: "grid", gap: 8 }}>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Ou colle le texte du post directement (si tu n'as pas le lien)"
                maxLength={6000}
                rows={4}
              />
              <input
                type="text"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Pourquoi il te plaît ? (optionnel — guide l'IA)"
                maxLength={500}
              />
              <input
                type="text"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="Nom de la structure (optionnel) — ex. « Accroche choc + 3 bullets + CTA »"
                maxLength={200}
              />
              <textarea
                value={structure}
                onChange={(e) => setStructure(e.target.value)}
                placeholder={"Structure à la main (optionnel), ligne par ligne — ex. :\n1. Accroche en une phrase choc\n2. 3 bullets avec un chiffre chacun\n3. Question finale pour faire commenter"}
                maxLength={4000}
                rows={4}
              />
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <input
                  type="text"
                  value={imageNote}
                  onChange={(e) => setImageNote(e.target.value)}
                  placeholder="Type d'image (optionnel) — ex. « juste deux logos côte à côte »"
                  maxLength={500}
                  style={{ flex: "2 1 220px" }}
                />
                <input
                  type="text"
                  value={imageUrl}
                  onChange={(e) => setImageUrl(e.target.value)}
                  placeholder="Lien d'une image d'exemple (optionnel)"
                  maxLength={2000}
                  style={{ flex: "1 1 180px" }}
                />
              </div>
            </div>
          </details>
        </div>
        {error && <div className="error" style={{ marginTop: 8 }}>{error}</div>}
        {collectMsg && (
          <div style={{ marginTop: 8, fontSize: 13, color: "var(--success)" }}>✓ {collectMsg}</div>
        )}
      </div>

      <div style={{ marginTop: 16, display: "grid", gap: 12 }}>
        {loading && entries.length === 0 ? (
          <div className="sk-list" aria-hidden style={{ display: "grid", gap: 12 }}>
            {Array.from({ length: 3 }).map((_, i) => (
              <div className="card" key={i} style={{ display: "grid", gap: 8 }}>
                <div style={{ display: "flex", gap: 8 }}>
                  <Sk h={14} w={160} r={6} />
                  <Sk h={14} w={54} r={6} />
                </div>
                <Sk h={10} w="92%" />
                <Sk h={10} w="78%" />
              </div>
            ))}
          </div>
        ) : entries.length === 0 ? (
          <div className="card" style={{ textAlign: "center", padding: 24 }}>
            <p style={{ margin: 0, color: "var(--muted)" }}>
              Ta bibliothèque est vide — colle le lien d&apos;un post qui t&apos;a plu ci-dessus, tu le retrouveras
              comme inspiration et comme template dans le Générateur.
            </p>
          </div>
        ) : (
          entries.map((t) => {
            const postText = (t.post_text || "").trim();
            const structureText = (t.structure_text || "").trim();
            const leadSource = t.source_post_url ? leadSources[t.source_post_url] : undefined;
            return (
              <div key={t.id} className="card" style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
                    <strong>{libraryEntryTitle(t)}</strong>
                    {postText && <span className="daily-seed-tag">texte</span>}
                    {structureText && <span className="daily-seed-tag">structure</span>}
                    {t.image_url && <span className="daily-seed-tag">image</span>}
                    {t.source === "influencer" && (
                      <span className="daily-seed-tag">depuis la veille{t.source_author ? ` · ${t.source_author}` : ""}</span>
                    )}
                    {leadSource && (
                      <span
                        className="daily-seed-tag"
                        style={{ color: "var(--success)", fontWeight: 600 }}
                        title="Ce post demande de commenter un mot-clé pour recevoir une ressource — ses commentateurs sont des prospects chauds"
                      >
                        🎯 lead magnet{leadSource.trigger_keyword ? ` · « ${leadSource.trigger_keyword} »` : ""}
                      </span>
                    )}
                  </div>
                  {postText && (
                    <>
                      <p style={{ margin: "6px 0 0", whiteSpace: "pre-wrap", fontSize: 13, color: "var(--muted)" }}>
                        {expanded[t.id] || postText.length <= 300 ? postText : `${postText.slice(0, 300)}…`}
                      </p>
                      {postText.length > 300 && (
                        <button
                          type="button"
                          className="link-button"
                          style={{ fontSize: 12, marginTop: 4 }}
                          onClick={() => setExpanded((prev) => ({ ...prev, [t.id]: !prev[t.id] }))}
                        >
                          {expanded[t.id] ? "Voir moins" : "Voir le post complet"}
                        </button>
                      )}
                    </>
                  )}
                  {structureText && (
                    <p style={{ margin: "6px 0 0", whiteSpace: "pre-wrap", fontSize: 13, color: "var(--muted)" }}>
                      <ListChecks size={12} style={{ verticalAlign: "-2px" }} />{" "}
                      {structureText.length > 400 ? `${structureText.slice(0, 400)}…` : structureText}
                    </p>
                  )}
                  {t.note && (
                    <p style={{ margin: "6px 0 0", fontSize: 12, color: "var(--muted)" }}>↳ pourquoi : {t.note}</p>
                  )}
                  {t.image_note && (
                    <p style={{ margin: "6px 0 0", fontSize: 12, color: "var(--muted)" }}>
                      <ImageIcon size={12} style={{ verticalAlign: "-2px" }} /> Image : {t.image_note}
                    </p>
                  )}
                  {(t.source_author || t.source_post_url) && !t.structure_label && (
                    <p style={{ margin: "6px 0 0", fontSize: 12, color: "var(--muted)" }}>
                      {safeHttpUrl(t.source_post_url) ? (
                        <a href={safeHttpUrl(t.source_post_url)} target="_blank" rel="noreferrer">voir le post</a>
                      ) : null}
                    </p>
                  )}
                  {/* ALE-233 : ce post est directement sélectionnable comme template dans le
                      Générateur (menu « Template ») — plus de bouton d'extraction ni de
                      « Générer un post inspiré » (chemin redondant). Seule action restante :
                      la collecte de commentateurs quand le post est un lead magnet. */}
                  {leadSource && (
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
                      <button
                        className="secondary-button"
                        style={{ fontSize: 12, minHeight: 28, padding: "0 10px" }}
                        title="Récupère les personnes qui ont commenté ce post — elles deviennent des leads dans l'onglet Prospection"
                        onClick={() => collectCommenters(leadSource)}
                        disabled={collectingId === leadSource.id}
                      >
                        {collectingId === leadSource.id ? <Loader2 size={12} className="spinning" /> : <Users size={12} />}{" "}
                        {leadSource.collected_at
                          ? `Mettre à jour les commentateurs (${leadSource.comments_count ?? 0} récupérés)`
                          : "Récupérer les commentateurs"}
                      </button>
                    </div>
                  )}
                </div>
                {t.image_url && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={t.image_url} alt="" style={{ width: 90, maxHeight: 90, objectFit: "cover", borderRadius: 8, flex: "0 0 auto" }} />
                )}
                <button className="icon-button" title="Supprimer" onClick={() => deleteEntry(t.id)}><Trash2 size={14} /></button>
              </div>
            );
          })
        )}
      </div>
    </LibDrawer>
  );
}

// ─── ALE-229 : onglet Prospection — liste des leads + panneau latéral de détail ───
// V1 volontairement sans import (l'alimentation vient de la veille ALE-227 et de
// Ma bibliothèque ALE-234). Le ciblage ICP + score (ALE-228) sont ici ; l'envoi
// du premier message reste à venir (ALE-230).

type LeadSignal = {
  source_id?: string | null;
  post_url?: string | null;
  author?: string | null;
  trigger_keyword?: string | null;
  comment_text?: string | null;
  commented_at?: string | null;
};

type Lead = {
  id: string;
  profile_url: string;
  name?: string | null;
  headline?: string | null;
  comment_text?: string | null;
  commented_at?: string | null;
  reaction_count?: number | null;
  signals?: LeadSignal[];
  signal_count?: number;
  status?: string;
  created_at?: string;
  score?: number | null;
  score_reason?: string | null;
  // ALE-230 : état d'outreach LinkedIn (envoi via Unipile).
  outreach_status?: string | null;   // none | invite_sent | connected | messaged
  provider_id?: string | null;
  outreach_chat_id?: string | null;
  // ALE-243 : curation manuelle — 'to_contact' (défaut) | 'skip' (écarté).
  contact_status?: string | null;
  skip_reason?: string | null;
};

/** Libellé court de l'état d'outreach d'un lead (badge de liste). */
function outreachLabel(s?: string | null): string | null {
  switch (s) {
    case "invite_sent": return "Invité";
    case "connected": return "En relation";
    case "messaged": return "Contacté";
    default: return null;
  }
}

type LeadTargeting = {
  ideal_client?: string | null;
  offer?: string | null;
  interest_keywords?: string[] | null;
  score_threshold?: number | null;
  first_message_instructions?: string | null;
};

/** Couleur d'une pastille de score ICP : vert (fort) / ambre (moyen) / gris (faible). */
function scoreColor(score: number): string {
  if (score >= 70) return "var(--success)";
  if (score >= 40) return "var(--warning, #b8860b)";
  return "var(--muted)";
}

function leadInitials(l: Lead): string {
  const parts = (l.name || "").trim().split(/\s+/).filter(Boolean);
  const ini = ((parts[0]?.[0] || "") + (parts[1]?.[0] || "")).toUpperCase();
  return ini || "?";
}

function leadDate(iso?: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
  } catch {
    return "";
  }
}

/** Dernier signal d'un lead (le plus récent ajouté) — porte mot-clé, auteur source et commentaire. */
function leadLastSignal(l: Lead): LeadSignal {
  if (l.signals && l.signals.length) return l.signals[l.signals.length - 1];
  return { comment_text: l.comment_text, commented_at: l.commented_at };
}

/** Les URLs de leads viennent du scraping (non fiables) : on ne rend que http(s). */
function safeHttpUrl(u?: string | null): string | undefined {
  if (!u) return undefined;
  try {
    const parsed = new URL(u);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.toString() : undefined;
  } catch {
    return undefined;
  }
}

function ProspectingView({
  isAuthed,
  requireAuth,
  onNavigateInbox,
}: {
  isAuthed: boolean;
  requireAuth: (reason?: string, mode?: AuthMode) => void;
  onNavigateInbox: (chatId?: string) => void;
}) {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Lead | null>(null);
  // Ciblage ICP (ALE-228)
  const [targeting, setTargeting] = useState<LeadTargeting | null>(null);
  const [targetingLoading, setTargetingLoading] = useState(true); // ALE-247 : réserve l'espace, évite le pop-in
  const [targetOpen, setTargetOpen] = useState(false);
  const [savingTarget, setSavingTarget] = useState(false);
  const [targetMsg, setTargetMsg] = useState("");
  // Envoi via Unipile (ALE-230)
  const outreach = useLinkedInOutreach(isAuthed);
  const lnConnected = !!outreach.status?.connected;
  const quota = outreach.status?.quota;
  const [outreachBusy, setOutreachBusy] = useState(false);
  const [genBusy, setGenBusy] = useState(false);
  const [outreachMsg, setOutreachMsg] = useState("");
  const [composeOpen, setComposeOpen] = useState(false);
  const [messageText, setMessageText] = useState("");
  const [skipReason, setSkipReason] = useState(""); // ALE-243 : raison « ne pas contacter »

  // Réinitialise le bloc d'envoi quand on change de lead sélectionné.
  useEffect(() => {
    setComposeOpen(false);
    setMessageText("");
    setOutreachMsg("");
    setSkipReason(selected?.skip_reason || "");
  }, [selected?.id]);

  // Applique le lead mis à jour renvoyé par le serveur (liste + panneau).
  const patchLead = (updated: Lead) => {
    setLeads((prev) => prev.map((l) => (l.id === updated.id ? { ...l, ...updated } : l)));
    setSelected((prev) => (prev && prev.id === updated.id ? { ...prev, ...updated } : prev));
  };
  const applyQuota = (quota?: OutreachQuota) => {
    if (quota) outreach.setStatus((prev) => (prev ? { ...prev, quota } : prev));
  };
  const applyEngine = (engine?: OutreachEngine | null) => {
    if (engine) outreach.setStatus((prev) => (prev ? { ...prev, engine } : prev));
  };

  // ALE-174 — actions déjà en file, par lead et par type (« Invitation en file »).
  const queuedByLead = new Map<string, OutreachQueueItem>();
  for (const item of outreach.queue) queuedByLead.set(`${item.lead_id}:${item.action_type}`, item);
  const queuedInvite = (lead: Lead) => queuedByLead.get(`${lead.id}:invite`);
  const queuedMessage = (lead: Lead) => queuedByLead.get(`${lead.id}:message`);

  useEffect(() => { void outreach.reloadQueue(); }, [outreach.reloadQueue]);

  // ALE-243 : curation manuelle — marque « ne pas contacter » / remet en liste.
  async function setContactStatus(lead: Lead, contact_status: "to_contact" | "skip", reason?: string) {
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/leads/${lead.id}`, {
        method: "PATCH",
        headers: { ...(await authHeaders()), "Content-Type": "application/json" },
        body: JSON.stringify({ contact_status, skip_reason: reason ?? null }),
      });
      const data = await res.json();
      if (res.ok && data.lead) patchLead(data.lead);
    } catch { /* non bloquant */ }
  }

  // ALE-174 — par défaut, l'invitation entre en FILE : c'est le moteur qui choisit
  // le créneau (plage horaire, délai variable, palier de mise en route). `immediate`
  // = la soupape, pour le cas « je sors d'une visio avec cette personne ».
  async function inviteLead(lead: Lead, immediate = false) {
    setOutreachBusy(true); setOutreachMsg("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/leads/${lead.id}/invite`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ immediate }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Envoi impossible");
      if (data.lead) patchLead(data.lead);
      applyQuota(data.quota);
      applyEngine(data.engine);
      if (data.queued) {
        await outreach.reloadQueue();
        setOutreachMsg(`En file — partira ${formatEta(data.scheduled_for)}.`);
      } else {
        setOutreachMsg(data.already_connected ? "Vous êtes déjà en relation — prêt pour un message." : "Demande de connexion envoyée ✓");
      }
    } catch (err: any) { setOutreachMsg(err.message); }
    finally { setOutreachBusy(false); }
  }

  async function cancelQueued(itemId: string) {
    setOutreachBusy(true);
    try {
      if (await outreach.cancelQueued(itemId)) setOutreachMsg("Action retirée de la file.");
    } finally { setOutreachBusy(false); }
  }

  async function checkConnection(lead: Lead) {
    setOutreachBusy(true); setOutreachMsg("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/leads/${lead.id}/check-connection`, { method: "POST", headers: await authHeaders() });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Vérification impossible");
      if (data.lead) patchLead(data.lead);
      setOutreachMsg(data.connected
        ? "Invitation acceptée ✓ Tu peux envoyer ton premier message."
        : "Pas encore acceptée — LinkedIn peut mettre un moment. Réessaie plus tard.");
    } catch (err: any) { setOutreachMsg(err.message); }
    finally { setOutreachBusy(false); }
  }

  async function generateMessage(lead: Lead) {
    setGenBusy(true); setOutreachMsg("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/leads/${lead.id}/message/preview`, { method: "POST", headers: await authHeaders() });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Génération impossible");
      setMessageText(data.message || "");
    } catch (err: any) { setOutreachMsg(err.message); }
    finally { setGenBusy(false); }
  }

  async function sendFirstMessage(lead: Lead, immediate = false) {
    if (!messageText.trim()) return;
    setOutreachBusy(true); setOutreachMsg("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/leads/${lead.id}/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ text: messageText.trim(), immediate }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Envoi impossible");
      if (data.lead) patchLead(data.lead);
      applyQuota(data.quota);
      applyEngine(data.engine);
      setComposeOpen(false); setMessageText("");
      if (data.queued) {
        await outreach.reloadQueue();
        setOutreachMsg(`Message en file — partira ${formatEta(data.scheduled_for)}.`);
      } else {
        setOutreachMsg("Premier message envoyé ✓ Retrouve la conversation dans l'Inbox › LinkedIn.");
      }
    } catch (err: any) { setOutreachMsg(err.message); }
    finally { setOutreachBusy(false); }
  }

  const loadLeads = async () => {
    const res = await fetch(`${DIRECT_API_URL}/me/leads`, { headers: await authHeaders() });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Chargement des leads impossible");
    return Array.isArray(data.leads) ? (data.leads as Lead[]) : [];
  };

  useEffect(() => {
    if (!isAuthed) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const rows = await loadLeads();
        if (!cancelled) setLeads(rows);
      } catch (err: any) {
        if (!cancelled) setError(err.message || "Chargement impossible");
      } finally {
        if (!cancelled) setLoading(false);
      }
      // Ciblage (best-effort, ne bloque pas la liste). ALE-247 : on trace le
      // chargement (skeleton pour réserver l'espace) et on pose un objet vide
      // si aucun ciblage n'est encore configuré → le bloc reste visible/à remplir.
      try {
        const res = await fetch(`${DIRECT_API_URL}/me/lead-targeting`, { headers: await authHeaders() });
        const data = await res.json();
        if (!cancelled) setTargeting(res.ok && data.targeting ? data.targeting : {});
      } catch {
        if (!cancelled) setTargeting({});
      } finally {
        if (!cancelled) setTargetingLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isAuthed]);

  const saveTargeting = async () => {
    if (!targeting) return;
    setSavingTarget(true);
    setTargetMsg("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/lead-targeting`, {
        method: "PUT",
        headers: { ...(await authHeaders()), "Content-Type": "application/json" },
        body: JSON.stringify({
          ideal_client: targeting.ideal_client || "",
          offer: targeting.offer || "",
          interest_keywords: targeting.interest_keywords || [],
          first_message_instructions: targeting.first_message_instructions || "",
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Enregistrement impossible");
      if (data.targeting) setTargeting(data.targeting);
      // Recalcule les scores puis recharge la liste (le classement change).
      setTargetMsg("Ciblage enregistré, recalcul des scores…");
      try {
        await fetch(`${DIRECT_API_URL}/me/leads/rescore`, {
          method: "POST",
          headers: await authHeaders(),
        });
        setLeads(await loadLeads());
      } catch {
        /* le rescore peut échouer (ex. aucun lead) sans invalider la sauvegarde */
      }
      setTargetMsg("Ciblage enregistré ✓ Les leads sont reclassés par pertinence.");
    } catch (err: any) {
      setTargetMsg(err.message || "Enregistrement impossible");
    } finally {
      setSavingTarget(false);
    }
  };

  useEffect(() => {
    if (!selected) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSelected(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected]);

  if (!isAuthed) {
    return (
      <div className="card" style={{ textAlign: "center", padding: 40 }}>
        <Lock size={28} style={{ opacity: 0.4, marginBottom: 12 }} />
        <h2 style={{ margin: "0 0 8px" }}>Prospection</h2>
        <p style={{ color: "var(--muted)", marginBottom: 16 }}>
          Connecte-toi pour retrouver les personnes qui commentent les posts lead-magnet de tes concurrents.
        </p>
        <button type="button" className="primary-button" onClick={() => requireAuth("Crée un compte gratuit pour débloquer la prospection.")}>
          <Sparkles size={14} /> Créer un compte gratuit
        </button>
      </div>
    );
  }

  return (
    <div>
      <h2 className="section-title"><Target size={20} /> Prospection</h2>
      <p style={{ color: "var(--muted)", margin: "0 0 16px", fontSize: 14, maxWidth: 640 }}>
        Les personnes qui viennent de commenter les posts lead-magnet de tes concurrents — le signal
        d&apos;intention le plus chaud de LinkedIn. Clique une ligne pour le détail.
      </p>

      {/* ALE-228 : ciblage ICP — note chaque lead vs le client idéal. ALE-247 : skeleton au chargement pour éviter le pop-in. */}
      {targetingLoading ? (
        <div className="card sk-list" style={{ marginBottom: 16, padding: "12px 16px", display: "flex", alignItems: "center", gap: 10 }}>
          <Sk circle w={16} h={16} />
          <Sk h={12} w="30%" r={6} />
          <Sk h={10} w="42%" style={{ marginLeft: 4 }} />
        </div>
      ) : targeting && (
        <div className="card" style={{ marginBottom: 16, padding: 0, overflow: "hidden" }}>
          <button
            type="button"
            onClick={() => setTargetOpen((o) => !o)}
            style={{
              display: "flex", alignItems: "center", gap: 8, width: "100%", textAlign: "left",
              padding: "12px 16px", background: "none", border: "none", cursor: "pointer",
              font: "inherit", color: "inherit",
            }}
          >
            <ChevronRight size={18} style={{ flexShrink: 0, transform: targetOpen ? "rotate(90deg)" : "none", transition: "transform 0.15s" }} />
            <Target size={16} style={{ flexShrink: 0 }} />
            <strong>Mon ciblage</strong>
            <span style={{ color: "var(--muted)", fontWeight: 400, fontSize: 12.5, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              — chaque lead est noté selon ton client idéal
            </span>
          </button>
          {targetOpen && (
            <div style={{ padding: "0 16px 16px", display: "grid", gap: 12 }}>
              <label style={{ display: "grid", gap: 4, fontSize: 13, fontWeight: 600 }}>
                Ton client idéal
                <textarea
                  value={targeting.ideal_client || ""}
                  onChange={(e) => setTargeting({ ...targeting, ideal_client: e.target.value })}
                  placeholder="Ex. Dirigeants et responsables marketing de PME B2B (10-200 salariés)…"
                  rows={2}
                  style={{ width: "100%", padding: 8, fontSize: 13, fontWeight: 400, resize: "vertical" }}
                />
              </label>
              <label style={{ display: "grid", gap: 4, fontSize: 13, fontWeight: 600 }}>
                Ton offre
                <textarea
                  value={targeting.offer || ""}
                  onChange={(e) => setTargeting({ ...targeting, offer: e.target.value })}
                  placeholder="Ex. Accompagnement à la prospection LinkedIn automatisée…"
                  rows={2}
                  style={{ width: "100%", padding: 8, fontSize: 13, fontWeight: 400, resize: "vertical" }}
                />
              </label>
              <p style={{ margin: "-4px 0 0", fontSize: 12, color: "var(--muted)", fontWeight: 400 }}>
                Pré-remplis depuis ton profil éditorial ; les modifier ici ne change pas ton profil.
              </p>
              <label style={{ display: "grid", gap: 4, fontSize: 13, fontWeight: 600 }}>
                Thèmes qui trahissent un bon prospect (séparés par des virgules)
                <input
                  value={(targeting.interest_keywords || []).join(", ")}
                  onChange={(e) => setTargeting({ ...targeting, interest_keywords: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
                  placeholder="Ex. automatisation, IA, growth, closing"
                  style={{ width: "100%", padding: 8, fontSize: 13, fontWeight: 400 }}
                />
                <span style={{ fontSize: 12, color: "var(--muted)", fontWeight: 400 }}>
                  Les sujets qui indiquent un prospect intéressant — rien à voir avec le mot-clé
                  à commenter (« LEADS », « CLAUDE »…), lui est détecté automatiquement par post.
                </span>
              </label>
              <label style={{ display: "grid", gap: 4, fontSize: 13, fontWeight: 600 }}>
                Instructions du premier message
                <textarea
                  value={targeting.first_message_instructions || ""}
                  onChange={(e) => setTargeting({ ...targeting, first_message_instructions: e.target.value })}
                  placeholder="Ton, longueur, ce qu'il faut mentionner ou éviter, appel à l'action…"
                  rows={3}
                  style={{ width: "100%", padding: 8, fontSize: 13, fontWeight: 400, resize: "vertical" }}
                />
                <span style={{ fontSize: 12, color: "var(--muted)", fontWeight: 400 }}>
                  Serviront à rédiger le premier message quand l&apos;envoi sera disponible.
                </span>
              </label>
              <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                <button type="button" className="primary-button" onClick={saveTargeting} disabled={savingTarget}>
                  {savingTarget ? <Loader2 size={14} className="spinning" /> : <Target size={14} />}
                  {savingTarget ? "Enregistrement…" : "Enregistrer & recalculer les scores"}
                </button>
                {targetMsg && <span style={{ fontSize: 12.5, color: "var(--muted)" }}>{targetMsg}</span>}
              </div>
            </div>
          )}
        </div>
      )}

      {error && <div className="error" style={{ marginBottom: 12 }}>{error}</div>}
      {loading && leads.length === 0 ? (
        <div className="card" style={{ textAlign: "center", padding: 24 }}>
          <Loader2 size={20} className="spinning" style={{ opacity: 0.5 }} />
        </div>
      ) : leads.length === 0 ? (
        <div className="card" style={{ textAlign: "center", padding: 32 }}>
          <p style={{ margin: 0, color: "var(--muted)" }}>
            Aucun lead pour l&apos;instant. Ils arrivent automatiquement des posts lead-magnet détectés
            dans <strong>Contenu › Analyses</strong> et de ceux que tu importes dans <strong>Contenu › Ma bibliothèque</strong>
            {" "}(bouton « Récupérer les commentateurs »).
          </p>
        </div>
      ) : (
        // minmax(0, 1fr) : sans ça, la colonne `auto` du grid se dimensionne sur
        // le max-content (intitulés en nowrap) et déborde du <main> → l'ellipsis
        // ne se déclenche jamais. Le floor à 0 force les cartes à la largeur dispo.
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: 6 }}>
          {leads.map((l, i) => {
            const sig = leadLastSignal(l);
            const multi = (l.signal_count ?? 1) > 1;
            const skipped = l.contact_status === "skip";
            // ALE-243 : séparateur avant le 1er lead écarté (les écartés sont triés en bas par le backend).
            const showSkipDivider = skipped && i > 0 && leads[i - 1]?.contact_status !== "skip";
            return (
              <React.Fragment key={l.id}>
                {showSkipDivider && (
                  <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "10px 2px 2px", color: "var(--muted)", fontSize: 11, textTransform: "uppercase", letterSpacing: ".06em", fontWeight: 700 }}>
                    <span style={{ flex: 1, height: 1, background: "var(--border)" }} />
                    Écartés
                    <span style={{ flex: 1, height: 1, background: "var(--border)" }} />
                  </div>
                )}
              <div
                role="button"
                tabIndex={0}
                className="card"
                onClick={() => setSelected(l)}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSelected(l); } }}
                style={{
                  display: "flex", gap: 12, alignItems: "center", width: "100%", textAlign: "left",
                  cursor: "pointer", padding: "10px 14px", font: "inherit", color: "inherit",
                  opacity: skipped ? 0.6 : undefined,
                  border: selected?.id === l.id ? "1px solid var(--accent, #2e6bd6)" : undefined,
                }}
              >
                <span style={{ width: 34, height: 34, borderRadius: 99, background: "var(--surface-high)", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: 12, flexShrink: 0 }}>
                  {leadInitials(l)}
                </span>
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ display: "flex", gap: 8, alignItems: "baseline", minWidth: 0 }}>
                    <strong style={{ whiteSpace: "nowrap", flexShrink: 0 }}>{l.name || "Profil LinkedIn"}</strong>
                    {l.headline && (
                      <span style={{ flex: "1 1 auto", minWidth: 0, color: "var(--muted)", fontSize: 12.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {l.headline}
                      </span>
                    )}
                  </span>
                  <span style={{ display: "block", color: "var(--muted)", fontSize: 12, marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    a commenté{sig.trigger_keyword ? <> « <strong>{sig.trigger_keyword}</strong> »</> : null}
                    {sig.author ? ` chez ${sig.author}` : ""}
                    {leadDate(sig.commented_at) ? ` · ${leadDate(sig.commented_at)}` : ""}
                    {multi ? <strong style={{ color: "var(--success)" }}> · {l.signal_count} signaux</strong> : null}
                  </span>
                </span>
                {typeof l.score === "number" && (
                  <span
                    title={l.score_reason || "Score de pertinence vs ton client idéal"}
                    style={{
                      flexShrink: 0, fontSize: 12, fontWeight: 700, color: scoreColor(l.score),
                      border: `1px solid ${scoreColor(l.score)}`, borderRadius: 99, padding: "2px 8px",
                    }}
                  >
                    {l.score}
                  </span>
                )}
                {skipped ? (
                  <span className="daily-seed-tag" style={{ flexShrink: 0 }}>Écarté</span>
                ) : outreachLabel(l.outreach_status) ? (
                  <span className="daily-seed-tag" style={{ flexShrink: 0, color: l.outreach_status === "messaged" ? "var(--success)" : undefined }}>
                    {outreachLabel(l.outreach_status)}
                  </span>
                ) : l.status === "new" ? (
                  <span className="daily-seed-tag" style={{ flexShrink: 0 }}>Nouveau</span>
                ) : null}
                {/* ALE-245 : raccourcis d'action sur la ligne — stopPropagation pour ne pas ouvrir le volet.
                    ALE-174 : « Inviter » met en file (le moteur choisit le créneau) — donc plus de
                    blocage sur le quota ici : c'est à l'envoi que le plafond s'applique. */}
                {lnConnected && (!l.outreach_status || l.outreach_status === "none") && (
                  queuedInvite(l) ? (
                    <span className="daily-seed-tag" style={{ flexShrink: 0 }} title={`Partira ${formatEta(outreach.status?.engine?.next_send_estimate)}`}>
                      📮 En file
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="secondary-button"
                      style={{ flexShrink: 0, fontSize: 12, minHeight: 30, padding: "0 10px" }}
                      disabled={outreachBusy}
                      title="Mettre l'invitation en file — elle partira dans ta plage horaire, à un rythme humain."
                      onClick={(e) => { e.stopPropagation(); inviteLead(l); }}
                    >
                      <UserRound size={13} /> Inviter
                    </button>
                  )
                )}
                {lnConnected && (l.outreach_status === "connected" || l.outreach_status === "messaged") && (
                  <button
                    type="button"
                    className="secondary-button"
                    style={{ flexShrink: 0, fontSize: 12, minHeight: 30, padding: "0 10px" }}
                    title="Ouvrir la conversation dans l'Inbox"
                    onClick={(e) => { e.stopPropagation(); onNavigateInbox(l.outreach_chat_id || undefined); }}
                  >
                    <MessageSquare size={13} /> {l.outreach_status === "messaged" ? "Inbox" : "Message"}
                  </button>
                )}
              </div>
              </React.Fragment>
            );
          })}
        </div>
      )}
      {leads.length > 0 && (
        <p style={{ color: "var(--muted)", fontSize: 12, textAlign: "center", marginTop: 14 }}>
          {leads.length} lead(s) · classés par pertinence (score) — les moins pertinents restent en bas, rien n&apos;est masqué.
        </p>
      )}

      {/* Panneau latéral de détail */}
      {selected && (
        <>
          <div
            onClick={() => setSelected(null)}
            style={{ position: "fixed", inset: 0, background: "rgba(15,18,25,.35)", zIndex: 40 }}
          />
          <aside
            role="dialog"
            aria-modal="true"
            style={{
              position: "fixed", top: 0, right: 0, height: "100vh", width: 400, maxWidth: "92vw",
              background: "var(--surface)", borderLeft: "1px solid var(--border)", zIndex: 50,
              overflowY: "auto", padding: 20, display: "flex", flexDirection: "column", gap: 14,
            }}
          >
            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              <span style={{ width: 46, height: 46, borderRadius: 99, background: "var(--surface-high)", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: 15, flexShrink: 0 }}>
                {leadInitials(selected)}
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 700, fontSize: 16 }}>{selected.name || "Profil LinkedIn"}</div>
                {selected.headline && <div style={{ color: "var(--muted)", fontSize: 12.5 }}>{selected.headline}</div>}
              </div>
              <button className="icon-button" title="Fermer" onClick={() => setSelected(null)}><X size={16} /></button>
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
              {typeof selected.score === "number" && (
                <span
                  style={{
                    fontSize: 12, fontWeight: 700, color: scoreColor(selected.score),
                    border: `1px solid ${scoreColor(selected.score)}`, borderRadius: 99, padding: "2px 9px",
                  }}
                >
                  Score {selected.score}/100
                </span>
              )}
              {selected.status === "new" && <span className="daily-seed-tag">Nouveau</span>}
              {(selected.signal_count ?? 1) > 1 && (
                <span className="daily-seed-tag" style={{ color: "var(--success)", fontWeight: 600 }}>
                  {selected.signal_count} signaux
                </span>
              )}
            </div>
            {selected.score_reason && (
              <p style={{ margin: 0, fontSize: 12.5, color: "var(--muted)", fontStyle: "italic" }}>
                {selected.score_reason}
              </p>
            )}
            {/* ALE-243 : curation manuelle — « ne pas contacter » (le lead reste dans la liste, relégué en bas). */}
            {selected.contact_status === "skip" ? (
              <div className="card" style={{ padding: "10px 12px", display: "grid", gap: 8, background: "var(--surface-low)" }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>🚫 Écarté — ne pas contacter</div>
                {selected.skip_reason && (
                  <div style={{ fontSize: 12.5, color: "var(--muted)" }}>Raison : {selected.skip_reason}</div>
                )}
                <button className="secondary-button" style={{ justifySelf: "start", fontSize: 12.5 }} onClick={() => setContactStatus(selected, "to_contact")}>
                  Remettre dans la liste
                </button>
              </div>
            ) : (
              <details className="card" style={{ padding: "10px 12px" }}>
                <summary style={{ cursor: "pointer", fontSize: 13 }}>Ne pas contacter ce lead</summary>
                <div style={{ display: "grid", gap: 8, marginTop: 8 }}>
                  <input
                    type="text"
                    placeholder="Raison (optionnel) : hors cible, concurrent, déjà client…"
                    maxLength={280}
                    value={skipReason}
                    onChange={(e) => setSkipReason(e.target.value)}
                    style={{ padding: "7px 9px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--surface)", font: "inherit", fontSize: 13 }}
                  />
                  <button className="secondary-button" style={{ justifySelf: "start", fontSize: 12.5 }} onClick={() => setContactStatus(selected, "skip", skipReason.trim() || undefined)}>
                    Marquer « ne pas contacter »
                  </button>
                </div>
              </details>
            )}
            <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: ".06em", color: "var(--muted)", fontWeight: 700, marginTop: 4 }}>
              Signaux d&apos;intention
            </div>
            <div style={{ display: "grid", gap: 8 }}>
              {(selected.signals && selected.signals.length
                ? [...selected.signals].reverse()
                : [leadLastSignal(selected)]
              ).map((sig, i) => (
                <div key={i} className="card" style={{ padding: "10px 12px" }}>
                  {sig.comment_text && (
                    <p style={{ margin: 0, fontSize: 13, whiteSpace: "pre-wrap" }}>« {sig.comment_text} »</p>
                  )}
                  <p style={{ margin: "6px 0 0", fontSize: 12, color: "var(--muted)" }}>
                    {sig.trigger_keyword ? <>mot-clé « <strong>{sig.trigger_keyword}</strong> » · </> : null}
                    {sig.author ? `chez ${sig.author}` : "post concurrent"}
                    {leadDate(sig.commented_at) ? ` · ${leadDate(sig.commented_at)}` : ""}
                    {safeHttpUrl(sig.post_url) ? (
                      <> · <a href={safeHttpUrl(sig.post_url)} target="_blank" rel="noreferrer">voir le post</a></>
                    ) : null}
                  </p>
                </div>
              ))}
            </div>
            <div style={{ marginTop: "auto", display: "grid", gap: 10 }}>
              {/* ALE-230 : envoi via Unipile — demande de connexion → acceptation → 1er message */}
              <div style={{ borderTop: "1px solid var(--border)", paddingTop: 12, display: "grid", gap: 8 }}>
                <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: ".06em", color: "var(--muted)", fontWeight: 700 }}>
                  Contacter sur LinkedIn
                </div>
                {!outreach.status?.connected ? (
                  <p style={{ margin: 0, fontSize: 12.5, color: "var(--muted)" }}>
                    Connecte ton compte LinkedIn dans <strong>Mon profil</strong> pour envoyer une demande
                    de connexion et un premier message depuis ici.
                  </p>
                ) : (() => {
                  const q = outreach.status?.quota;
                  const eng = outreach.status?.engine;
                  const oStatus = selected.outreach_status || "none";
                  const pendingInvite = queuedInvite(selected);
                  const pendingMessage = queuedMessage(selected);
                  const immediateLeft = eng?.immediate_left ?? 0;
                  return (
                    <>
                      {q && (
                        <div style={{ fontSize: 11.5, color: "var(--muted)" }}>
                          Invitations {q.invites_today}/{q.daily_cap} · Messages {q.messages_today}/{q.daily_cap} (aujourd&apos;hui)
                        </div>
                      )}
                      {/* ALE-174 — l'action entre en file : le client choisit QUI, le moteur choisit QUAND. */}
                      {oStatus === "none" && pendingInvite && (
                        <>
                          <div style={{ fontSize: 13 }}>
                            📮 Invitation <strong>en file</strong> — partira {formatEta(eng?.next_send_estimate)}.
                          </div>
                          <button className="secondary-button" disabled={outreachBusy} onClick={() => cancelQueued(pendingInvite.id)} style={{ fontSize: 12 }}>
                            {outreachBusy ? <Loader2 size={13} className="spinning" /> : <X size={13} />} Retirer de la file
                          </button>
                        </>
                      )}
                      {oStatus === "none" && !pendingInvite && (
                        <>
                          <button
                            className="primary-button"
                            disabled={outreachBusy}
                            title="L'invitation part en file : le moteur l'enverra dans ta plage horaire, à un rythme humain."
                            onClick={() => inviteLead(selected)}
                          >
                            {outreachBusy ? <Loader2 size={14} className="spinning" /> : <UserRound size={14} />}
                            Mettre l&apos;invitation en file
                          </button>
                          <button
                            className="secondary-button"
                            disabled={outreachBusy || !q?.can_invite || immediateLeft <= 0}
                            title={
                              immediateLeft <= 0
                                ? "Soupape épuisée pour aujourd'hui — mets l'invitation en file."
                                : !q?.can_invite ? (q?.invite_blocked_reason || "") : "Envoi immédiat, hors file"
                            }
                            onClick={() => inviteLead(selected, true)}
                            style={{ fontSize: 12 }}
                          >
                            <Zap size={13} /> Envoyer maintenant ({immediateLeft} restant{immediateLeft > 1 ? "s" : ""})
                          </button>
                          {!q?.can_invite && q?.invite_blocked_reason && (
                            <p style={{ margin: 0, fontSize: 11.5, color: "var(--warning, #b8860b)" }}>{q.invite_blocked_reason}</p>
                          )}
                        </>
                      )}
                      {oStatus === "invite_sent" && (
                        <>
                          <div style={{ fontSize: 13 }}>⏳ Demande envoyée — en attente d&apos;acceptation.</div>
                          <button className="secondary-button" disabled={outreachBusy} onClick={() => checkConnection(selected)}>
                            {outreachBusy ? <Loader2 size={14} className="spinning" /> : <RefreshCw size={14} />}
                            Vérifier l&apos;acceptation
                          </button>
                        </>
                      )}
                      {oStatus === "connected" && pendingMessage && (
                        <>
                          <div style={{ fontSize: 13 }}>
                            📮 Message <strong>en file</strong> — partira {formatEta(eng?.next_send_estimate)}.
                          </div>
                          <button className="secondary-button" disabled={outreachBusy} onClick={() => cancelQueued(pendingMessage.id)} style={{ fontSize: 12 }}>
                            {outreachBusy ? <Loader2 size={13} className="spinning" /> : <X size={13} />} Retirer de la file
                          </button>
                        </>
                      )}
                      {oStatus === "connected" && !pendingMessage && (
                        <>
                          <div style={{ fontSize: 13, color: "var(--success)" }}>✓ En relation — prêt pour le premier message.</div>
                          {!composeOpen ? (
                            <button
                              className="primary-button"
                              onClick={() => { setComposeOpen(true); if (!messageText) generateMessage(selected); }}
                            >
                              <Send size={14} /> Rédiger le premier message
                            </button>
                          ) : (
                            <div style={{ display: "grid", gap: 8 }}>
                              <textarea
                                value={messageText}
                                onChange={(e) => setMessageText(e.target.value)}
                                rows={5}
                                placeholder={genBusy ? "Génération du message…" : "Ton premier message…"}
                                style={{ width: "100%", padding: 8, fontSize: 13, resize: "vertical" }}
                              />
                              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                                <button className="secondary-button" disabled={genBusy} onClick={() => generateMessage(selected)} style={{ fontSize: 12 }}>
                                  {genBusy ? <Loader2 size={13} className="spinning" /> : <Sparkles size={13} />} Régénérer
                                </button>
                                {/* Le texte est relu et validé AVANT d'entrer dans la file : rien n'est
                                    généré à la volée au moment où le moteur envoie. */}
                                <button
                                  className="primary-button"
                                  disabled={outreachBusy || genBusy || !messageText.trim()}
                                  onClick={() => sendFirstMessage(selected)}
                                  style={{ fontSize: 12 }}
                                >
                                  {outreachBusy ? <Loader2 size={13} className="spinning" /> : <Send size={13} />} Mettre en file
                                </button>
                                <button
                                  className="secondary-button"
                                  disabled={outreachBusy || genBusy || !messageText.trim() || !q?.can_message || immediateLeft <= 0}
                                  title={
                                    immediateLeft <= 0
                                      ? "Soupape épuisée pour aujourd'hui — mets le message en file."
                                      : !q?.can_message ? (q?.message_blocked_reason || "") : "Envoi immédiat, hors file"
                                  }
                                  onClick={() => sendFirstMessage(selected, true)}
                                  style={{ fontSize: 12 }}
                                >
                                  <Zap size={13} /> Envoyer maintenant
                                </button>
                              </div>
                              {!q?.can_message && q?.message_blocked_reason && (
                                <p style={{ margin: 0, fontSize: 11.5, color: "var(--warning, #b8860b)" }}>{q.message_blocked_reason}</p>
                              )}
                            </div>
                          )}
                        </>
                      )}
                      {oStatus === "messaged" && (
                        <div style={{ fontSize: 13, color: "var(--success)" }}>
                          ✓ Premier message envoyé. Retrouve la conversation dans <strong>Inbox › LinkedIn</strong>.
                        </div>
                      )}
                      {outreachMsg && <p style={{ margin: 0, fontSize: 12, color: "var(--muted)" }}>{outreachMsg}</p>}
                    </>
                  );
                })()}
              </div>
              {safeHttpUrl(selected.profile_url) && (
                <a
                  className="secondary-button"
                  style={{ textAlign: "center", textDecoration: "none" }}
                  href={safeHttpUrl(selected.profile_url)}
                  target="_blank"
                  rel="noreferrer"
                >
                  <Linkedin size={14} /> Voir le profil LinkedIn
                </a>
              )}
            </div>
          </aside>
        </>
      )}
    </div>
  );
}

// ALE-223 : onglet unique « Ma bibliothèque » regroupant, en tiroirs repliables,
// les contenus sauvegardés + les posts programmés (LibraryView) et la bibliothèque
// de références/templates (MyLibraryView).
function MyContentHub({
  isAuthed,
  requireAuth,
  onReuse,
  onRework,
  onInspire,
  imageJobs,
  onImageJobCreated,
}: {
  isAuthed: boolean;
  requireAuth: (reason?: string, mode?: AuthMode) => void;
  onReuse: (topic: string) => void;
  onRework?: (post: string) => void;
  onInspire: (topic: string) => void;
  imageJobs: ImageJob[];
  onImageJobCreated: (job: ImageJob) => void;
}) {
  if (!isAuthed) {
    return (
      <div className="card" style={{ textAlign: "center", padding: 40 }}>
        <ListChecks size={28} style={{ opacity: 0.4, marginBottom: 12 }} />
        <h2 style={{ margin: "0 0 8px" }}>Ma bibliothèque</h2>
        <p style={{ color: "var(--muted)", marginBottom: 16 }}>
          Connecte-toi pour retrouver tes contenus sauvegardés, tes posts programmés et ta bibliothèque de références.
        </p>
        <button type="button" className="primary-button" onClick={() => requireAuth("Crée un compte gratuit pour retrouver tes contenus.")}>
          <Sparkles size={14} /> Créer un compte gratuit
        </button>
      </div>
    );
  }
  return (
    <div>
      <p className="section-desc" style={{ marginTop: 0, marginBottom: 20 }}>
        Ta bibliothèque de références, tes contenus sauvegardés, tes posts programmés et la veille de tes influenceurs suivis — pour t&apos;y retrouver facilement.
      </p>
      {/* Bloc « Posts de référence & templates » tout en haut (demande Alex). */}
      <MyLibraryView isAuthed={isAuthed} requireAuth={requireAuth} />
      <LibraryView isAuthed={isAuthed} requireAuth={requireAuth} onReuse={onReuse} onRework={onRework} imageJobs={imageJobs} onImageJobCreated={onImageJobCreated} />
      {/* Veille des influenceurs suivis — tiroir compact replié par défaut, en bas de page. */}
      <MonitoringFeedView isAuthed={isAuthed} requireAuth={requireAuth} onInspire={onInspire} />
    </div>
  );
}

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
  imageJobs,
  onImageJobCreated,
  // ALE-257 : props « Analyses » (Veille fusionnée dans Contenu).
  loadedReport,
  onCloseReport,
  jobs,
  jobsLoading,
  onJobCreated,
  onJobUpdated,
  onOpenReport,
  influencers,
  influencersLoading,
  onOpenLibraryReport,
  onInspire,
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
  imageJobs: ImageJob[];
  onImageJobCreated: (job: ImageJob) => void;
  loadedReport: Report | null;
  onCloseReport: () => void;
  jobs: Job[];
  jobsLoading: boolean;
  onJobCreated: (job: Job) => void;
  onJobUpdated: (job: Job) => void;
  onOpenReport: (markdown: string, name: string) => void;
  influencers: InfluencerLibraryEntry[];
  influencersLoading: boolean;
  onOpenLibraryReport: (entry: InfluencerLibraryEntry) => Promise<void>;
  onInspire: (topic: string) => void;
}) {
  const subTabs: { key: ContentTab; label: string; icon: React.ReactNode }[] = [
    { key: "generator", label: "Générateur de posts", icon: <PenTool size={14} /> },
    // ALE-257 : Veille fusionnée ici — « Analyses » placée à droite du Générateur.
    { key: "analyses", label: "Analyses", icon: <BarChart3 size={14} /> },
    // ALE-223 : onglet unique regroupant contenus sauvegardés, posts programmés
    // et bibliothèque de références/templates (voir MyContentHub).
    { key: "library", label: "Ma bibliothèque", icon: <ListChecks size={14} /> },
  ];

  // Compte client restreint : on ne montre que le réservoir d'idées, sans sous-onglets
  // (et donc pas de page « Analyses » — voir ALE-257, feature agence uniquement).
  if (reservoirOnly) {
    return (
      <div>
        <DailyIdeasView isAuthed={isAuthed} requireAuth={requireAuth} onReuse={onReuse} reservoirOnly imageJobs={imageJobs} onImageJobCreated={onImageJobCreated} />
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

      {tab === "analyses" && (
        loadedReport ? (
          <>
            <button className="secondary-button" style={{ marginBottom: 12 }} onClick={onCloseReport}>
              ← Retour aux analyses
            </button>
            <div className="markdown card"><ReactMarkdown remarkPlugins={[remarkGfm]}>{loadedReport.content}</ReactMarkdown></div>
          </>
        ) : (
          <LinkedInAnalysesView
            jobs={jobs}
            jobsLoading={jobsLoading}
            onJobCreated={onJobCreated}
            onJobUpdated={onJobUpdated}
            onOpenReport={onOpenReport}
            influencers={influencers}
            influencersLoading={influencersLoading}
            onOpenLibraryReport={onOpenLibraryReport}
            isAuthed={isAuthed}
            requireAuth={requireAuth}
          />
        )
      )}
      {tab === "generator" && <Generator isAuthed={isAuthed} requireAuth={requireAuth} seed={seed} generationJobs={generationJobs} onGenerationJobCreated={onGenerationJobCreated} imageJobs={imageJobs} onImageJobCreated={onImageJobCreated} onRework={onRework} />}
      {tab === "library" && (
        <MyContentHub isAuthed={isAuthed} requireAuth={requireAuth} onReuse={onReuse} onRework={onRework} onInspire={onInspire} imageJobs={imageJobs} onImageJobCreated={onImageJobCreated} />
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
  const [contentTab, setContentTab] = useState<ContentTab>("generator");
  // Sujet pré-rempli quand on "réutilise" une idée/un post depuis Mes contenus.
  const [generatorSeed, setGeneratorSeed] = useState<{ topic: string; nonce: number } | null>(null);
  // Post pré-rempli quand on "retravaille" un variant depuis le Générateur vers l'Agent IA.
  const [assistantSeed, setAssistantSeed] = useState<{ post: string; nonce: number } | null>(null);
  // ALE-245 : conversation à pré-sélectionner dans l'Inbox (depuis un lead).
  const [inboxSelect, setInboxSelect] = useState<{ network: InboxNetwork; id: string; nonce: number } | null>(null);
  const [loadedReport, setLoadedReport] = useState<Report | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  // ALE-141 : jobs de génération de posts (file d'attente, vit dans Home pour que
  // le polling continue quand on change d'onglet / quitte le générateur).
  const [generationJobs, setGenerationJobs] = useState<GenerationJob[]>([]);
  // ALE-261 : jobs de génération d'image IA (même principe — vit dans Home pour
  // que fermer la pop-up ou changer d'onglet n'interrompe jamais la génération).
  const [imageJobs, setImageJobs] = useState<ImageJob[]>([]);
  const [session, setSession] = useState<Session | null>(null);
  const [authOpen, setAuthOpen] = useState(false);
  const [authReason, setAuthReason] = useState("");
  const [authMode, setAuthMode] = useState<AuthMode>("signup");
  const [credits, setCredits] = useState<number | null>(null);
  // Nombre de conversations Inbox avec un message plus récent que la dernière
  // visite → pastille d'alerte dans la sidebar (poll global, cf. effet plus bas).
  const [igUnread, setIgUnread] = useState(0);
  const [showOnboarding, setShowOnboarding] = useState(false);
  // Le temps de vérifier (côté serveur) si le profil est vide, on affiche un
  // écran de chargement neutre plutôt que l'app qui "flashe" puis l'onboarding.
  const [checkingProfile, setCheckingProfile] = useState(false);
  const userIdRef = useRef<string | null>(null);

  // Un post en préparation vit en mémoire de la page : recharger ou fermer
  // l'onglet le perd (avec les 3 idées déjà payées). On prévient AVANT, pas
  // après. Posé dans `Home` (jamais démonté) : l'alerte doit se déclencher
  // depuis n'importe quel onglet de l'app, pas seulement le Générateur.
  // Le test se fait au déclenchement, pas au montage : rien à re-souscrire quand
  // la liste des brouillons change.
  // ⚠️ Le navigateur impose son propre texte — on ne peut que réclamer sa pop-up
  // (et il ne l'affiche que si l'utilisateur a interagi avec la page).
  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (_wizardDrafts.length === 0) return;
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, []);
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

  // Vue client : navigation verrouillée sur la page idées (LinkedIn → Contenu).
  // ALE-286 : le sous-onglet n'existe plus côté agence — c'est `reservoirOnly`
  // dans ContentHub qui rend la page idées, quel que soit l'onglet courant.
  useEffect(() => {
    if (!restricted) return;
    setView("content");
    setPlatform("linkedin");
  }, [restricted]);

  useEffect(() => {
    try {
      const savedPlatform = localStorage.getItem("lkd_platform");
      // Instagram est grisé : on ne restaure pas cette préférence, sinon le compte
      // rouvre sur une vue Instagram qui n'a plus d'entrée dans la navigation.
      if (savedPlatform === "linkedin") {
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

  // ALE-261 : génération d'image IA en file d'attente.
  async function loadImageJobs() {
    try {
      const res = await fetch(`${DIRECT_API_URL}/generate-image/jobs`, { headers: await authHeaders() });
      const data = await res.json();
      if (res.ok && Array.isArray(data)) setImageJobs(data);
    } catch { /* ignore */ }
  }

  function onImageJobCreated(job: ImageJob) {
    setImageJobs((prev) => [job, ...prev]);
  }

  const anyImageJobActive = imageJobs.some(imageJobIsActive);

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
    // Non-chevauchant (ALE-271) : on replanifie seulement après la fin de la
    // requête précédente (succès OU échec), sinon les appels s'empilent sur un
    // backend lent (même pattern que le badge Inbox, PR #192).
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const loop = async () => { await loadJobs(); if (!stop) timer = setTimeout(loop, 3000); };
    timer = setTimeout(loop, 3000);
    return () => { stop = true; clearTimeout(timer); };
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
    // Non-chevauchant (ALE-271) : même pattern que le poll des séries ci-dessus.
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const loop = async () => { await loadGenerationJobs(); if (!stop) timer = setTimeout(loop, 3000); };
    timer = setTimeout(loop, 3000);
    return () => { stop = true; clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed, anyGenerationJobActive]);

  // ALE-261 : premier chargement des jobs d'image + polling tant qu'un tourne.
  // Vit dans Home (comme les jobs de génération de posts) pour que fermer la
  // pop-up ImageGenModal ou changer d'onglet n'interrompe jamais le polling.
  useEffect(() => {
    if (!isAuthed) { setImageJobs([]); return; }
    loadImageJobs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed, session?.access_token]);

  useEffect(() => {
    if (!isAuthed || !anyImageJobActive) return;
    // Non-chevauchant (ALE-271) : même pattern que les autres polls ci-dessus.
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const loop = async () => { await loadImageJobs(); if (!stop) timer = setTimeout(loop, 3000); };
    timer = setTimeout(loop, 3000);
    return () => { stop = true; clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed, anyImageJobActive]);

  useEffect(() => {
    if (prevJobActiveRef.current && !anyJobActive && isAuthed) {
      loadReports();
      loadInfluencerLibrary();
    }
    prevJobActiveRef.current = anyJobActive;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anyJobActive, isAuthed]);

  // Pastille d'alerte Inbox : poll léger et global (indépendant de l'écran actif,
  // contrairement au poll interne de l'Inbox qui ne tourne que quand elle est
  // ouverte). Une conversation est « non lue » si son dernier message est plus
  // récent que le repère de dernière visite (max des last_message_at vus, stocké
  // par utilisateur dans localStorage → pas de fuite cross-user, cf. clé keyée).
  // Sur l'écran Inbox on considère tout comme vu et on met à jour le repère.
  useEffect(() => {
    if (!isAuthed) { setIgUnread(0); return; }
    const uid = session?.user?.id ?? "anon";
    const seenKey = `ig_inbox_seen_at:${uid}`;
    const ts = (c: { last_message_at?: string | null }) =>
      c?.last_message_at ? new Date(c.last_message_at).getTime() : 0;
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const res = await fetch(`${DIRECT_API_URL}/me/ig/conversations`, { headers: await authHeaders() });
        if (!res.ok || stop) return;
        const data = await res.json();
        if (stop || !Array.isArray(data)) return;
        const latest = data.reduce((m: number, c: { last_message_at?: string | null }) => Math.max(m, ts(c)), 0);
        if (view === "inbox") {
          try { localStorage.setItem(seenKey, String(latest)); } catch { /* ignore */ }
          setIgUnread(0);
        } else {
          let seen = 0;
          try { seen = Number(localStorage.getItem(seenKey) || 0); } catch { /* ignore */ }
          setIgUnread(data.filter((c: { last_message_at?: string | null }) => ts(c) > seen).length);
        }
      } catch { /* non bloquant */ }
    };
    // Non-chevauchant : on replanifie seulement après la fin du tick (backend lent).
    const loop = async () => { await tick(); if (!stop) timer = setTimeout(loop, 25000); };
    loop();
    return () => { stop = true; clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed, session?.access_token, view]);

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
      setImageJobs([]);
      setIgUnread(0);
      // ALE-145 : purge le cache générateur quand l'utilisateur change (anti fuite
      // cross-user). Le cache est module-level : sans ça, le brouillon et les
      // images du compte précédent réapparaîtraient chez le suivant dans le même
      // onglet. Toute clé ajoutée à `_genCache` doit être purgée ici.
      _genCache.appliedImageJobIds = new Set();
      _genCache.edited = {};
      _genCache.images = {};
      _genCache.expanded = null;
      // Les parcours inachevés sont gardés en mémoire : sans cette purge, les
      // idées (et les structures) du compte précédent réapparaîtraient en file
      // chez le suivant dans le même onglet.
      _wizardDrafts = [];
      _dailyIdeaCache.ideaImages = {};
      _dailyIdeaCache.appliedImageJobIds = new Set();
      _libraryAppliedImageJobIds.clear();
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

  // ALE-274 — arrivée depuis la page de vente (/offre → `?subscribe=1`).
  //
  // On ne peut PAS envoyer le prospect sur un lien de paiement Stripe autonome :
  // les crédits sont attribués par le webhook, qui doit savoir à quel compte
  // rattacher le paiement. Le passage par un compte est donc obligatoire.
  //
  // L'intention est mémorisée en localStorage (et pas en sessionStorage) pour
  // survivre au cas « confirmation d'e-mail activée » : le lien de confirmation
  // ouvre un autre onglet, et on veut quand même reprendre le paiement là où on
  // l'avait laissé. Purgée au bout d'une heure pour ne pas rediriger quelqu'un
  // vers un paiement qu'il ne demande plus.
  const SUBSCRIBE_INTENT_KEY = "cibl_subscribe_intent";
  const SUBSCRIBE_INTENT_TTL_MS = 60 * 60 * 1000;

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("subscribe") !== "1") return;
    params.delete("subscribe");
    const qs = params.toString();
    window.history.replaceState({}, "", window.location.pathname + (qs ? `?${qs}` : ""));
    try { localStorage.setItem(SUBSCRIBE_INTENT_KEY, String(Date.now())); } catch { /* ignore */ }
    if (!isAuthed) {
      requireAuth("Crée ton compte, puis tu es redirigé vers le paiement sécurisé Stripe.", "signup");
    }
  }, [isAuthed]);

  // Intention d'abonnement en attente + utilisateur désormais connecté → on
  // enchaîne sur le paiement. Couvre les deux cas : session immédiate après
  // inscription, ou retour après confirmation d'e-mail.
  useEffect(() => {
    if (!isAuthed) return;
    let stamp: string | null = null;
    try { stamp = localStorage.getItem(SUBSCRIBE_INTENT_KEY); } catch { /* ignore */ }
    if (!stamp) return;
    try { localStorage.removeItem(SUBSCRIBE_INTENT_KEY); } catch { /* ignore */ }
    if (Date.now() - Number(stamp) > SUBSCRIBE_INTENT_TTL_MS) return;
    (async () => {
      try {
        const base = `${window.location.origin}${window.location.pathname}`;
        const res = await fetch(`${DIRECT_API_URL}/me/billing/checkout`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...(await authHeaders()) },
          body: JSON.stringify({ success_url: `${base}?billing=success`, cancel_url: `${base}?billing=cancelled` }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Paiement indisponible");
        window.location.href = data.url;
      } catch {
        // Échec (facturation non configurée, réseau…) : on n'affiche pas d'erreur
        // brutale — l'utilisateur atterrit sur son profil, où la carte
        // « Abonnement » lui permet de réessayer.
        setView("profile");
      }
    })();
  }, [isAuthed]);

  // ALE-274 — retour de la page de paiement Stripe. Le crédit et l'état
  // d'abonnement sont posés par le webhook (source de vérité) : ce retour ne fait
  // que resynchroniser l'affichage. Le webhook peut arriver une poignée de
  // secondes après la redirection, d'où la relecture du solde en léger différé.
  useEffect(() => {
    if (!isAuthed) return;
    const params = new URLSearchParams(window.location.search);
    const outcome = params.get("billing");
    if (outcome !== "success" && outcome !== "cancelled") return;
    params.delete("billing");
    const qs = params.toString();
    window.history.replaceState({}, "", window.location.pathname + (qs ? `?${qs}` : ""));
    setView("profile");
    if (outcome !== "success") return;
    (async () => {
      try {
        await fetch(`${DIRECT_API_URL}/me/billing/refresh`, { method: "POST", headers: await authHeaders() });
      } catch { /* ignore */ }
      for (const delay of [0, 3000]) {
        await new Promise((resolve) => setTimeout(resolve, delay));
        try {
          const res = await fetch(`${DIRECT_API_URL}/me/credits`, { headers: await authHeaders() });
          if (res.ok) emitCredits((await res.json()).balance);
        } catch { /* ignore */ }
      }
    })();
  }, [isAuthed]);

  // ALE-230 — retour du flux d'auth hébergée Unipile (messagerie LinkedIn) :
  // on retrouve le compte connecté côté serveur, on nettoie l'URL, on va au Profil.
  useEffect(() => {
    if (!isAuthed) return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("linkedin_outreach") !== "connected") return;
    (async () => {
      try {
        await fetch(`${DIRECT_API_URL}/me/linkedin/outreach/refresh`, { method: "POST", headers: await authHeaders() });
      } catch { /* ignore */ }
      params.delete("linkedin_outreach");
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

  /** ALE-257 : ouvre un rapport (depuis le backlog) dans Contenu › Analyses. */
  function openReport(markdown: string, name: string) {
    setLoadedReport({ name, path: name, updated_at: Date.now() / 1000, content: markdown });
    setResult(null);
    setContentTab("analyses");
    setView("content");
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
    setContentTab("analyses");
    setView("content");
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
          igUnread={igUnread}
          platform={platform}
          onNavigate={(v) => {
            setView(v);
            // ALE-257 : cliquer « Contenu » dans la nav repart d'un état propre (referme
            // un rapport ouvert) ; idem pour le Profil.
            if (v === "content" || v === "profile") {
              setResult(null);
              setLoadedReport(null);
              setError("");
            }
          }}
          onLoadReport={(r) => { setLoadedReport(r); setContentTab("analyses"); setView("content"); setResult(null); }}
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
          {/* Agent IA, Inbox IG et Profil (qui inclut le Tableau de bord) sont indépendants du réseau */}
          {view === "inbox" ? (
            <UnifiedInbox isAuthed={isAuthed} requireAuth={requireAuth} userId={session?.user?.id ?? null} initialSelect={inboxSelect} />
          ) : view === "assistant" ? (
            <Assistant isAuthed={isAuthed} requireAuth={requireAuth} seed={assistantSeed} imageJobs={imageJobs} onImageJobCreated={onImageJobCreated} />
          ) : view === "profile" ? (
            <ProfileView isAuthed={isAuthed} requireAuth={requireAuth} />
          ) : platform === "instagram" ? (
            view === "content" ? (
              // ALE-257 : Veille IG fusionnée dans Contenu › Analyses.
              <InstagramContentHub
                tab={contentTab}
                onTab={setContentTab}
                isAuthed={isAuthed}
                requireAuth={requireAuth}
                loadedReport={loadedReport}
                onCloseReport={() => setLoadedReport(null)}
                jobs={jobs}
                jobsLoading={jobsLoading}
                onJobCreated={onJobCreated}
                onJobUpdated={onJobUpdated}
                onOpenReport={(markdown, name) => {
                  setLoadedReport({ content: markdown, name, path: "", updated_at: Date.now() / 1000 });
                  setContentTab("analyses");
                }}
              />
            ) : (
              <InstagramPlaceholder />
            )
          ) : (
            <>
              {view === "content" && (
                // ALE-257 : Veille LinkedIn fusionnée dans Contenu › Analyses (page empilée).
                <ContentHub
                  tab={contentTab}
                  onTab={setContentTab}
                  seed={generatorSeed}
                  isAuthed={isAuthed}
                  reservoirOnly={restricted}
                  requireAuth={requireAuth}
                  generationJobs={generationJobs}
                  onGenerationJobCreated={onGenerationJobCreated}
                  imageJobs={imageJobs}
                  onImageJobCreated={onImageJobCreated}
                  loadedReport={loadedReport}
                  onCloseReport={() => setLoadedReport(null)}
                  jobs={jobs}
                  jobsLoading={jobsLoading}
                  onJobCreated={onJobCreated}
                  onJobUpdated={onJobUpdated}
                  onOpenReport={openReport}
                  influencers={influencers}
                  influencersLoading={influencersLoading}
                  onOpenLibraryReport={openLibraryReport}
                  onInspire={(topic) => {
                    setGeneratorSeed({ topic, nonce: Date.now() });
                    setContentTab("generator");
                    setView("content");
                  }}
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
              {view === "prospecting" && (
                <ProspectingView
                  isAuthed={isAuthed}
                  requireAuth={requireAuth}
                  onNavigateInbox={(chatId) => {
                    if (chatId) setInboxSelect({ network: "linkedin", id: chatId, nonce: Date.now() });
                    setView("inbox");
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
