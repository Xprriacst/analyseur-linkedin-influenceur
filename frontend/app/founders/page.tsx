"use client";

/**
 * Tunnel fondateurs SaaS (/founders) — variante de /start pour une autre cible et
 * une autre promesse de sortie.
 *
 *   onboarding SaaS (sans compte) → compte → essai 7 jours → app
 *
 * Deux différences avec /start, et elles sont volontaires :
 *
 *  1. **Les questions ne sont pas les mêmes** (`variant="saas"`) : un fondateur de
 *     SaaS ne se reconnaît pas dans « Coachs & consultants » ni dans « Des
 *     prestations sur-mesure », et ses montants se raisonnent en ACV, pas en
 *     panier de prestation. Des chips où personne ne se retrouve renvoient tout le
 *     monde vers « Autre » et vident la qualification de son sens.
 *  2. **La sortie n'est pas la prise de rendez-vous mais l'essai** (`funnel="trial"`) :
 *     pas de formulaire nom/e-mail/téléphone, l'e-mail est capturé par la création
 *     de compte. Le demander avant serait le demander deux fois.
 *
 * ⚠️ La réserve de réponses porte une clé DISTINCTE de celle de /start. Les deux
 * tunnels ne posent pas les mêmes questions : partager la clé ferait ressortir,
 * dans l'un, des réponses cochées dans les chips de l'autre.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Outfit } from "next/font/google";
import { ArrowRight, CheckCircle2, Loader2, Pencil, Rocket } from "lucide-react";
import { supabase, authHeaders } from "../lib/supabase";
import OnboardingScreen, {
  FoundersAlternatives,
  FoundersSplit,
  type OnboardingProfile,
} from "../components/Onboarding";
import {
  FOUNDERS_MONTHLY_SEATS,
  FOUNDERS_GUARANTEE_DAYS,
  PROOF_INFLUENCERS_ANALYZED,
  PROOF_POSTS_ANALYZED,
} from "../lib/founders";
import FoundersHeroArt from "./FoundersHeroArt";

const outfit = Outfit({
  subsets: ["latin"],
  weight: ["500", "600", "700", "800", "900"],
  variable: "--font-founders",
});

const DIRECT_API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "https://analyseur-linkedin-influenceur-api-eu.onrender.com";

const PENDING_PROFILE_KEY = "cibl_pending_profile_founders";
/** E-mail capté par la porte d'entrée de la landing — pré-remplit la création de compte. */
const FOUNDERS_EMAIL_KEY = "cibl_founders_email";

/** Repli d'affichage si `/billing/plan` est injoignable — le serveur reste l'arbitre. */
const FALLBACK_TRIAL_DAYS = 7;

type Phase = "landing" | "onboarding" | "account";

/** Les trois réponses qui pilotent toute la génération — donc corrigeables ici. */
const PROFILE_FIELDS: { key: string; label: string; placeholder: string }[] = [
  { key: "display_name", label: "Profil", placeholder: "Ton nom et prénom" },
  { key: "target_audience", label: "ICP", placeholder: "À qui tu vends" },
  { key: "core_offer", label: "Produit", placeholder: "Ce que tu vends" },
];

export default function FoundersPage() {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("landing");
  const [profile, setProfile] = useState<OnboardingProfile | null>(null);
  const [trialDays, setTrialDays] = useState(FALLBACK_TRIAL_DAYS);
  // Prix réel du plan (Stripe) pour le cadrage ROI du closing — repli 49 €.
  const [planPrice, setPlanPrice] = useState(49);
  const [editing, setEditing] = useState(false);
  const [mode, setMode] = useState<"signup" | "signin">("signup");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(false);

  // Déjà connecté ? Ce parcours ne le concerne pas : l'app gère son onboarding.
  useEffect(() => {
    (async () => {
      const { data } = await supabase.auth.getSession();
      if (data.session) router.replace("/");
    })();
  }, [router]);

  // Durée réelle de l'essai, lue côté serveur : le bouton final l'annonce, il ne
  // doit pas promettre une durée que Stripe n'accorde pas.
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${DIRECT_API_URL}/billing/plan`);
        if (!res.ok) return;
        const data = await res.json();
        if (typeof data?.trial_days === "number" && data.trial_days > 0) setTrialDays(data.trial_days);
        if (typeof data?.plan?.amount === "number" && data.plan.amount > 0) setPlanPrice(data.plan.amount);
      } catch { /* repli silencieux sur la valeur par défaut */ }
    })();
  }, []);

  // Reprise après un rechargement en cours de parcours — y compris l'e-mail de
  // la porte d'entrée, pour que le compte reste pré-rempli.
  useEffect(() => {
    try {
      const savedEmail = sessionStorage.getItem(FOUNDERS_EMAIL_KEY);
      if (savedEmail) setEmail((prev) => prev || savedEmail);
      const raw = sessionStorage.getItem(PENDING_PROFILE_KEY);
      if (raw) {
        setProfile(JSON.parse(raw));
        setPhase("account");
      }
    } catch { /* parcours reparti de zéro — sans gravité */ }
  }, []);

  const onboardingDone = useCallback((p: OnboardingProfile) => {
    setProfile(p);
    try { sessionStorage.setItem(PENDING_PROFILE_KEY, JSON.stringify(p)); } catch { /* ignore */ }
    setPhase("account");
  }, []);

  const onboardingSkipped = useCallback(() => {
    setProfile(null);
    try { sessionStorage.removeItem(PENDING_PROFILE_KEY); } catch { /* ignore */ }
    setPhase("account");
  }, []);

  /**
   * Enregistre le profil recueilli avant l'inscription, sur le compte tout juste créé.
   * ⚠️ Doit réussir AVANT de quitter cette page : une fois partie sur Stripe, elle
   * n'existe plus et les réponses seraient perdues.
   */
  async function persistProfile() {
    if (!profile) return;
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify(profile),
      });
      if (res.ok) {
        try { sessionStorage.removeItem(PENDING_PROFILE_KEY); } catch { /* ignore */ }
      }
    } catch {
      // Best effort, même arbitrage que /start : mieux vaut un compte qui démarre
      // son essai et refait son profil qu'un compte bloqué ici.
    }
  }

  /**
   * Corrige une réponse avant la création du compte.
   *
   * ⚠️ La réserve de session est mise à jour en même temps que l'état : sans ça,
   * un rechargement de la page (ou le retour depuis Stripe) ressusciterait la
   * version déduite automatiquement et la correction serait perdue en silence.
   */
  function updateProfileField(key: string, value: string) {
    setProfile((prev) => {
      const next = { ...(prev || {}), [key]: value };
      try { sessionStorage.setItem(PENDING_PROFILE_KEY, JSON.stringify(next)); } catch { /* ignore */ }
      return next;
    });
  }

  /**
   * Après le compte : direction Stripe DIRECTEMENT quand l'essai est confirmé
   * éligible — l'écran /essai re-déroulait un argumentaire à quelqu'un de déjà
   * convaincu, un clic de trop en plein élan (patron des funnels Catalog/Blow Up).
   *
   * ⚠️ /essai reste la destination de TOUS les autres cas, et c'est structurel :
   *  - compte non éligible (`trial_eligible` false) : il doit lire « tu repars
   *    sur X €/mois » AVANT le Checkout — l'envoyer directement sur un paiement
   *    immédiat après lui avoir promis des jours gratuits serait la pire panne
   *    silencieuse de ce parcours ;
   *  - état de facturation illisible ou checkout en échec : repli, jamais d'impasse.
   */
  async function toTrial() {
    await persistProfile();
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/billing`, { headers: await authHeaders() });
      if (res.ok) {
        const state = await res.json();
        if (state?.subscribed) { router.push("/"); return; }
        if (state?.trial_eligible) {
          const co = await fetch(`${DIRECT_API_URL}/me/billing/checkout`, {
            method: "POST",
            headers: { "Content-Type": "application/json", ...(await authHeaders()) },
            body: JSON.stringify({
              trial: true,
              success_url: `${window.location.origin}/?billing=success`,
              // Abandon sur Stripe : il entre quand même dans l'app avec ses
              // crédits offerts, profil déjà enregistré (même filet que /essai).
              cancel_url: `${window.location.origin}/?billing=cancelled`,
            }),
          });
          const data = await co.json().catch(() => ({}));
          if (co.ok && data?.url) {
            window.location.href = data.url;
            return;
          }
        }
      }
    } catch { /* repli ci-dessous */ }
    router.push("/essai");
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setInfo("");
    setLoading(true);
    try {
      if (mode === "signin") {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw error;
        await toTrial();
        return; // redirection en cours — on garde le spinner
      }

      const { data, error } = await supabase.auth.signUp({
        email,
        password,
        // L'onboarding vient d'être fait : il ne doit JAMAIS se relancer dans l'app.
        options: { data: { onboarding_done: true, onboarding_pending: false } },
      });
      if (error) throw error;

      if (data.session) {
        await toTrial();
        return;
      }

      setInfo(
        `Compte créé ! Confirme ton e-mail, puis reviens ici : on enregistre ton profil et on lance tes ${trialDays} jours gratuits.`
      );
      setMode("signin");
      setLoading(false);
    } catch (err: any) {
      const msg = err?.message || "Une erreur est survenue.";
      if (/already registered|already been registered|user already exists/i.test(msg)) {
        setMode("signin");
        setError("Tu as déjà un compte avec cet e-mail. Connecte-toi : on garde tes réponses.");
      } else {
        setError(msg);
      }
      setLoading(false);
    }
  }

  if (phase === "landing") {
    return (
      <FoundersLanding
        onStart={(gateEmail) => {
          if (gateEmail) {
            setEmail(gateEmail);
            try { sessionStorage.setItem(FOUNDERS_EMAIL_KEY, gateEmail); } catch { /* ignore */ }
          }
          setPhase("onboarding");
        }}
        onSignIn={() => { setMode("signin"); setPhase("account"); }}
      />
    );
  }

  if (phase === "onboarding") {
    return (
      <OnboardingScreen
        anonymous
        funnel="trial"
        variant="saas"
        trialDays={trialDays}
        planPrice={planPrice}
        monthlySeats={FOUNDERS_MONTHLY_SEATS}
        guaranteeDays={FOUNDERS_GUARANTEE_DAYS}
        onFinish={onboardingDone}
        onSkip={onboardingSkipped}
        finishLabel="Continuer"
      />
    );
  }

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: "40px 20px",
        background:
          "radial-gradient(circle at 85% 12%, rgba(70,72,212,0.07) 0%, rgba(70,72,212,0) 42%), var(--surface-low)",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 16, width: "100%" }}>
        <form onSubmit={submit} className="auth-card" style={{ maxWidth: 420, padding: 32, gap: 6 }}>
          <span
            style={{
              alignSelf: "center",
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "4px 11px",
              borderRadius: 20,
              fontSize: 12,
              fontWeight: 600,
              color: "var(--primary)",
              background: "rgba(70,72,212,0.08)",
              border: "1px solid rgba(70,72,212,0.18)",
              marginBottom: 6,
            }}
          >
            <Rocket size={12} /> {trialDays} jours gratuits
          </span>

          <h2 className="auth-title" style={{ fontSize: 22 }}>
            {mode === "signup" ? "Crée ton compte fondateur" : "Connecte-toi pour continuer"}
          </h2>
          <p className="auth-sub">
            {mode === "signup"
              ? `Dernière étape avant tes ${trialDays} jours d'accès complet.`
              : "On récupère ton profil et on lance ton essai."}
          </p>

          {profile && (
            <div
              style={{
                margin: "6px 0 10px",
                padding: "12px 14px",
                borderRadius: 12,
                background: "var(--surface-low)",
                border: "1px solid var(--border)",
                display: "grid",
                gap: 10,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--muted)" }}>
                  Ce qu&apos;on a compris
                </span>
                <button
                  type="button"
                  className="link-button"
                  onClick={() => setEditing((v) => !v)}
                  style={{ fontSize: 12.5, display: "inline-flex", alignItems: "center", gap: 5 }}
                >
                  <Pencil size={12} /> {editing ? "Terminé" : "Modifier"}
                </button>
              </div>

              {/* Ces trois réponses partent dans le profil éditorial et servent à
                  TOUTE la génération ensuite. Une déduction approximative laissée
                  telle quelle se retrouve dans chaque post produit — d'où
                  l'édition ici, tant que la correction ne coûte qu'un clic. */}
              {PROFILE_FIELDS.map(({ key, label, placeholder }) =>
                editing ? (
                  <label key={key} style={{ display: "grid", gap: 4 }}>
                    <span style={{ fontSize: 11.5, fontWeight: 600, color: "var(--muted)" }}>{label}</span>
                    <textarea
                      className="auth-input"
                      rows={key === "display_name" ? 1 : 2}
                      value={profile[key] || ""}
                      placeholder={placeholder}
                      onChange={(e) => updateProfileField(key, e.target.value)}
                      style={{ fontSize: 13, lineHeight: 1.45, resize: "vertical", minHeight: 34, padding: "8px 10px" }}
                    />
                  </label>
                ) : profile[key] ? (
                  <div key={key} style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13, lineHeight: 1.45 }}>
                    <CheckCircle2 size={14} style={{ color: "var(--primary)", flexShrink: 0, marginTop: 2 }} />
                    <span style={{ color: "var(--muted)" }}>
                      <strong style={{ fontWeight: 600 }}>{label}</strong> : {profile[key]}
                    </span>
                  </div>
                ) : null,
              )}
            </div>
          )}

          <label className="auth-label">Email</label>
          <input
            className="auth-input"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="toi@ton-saas.com"
            autoComplete="email"
          />

          <label className="auth-label">Mot de passe</label>
          <input
            className="auth-input"
            type="password"
            required
            minLength={6}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            autoComplete={mode === "signup" ? "new-password" : "current-password"}
          />

          {error && <div className="error" style={{ marginTop: 10 }}>{error}</div>}
          {info && <div className="auth-info" style={{ marginTop: 10 }}>{info}</div>}

          <button
            className="auth-submit"
            type="submit"
            disabled={loading}
            style={{ height: 46, fontSize: 15, display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}
          >
            {loading ? (
              <Loader2 className="spin" size={16} />
            ) : (
              <>
                {mode === "signup" ? "Créer mon compte" : "Se connecter"} <ArrowRight size={15} />
              </>
            )}
          </button>

          {/* L'étape suivante est la page de paiement Stripe : le dire ICI, avant
              le clic — arriver sur une demande de carte sans avoir été prévenu,
              juste après avoir tapé un mot de passe, c'est le réflexe « arnaque »
              assuré. C'est cette note qui permet de sauter l'écran intermédiaire. */}
          <p
            style={{
              margin: "12px 0 0",
              padding: "10px 12px",
              borderRadius: 10,
              fontSize: 12.5,
              lineHeight: 1.5,
              color: "var(--muted)",
              background: "rgba(70,72,212,0.05)",
              border: "1px solid rgba(70,72,212,0.14)",
            }}
          >
            Ensuite : paiement sécurisé Stripe — ta carte est enregistrée mais{" "}
            <strong style={{ color: "var(--ink)" }}>0&nbsp;€ prélevé pendant tes {trialDays} jours d&apos;essai</strong>,
            résiliable en un clic depuis ton espace.
          </p>

          <button
            type="button"
            className="auth-switch"
            onClick={() => { setMode(mode === "signup" ? "signin" : "signup"); setError(""); setInfo(""); }}
          >
            {mode === "signup" ? "Déjà un compte ? Se connecter" : "Pas de compte ? En créer un"}
          </button>
        </form>

        <Link href="/offre" style={{ fontSize: 12.5, color: "var(--muted)" }}>
          ← Retour à la présentation
        </Link>
      </div>
    </main>
  );
}

/**
 * Landing /founders — page d'opt-in façon Catalog/zoomgtm : fond clair, H1 900,
 * kicker uppercase, CTA sombre, illustration au trait. L'argumentaire long reste
 * en dessous (preuve + problème + rôles + alternatives) ; le premier écran fait
 * le travail d'entrée.
 */
function FoundersLanding({
  onStart,
  onSignIn,
}: {
  /** Entre dans le tunnel — avec l'e-mail capté par la porte d'entrée. */
  onStart: (email: string) => void;
  onSignIn: () => void;
}) {
  // Porte d'entrée façon Catalog : l'e-mail AVANT le tunnel, avec la vraie
  // rareté (20 comptes/mois) comme raison d'être. Sans ça, un visiteur qui
  // ferme l'onglet au milieu du quiz est perdu sans laisser de trace.
  const [gateEmail, setGateEmail] = useState("");
  const [gateError, setGateError] = useState("");
  const [gateSending, setGateSending] = useState(false);
  const gateRef = useRef<HTMLInputElement>(null);

  async function submitGate() {
    const v = gateEmail.trim().toLowerCase();
    if (!/^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$/.test(v)) {
      setGateError("Indique une adresse e-mail valide.");
      gateRef.current?.focus();
      return;
    }
    setGateError("");
    setGateSending(true);
    // Best-effort assumé : la capture ne doit JAMAIS bloquer l'entrée dans le
    // tunnel — perdre la trace est moins grave que perdre le visiteur.
    try {
      await fetch(`${DIRECT_API_URL}/onboarding/founders-lead`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: v, source: "founders" }),
      });
    } catch { /* ignore */ }
    onStart(v);
  }

  const focusGate = () => {
    gateRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    setTimeout(() => gateRef.current?.focus({ preventScroll: true }), 450);
  };

  return (
    <main className={`fl-page ${outfit.variable}`}>
      <div className="fl-container">
        <header className="fl-hero">
          <div className="fl-brand" aria-label="Cibl">
            <span className="fl-brand-mark" aria-hidden="true" />
            Cibl
          </div>

          <p className="fl-eyebrow">Pour les fondateurs de SaaS</p>

          <h1 className="fl-h1">
            Le LinkedIn qui remplit ton pipeline — pendant que tu construis ton produit
          </h1>

          <p className="fl-sub">
            On écrit tes posts, on prospecte ton ICP. Toi, tu valides — moins d&apos;une minute par jour.
          </p>

          <div className="fl-gate">
            <label className="fl-gate-label" htmlFor="founders-gate-email">
              Ton e-mail pour vérifier s&apos;il reste une place&nbsp;<span aria-hidden="true">*</span>
            </label>
            <p className="fl-gate-hint">
              On onboard ~{FOUNDERS_MONTHLY_SEATS} fondateurs par mois. On te confirme s&apos;il reste un créneau.
            </p>
            <div className="fl-gate-row">
              <input
                id="founders-gate-email"
                ref={gateRef}
                className="fl-gate-input"
                type="email"
                value={gateEmail}
                onChange={(e) => setGateEmail(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") submitGate(); }}
                placeholder="toi@ton-saas.com"
                autoComplete="email"
                required
              />
              <button type="button" className="fl-cta" onClick={submitGate} disabled={gateSending}>
                {gateSending ? <Loader2 size={16} className="spin" /> : null}
                Vérifier ma place →
              </button>
            </div>
            <p className="fl-gate-micro">Places limitées. Ça prend 90 secondes.</p>
            {gateError && <div className="fl-gate-error">{gateError}</div>}
          </div>

          <FoundersHeroArt />
        </header>

        <div className="fl-proof">
          <div className="fl-proof-item">
            <strong>{PROOF_INFLUENCERS_ANALYZED}+</strong>
            <span>comptes analysés</span>
          </div>
          <div className="fl-proof-item">
            <strong>{PROOF_POSTS_ANALYZED.toLocaleString("fr-FR")}+</strong>
            <span>posts au crible</span>
          </div>
          <div className="fl-proof-item">
            <strong>{FOUNDERS_MONTHLY_SEATS}/mois</strong>
            <span>places fondateurs</span>
          </div>
        </div>

        <section className="fl-section">
          <h2 className="fl-section-title">Le vrai goulot, ce n&apos;est pas ton produit</h2>
          <div className="fl-card">
            <p className="fl-card-p">
              90&nbsp;% développeur le matin, 10&nbsp;% marketeur l&apos;après-midi. Chaque
              casquette coûte 20 à 30 minutes de refocus — et à la fin de la journée,
              seule la build a avancé. Ton LinkedIn reste muet.
            </p>
            <p className="fl-card-p">
              Ce n&apos;est pas un problème de discipline : un fondateur seul ne peut
              pas tenir le marketing ET livrer. C&apos;est un problème de rôle — et un
              rôle, ça se délègue.
            </p>
          </div>
        </section>

        <section className="fl-section fl-section-benefits">
          <FoundersSplit />
        </section>

        <section className="fl-section">
          <h2 className="fl-section-title">Les alternatives, honnêtement</h2>
          <div className="fl-card">
            <FoundersAlternatives />
          </div>
        </section>

        <footer className="fl-footer">
          <button type="button" className="fl-cta" onClick={focusGate}>
            Vérifier ma place →
          </button>
          <button type="button" className="fl-signin" onClick={onSignIn}>
            Déjà un compte&nbsp;? Se connecter
          </button>
        </footer>
      </div>
    </main>
  );
}
