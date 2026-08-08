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
  Bell,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Linkedin,
  Loader2,
  Mail,
  Sparkles,
  Target,
  TrendingUp,
  Users,
} from "lucide-react";
import { authHeaders } from "../lib/supabase";

const DIRECT_API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "https://analyseur-linkedin-influenceur-api-eu.onrender.com";

/** Fin du tunnel « audit complet » : choix d'un créneau de 15 min avec Tom. */
const CALENDLY_URL = "https://calendly.com/tom-clareo-solutions/15min";

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

// --- Onboarding « Cible » : wizard accueil → scan → analyse → confirmation ---
// Parcours anonyme (/start) uniquement, après l'analyse : gains → simulation →
// formulaire (audit complet par e-mail) → Calendly. Le wizard des comptes
// connectés garde son chemin historique analyse → chips (page1/page2).
type OnbStep =
  | "intro" | "scanning" | "analysis" | "analysis_detail"
  | "gains" | "simulation" | "leadform" | "leadsent"
  | "page1" | "page2";
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

/** Projection prudente d'abonnés pour la SIMULATION avant/après (étiquetée comme
 * telle à l'écran) : jamais présentée comme une promesse, juste un ordre de
 * grandeur cohérent avec le point de départ réel scrapé. */
function projectFollowers(current: number): number {
  if (!current || current <= 0) return 750;
  return Math.max(current + 250, Math.round(current * 1.35));
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
  onFinish,
  onSkip,
  finishLabel = "C'est parti",
}: {
  /** true = visiteur sans compte : analyse via la route publique, réponses rendues à l'appelant. */
  anonymous?: boolean;
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
  // Formulaire « audit complet » (tunnel anonyme) — les 3 champs sont obligatoires.
  const [leadName, setLeadName] = useState("");
  const [leadEmail, setLeadEmail] = useState("");
  const [leadPhone, setLeadPhone] = useState("");
  const [leadError, setLeadError] = useState("");
  const [leadSending, setLeadSending] = useState(false);

  const up = (patch: Partial<ReturnType<typeof onbInitSel>>) =>
    setSel((s) => ({ ...s, ...patch }));

  const inputKind: "linkedin" | "website" | "description" = (() => {
    const v = aiInput.trim();
    if (!v || /\s/.test(v)) return "description";
    if (/linkedin\.com\/in\//i.test(v)) return "linkedin";
    if (/^https?:\/\//i.test(v) || /^www\./i.test(v) || /^[\w-]+(\.[\w-]+)+(\/|$)/i.test(v)) return "website";
    return "description";
  })();

  // Confirmation lue (~4,5 s) puis départ vers Calendly dans le MÊME onglet :
  // la note « ton audit arrive par e-mail » doit avoir le temps d'être vue.
  useEffect(() => {
    if (step !== "leadsent") return;
    const id = setTimeout(() => { window.location.href = CALENDLY_URL; }, 4500);
    return () => clearTimeout(id);
  }, [step]);

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

  /** Envoie le lead « audit complet ». Le pack est généré et envoyé par e-mail
   * côté serveur (tâche de fond) — ici on passe direct à la confirmation. */
  async function submitLead() {
    const name = leadName.trim();
    const email = leadEmail.trim();
    const phone = leadPhone.trim();
    if (!name || !email || !phone) {
      setLeadError("Les trois champs sont obligatoires pour recevoir ton audit.");
      return;
    }
    setLeadError("");
    setLeadSending(true);
    try {
      const res = await fetch(`${DIRECT_API_URL}/onboarding/full-audit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          email,
          phone,
          linkedin_url: inputKind === "linkedin" ? aiInput.trim() : "",
          input_kind: inputKind,
          preview,
          profile: draft,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Envoi impossible — réessaie.");
      setStep("leadsent");
    } catch (err: any) {
      setLeadError(err?.message || "Envoi impossible — réessaie.");
    } finally {
      setLeadSending(false);
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
      await onFinish(merged);
    } catch {
      // L'appelant gère ses erreurs. Ici on relâche juste le bouton pour ne pas
      // laisser l'utilisateur bloqué sur un spinner définitif.
      setSaving(false);
    }
  }

  const showProgress = step === "page1" || step === "page2";
  const isAnalysis =
    step === "analysis" || step === "analysis_detail" ||
    step === "gains" || step === "simulation" || step === "leadform" || step === "leadsent";

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
              onClick={() => {
                // Visiteur sans compte : direction le tunnel audit complet
                // (gains → simulation → formulaire → Calendly). Compte connecté :
                // chemin historique vers les chips.
                if (anonymous) {
                  setLeadName(preview.name || "");
                  setStep("gains");
                } else {
                  setStep("page1");
                }
              }}
            >
              {anonymous ? "Ce que tu peux gagner" : "Continuer"} <ChevronRight size={16} />
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

        {step === "gains" && preview && (
          <div className="onb-screen onb-analysis" key="gains">
            <h2 className="onb-analysis-title">Ce que tu peux gagner</h2>
            <p className="onb-gains-sub">
              Fourchettes observées chez des profils comparables au tien (indépendants
              et dirigeants B2B) qui structurent leur LinkedIn — un ordre de grandeur,
              pas une promesse.
            </p>

            <div className="onb-gain-item">
              <div className="onb-gain-icon"><Mail size={18} /></div>
              <div>
                <div className="onb-gain-range">2 à 5 demandes de contact entrantes / semaine</div>
                <div className="onb-gain-how">en optimisant ton profil et tes posts</div>
              </div>
            </div>
            <div className="onb-gain-item">
              <div className="onb-gain-icon"><Target size={18} /></div>
              <div>
                <div className="onb-gain-range">5 à 15 conversations qualifiées / mois</div>
                <div className="onb-gain-how">avec une prospection ciblée sur ta niche</div>
              </div>
            </div>
            <div className="onb-gain-item">
              <div className="onb-gain-icon"><TrendingUp size={18} /></div>
              <div>
                <div className="onb-gain-range">×2 à ×3 de portée sur tes posts</div>
                <div className="onb-gain-how">avec des structures qui ont fait leurs preuves</div>
              </div>
            </div>

            <button type="button" className="onb-analysis-cta" onClick={() => setStep("simulation")}>
              Voir mon profil dans 90 jours <ChevronRight size={16} />
            </button>
            <button type="button" className="onb-analysis-skip" onClick={() => setStep("analysis_detail")}>
              ← Retour
            </button>
          </div>
        )}

        {step === "simulation" && preview && (
          <div className="onb-screen onb-analysis" key="simulation">
            <h2 className="onb-analysis-title">Ton profil dans 90 jours</h2>
            <p className="onb-gains-sub">
              Simulation basée sur des trajectoires de profils comparables — pas une
              promesse chiffrée.
            </p>

            <div className="onb-sim-card">
              <div className="onb-sim-banner">Bannière optimisée — proposition dans ton audit</div>
              <div className="onb-sim-head">
                {preview.avatar_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    className="onb-sim-avatar"
                    src={preview.avatar_url}
                    alt=""
                    onError={(e) => { e.currentTarget.style.display = "none"; }}
                  />
                ) : (
                  <div className="onb-sim-avatar onb-sim-avatar-fallback" aria-hidden>
                    {initials(preview.name, preview.handle)}
                  </div>
                )}
                <div>
                  <div className="onb-sim-name">{preview.name || "Ton profil"}</div>
                  <div className="onb-sim-headline">Titre de profil réécrit — 3 propositions dans ton audit</div>
                </div>
              </div>
              <div className="onb-sim-stats">
                <div className="onb-sim-stat">
                  <Users size={15} />
                  <div>
                    <strong>{fmtCompact(projectFollowers(preview.followers))}</strong>
                    <span>
                      abonnés{preview.followers > 0 ? ` (aujourd'hui ${fmtCompact(preview.followers)})` : ""}
                    </span>
                  </div>
                </div>
              </div>
              <div className="onb-sim-badge">
                <Mail size={15} />
                <span><strong>5 messages non lus</strong> — dont 2 demandes de mission</span>
              </div>
              <div className="onb-sim-badge">
                <Bell size={15} />
                <span><strong>12 demandes de contact</strong> reçues cette semaine</span>
              </div>
              <div className="onb-sim-tag">Simulation</div>
            </div>

            <button type="button" className="onb-analysis-cta" onClick={() => setStep("leadform")}>
              Recevoir mon audit complet gratuit <ChevronRight size={16} />
            </button>
            <button type="button" className="onb-analysis-skip" onClick={() => setStep("gains")}>
              ← Retour
            </button>
          </div>
        )}

        {step === "leadform" && (
          <div className="onb-screen onb-analysis" key="leadform">
            <h2 className="onb-analysis-title">Ton audit complet, offert</h2>
            <p className="onb-gains-sub">
              Par e-mail : plan d&apos;action 90 jours, titres de profil prêts à copier,
              section « À propos », concepts de bannière, influenceurs à suivre dans ta
              niche, angles de posts et ciblage de prospection.
            </p>

            <div className="onb-lead-form">
              <label className="onb-lead-label">Nom et prénom *</label>
              <input
                className="onb-lead-input"
                value={leadName}
                onChange={(e) => setLeadName(e.target.value)}
                placeholder="Ton nom et prénom"
                autoComplete="name"
              />
              <label className="onb-lead-label">E-mail *</label>
              <input
                className="onb-lead-input"
                type="email"
                value={leadEmail}
                onChange={(e) => setLeadEmail(e.target.value)}
                placeholder="toi@exemple.com"
                autoComplete="email"
              />
              <label className="onb-lead-label">Téléphone *</label>
              <input
                className="onb-lead-input"
                type="tel"
                value={leadPhone}
                onChange={(e) => setLeadPhone(e.target.value)}
                placeholder="06 12 34 56 78"
                autoComplete="tel"
              />
            </div>

            <div className="onb-lead-note">
              📩 Ton audit complet arrive par e-mail d&apos;ici quelques minutes. Ensuite,
              choisis un créneau de 15 min avec Tom pour le décoder ensemble.
            </div>

            {leadError && <div className="onb-lead-error">{leadError}</div>}

            <button
              type="button"
              className="onb-analysis-cta"
              onClick={submitLead}
              disabled={leadSending}
            >
              {leadSending ? <Loader2 size={16} className="spinning" /> : <Sparkles size={16} />}
              Recevoir mon audit complet gratuit
            </button>
            <button type="button" className="onb-analysis-skip" onClick={() => setStep("simulation")}>
              ← Retour
            </button>
          </div>
        )}

        {step === "leadsent" && (
          <div className="onb-screen onb-analysis onb-leadsent" key="leadsent">
            <div className="onb-leadsent-icon"><CheckCircle2 size={40} /></div>
            <h2 className="onb-analysis-title">C&apos;est noté !</h2>
            <p className="onb-gains-sub">
              Ton audit complet arrive <strong>par e-mail</strong> d&apos;ici quelques
              minutes. On t&apos;emmène choisir ton créneau de 15 min avec Tom…
            </p>
            <div className="onb-leadsent-wait"><Loader2 size={18} className="spinning" /> Redirection en cours</div>
            <a className="onb-analysis-cta" href={CALENDLY_URL}>
              Choisir mon créneau maintenant
            </a>
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
              <button type="button" className="onb-cta" onClick={finish} disabled={saving}>
                {saving ? <Loader2 size={16} className="spinning" /> : <Sparkles size={16} />} {finishLabel}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
