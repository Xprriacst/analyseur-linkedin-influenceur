"use client";

/**
 * Onboarding partagé — le MÊME parcours sert deux situations :
 *
 *  - `anonymous` (page /start) : le visiteur n'a pas de compte. L'analyse passe par
 *    la route publique bornée par IP, et les réponses sont RENDUES à l'appelant
 *    (via onFinish) au lieu d'être enregistrées : il n'y a pas encore de compte où
 *    les mettre.
 *  - authentifié (page.tsx) : l'appelant enregistre le profil dans la foulée.
 *
 * Dans les DEUX cas, si une preview « Analyse IA » est dispo, on la montre avant
 * les chips (include_preview: true sur les deux routes).
 *
 * Le composant ne décide donc JAMAIS quoi faire des réponses — il les calcule et
 * les passe. C'est ce qui lui permet de servir avant ET après la création du compte
 * sans se dédoubler.
 */

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Briefcase,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Linkedin,
  Loader2,
  Mail,
  MessageSquare,
  Sparkles,
  Target,
  Users,
} from "lucide-react";
import { authHeaders } from "../lib/supabase";

const DIRECT_API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "https://analyseur-linkedin-influenceur-api-eu.onrender.com";

/** Le profil éditorial tel que rendu par l'onboarding (clés du draft + réponses). */
export type OnboardingProfile = Record<string, string>;

/** Preview « Analyse IA » renvoyée par `/onboarding/draft` (optionnelle). */
export type OnboardingPreview = {
  handle: string;
  name: string;
  headline: string;
  avatar_url?: string;
  posts_count: number;
  followers: number;
  connections: number;
  niche: string;
  summary: string;
  hook: string;
  hashtags: string[];
  strengths: string[];
  improvements: string[];
};

/** Fourchette basse/haute — le tunnel n'affiche jamais de valeur unique. */
export type OnbRange = { low: number; high: number };

/** Gains projetés pour un palier de panier moyen (calculés par le serveur). */
export type OnbProjection = {
  followers_now: number;
  followers_gain: OnbRange;
  followers_after: OnbRange;
  relations_per_month: OnbRange;
  conversations_per_month: OnbRange;
  clients_per_month: OnbRange;
  revenue_per_month: OnbRange;
  deal_value: number;
};

export type OnbBand = {
  key: string;
  label: string;
  deal_value: number;
  projection: OnbProjection;
  assumptions: string[];
};

// --- Onboarding « Cible » : wizard accueil → scan → analyse → confirmation ---
//
// Sur la landing (`leadFunnel`), le parcours ne s'arrête pas à la confirmation :
// il enchaîne sur les gains projetés, une simulation « avant / après », puis
// l'échange audit complet ↔ coordonnées, et se termine sur la prise de rendez-vous.
type OnbStep =
  | "intro"
  | "scanning"
  | "analysis"
  | "analysis_detail"
  | "page1"
  | "page2"
  | "gains"
  | "simulation"
  | "lead_form"
  | "lead_done";
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

function fmtCompact(n: number): string {
  if (!n || n < 0) return "—";
  if (n < 1000) return String(n);
  if (n < 10000) return `${(n / 1000).toFixed(1).replace(".0", "")}K`;
  if (n < 1000000) return `${Math.round(n / 1000)}K`;
  return `${(n / 1000000).toFixed(1).replace(".0", "")}M`;
}

/** Entier en français, avec espaces insécables sur les milliers. */
function fmtInt(n: number): string {
  return Math.round(n || 0).toLocaleString("fr-FR");
}

/** Montant arrondi — la projection est une estimation, pas une facture. */
function fmtMoney(n: number): string {
  return `${fmtInt(n)} €`;
}

/** Fourchette affichée « bas à haut ». Bornes égales ⇒ une seule valeur. */
function fmtRange(range: OnbRange | undefined, fmt: (n: number) => string): string {
  if (!range) return "—";
  if (range.low === range.high) return fmt(range.low);
  return `${fmt(range.low)} à ${fmt(range.high)}`;
}

function initials(name: string, handle: string): string {
  const base = (name || handle || "?").trim();
  const parts = base.replace(/[@._-]+/g, " ").split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return base.slice(0, 2).toUpperCase();
}

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

export default function OnboardingScreen({
  anonymous = false,
  leadFunnel = false,
  onFinish,
  onSkip,
  finishLabel = "C'est parti",
}: {
  /** true = visiteur sans compte : analyse via la route publique, réponses rendues à l'appelant. */
  anonymous?: boolean;
  /**
   * true = landing : après les questions, on enchaîne sur les gains projetés et
   * l'échange « audit complet contre coordonnées » plutôt que sur la création de
   * compte. Le wizard in-app (compte déjà créé) ne doit jamais voir ces écrans.
   */
  leadFunnel?: boolean;
  /** Reçoit le profil complet. L'appelant décide : enregistrer, ou emmener vers l'inscription. */
  onFinish: (profile: OnboardingProfile) => void | Promise<void>;
  /** « Passer » — l'utilisateur refuse de répondre. */
  onSkip: () => void;
  finishLabel?: string;
}) {
  const [step, setStep] = useState<OnbStep>("intro");
  const [aiInput, setAiInput] = useState("");
  const [error, setError] = useState("");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<OnboardingPreview | null>(null);
  const [sel, setSel] = useState(() => onbInitSel({}));
  const [saving, setSaving] = useState(false);
  const [scanIdx, setScanIdx] = useState(0);

  // --- Tunnel « audit complet » (landing uniquement) ---
  const [bands, setBands] = useState<OnbBand[]>([]);
  const [bandKey, setBandKey] = useState<string>("mid");
  const [lead, setLead] = useState({ name: "", email: "", phone: "" });
  const [leadError, setLeadError] = useState("");
  const [calendlyUrl, setCalendlyUrl] = useState("");

  const band = bands.find((b) => b.key === bandKey) || bands[0] || null;
  const projection = band?.projection || null;

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
        // Sans compte : route publique (bornée par IP). Avec compte : la route
        // authentifiée, qui sait en plus relire un profil déjà analysé.
        const res = await fetch(`${DIRECT_API_URL}${anonymous ? "/onboarding/draft" : "/me/profile/draft"}`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(anonymous ? {} : await authHeaders()),
          },
          body: JSON.stringify({
            activity_description: isLinkedin || isWebsite ? "" : trimmed,
            linkedin_url: isLinkedin ? trimmed : "",
            website_url: isWebsite ? trimmed : "",
            use_apify_linkedin: isLinkedin,
            include_preview: true,
          }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Analyse impossible");
        return data as { profile?: Record<string, string>; preview?: OnboardingPreview | null };
      })();
      const [data] = await Promise.all([fetchDraft, minWait]);
      const d = (data.profile || {}) as Record<string, string>;
      setDraft(d);
      setSel(onbInitSel(d));
      const p = data.preview && data.preview.niche && data.preview.summary ? data.preview : null;
      setPreview(p);
      // L'analyse s'affiche sur les DEUX parcours (public /start ET wizard d'un
      // compte connecté) — sans elle, on saute directement aux questions.
      setStep(p ? "analysis" : "page1");
    } catch (err: any) {
      setError(err?.message || "Analyse impossible");
      setStep("intro");
    }
  }

  /** Le profil consolidé : brouillon IA + réponses confirmées par le visiteur. */
  function mergedProfile(): Record<string, string> {
    return {
      ...draft,
      display_name: sel.displayName.trim() || draft.display_name || "",
      target_audience: sel.audienceMode === "large" ? "Large, pas de niche précise" : onbJoin(sel.audience),
      core_offer: onbJoin(sel.offer),
      linkedin_objective: onbJoin(sel.objective),
      industry: onbJoin(sel.industry),
    };
  }

  async function finish() {
    setSaving(true);
    try {
      await onFinish(mergedProfile());
    } catch {
      // L'appelant gère ses erreurs. Ici on relâche juste le bouton pour ne pas
      // laisser l'utilisateur bloqué sur un spinner définitif.
      setSaving(false);
    }
  }

  /**
   * Charge les gains projetés (un jeu par palier de panier moyen).
   *
   * Best-effort assumé : si le calcul est injoignable, on saute directement au
   * formulaire. Bloquer l'accès à l'audit complet parce qu'un écran de mise en
   * scène n'a pas répondu ferait perdre le prospect pour rien.
   */
  async function toGains() {
    setStep("gains");
    if (bands.length > 0) return;
    try {
      const res = await fetch(`${DIRECT_API_URL}/onboarding/projection`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          followers: preview?.followers || 0,
          connections: preview?.connections || 0,
          posts_count: preview?.posts_count || 0,
        }),
      });
      if (!res.ok) throw new Error("projection indisponible");
      const data = await res.json();
      const list: OnbBand[] = Array.isArray(data?.bands) ? data.bands : [];
      if (list.length === 0) throw new Error("projection vide");
      setBands(list);
      setBandKey(data?.default_band || list[0].key);
    } catch {
      setStep("lead_form");
    }
  }

  async function submitLead() {
    const name = lead.name.trim();
    const email = lead.email.trim();
    const phone = lead.phone.trim();
    if (!name) { setLeadError("Indique ton nom et prénom."); return; }
    if (!/^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$/.test(email)) { setLeadError("Indique une adresse e-mail valide."); return; }
    if (phone.replace(/\D/g, "").length < 6) { setLeadError("Indique un numéro de téléphone valide."); return; }

    setLeadError("");
    setSaving(true);
    try {
      const res = await fetch(`${DIRECT_API_URL}/onboarding/audit-lead`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          full_name: name,
          email,
          phone,
          linkedin_url: inputKind === "linkedin" ? aiInput.trim() : "",
          website_url: inputKind === "website" ? aiInput.trim() : "",
          input_kind: inputKind,
          consent: true,
          preview,
          profile: mergedProfile(),
          projection: projection || null,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.detail || "Envoi impossible. Réessaie dans un instant.");
      setCalendlyUrl(data?.calendly_url || "");
      setStep("lead_done");
    } catch (err: any) {
      setLeadError(err?.message || "Envoi impossible. Réessaie dans un instant.");
    } finally {
      setSaving(false);
    }
  }

  /**
   * Redirection vers la prise de rendez-vous, après un temps de lecture.
   *
   * ⚠️ Le délai n'est pas cosmétique : sans lui, la page saute sur Calendly avant
   * que « ton audit arrive par e-mail » ait pu être lu, et le visiteur ne sait
   * plus ce qu'il est censé recevoir.
   */
  useEffect(() => {
    if (step !== "lead_done" || !calendlyUrl) return;
    const id = setTimeout(() => { window.location.href = calendlyUrl; }, 4000);
    return () => clearTimeout(id);
  }, [step, calendlyUrl]);

  const showProgress = step === "page1" || step === "page2";
  const isAnalysis =
    step === "analysis" ||
    step === "analysis_detail" ||
    step === "gains" ||
    step === "simulation" ||
    step === "lead_form" ||
    step === "lead_done";

  return (
    <div className={"onb-overlay" + (isAnalysis ? " onb-overlay-analysis" : "")}>
      <div className={"onb-shell" + (isAnalysis ? " onb-shell-analysis" : "")}>
        {showProgress && (
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
              <button type="button" className="onb-cta" onClick={analyze}>
                <Sparkles size={16} /> Analyser
              </button>
            </div>
            {error && <div className="onb-error">{error}</div>}
            <button type="button" className="onb-skip" onClick={() => setStep("page1")}>Continuer sans LinkedIn</button>
          </div>
        )}

        {step === "scanning" && (
          <div className="onb-screen onb-scan" key="scan">
            <div className="onb-orb"><Linkedin size={34} /></div>
            <div className="onb-scan-status" key={scanIdx}>{ONB_SCAN_STEPS[scanIdx]}</div>
          </div>
        )}

        {step === "analysis" && preview && (
          <div className="onb-screen onb-analysis" key="analysis">
            <div className="onb-analysis-card onb-analysis-profile">
              {preview.avatar_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  className="onb-analysis-avatar onb-analysis-avatar-img"
                  src={preview.avatar_url}
                  alt=""
                  onError={(e) => { e.currentTarget.style.display = "none"; }}
                />
              ) : (
                <div className="onb-analysis-avatar" aria-hidden>
                  {initials(preview.name, preview.handle)}
                </div>
              )}
              <div className="onb-analysis-name">{preview.name || "Ton profil"}</div>
              {preview.handle && (
                <div className="onb-analysis-handle">@{preview.handle.replace(/^@+/, "")}</div>
              )}
              {preview.headline && (
                <div className="onb-analysis-headline">{preview.headline}</div>
              )}
              {(preview.posts_count > 0 || preview.followers > 0 || preview.connections > 0) && (
                <div className="onb-analysis-stats">
                  <div>
                    <strong>{preview.posts_count || "—"}</strong>
                    <span>Posts lus</span>
                  </div>
                  <div>
                    <strong>{fmtCompact(preview.followers)}</strong>
                    <span>Abonnés</span>
                  </div>
                  <div>
                    <strong>{fmtCompact(preview.connections)}</strong>
                    <span>Relations</span>
                  </div>
                </div>
              )}
            </div>

            <h2 className="onb-analysis-title">Analyse IA</h2>

            <div className="onb-analysis-card">
              <div className="onb-analysis-label">Niche</div>
              <p className="onb-analysis-niche">{preview.niche}</p>
            </div>

            <div className="onb-analysis-card">
              <div className="onb-analysis-label">Résumé</div>
              {preview.summary.split(/\n{2,}/).filter(Boolean).map((para, i) => (
                <p key={i} className="onb-analysis-summary">{para.trim()}</p>
              ))}
            </div>

            <button
              type="button"
              className="onb-analysis-cta"
              onClick={() => setStep("analysis_detail")}
            >
              Voir mon potentiel
            </button>
          </div>
        )}

        {step === "analysis_detail" && preview && (
          <div className="onb-screen onb-analysis" key="analysis_detail">
            {preview.hook && (
              <div className="onb-analysis-card">
                <p className="onb-analysis-summary">{preview.hook}</p>
              </div>
            )}

            {preview.hashtags.length > 0 && (
              <div className="onb-analysis-block">
                <div className="onb-analysis-label">Hashtags</div>
                <div className="onb-analysis-tags">
                  {preview.hashtags.map((tag) => (
                    <span key={tag} className="onb-analysis-tag">{tag}</span>
                  ))}
                </div>
              </div>
            )}

            <div className="onb-analysis-block">
              <div className="onb-analysis-label">Points forts</div>
              <ul className="onb-analysis-list">
                {preview.strengths.map((s) => (
                  <li key={s}>
                    <CheckCircle2 size={16} className="onb-analysis-ok" />
                    <span>{s}</span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="onb-analysis-block">
              <div className="onb-analysis-label">Points à améliorer</div>
              <ul className="onb-analysis-list">
                {preview.improvements.map((s) => (
                  <li key={s}>
                    <AlertTriangle size={16} className="onb-analysis-warn" />
                    <span>{s}</span>
                  </li>
                ))}
              </ul>
            </div>

            <button
              type="button"
              className="onb-analysis-cta"
              onClick={() => setStep("page1")}
            >
              Continuer <ChevronRight size={16} />
            </button>
            <button
              type="button"
              className="onb-analysis-skip"
              onClick={() => setStep("analysis")}
            >
              ← Retour à l&apos;analyse
            </button>
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
              <label className="onb-block-label">À qui tu t&apos;adresses&nbsp;?</label>
              <div className="onb-toggle">
                <button
                  type="button"
                  className={"onb-toggle-btn" + (sel.audienceMode === "niche" ? " selected" : "")}
                  onClick={() => up({ audienceMode: "niche" })}
                >
                  Une cible précise
                </button>
                <button
                  type="button"
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
              <button type="button" className="onb-back" onClick={onSkip}>Passer</button>
              <button type="button" className="onb-cta" onClick={() => setStep("page2")}>
                Continuer <ChevronRight size={16} />
              </button>
            </div>
          </div>
        )}

        {step === "page2" && (
          <div className="onb-screen" key="page2">
            <h2 className="onb-greeting">Presque fini</h2>
            <p className="onb-lead">Deux derniers points et c&apos;est parti — ensuite tu crées ton compte.</p>

            <div className="onb-block">
              <label className="onb-block-label">Ton objectif sur LinkedIn</label>
              <OnbChips options={ONB_OBJECTIVE_OPTIONS} field={sel.objective} onChange={(v) => up({ objective: v })} />
            </div>

            <div className="onb-block">
              <label className="onb-block-label">Ton secteur</label>
              <OnbChips options={ONB_INDUSTRY_OPTIONS} field={sel.industry} onChange={(v) => up({ industry: v })} />
            </div>

            <div className="onb-nav">
              <button type="button" className="onb-back" onClick={() => setStep("page1")}>
                <ChevronLeft size={16} /> Retour
              </button>
              <button
                type="button"
                className="onb-cta"
                onClick={leadFunnel ? toGains : finish}
                disabled={saving}
              >
                {saving ? <Loader2 size={16} className="spinning" /> : <Sparkles size={16} />}{" "}
                {leadFunnel ? "Voir ce que je peux gagner" : finishLabel}
              </button>
            </div>
          </div>
        )}

        {step === "gains" && (
          <div className="onb-screen onb-analysis" key="gains">
            <h2 className="onb-analysis-title">Ce que tu peux gagner</h2>
            <p className="onb-analysis-summary" style={{ opacity: 0.8 }}>
              En tenant ton LinkedIn et en prospectant les bonnes personnes, voici ce que
              donne un trimestre.
            </p>

            {!projection ? (
              <div className="onb-scan" style={{ padding: "28px 0" }}>
                <Loader2 size={26} className="spinning" />
              </div>
            ) : (
              <>
                <div className="onb-gain-grid">
                  <div className="onb-gain-card">
                    <div className="onb-gain-label">Abonnés dans 90 jours</div>
                    <div className="onb-gain-value">{fmtRange(projection.followers_after, fmtInt)}</div>
                    <div className="onb-gain-hint">
                      aujourd&apos;hui {fmtInt(projection.followers_now)} · +{fmtRange(projection.followers_gain, fmtInt)}
                    </div>
                  </div>
                  <div className="onb-gain-card">
                    <div className="onb-gain-label">Nouvelles relations ciblées</div>
                    <div className="onb-gain-value">{fmtRange(projection.relations_per_month, fmtInt)}</div>
                    <div className="onb-gain-hint">par mois</div>
                  </div>
                  <div className="onb-gain-card">
                    <div className="onb-gain-label">Conversations qualifiées</div>
                    <div className="onb-gain-value">{fmtRange(projection.conversations_per_month, fmtInt)}</div>
                    <div className="onb-gain-hint">par mois</div>
                  </div>
                  <div className="onb-gain-card">
                    <div className="onb-gain-label">Nouveaux clients</div>
                    <div className="onb-gain-value">{fmtRange(projection.clients_per_month, fmtInt)}</div>
                    <div className="onb-gain-hint">par mois</div>
                  </div>
                </div>

                <div className="onb-analysis-block">
                  <div className="onb-analysis-label">Ton panier moyen</div>
                  <div className="onb-analysis-tags">
                    {bands.map((b) => (
                      <button
                        key={b.key}
                        type="button"
                        className={"onb-band" + (b.key === bandKey ? " selected" : "")}
                        aria-pressed={b.key === bandKey}
                        onClick={() => setBandKey(b.key)}
                      >
                        {b.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="onb-gain-highlight">
                  <div className="onb-gain-label">Chiffre d&apos;affaires mensuel supplémentaire</div>
                  <div className="onb-gain-money">{fmtRange(projection.revenue_per_month, fmtMoney)}</div>
                </div>

                <div className="onb-note">
                  {(band?.assumptions || []).map((line) => (
                    <div key={line}>{line}</div>
                  ))}
                </div>

                <button type="button" className="onb-analysis-cta" onClick={() => setStep("simulation")}>
                  Voir mon profil dans 90 jours
                </button>
              </>
            )}

            <button type="button" className="onb-analysis-skip" onClick={() => setStep("page2")}>
              ← Retour
            </button>
          </div>
        )}

        {step === "simulation" && projection && (
          <div className="onb-screen onb-analysis" key="simulation">
            <h2 className="onb-analysis-title">Ton profil dans 90 jours</h2>
            <p className="onb-analysis-summary" style={{ opacity: 0.8 }}>
              À gauche ton compte aujourd&apos;hui, à droite la même page une fois la
              machine lancée.
            </p>

            <div className="onb-sim-grid">
              <SimCard
                variant="before"
                caption="Aujourd'hui"
                preview={preview}
                followers={projection.followers_now}
                invites={0}
                messages={0}
                offers={0}
              />
              <SimCard
                variant="after"
                caption="Dans 90 jours"
                preview={preview}
                followers={projection.followers_after.high}
                invites={projection.relations_per_month.high}
                messages={projection.conversations_per_month.high}
                offers={projection.clients_per_month.high}
              />
            </div>

            <div className="onb-note">
              Simulation à partir des fourchettes hautes de l&apos;écran précédent.
              Aucune donnée réelle de ton compte n&apos;est modifiée.
            </div>

            <button type="button" className="onb-analysis-cta" onClick={() => setStep("lead_form")}>
              Recevoir mon audit complet gratuit
            </button>
            <button type="button" className="onb-analysis-skip" onClick={() => setStep("gains")}>
              ← Retour aux chiffres
            </button>
          </div>
        )}

        {step === "lead_form" && (
          <div className="onb-screen onb-analysis" key="lead_form">
            <h2 className="onb-analysis-title">Ton audit complet, offert</h2>
            <p className="onb-analysis-summary" style={{ opacity: 0.85 }}>
              Tu le reçois par e-mail : ton titre et ta section « Infos » réécrits,
              3 concepts de bannière, les comptes à suivre dans ta niche, tes angles
              de posts, ton ciblage de prospection et un plan sur 90 jours.
            </p>

            <div className="onb-analysis-card">
              <label className="onb-analysis-label" htmlFor="lead-name">Nom et prénom</label>
              <input
                id="lead-name"
                className="onb-dark-input"
                value={lead.name}
                onChange={(e) => setLead({ ...lead, name: e.target.value })}
                placeholder="Camille Durand"
                autoComplete="name"
              />

              <label className="onb-analysis-label" htmlFor="lead-email" style={{ marginTop: 14 }}>E-mail</label>
              <input
                id="lead-email"
                className="onb-dark-input"
                type="email"
                value={lead.email}
                onChange={(e) => setLead({ ...lead, email: e.target.value })}
                placeholder="camille@exemple.com"
                autoComplete="email"
              />

              <label className="onb-analysis-label" htmlFor="lead-phone" style={{ marginTop: 14 }}>Téléphone</label>
              <input
                id="lead-phone"
                className="onb-dark-input"
                type="tel"
                value={lead.phone}
                onChange={(e) => setLead({ ...lead, phone: e.target.value })}
                placeholder="06 12 34 56 78"
                autoComplete="tel"
                onKeyDown={(e) => { if (e.key === "Enter") submitLead(); }}
              />
            </div>

            <div className="onb-note">
              Ces informations servent à t&apos;envoyer ton audit et à te recontacter à
              ce sujet. Rien d&apos;autre.
            </div>

            {leadError && <div className="onb-error">{leadError}</div>}

            <button type="button" className="onb-analysis-cta" onClick={submitLead} disabled={saving}>
              {saving ? <Loader2 size={16} className="spinning" /> : <Mail size={16} />}{" "}
              Recevoir mon audit gratuit
            </button>
            <button type="button" className="onb-analysis-skip" onClick={finish}>
              Je préfère créer mon compte directement
            </button>
          </div>
        )}

        {step === "lead_done" && (
          <div className="onb-screen onb-analysis" key="lead_done">
            <div className="onb-done-badge"><CheckCircle2 size={30} /></div>
            <h2 className="onb-analysis-title" style={{ textAlign: "center" }}>C&apos;est envoyé</h2>
            <div className="onb-analysis-card" style={{ textAlign: "center" }}>
              <p className="onb-analysis-summary">
                Ton audit complet arrive par e-mail sur <strong>{lead.email}</strong> dans
                les prochaines minutes.
              </p>
              <p className="onb-analysis-summary" style={{ marginTop: 10, opacity: 0.8 }}>
                On t&apos;emmène choisir un créneau de 15 minutes pour le passer en revue
                ensemble.
              </p>
            </div>
            {calendlyUrl && (
              <a className="onb-analysis-cta" href={calendlyUrl} style={{ textDecoration: "none" }}>
                Choisir mon créneau <ChevronRight size={16} />
              </a>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Une carte de la simulation « avant / après ».
 *
 * C'est une mise en scène, pas une capture : la photo et le nom viennent du
 * scrape (donc du vrai compte), les compteurs viennent de la projection affichée
 * juste avant. Rien n'est inventé ici qui n'ait déjà été montré et justifié.
 */
function SimCard({
  variant,
  caption,
  preview,
  followers,
  invites,
  messages,
  offers,
}: {
  variant: "before" | "after";
  caption: string;
  preview: OnboardingPreview | null;
  followers: number;
  invites: number;
  messages: number;
  offers: number;
}) {
  const name = preview?.name || "Ton profil";
  return (
    <div className={"onb-sim-card" + (variant === "after" ? " onb-sim-after" : "")}>
      <div className="onb-sim-caption">{caption}</div>
      <div className="onb-sim-banner" />
      {preview?.avatar_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img className="onb-sim-avatar onb-sim-avatar-img" src={preview.avatar_url} alt="" />
      ) : (
        <div className="onb-sim-avatar" aria-hidden>{initials(name, preview?.handle || "")}</div>
      )}
      <div className="onb-sim-name">{name}</div>
      <div className="onb-sim-followers">{fmtInt(followers)} abonnés</div>
      <div className="onb-sim-rows">
        <SimRow icon={<Users size={14} />} label="Invitations reçues" value={invites} />
        <SimRow icon={<MessageSquare size={14} />} label="Messages non lus" value={messages} />
        <SimRow icon={<Briefcase size={14} />} label="Propositions" value={offers} />
      </div>
    </div>
  );
}

function SimRow({ icon, label, value }: { icon: React.ReactNode; label: string; value: number }) {
  return (
    <div className="onb-sim-row">
      <span className="onb-sim-row-icon">{icon}</span>
      <span className="onb-sim-row-label">{label}</span>
      <span className={"onb-sim-badge" + (value > 0 ? " active" : "")}>{value > 0 ? value : "—"}</span>
    </div>
  );
}
