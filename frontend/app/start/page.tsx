"use client";

/**
 * Parcours d'entrée (/start) — l'ordre est le sujet de cette page.
 *
 *   onboarding (sans compte) → compte → paiement → app
 *
 * On montre le travail AVANT de demander l'e-mail et la carte. D'où deux
 * contraintes qui expliquent tout le code ci-dessous :
 *
 *  1. Les réponses sont recueillies avant qu'un compte existe → elles vivent dans
 *     sessionStorage le temps du parcours. S'il ferme l'onglet avant l'inscription,
 *     c'est perdu — assumé.
 *  2. ⚠️ Le profil DOIT être enregistré avant de partir sur Stripe. Une fois
 *     redirigé, cette page est détruite : ce qui n'est pas parti en base est perdu,
 *     et le client reviendrait payé mais avec un onboarding à refaire — exactement
 *     ce que ce parcours existe pour éviter.
 *
 * ⚠️ Si l'inscription échoue APRÈS que le compte a été créé (paiement injoignable),
 * on ne renvoie pas au début : le compte existe, le profil est enregistré, il ne
 * manque que le paiement. On propose donc de reprendre, pas de recommencer.
 */

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowRight, CheckCircle2, Loader2, Lock, Target } from "lucide-react";
import { supabase, authHeaders } from "../lib/supabase";
import OnboardingScreen, { type OnboardingProfile } from "../components/Onboarding";

const DIRECT_API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "https://analyseur-linkedin-influenceur-api-eu.onrender.com";

/** Les réponses de l'onboarding, le temps d'arriver jusqu'à la création du compte. */
const PENDING_PROFILE_KEY = "cibl_pending_profile";

type Phase = "onboarding" | "account";

export default function StartPage() {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("onboarding");
  const [profile, setProfile] = useState<OnboardingProfile | null>(null);
  const [mode, setMode] = useState<"signup" | "signin">("signup");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(false);
  const [price, setPrice] = useState("49 €");
  const [credits, setCredits] = useState(1000);

  // Déjà connecté ? Ce parcours ne le concerne pas : l'app gère son onboarding.
  useEffect(() => {
    (async () => {
      const { data } = await supabase.auth.getSession();
      if (data.session) router.replace("/");
    })();
  }, [router]);

  // Reprise après un rechargement en cours de parcours.
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(PENDING_PROFILE_KEY);
      if (raw) {
        setProfile(JSON.parse(raw));
        setPhase("account");
      }
    } catch { /* parcours reparti de zéro — sans gravité */ }
  }, []);

  // Prix lu depuis Stripe (source de vérité) — repli sur 49 € si injoignable.
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${DIRECT_API_URL}/billing/plan`);
        if (!res.ok) return;
        const plan = (await res.json())?.plan;
        if (!plan) return;
        if (typeof plan.credits === "number") setCredits(plan.credits);
        if (typeof plan.amount === "number") {
          setPrice(
            new Intl.NumberFormat("fr-FR", {
              style: "currency",
              currency: (plan.currency || "eur").toUpperCase(),
              maximumFractionDigits: plan.amount % 1 === 0 ? 0 : 2,
            }).format(plan.amount)
          );
        }
      } catch { /* repli silencieux */ }
    })();
  }, []);

  /** Fin de l'onboarding : on garde les réponses sous la main et on demande le compte. */
  const onboardingDone = useCallback((p: OnboardingProfile) => {
    setProfile(p);
    try { sessionStorage.setItem(PENDING_PROFILE_KEY, JSON.stringify(p)); } catch { /* ignore */ }
    setPhase("account");
  }, []);

  /** Il refuse de répondre : on demande quand même le compte, profil vide. */
  const onboardingSkipped = useCallback(() => {
    setProfile(null);
    try { sessionStorage.removeItem(PENDING_PROFILE_KEY); } catch { /* ignore */ }
    setPhase("account");
  }, []);

  /**
   * Enregistre le profil recueilli avant l'inscription, sur le compte fraîchement créé.
   * ⚠️ Doit réussir AVANT la redirection Stripe : après, cette page n'existe plus.
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
      // Best effort : mieux vaut un client qui paie et refait son profil qu'un
      // client bloqué au paiement parce que l'enregistrement a hoqueté.
    }
  }

  /** Compte prêt (session active) → session Checkout → redirection Stripe. */
  async function goCheckout() {
    const res = await fetch(`${DIRECT_API_URL}/me/billing/checkout`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(await authHeaders()) },
      body: JSON.stringify({
        success_url: `${window.location.origin}/?billing=success`,
        // Paiement abandonné → il entre quand même dans l'app avec ses crédits
        // offerts, profil déjà enregistré. Rien de ce qu'il a fait n'est perdu.
        cancel_url: `${window.location.origin}/?billing=cancelled`,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Paiement indisponible — réessaie dans un instant.");
    window.location.href = data.url;
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
        await persistProfile();
        await goCheckout();
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
        await persistProfile();
        await goCheckout();
        return;
      }

      // Confirmation d'e-mail activée : pas de session, donc ni enregistrement du
      // profil ni paiement possibles maintenant. Les réponses restent en réserve.
      setInfo(
        "Compte créé ! Confirme ton e-mail, puis reviens ici : on enregistre ton profil et on enchaîne sur le paiement."
      );
      setMode("signin");
      setLoading(false);
    } catch (err: any) {
      const msg = err?.message || "Une erreur est survenue.";
      // L'e-mail existe déjà : inutile de lui refaire remplir l'onboarding, ses
      // réponses sont en réserve et seront posées sur son compte à la connexion.
      if (/already registered|already been registered|user already exists/i.test(msg)) {
        setMode("signin");
        setError("Tu as déjà un compte avec cet e-mail. Connecte-toi : on garde tes réponses.");
      } else {
        setError(msg);
      }
      setLoading(false);
    }
  }

  if (phase === "onboarding") {
    return (
      <OnboardingScreen
        anonymous
        onFinish={onboardingDone}
        onSkip={onboardingSkipped}
        finishLabel="Voir mon offre"
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
              alignSelf: "flex-start",
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "4px 10px",
              borderRadius: 20,
              fontSize: 12,
              fontWeight: 600,
              color: "var(--primary)",
              background: "rgba(70,72,212,0.08)",
              border: "1px solid rgba(70,72,212,0.18)",
              marginBottom: 8,
            }}
          >
            <Target size={12} /> Abonnement Cibl · {price}/mois
          </span>

          <h2 className="auth-title" style={{ fontSize: 22 }}>
            {mode === "signup" ? "Ton profil est prêt" : "Connecte-toi pour continuer"}
          </h2>
          <p className="auth-sub">
            {mode === "signup"
              ? profile
                ? "On a tout ce qu'il faut. Crée ton compte pour le garder et lancer ton abonnement."
                : "Crée ton compte pour lancer ton abonnement."
              : "On enregistre ton profil et on enchaîne sur le paiement."}
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
                gap: 7,
              }}
            >
              {[
                profile.display_name && `Profil : ${profile.display_name}`,
                profile.target_audience && `Cible : ${profile.target_audience}`,
                profile.core_offer && `Offre : ${profile.core_offer}`,
              ]
                .filter(Boolean)
                .map((line) => (
                  <div key={line as string} style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13, lineHeight: 1.45 }}>
                    <CheckCircle2 size={14} style={{ color: "var(--primary)", flexShrink: 0, marginTop: 2 }} />
                    <span style={{ color: "var(--muted)" }}>{line}</span>
                  </div>
                ))}
            </div>
          )}

          <label className="auth-label">Email</label>
          <input
            className="auth-input"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="toi@exemple.com"
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

          {/* display:flex — sinon la flèche du libellé retombe à la ligne. */}
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
                {mode === "signup" ? "Créer mon compte et payer" : "Se connecter et payer"} <ArrowRight size={15} />
              </>
            )}
          </button>

          <p style={{ margin: "8px 0 0", fontSize: 12.5, color: "var(--muted)", textAlign: "center" }}>
            {price}/mois · {credits.toLocaleString("fr-FR")} crédits par mois · sans engagement
          </p>

          <button
            type="button"
            className="auth-switch"
            onClick={() => { setMode(mode === "signup" ? "signin" : "signup"); setError(""); setInfo(""); }}
          >
            {mode === "signup" ? "Déjà un compte ? Se connecter" : "Pas de compte ? En créer un"}
          </button>
        </form>

        <p style={{ margin: 0, fontSize: 12.5, color: "var(--muted)", display: "flex", alignItems: "center", gap: 6 }}>
          <Lock size={13} /> Paiement sécurisé par Stripe — ta carte est gérée par Stripe, jamais par nous.
        </p>
        <Link href="/offre" style={{ fontSize: 12.5, color: "var(--muted)" }}>
          ← Retour à la présentation
        </Link>
      </div>
    </main>
  );
}
