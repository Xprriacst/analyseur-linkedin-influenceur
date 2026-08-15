"use client";

/**
 * Tunnel d'essai (/onboarding, alias /founders) — variante de /start pour une
 * autre promesse de sortie, ouverte à tous les builders (SaaS et freelance).
 *
 *   landing → lien (site ou LinkedIn) → compte → essai 7 jours → app
 *
 * Deux différences avec /start, et elles sont volontaires :
 *
 *  1. **Les questions ne sont pas les mêmes** (`variant="saas"`) : chips ICP/offre
 *     qui couvrent le produit ET la mission, montants en ACV (ce qu'un client
 *     rapporte sur 12 mois — ça parle aux deux). Des chips où personne ne se
 *     retrouve renvoient tout le monde vers « Autre ».
 *  2. **La sortie n'est pas la prise de rendez-vous mais l'essai** (`funnel="trial"`) :
 *     pas de formulaire nom/e-mail/téléphone, l'e-mail est capturé par la création
 *     de compte. Le demander avant serait le demander deux fois.
 *
 * ⚠️ La réserve de réponses porte une clé DISTINCTE de celle de /start. Les deux
 * tunnels ne posent pas les mêmes questions : partager la clé ferait ressortir,
 * dans l'un, des réponses cochées dans les chips de l'autre.
 *
 * `/founders` reste un alias (liens déjà en circulation) — même page, même tunnel.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Outfit } from "next/font/google";
import { ArrowRight, Loader2, Rocket } from "lucide-react";
import { supabase, authHeaders } from "../lib/supabase";
import OnboardingScreen, {
  FoundersAlternatives,
  FoundersSplit,
  type OnboardingProfile,
} from "../components/Onboarding";
import {
  FOUNDERS_MONTHLY_SEATS,
  FOUNDERS_FIRST_MONTH_OFF_PCT,
  FOUNDERS_TESTIMONIAL,
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

/**
 * Le profil éditorial ne porte qu'un `display_name`. L'écran compte le
 * découpe en prénom / nom (champs de formulaire, pas un récap), puis le
 * recoud à la sauvegarde.
 */
function splitDisplayName(name: string): { first: string; last: string } {
  const t = (name || "").trim();
  if (!t) return { first: "", last: "" };
  const i = t.search(/\s+/);
  if (i < 0) return { first: t, last: "" };
  return { first: t.slice(0, i), last: t.slice(i).trim() };
}

function joinDisplayName(first: string, last: string): string {
  return [first.trim(), last.trim()].filter(Boolean).join(" ");
}

export default function FoundersPage() {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("landing");
  const [profile, setProfile] = useState<OnboardingProfile | null>(null);
  const [trialDays, setTrialDays] = useState(FALLBACK_TRIAL_DAYS);
  // Prix réel du plan (Stripe) pour le cadrage ROI du closing — repli 49 €.
  const [planPrice, setPlanPrice] = useState(49);
  const [mode, setMode] = useState<"signup" | "signin">("signup");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const password2Ref = useRef<HTMLInputElement>(null);
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
        const saved = JSON.parse(raw) as OnboardingProfile;
        setProfile(saved);
        const { first, last } = splitDisplayName(saved.display_name || "");
        setFirstName(first);
        setLastName(last);
        setPhase("account");
      }
    } catch { /* parcours reparti de zéro — sans gravité */ }
  }, []);

  const onboardingDone = useCallback((p: OnboardingProfile) => {
    setProfile(p);
    const { first, last } = splitDisplayName(p.display_name || "");
    setFirstName(first);
    setLastName(last);
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
    const display_name = joinDisplayName(firstName, lastName);
    const payload: OnboardingProfile = { ...(profile || {}), display_name };
    if (!display_name && !profile) return;
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify(payload),
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

  function onFirstName(value: string) {
    setFirstName(value);
    updateProfileField("display_name", joinDisplayName(value, lastName));
  }

  function onLastName(value: string) {
    setLastName(value);
    updateProfileField("display_name", joinDisplayName(firstName, value));
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
    // Vérifié AVANT le moindre appel : un compte créé sur un mot de passe mal
    // tapé n'est plus rattrapable ici, il l'est par la boîte mail. Pas de second
    // message d'erreur — celui du champ est déjà à l'écran (le champ est
    // `required`, donc il ne peut pas être vide ici) : on y renvoie, c'est tout.
    if (mode === "signup" && password !== password2) {
      password2Ref.current?.focus();
      return;
    }
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
        onFinish={onboardingDone}
        onSkip={onboardingSkipped}
        finishLabel="Continuer"
      />
    );
  }

  const offPct = FOUNDERS_FIRST_MONTH_OFF_PCT;
  const introPrice = Math.round(planPrice * (100 - offPct)) / 100;
  const perDay = introPrice / 30;
  const fmtPrice = (n: number) => {
    const rounded = Math.round(n * 100) / 100;
    return `${rounded.toLocaleString("fr-FR", {
      minimumFractionDigits: Number.isInteger(rounded) ? 0 : 2,
      maximumFractionDigits: 2,
    })} €`;
  };

  return (
    <main className="onb-account-page">
      {/* Plan + compte sur le MÊME écran, en vis-à-vis dès qu'il y a la
          place : plus de paywall à re-cliquer, plus de colonne unique qui
          force le scroll. Un seul plan ⇒ un fait tarifaire, pas un choix. */}
      <div className={"onb-account" + (mode === "signin" ? " onb-account-solo" : "")}>
        {mode === "signup" && (
          <aside className="onb-account-side">
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

            <div className="onb-plan">
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
            <p className="onb-pitch-legal onb-account-legal">
              Le prix réduit s&apos;applique à ton premier mois après l&apos;essai.
              Ton abonnement sera ensuite renouvelé à {fmtPrice(planPrice)}/mois,
              jusqu&apos;à annulation dans ton compte.
            </p>
          </aside>
        )}

        <form onSubmit={submit} className="auth-card onb-account-form">
          <span className="onb-account-badge">
            <Rocket size={12} /> {trialDays} jours gratuits
          </span>

          <h2 className="auth-title" style={{ fontSize: 22 }}>
            {mode === "signup" ? "Crée ton compte" : "Connecte-toi pour continuer"}
          </h2>
          <p className="auth-sub">
            {mode === "signup"
              ? `Dernière étape avant tes ${trialDays} jours d'accès complet.`
              : "On récupère ton profil et on lance ton essai."}
          </p>

          {mode === "signup" && (
            <div className="onb-name-row">
              <div className="onb-field">
                <label className="auth-label" htmlFor="onb-first-name">Prénom</label>
                <input
                  id="onb-first-name"
                  className="auth-input"
                  type="text"
                  required
                  value={firstName}
                  onChange={(e) => onFirstName(e.target.value)}
                  placeholder="Camille"
                  autoComplete="given-name"
                />
              </div>
              <div className="onb-field">
                <label className="auth-label" htmlFor="onb-last-name">Nom</label>
                <input
                  id="onb-last-name"
                  className="auth-input"
                  type="text"
                  value={lastName}
                  onChange={(e) => onLastName(e.target.value)}
                  placeholder="Martin"
                  autoComplete="family-name"
                />
              </div>
            </div>
          )}

          <label className="auth-label" htmlFor="onb-email">Email</label>
          <input
            id="onb-email"
            className="auth-input"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="toi@email.com"
            autoComplete="email"
          />

          {mode === "signup" ? (
            <div className="onb-pass-row">
              <div className="onb-field">
                <label className="auth-label" htmlFor="onb-password">Mot de passe</label>
                <input
                  id="onb-password"
                  className="auth-input"
                  type="password"
                  required
                  minLength={6}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  autoComplete="new-password"
                />
              </div>
              <div className="onb-field">
                <label className="auth-label" htmlFor="onb-password2">Confirme</label>
                <input
                  id="onb-password2"
                  ref={password2Ref}
                  className="auth-input"
                  type="password"
                  required
                  minLength={6}
                  value={password2}
                  onChange={(e) => setPassword2(e.target.value)}
                  placeholder="Retape ton mot de passe"
                  autoComplete="new-password"
                />
              </div>
            </div>
          ) : (
            <>
              <label className="auth-label" htmlFor="onb-password">Mot de passe</label>
              <input
                id="onb-password"
                className="auth-input"
                type="password"
                required
                minLength={6}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                autoComplete="current-password"
              />
            </>
          )}

          {mode === "signup" && password2.length > 0 && password !== password2 && (
            <span className="onb-account-mismatch">
              Les deux mots de passe ne sont pas identiques.
            </span>
          )}

          {error && <div className="error" style={{ marginTop: 10 }}>{error}</div>}
          {info && <div className="auth-info" style={{ marginTop: 10 }}>{info}</div>}

          <button
            className={mode === "signup" ? "onb-pitch-cta" : "auth-submit"}
            type="submit"
            disabled={loading}
            style={
              mode === "signup"
                ? { marginTop: 14 }
                : { height: 46, fontSize: 15, display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }
            }
          >
            {loading ? (
              <Loader2 className="spin" size={16} />
            ) : mode === "signup" ? (
              <>Démarrer mes {trialDays} jours gratuits</>
            ) : (
              <>
                Se connecter <ArrowRight size={15} />
              </>
            )}
          </button>

          {/* L'étape suivante est la page de paiement Stripe : le dire ICI, avant
              le clic — arriver sur une demande de carte sans avoir été prévenu,
              juste après avoir tapé un mot de passe, c'est le réflexe « arnaque »
              assuré. */}
          <p className="onb-account-stripe">
            Ensuite : paiement sécurisé Stripe — ta carte est enregistrée mais{" "}
            <strong>0&nbsp;€ prélevé pendant tes {trialDays} jours d&apos;essai</strong>,
            résiliable en un clic depuis ton espace.
          </p>

          <button
            type="button"
            className="auth-switch"
            onClick={() => { setMode(mode === "signup" ? "signin" : "signup"); setPassword2(""); setError(""); setInfo(""); }}
          >
            {mode === "signup" ? "Déjà un compte ? Se connecter" : "Pas de compte ? En créer un"}
          </button>
        </form>
      </div>
    </main>
  );
}

/**
 * Landing /onboarding (alias /founders) — page d'opt-in façon Catalog/zoomgtm :
 * fond clair, H1 900, kicker uppercase, CTA sombre, illustration au trait.
 * Premier écran : tous les builders (SaaS et freelance). Ensuite : le même
 * champ de lien (site ou LinkedIn).
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

          <p className="fl-eyebrow">Pour les builders — SaaS et freelance</p>

          <h1 className="fl-h1">
            Le LinkedIn qui remplit ton pipeline — pendant que tu construis
          </h1>

          <p className="fl-sub">
            On écrit tes posts, on prospecte ton ICP. Toi, tu valides — moins d&apos;une minute par jour.
          </p>

          <div className="fl-gate">
            <label className="fl-gate-label" htmlFor="founders-gate-email">
              Ton e-mail pour vérifier s&apos;il reste une place&nbsp;<span aria-hidden="true">*</span>
            </label>
            <p className="fl-gate-hint">
              On onboard ~{FOUNDERS_MONTHLY_SEATS} builders par mois. On te confirme s&apos;il reste un créneau.
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
                placeholder="toi@email.com"
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
            <span>places builders</span>
          </div>
        </div>

        <section className="fl-section">
          <h2 className="fl-section-title">Le vrai goulot, ce n&apos;est pas ton offre</h2>
          <div className="fl-card">
            <p className="fl-card-p">
              90&nbsp;% sur le craft le matin, 10&nbsp;% marketeur l&apos;après-midi. Chaque
              casquette coûte 20 à 30 minutes de refocus — et à la fin de la journée,
              seule la mission a avancé. Ton LinkedIn reste muet.
            </p>
            <p className="fl-card-p">
              Ce n&apos;est pas un problème de discipline : un builder seul ne peut
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
