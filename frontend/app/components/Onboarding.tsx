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
  Globe,
  Linkedin,
  Loader2,
  Lock,
  Mail,
  MessageSquare,
  Sparkles,
  Target,
  Users,
} from "lucide-react";
import { authHeaders } from "../lib/supabase";
import { FOUNDERS_FIRST_MONTH_OFF_PCT, FOUNDERS_TESTIMONIAL } from "../lib/founders";

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
// Sur les tunnels de landing, le parcours ne s'arrête pas à la confirmation : il
// enchaîne sur les gains projetés puis une simulation « avant / après ». Il se
// termine soit sur l'échange audit complet ↔ coordonnées (/start), soit sur le
// démarrage de l'essai gratuit (/founders).
type OnbStep =
  | "intro"
  | "scanning"
  | "analysis"
  | "analysis_detail"
  | "page1"
  | "page2"
  | "gains"
  | "simulation"
  | "pitch"
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

// --- Variante « fondateurs SaaS » (/founders) --------------------------------
//
// Ce ne sont PAS les mêmes questions traduites : un fondateur de SaaS ne se
// reconnaît ni dans « Coachs & consultants » ni dans « Des prestations
// sur-mesure ». Des chips où personne ne se retrouve poussent tout le monde vers
// « Autre », et le profil éditorial reparti en texte libre perd la qualification
// que ces écrans existent pour produire.

const ONB_SAAS_AUDIENCE_OPTIONS: OnbOption[] = [
  { label: "Fondateurs & CEO de SaaS", match: ["fondateur", "founder", "ceo", "saas"] },
  { label: "CTO & équipes tech", match: ["cto", "tech lead", "développeur", "engineering", "dev"] },
  { label: "Head of Growth / Marketing", match: ["growth", "marketing", "cmo", "acquisition"] },
  { label: "Product managers", match: ["product", "pm", "produit"] },
  { label: "Ops & RevOps", match: ["ops", "revops", "opérations"] },
  { label: "PME en digitalisation", match: ["pme", "tpe", "dirigeant", "digitalisation"] },
  { label: "Investisseurs & VCs", match: ["investisseur", "vc", "business angel", "fonds"] },
];

const ONB_SAAS_OFFER_OPTIONS: OnbOption[] = [
  { label: "Un SaaS en self-serve", match: ["self-serve", "freemium", "abonnement", "plg"] },
  { label: "Un SaaS vendu en démo", match: ["démo", "demo", "sales", "b2b", "saas", "logiciel"] },
  { label: "Une API / de l'infra dev", match: ["api", "infra", "sdk", "devtool", "librairie"] },
  { label: "Une marketplace / plateforme", match: ["marketplace", "plateforme", "place de marché"] },
  { label: "Un produit IA", match: ["ia", "ai", "llm", "intelligence artificielle", "agent"] },
  { label: "Du service autour du produit", match: ["service", "intégration", "onboarding", "conseil", "prestation"] },
];

const ONB_SAAS_OBJECTIVE_OPTIONS: OnbOption[] = [
  { label: "Générer des démos qualifiées", match: ["démo", "demo", "lead", "prospect", "rendez-vous", "pipeline"] },
  { label: "Trouver mes premiers clients", match: ["premier client", "traction", "early adopter", "acquisition"] },
  { label: "Construire ma marque de fondateur", match: ["notoriété", "personal branding", "marque", "visibilité", "audience"] },
  { label: "Recruter (tech, sales)", match: ["recrut", "talent", "embauche", "hiring", "équipe"] },
  { label: "Préparer une levée", match: ["levée", "fundraising", "investisseur", "seed", "série a"] },
  { label: "Fédérer une communauté d'utilisateurs", match: ["communauté", "community", "utilisateurs", "users"] },
];

const ONB_SAAS_INDUSTRY_OPTIONS: OnbOption[] = [
  { label: "IA & LLM", match: ["ia", "ai", "llm", "intelligence artificielle", "machine learning"] },
  { label: "DevTools & infra", match: ["devtool", "infra", "cloud", "api", "engineering"] },
  { label: "Fintech", match: ["fintech", "paiement", "banque", "finance", "compta"] },
  { label: "Data & analytics", match: ["data", "analytics", "bi", "reporting"] },
  { label: "Vertical SaaS (santé, immo, industrie…)", match: ["santé", "immo", "industrie", "vertical", "legal", "retail"] },
  { label: "Marketing & Growth tech", match: ["marketing", "growth", "crm", "ads"] },
  { label: "HR tech", match: ["rh", "hr", "recrutement", "talent"] },
  { label: "Cybersécurité", match: ["cyber", "sécurité", "security", "soc"] },
];

// Qualification fondateur (tunnel SaaS uniquement), posée PENDANT le scan du
// site : l'analyse prend de longues secondes, ces deux questions occupent
// l'attente au lieu d'ajouter une page. Chaque option porte sa raison d'être en
// sous-titre — le visiteur doit voir POURQUOI on demande, et l'écran de closing
// lui renvoie ses propres mots (effet miroir : ce sont ses obstacles à lui, pas
// un argumentaire générique).
const ONB_SAAS_STAGES: { label: string; hint: string }[] = [
  { label: "Pre-revenue", hint: "Je construis — pas encore de clients payants" },
  { label: "Premiers clients", hint: "Du revenu, pas encore de croissance régulière" },
  { label: "En croissance", hint: "Le product-market fit est là, je cherche le prochain levier" },
];

const ONB_SAAS_OBSTACLES: string[] = [
  "Je suis un builder, pas un marketeur",
  "Pas le temps de créer du contenu",
  "Je ne sais pas quoi raconter",
  "Ma prospection ne scale pas",
  "Je lance dans le silence",
];

// Sur /founders, le premier champ accepte le site du SaaS OU la page LinkedIn —
// un seul champ, pas d'onglets (cf. `inputKind` plus bas, qui détecte laquelle a
// été collée). L'animation de scan doit décrire ce qui a VRAIMENT été lu, jamais
// l'URI de la page ni la variante : ces trois jeux de libellés sont choisis par
// la source détectée dans le champ, exactement le principe du correctif du
// 2026-08-11 (l'honnêteté suit les données lues, pas l'endroit où on se trouve).
const ONB_SAAS_SCAN_STEPS_SITE = [
  "Lecture de ton site…",
  "On cerne ton produit et ta promesse…",
  "Identification de ton ICP…",
  "On peaufine tout ça…",
];
const ONB_SAAS_SCAN_STEPS_LINKEDIN = [
  "Lecture de ton profil…",
  "Analyse de ton audience…",
  "Identification de ton ICP…",
  "On peaufine tout ça…",
];
const ONB_SAAS_SCAN_STEPS_DESCRIPTION = [
  "Lecture de ta description…",
  "On cerne ton produit et ta promesse…",
  "Identification de ton ICP…",
  "On peaufine tout ça…",
];

/** Ce que le visiteur a réellement collé dans le premier champ. */
type OnbInputKind = "linkedin" | "linkedin_company" | "website" | "description";

/** Étapes de scan affichées pendant `step === "scanning"` sur le tunnel SaaS. */
function onbSaasScanSteps(kind: OnbInputKind): string[] {
  if (kind === "linkedin") return ONB_SAAS_SCAN_STEPS_LINKEDIN;
  if (kind === "description") return ONB_SAAS_SCAN_STEPS_DESCRIPTION;
  return ONB_SAAS_SCAN_STEPS_SITE; // website + repli (company bloqué avant d'arriver ici)
}

/** Badge affiché sur l'écran d'analyse quand rien n'a été scrapé (photo/compteurs absents). */
function onbSourceLabel(kind: OnbInputKind): string {
  if (kind === "linkedin") return "Analysé depuis ton profil";
  if (kind === "description") return "Analysé depuis ta description";
  return "Analysé depuis ton site";
}

/** Ce qui change d'une audience de tunnel à l'autre : les chips et les mots. */
type OnbVariant = {
  /** Audience envoyée au serveur — décide de la grille de paliers de la projection. */
  audience: string;
  introTitle: string;
  introSubtitle: string;
  /** Ce qu'on demande sur le premier écran — et donc ce qui sera analysé. */
  introPlaceholder: string;
  introSkipLabel: string;
  introError: string;
  audienceLabel: string;
  offerLabel: string;
  objectiveLabel: string;
  industryLabel: string;
  gainsTitle: string;
  gainsIntro: string;
  /** Étapes de l'animation de scan — elles doivent décrire la source RÉELLE. */
  scanSteps: string[];
  audienceOptions: OnbOption[];
  offerOptions: OnbOption[];
  objectiveOptions: OnbOption[];
  industryOptions: OnbOption[];
};

const ONB_VARIANTS: Record<"default" | "saas", OnbVariant> = {
  default: {
    audience: "default",
    introTitle: "Bienvenue sur Cible",
    introSubtitle: "Colle ton profil LinkedIn, on prépare tout le reste pour toi.",
    introPlaceholder: "https://linkedin.com/in/ton-profil",
    introSkipLabel: "Continuer sans LinkedIn",
    introError: "Colle ton URL LinkedIn (ou une courte description).",
    audienceLabel: "À qui tu t'adresses ?",
    offerLabel: "Ce que tu proposes",
    objectiveLabel: "Ton objectif sur LinkedIn",
    industryLabel: "Ton secteur",
    gainsTitle: "Ce que tu peux gagner",
    gainsIntro:
      "En tenant ton LinkedIn et en prospectant les bonnes personnes, voici ce que donne un trimestre.",
    scanSteps: ONB_SCAN_STEPS,
    audienceOptions: ONB_AUDIENCE_OPTIONS,
    offerOptions: ONB_OFFER_OPTIONS,
    objectiveOptions: ONB_OBJECTIVE_OPTIONS,
    industryOptions: ONB_INDUSTRY_OPTIONS,
  },
  saas: {
    audience: "saas",
    introTitle: "Le LinkedIn qui remplit ton pipeline",
    introSubtitle:
      "Colle le lien de ton SaaS ou de ta page LinkedIn : on lit ce que tu as, puis on te montre ce que LinkedIn peut lui rapporter.",
    introPlaceholder: "https://ton-saas.com  ou  linkedin.com/in/toi",
    // Un lien LinkedIn collé ici est accepté au même titre qu'un site — un seul
    // champ, pas d'onglets (cf. `inputKind`). On demande les deux, on ne refuse
    // ni l'un ni l'autre.
    introSkipLabel: "Continuer sans lien",
    introError: "Colle un lien (site ou LinkedIn) ou une courte description.",
    audienceLabel: "Ton ICP — à qui tu vends ?",
    offerLabel: "Ce que tu vends",
    objectiveLabel: "Ce que tu attends de LinkedIn",
    industryLabel: "Ta catégorie de produit",
    gainsTitle: "Ce que ça peut rapporter à ton SaaS",
    gainsIntro:
      "En publiant régulièrement et en prospectant ton ICP depuis l'app, voici ce que donne un trimestre.",
    // Repli par défaut (variant.scanSteps n'est plus utilisé tel quel côté SaaS :
    // le composant calcule `scanSteps` depuis `inputKind` via `onbSaasScanSteps`,
    // cf. plus bas — ce champ ne sert que de valeur par défaut avant saisie).
    scanSteps: ONB_SAAS_SCAN_STEPS_SITE,
    audienceOptions: ONB_SAAS_AUDIENCE_OPTIONS,
    offerOptions: ONB_SAAS_OFFER_OPTIONS,
    objectiveOptions: ONB_SAAS_OBJECTIVE_OPTIONS,
    industryOptions: ONB_SAAS_INDUSTRY_OPTIONS,
  },
};

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

/** Prix catalogue (peut être décimal : 29,40 €). */
function fmtPrice(n: number): string {
  const rounded = Math.round(n * 100) / 100;
  return `${rounded.toLocaleString("fr-FR", {
    minimumFractionDigits: Number.isInteger(rounded) ? 0 : 2,
    maximumFractionDigits: 2,
  })} €`;
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

function onbInitSel(d: Record<string, string>, variant: OnbVariant) {
  const audience = onbField(d.target_audience, variant.audienceOptions);
  return {
    displayName: (d.display_name || "").trim(),
    audienceMode: (audience.picks.length || audience.other ? "niche" : "") as "" | "niche" | "large",
    audience,
    offer: onbField(d.core_offer, variant.offerOptions),
    objective: onbField(d.linkedin_objective, variant.objectiveOptions),
    industry: onbField(d.industry, variant.industryOptions),
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
  funnel = "app",
  variant: variantKey = "default",
  trialDays = 7,
  planPrice = 49,
  monthlySeats: _monthlySeats = 0,
  guaranteeDays: _guaranteeDays = 0,
  onFinish,
  onSkip,
  finishLabel = "C'est parti",
}: {
  /** true = visiteur sans compte : analyse via la route publique, réponses rendues à l'appelant. */
  anonymous?: boolean;
  /**
   * Ce qui suit les questions :
   *  - `app`   : rien de plus — le wizard in-app (compte déjà créé) rend la main.
   *  - `audit` : gains projetés → simulation → coordonnées → audit par e-mail (/start).
   *  - `trial` : gains projetés → simulation → essai gratuit (/founders). Pas de
   *    formulaire de coordonnées : l'e-mail est capturé par la création de compte,
   *    en demander un ici serait le demander deux fois.
   */
  funnel?: "app" | "audit" | "trial";
  /** Jeu de questions et de formulations (`saas` = tunnel fondateurs). */
  variant?: "default" | "saas";
  /**
   * Durée de l'essai annoncée sur le bouton final (`funnel="trial"`).
   * Elle vient du serveur via l'appelant, jamais d'une constante : un bouton qui
   * promet 7 jours quand Stripe en accorde 14 (ou zéro) est un mensonge que rien
   * ne rattrape ensuite.
   */
  trialDays?: number;
  /** Prix mensuel affiché dans le cadrage ROI — vient de Stripe via l'appelant. */
  planPrice?: number;
  /** Places ouvertes par mois (engagement réel, cf. lib/founders.ts). 0 = masqué. */
  monthlySeats?: number;
  /** Jours de garantie « satisfait ou remboursé » après l'essai. 0 = masqué. */
  guaranteeDays?: number;
  /** Reçoit le profil complet. L'appelant décide : enregistrer, ou emmener vers l'inscription. */
  onFinish: (profile: OnboardingProfile) => void | Promise<void>;
  /** « Passer » — l'utilisateur refuse de répondre. */
  onSkip: () => void;
  finishLabel?: string;
}) {
  const variant = ONB_VARIANTS[variantKey] || ONB_VARIANTS.default;
  // Les écrans de projection sont communs aux deux tunnels de landing ; seul ce
  // qui les suit diffère.
  const showsProjection = funnel === "audit" || funnel === "trial";
  const [step, setStep] = useState<OnbStep>("intro");
  const [aiInput, setAiInput] = useState("");
  const [error, setError] = useState("");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<OnboardingPreview | null>(null);
  const [sel, setSel] = useState(() => onbInitSel({}, variant));
  const [saving, setSaving] = useState(false);
  const [scanIdx, setScanIdx] = useState(0);
  /**
   * Résultat de l'analyse, en attente d'être appliqué (tunnel SaaS uniquement).
   *
   * ⚠️ Sur ce tunnel, l'écran de scan porte les questions de qualification : on
   * n'arrache JAMAIS l'écran quand l'analyse aboutit — le visiteur est peut-être
   * en train de cocher. Le résultat attend ici, et c'est SON clic qui avance.
   */
  const [scanResult, setScanResult] = useState<
    { profile: Record<string, string>; preview: OnboardingPreview | null } | null
  >(null);
  /**
   * Où en est le quiz du scan (tunnel SaaS) : 0 = animation seule (la pop-up
   * n'apparaît qu'après ~2,5 s — l'animation doit d'abord s'installer), 1 =
   * question du stade, 2 = question des obstacles, 3 = quiz terminé (retour à
   * l'animation si l'analyse n'est pas finie — l'avancée devient automatique,
   * il n'y a plus de choix à protéger).
   */
  const [quizIdx, setQuizIdx] = useState(0);
  // Qualification fondateur (pendant le scan, tunnel SaaS) — sert l'effet miroir
  // du closing. Volontairement hors du profil éditorial : le backend ignorerait
  // ces clés en silence, autant ne pas prétendre les enregistrer.
  const [stage, setStage] = useState("");
  const [obstacles, setObstacles] = useState<string[]>([]);
  // « Autre » : le blocage dans SES mots — c'est même le meilleur carburant du
  // miroir, puisque le closing le lui rendra tel quel.
  const [obstacleOther, setObstacleOther] = useState("");
  const [showObstacleOther, setShowObstacleOther] = useState(false);
  // Les obstacles restent captés pendant le scan (qualification) — plus restitués
  // au closing (paywall minimal).

  // --- Tunnel « audit complet » (landing uniquement) ---
  const [bands, setBands] = useState<OnbBand[]>([]);
  // Renseigné par la réponse du serveur (`default_band`) : les clés de paliers
  // diffèrent d'une audience à l'autre, en coder une en dur ici ferait retomber
  // l'écran SaaS sur le premier palier venu.
  const [bandKey, setBandKey] = useState<string>("");
  // Libellés des montants, fournis par le serveur avec les paliers : la grille
  // SaaS raisonne en ARR signé, pas en chiffre d'affaires du mois. Les écrire en
  // dur côté navigateur les ferait mentir dès que la grille change côté serveur.
  const [dealLabel, setDealLabel] = useState("Ton panier moyen");
  const [revenueLabel, setRevenueLabel] = useState("Chiffre d'affaires mensuel supplémentaire");
  const [lead, setLead] = useState({ name: "", email: "", phone: "" });
  const [leadError, setLeadError] = useState("");
  const [calendlyUrl, setCalendlyUrl] = useState("");

  /**
   * A-t-on lu un vrai compte LinkedIn (photo, abonnés, posts) ou seulement un site ?
   * Tout ce qui prétend décrire la PERSONNE — avatar, nom de profil, compteurs —
   * dépend de cette réponse. Un site ne dit rien du compte de son fondateur.
   */
  const hasScrapedProfile = !!preview && (
    !!preview.avatar_url || preview.followers > 0 || preview.posts_count > 0
  );

  const band = bands.find((b) => b.key === bandKey) || bands[0] || null;
  const projection = band?.projection || null;
  /**
   * A-t-on vraiment lu l'audience du compte ?
   *
   * ⚠️ Sur le tunnel fondateurs, l'entrée est le site du SaaS : aucun profil
   * LinkedIn n'est scrapé, donc `followers_now` vaut 0 — ce qui ne veut PAS dire
   * « ce compte a zéro abonné ». Afficher « aujourd'hui 0 » ou « 0 abonnés » à
   * quelqu'un qui en a 2 000 serait faux, et c'est le genre d'erreur qui fait
   * fermer l'onglet. On montre alors le GAIN, jamais un état actuel inventé.
   */
  const hasAudienceData = (projection?.followers_now || 0) > 0;

  const up = (patch: Partial<ReturnType<typeof onbInitSel>>) =>
    setSel((s) => ({ ...s, ...patch }));

  const inputKind: OnbInputKind = (() => {
    const v = aiInput.trim();
    if (!v || /\s/.test(v)) return "description";
    // Page entreprise : le distinguer d'un profil personnel AVANT toute autre
    // règle — sinon elle tomberait dans "website" (login-wall LinkedIn, analyse
    // creuse sans la moindre erreur, cf. piège documenté sur ce lot).
    if (/linkedin\.com\/company\//i.test(v)) return "linkedin_company";
    if (/linkedin\.com\/in\//i.test(v)) return "linkedin";
    // Lien court LinkedIn (lnkd.in) : jamais traité comme un site quelconque.
    if (/^https?:\/\/(www\.)?lnkd\.in\//i.test(v)) return "linkedin";
    if (/^https?:\/\//i.test(v) || /^www\./i.test(v) || /^[\w-]+(\.[\w-]+)+(\/|$)/i.test(v)) return "website";
    return "description";
  })();

  // Tunnel SaaS uniquement : les étapes de scan doivent décrire ce qui a
  // VRAIMENT été collé, pas l'URI de la page (`variant === "saas"`). Le tunnel
  // /start (`default`) garde ses étapes fixes, inchangées.
  const scanSteps = variantKey === "saas" ? onbSaasScanSteps(inputKind) : variant.scanSteps;

  useEffect(() => {
    if (step !== "scanning") return;
    setScanIdx(0);
    const id = setInterval(
      () => setScanIdx((i) => (i < scanSteps.length - 1 ? i + 1 : i)),
      850,
    );
    return () => clearInterval(id);
  }, [step]);

  // La pop-up du quiz n'apparaît que ~2,5 s après le lancement : l'animation de
  // scan doit d'abord raconter ce qui se passe, sinon la question tombe avant
  // même que « Lecture de ton site… » ait été lu.
  useEffect(() => {
    if (step !== "scanning" || variantKey !== "saas") return;
    const id = setTimeout(() => setQuizIdx((i) => (i === 0 ? 1 : i)), 2500);
    return () => clearTimeout(id);
  }, [step, variantKey]);

  // Quiz terminé + analyse prête ⇒ on avance tout seul. C'est le SEUL cas
  // d'avancée automatique : tant qu'une question est à l'écran, le résultat
  // attend — on n'arrache pas un choix en cours.
  useEffect(() => {
    if (step === "scanning" && variantKey === "saas" && quizIdx === 3 && scanResult) {
      applyScanResult(scanResult.profile, scanResult.preview);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, quizIdx, scanResult]);

  /** Applique le brouillon + la preview et avance vers l'écran d'analyse. */
  function applyScanResult(d: Record<string, string>, p: OnboardingPreview | null) {
    setDraft(d);
    setSel(onbInitSel(d, variant));
    setPreview(p);
    setStep(p ? "analysis" : "page1");
  }

  async function analyze() {
    const trimmed = aiInput.trim();
    if (!trimmed) { setError(variant.introError); return; }
    // Page entreprise : on ne prétend pas la lire (login-wall LinkedIn côté
    // fetch site → résumé vide → analyse creuse sans la moindre erreur visible).
    // Refusé AVANT tout appel serveur, avec la marche à suivre.
    if (inputKind === "linkedin_company") {
      setError("On ne lit pas les pages entreprise — colle ton profil perso (linkedin.com/in/…).");
      return;
    }
    setError(""); setScanResult(null); setQuizIdx(0); setStep("scanning");
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
      const p = data.preview && data.preview.niche && data.preview.summary ? data.preview : null;
      if (variantKey === "saas") {
        // L'écran de scan porte les questions de qualification : le résultat
        // attend le clic du visiteur au lieu de lui arracher l'écran des mains.
        setScanResult({ profile: d, preview: p });
        return;
      }
      // L'analyse s'affiche sur les DEUX parcours (public /start ET wizard d'un
      // compte connecté) — sans elle, on saute directement aux questions.
      applyScanResult(d, p);
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
          audience: variant.audience,
        }),
      });
      if (!res.ok) throw new Error("projection indisponible");
      const data = await res.json();
      const list: OnbBand[] = Array.isArray(data?.bands) ? data.bands : [];
      if (list.length === 0) throw new Error("projection vide");
      setBands(list);
      setBandKey(data?.default_band || list[0].key);
      if (data?.deal_label) setDealLabel(data.deal_label);
      if (data?.revenue_label) setRevenueLabel(data.revenue_label);
    } catch {
      // Projection injoignable : on ne bloque pas le parcours sur un écran de mise
      // en scène. Le tunnel audit passe au formulaire, le tunnel essai va droit à
      // la création de compte — dans les deux cas, l'étape utile est atteinte.
      if (funnel === "trial") { void finish(); return; }
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
  const progressPct = step === "page1" ? "50%" : "100%";
  // Écrans qui gagnent à respirer sur grand écran (grilles et colonnes), par
  // opposition aux écrans de saisie où une colonne étroite reste plus lisible.
  // Paywall closing : colonne un peu plus large que le mobile, centrée.
  const isPitch = step === "pitch";
  const isWideStep =
    step === "analysis" ||
    step === "analysis_detail" ||
    step === "gains" ||
    step === "simulation" ||
    step === "lead_form";
  const isAnalysis =
    step === "analysis" ||
    step === "analysis_detail" ||
    step === "gains" ||
    step === "simulation" ||
    step === "pitch" ||
    step === "lead_form" ||
    step === "lead_done";

  return (
    <div className={"onb-overlay" + (isAnalysis ? " onb-overlay-analysis" : "")}>
      <div
        className={
          "onb-shell" +
          (isAnalysis ? " onb-shell-analysis" : "") +
          (isWideStep ? " onb-shell-wide" : "") +
          (isPitch ? " onb-shell-pitch" : "")
        }
      >
        {showProgress && (
          <div className="onb-progress">
            <div className="onb-progress-fill" style={{ width: progressPct }} />
          </div>
        )}

        {step === "intro" && (
          <div className="onb-screen" key="intro">
            <div className="onb-icon-badge"><Target size={26} /></div>
            <h1 className="onb-title">{variant.introTitle}</h1>
            <p className="onb-subtitle">{variant.introSubtitle}</p>
            <div className="onb-input-row">
              <input
                className="onb-input"
                value={aiInput}
                onChange={(e) => setAiInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") analyze(); }}
                placeholder={variant.introPlaceholder}
                autoFocus
              />
              <button type="button" className="onb-cta" onClick={analyze}>
                <Sparkles size={16} /> Analyser
              </button>
            </div>
            {error && <div className="onb-error">{error}</div>}
            <button type="button" className="onb-skip" onClick={() => setStep("page1")}>{variant.introSkipLabel}</button>
          </div>
        )}

        {step === "scanning" && (
          <div className="onb-screen onb-scan" key="scan">
            <div className="onb-orb">
              {/* L'icône suit ce qui a VRAIMENT été collé (inputKind), pas la
                  variante — un LinkedIn collé sur /founders garde son logo. Le
                  tunnel /start (default) garde son icône fixe, inchangée. */}
              {variantKey === "saas" ? (
                inputKind === "linkedin" ? <Linkedin size={34} /> : inputKind === "website" ? <Globe size={34} /> : <Sparkles size={34} />
              ) : (
                <Linkedin size={34} />
              )}
            </div>
            {/* « Analyse prête » ne s'affiche qu'une fois le quiz fini : pendant
                les questions, le statut continue de raconter le scan — annoncer
                la fin inciterait à bâcler la réponse en cours. */}
            <div className="onb-scan-status" key={scanResult && quizIdx >= 3 ? "done" : scanIdx}>
              {scanResult && quizIdx >= 3 ? "Analyse prête ✓" : scanSteps[scanIdx]}
            </div>

            {/* Tunnel SaaS : la lecture du site prend de longues secondes — deux
                pop-up successives (une question chacune) occupent l'attente. Le
                bouton « Continuer » est TOUJOURS cliquable : répondre ne dépend
                pas de l'analyse. Après la 2ᵉ, si l'analyse n'est pas finie, on
                revient à l'animation et l'avancée devient automatique. */}
            {variantKey === "saas" && quizIdx === 1 && (
              <div className="onb-scan-quiz" key="quiz1">
                <div className="onb-scan-quiz-kicker">Pendant que ça tourne — question 1/2</div>

                <div className="onb-block" style={{ marginBottom: 6 }}>
                  <label className="onb-block-label">Où en est ton SaaS&nbsp;?</label>
                  <p className="onb-lead" style={{ margin: "0 0 8px", fontSize: 13 }}>
                    Le stade calibre la stratégie.
                  </p>
                  <div className="onb-chips" style={{ flexDirection: "column", alignItems: "stretch" }}>
                    {ONB_SAAS_STAGES.map((o) => (
                      <button
                        key={o.label}
                        type="button"
                        className={"onb-chip" + (stage === o.label ? " selected" : "")}
                        style={{ textAlign: "left", display: "block" }}
                        onClick={() => setStage(stage === o.label ? "" : o.label)}
                      >
                        <span style={{ fontWeight: 600 }}>{o.label}</span>
                        <span style={{ display: "block", fontSize: 12, opacity: 0.72, marginTop: 2 }}>
                          {o.hint}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>

                <button type="button" className="onb-analysis-cta" onClick={() => setQuizIdx(2)}>
                  Continuer <ChevronRight size={16} />
                </button>
              </div>
            )}

            {variantKey === "saas" && quizIdx === 2 && (
              <div className="onb-scan-quiz" key="quiz2">
                <div className="onb-scan-quiz-kicker">Pendant que ça tourne — question 2/2</div>

                <div className="onb-block" style={{ marginBottom: 6 }}>
                  <label className="onb-block-label">Qu&apos;est-ce qui te bloque le plus&nbsp;?</label>
                  <p className="onb-lead" style={{ margin: "0 0 8px", fontSize: 13 }}>
                    Coche tout ce qui te parle — le plan d&apos;attaque se calibre dessus.
                  </p>
                  <div className="onb-chips">
                    {ONB_SAAS_OBSTACLES.map((label) => (
                      <button
                        key={label}
                        type="button"
                        className={"onb-chip" + (obstacles.includes(label) ? " selected" : "")}
                        onClick={() =>
                          setObstacles((prev) =>
                            prev.includes(label) ? prev.filter((o) => o !== label) : [...prev, label],
                          )
                        }
                      >
                        {label}
                      </button>
                    ))}
                    <button
                      type="button"
                      className={"onb-chip" + (showObstacleOther ? " selected" : "")}
                      onClick={() => {
                        const next = !showObstacleOther;
                        setShowObstacleOther(next);
                        if (!next) setObstacleOther("");
                      }}
                    >
                      Autre
                    </button>
                  </div>
                  {showObstacleOther && (
                    <input
                      className="onb-other-input"
                      value={obstacleOther}
                      onChange={(e) => setObstacleOther(e.target.value)}
                      placeholder="Dis-le avec tes mots…"
                      autoFocus
                    />
                  )}
                </div>

                {/* Toujours cliquable : si l'analyse est prête on avance tout de
                    suite, sinon retour à l'animation — l'effet fera le reste. */}
                <button
                  type="button"
                  className="onb-analysis-cta"
                  onClick={() => {
                    setQuizIdx(3);
                    if (scanResult) applyScanResult(scanResult.profile, scanResult.preview);
                  }}
                >
                  Continuer <ChevronRight size={16} />
                </button>
              </div>
            )}
          </div>
        )}

        {step === "analysis" && preview && (
          <div className="onb-screen onb-analysis" key="analysis">
            <div className="onb-analysis-card onb-analysis-profile">
              {/* ⚠️ Pas d'avatar quand rien n'a été scrapé : une pastille d'initiales
                  sur un nom de produit (« ? », « TP ») ne représente personne et fait
                  passer l'écran pour un gabarit générique. On ne montre une identité
                  que si on l'a réellement lue. */}
              {preview.avatar_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  className="onb-analysis-avatar onb-analysis-avatar-img"
                  src={preview.avatar_url}
                  alt=""
                  onError={(e) => { e.currentTarget.style.display = "none"; }}
                />
              ) : hasScrapedProfile ? (
                <div className="onb-analysis-avatar" aria-hidden>
                  {initials(preview.name, preview.handle)}
                </div>
              ) : null}
              {!hasScrapedProfile && (
                <div className="onb-analysis-source">{onbSourceLabel(inputKind)}</div>
              )}
              <div className="onb-analysis-name">{preview.name || "Ton produit"}</div>
              {hasScrapedProfile && preview.handle && (
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

            {/* Deux colonnes sur desktop : ces deux listes se lisent en vis-à-vis
                (ce qui va / ce qui manque), pas l'une sous l'autre. */}
            <div className="onb-analysis-grid">
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
                <div className="onb-analysis-label">
                  {hasScrapedProfile ? "Points à améliorer" : "Ce qui manque pour vendre sur LinkedIn"}
                </div>
                <ul className="onb-analysis-list">
                  {preview.improvements.map((s) => (
                    <li key={s}>
                      <AlertTriangle size={16} className="onb-analysis-warn" />
                      <span>{s}</span>
                    </li>
                  ))}
                </ul>
              </div>
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
              <label className="onb-block-label">{variant.audienceLabel}</label>
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
                  options={variant.audienceOptions}
                  field={sel.audience}
                  onChange={(v) => up({ audience: v })}
                  placeholder="Ta niche…"
                />
              )}
            </div>

            <div className="onb-block">
              <label className="onb-block-label">{variant.offerLabel}</label>
              <OnbChips options={variant.offerOptions} field={sel.offer} onChange={(v) => up({ offer: v })} />
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
              <label className="onb-block-label">{variant.objectiveLabel}</label>
              <OnbChips options={variant.objectiveOptions} field={sel.objective} onChange={(v) => up({ objective: v })} />
            </div>

            <div className="onb-block">
              <label className="onb-block-label">{variant.industryLabel}</label>
              <OnbChips options={variant.industryOptions} field={sel.industry} onChange={(v) => up({ industry: v })} />
            </div>

            <div className="onb-nav">
              <button type="button" className="onb-back" onClick={() => setStep("page1")}>
                <ChevronLeft size={16} /> Retour
              </button>
              <button
                type="button"
                className="onb-cta"
                onClick={showsProjection ? toGains : finish}
                disabled={saving}
              >
                {saving ? <Loader2 size={16} className="spinning" /> : <Sparkles size={16} />}{" "}
                {showsProjection ? "Voir ce que je pourrais gagner" : finishLabel}
              </button>
            </div>
          </div>
        )}

        {step === "gains" && (
          <div className="onb-screen onb-analysis" key="gains">
            <h2 className="onb-analysis-title">{variant.gainsTitle}</h2>
            <p className="onb-analysis-summary" style={{ opacity: 0.8 }}>
              {variant.gainsIntro}
            </p>

            {!projection ? (
              <div className="onb-scan" style={{ padding: "28px 0" }}>
                <Loader2 size={26} className="spinning" />
              </div>
            ) : (
              <>
                <div className="onb-gain-grid">
                  <div className="onb-gain-card">
                    <div className="onb-gain-label">
                      {hasAudienceData ? "Abonnés dans 90 jours" : "Abonnés gagnés en 90 jours"}
                    </div>
                    <div className="onb-gain-value">
                      {fmtRange(
                        hasAudienceData ? projection.followers_after : projection.followers_gain,
                        fmtInt,
                      )}
                    </div>
                    <div className="onb-gain-hint">
                      {hasAudienceData
                        ? `aujourd'hui ${fmtInt(projection.followers_now)} · +${fmtRange(projection.followers_gain, fmtInt)}`
                        : "en publiant ~3 fois par semaine"}
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

                <div className="onb-analysis-card">
                  <div className="onb-analysis-label">
                    {hasAudienceData ? "Ton audience sur 90 jours" : "Abonnés gagnés sur 90 jours"}
                  </div>
                  <GrowthCurve
                    start={hasAudienceData ? projection.followers_now : 0}
                    endLow={hasAudienceData ? projection.followers_after.low : projection.followers_gain.low}
                    endHigh={hasAudienceData ? projection.followers_after.high : projection.followers_gain.high}
                    endText={
                      (hasAudienceData ? "" : "+") +
                      fmtRange(hasAudienceData ? projection.followers_after : projection.followers_gain, fmtInt)
                    }
                  />
                </div>

                <div className="onb-analysis-block">
                  <div className="onb-analysis-label">{dealLabel}</div>
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
                  <div className="onb-gain-label">{revenueLabel}</div>
                  <div className="onb-gain-money">{fmtRange(projection.revenue_per_month, fmtMoney)}</div>
                </div>

                <div className="onb-note">
                  {(band?.assumptions || []).map((line) => (
                    <div key={line}>{line}</div>
                  ))}
                </div>

                <button type="button" className="onb-analysis-cta" onClick={() => setStep("simulation")}>
                  Continuer <ChevronRight size={16} />
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
            <h2 className="onb-analysis-title">
              {hasScrapedProfile ? "Ton profil dans 90 jours" : "Ton LinkedIn dans 90 jours"}
            </h2>
            <p className="onb-analysis-summary" style={{ opacity: 0.8 }}>
              {hasScrapedProfile
                ? "À gauche ton compte aujourd'hui, à droite la même page une fois la machine lancée."
                : "À gauche ce qui arrive aujourd'hui, à droite une fois la machine lancée."}
            </p>

            <div className="onb-sim-grid">
              <SimCard
                variant="before"
                caption="Aujourd'hui"
                preview={preview}
                identified={hasScrapedProfile}
                followers={hasAudienceData ? projection.followers_now : null}
                invites={0}
                messages={0}
                offers={0}
              />
              <SimCard
                variant="after"
                caption="Dans 90 jours"
                preview={preview}
                identified={hasScrapedProfile}
                followers={hasAudienceData ? projection.followers_after.high : null}
                invites={projection.relations_per_month.high}
                messages={projection.conversations_per_month.high}
                offers={projection.clients_per_month.high}
              />
            </div>

            <div className="onb-note">
              Simulation à partir des fourchettes hautes de l&apos;écran précédent.
              Aucune donnée réelle de ton compte n&apos;est modifiée.
            </div>

            {funnel === "trial" ? (
              <button type="button" className="onb-analysis-cta" onClick={() => setStep("pitch")}>
                Comment on s&apos;y prend <ChevronRight size={16} />
              </button>
            ) : (
              <button type="button" className="onb-analysis-cta" onClick={() => setStep("lead_form")}>
                Recevoir mon audit complet gratuit
              </button>
            )}
            <button type="button" className="onb-analysis-skip" onClick={() => setStep("gains")}>
              ← Retour aux chiffres
            </button>
          </div>
        )}

        {step === "pitch" && funnel === "trial" && (() => {
          const offPct = FOUNDERS_FIRST_MONTH_OFF_PCT;
          const introPrice = Math.round(planPrice * (100 - offPct)) / 100;
          const perDay = introPrice / 30;
          return (
          <div className="onb-screen onb-pitch" key="pitch">
            {/* Paywall desktop-first : témoignage → 1 offre → CTA → fine print.
                Pas de miroir / ROI / garantie — trop de blocs bleus, trop de scroll. */}
            <a
              className="onb-testimonial"
              href={FOUNDERS_TESTIMONIAL.url}
              target="_blank"
              rel="noopener noreferrer"
            >
              <div className="onb-testimonial-head">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  className="onb-testimonial-avatar"
                  src={FOUNDERS_TESTIMONIAL.avatar}
                  alt={FOUNDERS_TESTIMONIAL.name}
                  width={48}
                  height={48}
                />
                <div className="onb-testimonial-meta">
                  <div className="onb-testimonial-name">{FOUNDERS_TESTIMONIAL.name}</div>
                  <div className="onb-testimonial-handle">{FOUNDERS_TESTIMONIAL.handle}</div>
                </div>
                <span className="onb-testimonial-stars" aria-hidden="true">★★★★★</span>
              </div>
              <p className="onb-testimonial-quote">«&nbsp;{FOUNDERS_TESTIMONIAL.quote}&nbsp;»</p>
            </a>

            <h2 className="onb-pitch-title">Choisis ton plan</h2>

            <div className="onb-plan" aria-pressed="true">
              <span className="onb-plan-radio" aria-hidden="true" />
              <div className="onb-plan-main">
                <div className="onb-plan-row">
                  <span className="onb-plan-name">Mensuel</span>
                  <span className="onb-plan-badge">−{offPct}&nbsp;%</span>
                </div>
                <div className="onb-plan-sub">1er mois après l&apos;essai</div>
              </div>
              <div className="onb-plan-price">
                <span className="onb-plan-was">{fmtPrice(planPrice)}</span>
                <span className="onb-plan-now">{fmtPrice(introPrice)}</span>
                <span className="onb-plan-day">{fmtPrice(perDay)}&nbsp;/jour</span>
              </div>
            </div>

            <button
              type="button"
              className="onb-pitch-cta"
              onClick={finish}
              disabled={saving}
            >
              {saving ? <Loader2 size={16} className="spinning" /> : null}
              Démarrer mes {trialDays} jours gratuits
            </button>

            <p className="onb-pitch-legal">
              Le prix réduit s&apos;applique à ton premier mois après l&apos;essai.
              Ton abonnement sera ensuite renouvelé à {fmtPrice(planPrice)}/mois,
              jusqu&apos;à annulation dans ton compte.
            </p>
          </div>
          );
        })()}

        {step === "lead_form" && (
          <div className="onb-screen onb-analysis" key="lead_form">
            <h2 className="onb-analysis-title">Ton audit complet, offert</h2>
            <p className="onb-analysis-summary" style={{ opacity: 0.85 }}>
              Tu le reçois par e-mail : ton titre et ta section « Infos » réécrits,
              3 concepts de bannière, les comptes à suivre dans ta niche, tes angles
              de posts, ton ciblage de prospection et un plan sur 90 jours.
            </p>

            {/* L'aperçu passe AVANT le formulaire dans le DOM : sur mobile il se
                lit donc en premier — on voit ce qu'on échange avant qu'on nous
                demande un téléphone. Sur desktop, la grille le remet à gauche,
                en vis-à-vis des champs. */}
            <div className="onb-lead-grid">
              <AuditPreviewMock name={sel.displayName || preview?.name} />

              <div className="onb-lead-form">
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
              </div>
            </div>

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
 * Aperçu flouté de l'audit complet, montré à côté du formulaire.
 *
 * Le formulaire demande trois informations dont un téléphone : il faut donc voir
 * ce qu'on échange AVANT de le remplir. Les titres de sections restent nets (on
 * doit pouvoir lire ce qu'on reçoit), seul le contenu est flouté.
 *
 * ⚠️ C'est une mise en scène assumée, pas un extrait du vrai audit — il n'existe
 * pas encore à cet instant, il est généré après l'envoi. D'où des lignes grises
 * plutôt qu'un faux texte lisible : rien ici ne prétend être un contenu réel, et
 * il n'y a donc aucune promesse qui puisse être démentie par l'e-mail reçu.
 */
function AuditPreviewMock({ name }: { name?: string }) {
  const sections: { title: string; lines: number[] }[] = [
    { title: "Diagnostic de ton profil", lines: [100, 92, 78] },
    { title: "Ton titre réécrit — 3 propositions", lines: [88, 95, 70] },
    { title: "Ta section « Infos »", lines: [100, 84, 96, 62] },
    { title: "3 concepts de bannière", lines: [90, 76] },
    { title: "Les comptes à suivre dans ta niche", lines: [94, 88, 72] },
    { title: "Tes angles de posts", lines: [86, 98, 68] },
    { title: "Ton plan sur 90 jours", lines: [92, 80, 88] },
  ];

  return (
    <div className="onb-doc" aria-hidden="true">
      <div className="onb-doc-page">
        <div className="onb-doc-head">
          <div className="onb-doc-kicker">Audit LinkedIn complet</div>
          <div className="onb-doc-title">{name?.trim() || "Ton profil"}</div>
        </div>
        {sections.map((section) => (
          <div className="onb-doc-section" key={section.title}>
            <div className="onb-doc-section-title">{section.title}</div>
            <div className="onb-doc-lines">
              {section.lines.map((width, i) => (
                <span className="onb-doc-line" key={i} style={{ width: `${width}%` }} />
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="onb-doc-fade" />
      <div className="onb-doc-seal">
        <Lock size={13} /> {sections.length} sections · débloquées à l&apos;envoi
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
  identified,
  followers,
  invites,
  messages,
  offers,
}: {
  variant: "before" | "after";
  caption: string;
  preview: OnboardingPreview | null;
  /** false = on n'a pas lu le compte : ni photo ni nom, seulement ce qui bouge. */
  identified: boolean;
  /** `null` = audience inconnue (entrée par le site) : on n'affiche aucun compteur. */
  followers: number | null;
  invites: number;
  messages: number;
  offers: number;
}) {
  const name = preview?.name || "Ton profil";
  return (
    <div className={"onb-sim-card" + (variant === "after" ? " onb-sim-after" : "")}>
      <div className="onb-sim-caption">{caption}</div>
      {identified && <div className="onb-sim-banner" />}
      {/* Sans compte lu, ni photo ni nom : une pastille « TP » sous un titre
          « Ton profil » ne ressemble au compte de personne. Ce qui compte ici,
          ce sont les trois lignes qui bougent. */}
      {identified && (preview?.avatar_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img className="onb-sim-avatar onb-sim-avatar-img" src={preview.avatar_url} alt="" />
      ) : (
        <div className="onb-sim-avatar" aria-hidden>{initials(name, preview?.handle || "")}</div>
      ))}
      {identified && <div className="onb-sim-name">{name}</div>}
      {followers !== null && (
        <div className="onb-sim-followers">{fmtInt(followers)} abonnés</div>
      )}
      <div className="onb-sim-rows">
        <SimRow icon={<Users size={14} />} label="Invitations reçues" value={invites} />
        <SimRow icon={<MessageSquare size={14} />} label="Messages non lus" value={messages} />
        <SimRow icon={<Briefcase size={14} />} label="Propositions" value={offers} />
      </div>
    </div>
  );
}

/**
 * Blocs de l'argumentaire fondateurs, PARTAGÉS entre le closing du tunnel et la
 * landing /founders. Une seule source : si l'argument change, les deux surfaces
 * changent ensemble — deux copies auraient fini par se contredire.
 *
 * Format Catalog : titre accent + sous-texte, deux colonnes — pas de listes.
 */
export function FoundersSplit() {
  return (
    <div className="fl-benefits">
      <div className="fl-benefits-col">
        <div className="fl-benefits-title">100&nbsp;% fait pour toi</div>
        <div className="fl-benefits-sub">on le fait, tu valides</div>
      </div>
      <div className="fl-benefits-col">
        <div className="fl-benefits-title">Prêt pour chaque pivot</div>
        <div className="fl-benefits-sub">ton audience suit chaque produit que tu lances</div>
      </div>
    </div>
  );
}

/** Comparatif à charge — ordres de grandeur constatés, jamais des devis. */
export function FoundersAlternatives() {
  const alts = [
    { name: "Ghostwriter LinkedIn", price: "500 à 2 000 €/mois", note: "il écrit — tu prospectes encore à la main" },
    { name: "Agence de prospection", price: "1 000 à 3 000 €/mois", note: "souvent sans le contenu, résultats opaques" },
    { name: "Tout faire toi-même", price: "10 h et + par semaine", note: "le changement de casquette, en boucle" },
  ];
  return (
    <>
      {alts.map((alt) => (
        <div className="onb-alt-row" key={alt.name}>
          <span className="onb-alt-name">{alt.name}</span>
          <span className="onb-alt-price">{alt.price}</span>
          <span className="onb-alt-note">— {alt.note}</span>
        </div>
      ))}
      <div className="onb-gain-hint" style={{ marginTop: 8 }}>
        Ordres de grandeur constatés sur le marché — pas des devis.
      </div>
    </>
  );
}

/**
 * Courbe de progression sur 90 jours — la « belle courbe qui grandit ».
 *
 * Elle n'invente rien : la bande claire est la fourchette basse↔haute de la
 * projection affichée juste au-dessus, la ligne suit le MILIEU de la fourchette
 * (pas la borne haute — tracer l'hypothèse optimiste en trait plein serait
 * survendre). La forme (départ lent puis accélération) reflète le warm-up réel
 * du moteur d'envoi : 8 → 15 → 20 actions/jour sur 3 semaines.
 */
function GrowthCurve({
  start,
  endLow,
  endHigh,
  endText,
}: {
  start: number;
  endLow: number;
  endHigh: number;
  endText: string;
}) {
  const W = 640, H = 190;
  const pad = { top: 26, right: 12, bottom: 10, left: 12 };
  const innerW = W - pad.left - pad.right;
  const innerH = H - pad.top - pad.bottom;
  const max = Math.max(endHigh, start + 1);
  const min = start;
  const y = (v: number) => pad.top + (1 - (v - min) / (max - min)) * innerH;
  const x = (t: number) => pad.left + t * innerW;
  // Départ lent (warm-up) puis accélération — exposant > 1 sur t.
  const value = (t: number, end: number) => start + (end - start) * Math.pow(t, 1.6);

  const N = 32;
  const pts = (end: number) =>
    Array.from({ length: N + 1 }, (_, i) => {
      const t = i / N;
      return `${x(t).toFixed(1)},${y(value(t, end)).toFixed(1)}`;
    });
  const mid = (endLow + endHigh) / 2;
  const bandPath =
    `M ${pts(endHigh).join(" L ")} L ${pts(endLow).reverse().join(" L ")} Z`;
  const midPath = `M ${pts(mid).join(" L ")}`;
  const endX = x(1), endY = y(value(1, mid));

  return (
    <div className="onb-curve-wrap">
      <svg
        className="onb-curve"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Projection sur 90 jours : ${endText}`}
      >
        {/* Grille discrète — 3 repères, pas d'axe chiffré : les valeurs exactes
            sont dans les cartes au-dessus, la courbe montre la trajectoire. */}
        {[0.25, 0.5, 0.75].map((f) => (
          <line
            key={f}
            x1={pad.left} x2={W - pad.right}
            y1={pad.top + f * innerH} y2={pad.top + f * innerH}
            stroke="rgba(27,27,35,.07)" strokeWidth="1"
          />
        ))}
        <line
          x1={pad.left} x2={W - pad.right} y1={pad.top + innerH} y2={pad.top + innerH}
          stroke="rgba(27,27,35,.14)" strokeWidth="1"
        />
        {/* Fourchette basse↔haute — apparaît quand la ligne a fini de se tracer */}
        <path className="onb-curve-band" d={bandPath} fill="rgba(70,72,212,.1)" />
        {/* Trajectoire médiane — se DESSINE à l'arrivée sur l'écran (pathLength
            normalisé à 1 : le dash-offset anime le tracé quelle que soit la
            longueur réelle de la courbe). */}
        <path
          className="onb-curve-line"
          d={midPath}
          pathLength={1}
          fill="none" stroke="#4648d4" strokeWidth="2.5"
          strokeLinecap="round" strokeLinejoin="round"
        />
        <g className="onb-curve-end">
          <circle cx={endX} cy={endY} r="4.5" fill="#4648d4" stroke="#fff" strokeWidth="2" />
          <text
            x={endX - 4} y={Math.max(pad.top - 8, endY - 12)}
            textAnchor="end" fontSize="13.5" fontWeight="700" fill="#1b1b23"
          >
            {endText}
          </text>
        </g>
      </svg>
      <div className="onb-curve-axis">
        <span>Aujourd&apos;hui</span>
        <span>Dans 90 jours</span>
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
