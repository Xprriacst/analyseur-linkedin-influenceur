"use client";

/**
 * Page d'abonnement (/offre) — un seul écran, format « closing call ».
 *
 * Gauche : la promesse + un extrait de tendances réelles (crédibilité).
 * Droite : création de compte + départ immédiat vers le paiement Stripe.
 *
 * ⚠️ Le paiement passe OBLIGATOIREMENT par un compte : les crédits sont attribués
 * par le webhook Stripe, qui doit savoir à quel compte rattacher la facture. Un
 * lien de paiement brut = un client qui paie sans jamais recevoir ses crédits.
 * D'où le formulaire intégré : compte créé → redirection Stripe dans la foulée.
 */

import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, Lock, Target, TrendingDown, TrendingUp } from "lucide-react";
import { supabase, authHeaders } from "../lib/supabase";

const DIRECT_API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "https://analyseur-linkedin-influenceur-api-eu.onrender.com";

// Même clé que dans Home : si la confirmation d'e-mail est activée, l'intention
// survit et Home reprend le paiement à la première connexion.
const SUBSCRIBE_INTENT_KEY = "cibl_subscribe_intent";

const PROMISES: string[] = [
  "L'analyse chiffrée de ce qui marche vraiment chez tes concurrents LinkedIn",
  "Des posts générés dans ta voix, à partir de ce qui performe sur ton marché",
  "Une idée de post chaque matin, publication et programmation incluses",
  "Les prospects qui commentent les posts de tes concurrents, contactés depuis l'app",
];

// Chiffres issus des tendances réellement mesurées par l'outil (corpus ~400 posts) —
// pas des chiffres marketing inventés.
const PROOF_STATS: { up: boolean; text: string }[] = [
  { up: true, text: "Appels à commenter : engagement ×2,5" },
  { up: true, text: "Posts texte : +22 % — reposts : −84 %" },
  { up: false, text: "Publier tous les jours : taux divisé par 4" },
];

export default function OffrePage() {
  const [price, setPrice] = useState("49 €");
  const [credits, setCredits] = useState(1000);
  const [mode, setMode] = useState<"signup" | "signin">("signup");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(false);

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
          setPrice(new Intl.NumberFormat("fr-FR", {
            style: "currency",
            currency: (plan.currency || "eur").toUpperCase(),
            maximumFractionDigits: plan.amount % 1 === 0 ? 0 : 2,
          }).format(plan.amount));
        }
      } catch { /* repli silencieux */ }
    })();
  }, []);

  /** Compte prêt (session active) → session Checkout → redirection Stripe. */
  async function goCheckout() {
    const res = await fetch(`${DIRECT_API_URL}/me/billing/checkout`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(await authHeaders()) },
      body: JSON.stringify({
        success_url: `${window.location.origin}/?billing=success`,
        cancel_url: `${window.location.origin}/offre`,
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
        await goCheckout();
        return; // redirection en cours — on garde le spinner
      }
      const { data, error } = await supabase.auth.signUp({
        email,
        password,
        options: { data: { onboarding_pending: true } },
      });
      if (error) throw error;
      if (data.session) {
        await goCheckout();
        return;
      }
      // Confirmation d'e-mail activée : pas de session tout de suite. On mémorise
      // l'intention — Home enchaînera sur le paiement à la première connexion.
      try { localStorage.setItem(SUBSCRIBE_INTENT_KEY, String(Date.now())); } catch { /* ignore */ }
      setInfo("Compte créé ! Confirme ton e-mail : à ta première connexion, tu seras redirigé vers le paiement.");
      setMode("signin");
      setLoading(false);
    } catch (err: any) {
      setError(err.message || "Une erreur est survenue.");
      setLoading(false);
    }
  }

  return (
    <main className="offre-split" style={{ minHeight: "100vh", display: "grid", gridTemplateColumns: "minmax(0, 1.1fr) minmax(0, 1fr)" }}>
      {/* ── Gauche : la promesse ── */}
      <section
        style={{
          position: "relative",
          overflow: "hidden",
          background: "linear-gradient(158deg, #2b2d7e 0%, #4648d4 58%, #5d60ea 100%)",
          color: "#fff",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "64px clamp(28px, 6vw, 84px)",
        }}
      >
        {/* Halos décoratifs */}
        <div aria-hidden style={{ position: "absolute", top: -140, right: -120, width: 420, height: 420, borderRadius: "50%", background: "radial-gradient(circle, rgba(255,255,255,0.14) 0%, rgba(255,255,255,0) 65%)" }} />
        <div aria-hidden style={{ position: "absolute", bottom: -180, left: -140, width: 480, height: 480, borderRadius: "50%", background: "radial-gradient(circle, rgba(0,0,0,0.22) 0%, rgba(0,0,0,0) 65%)" }} />

        <div style={{ position: "relative" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ display: "grid", placeItems: "center", width: 34, height: 34, borderRadius: 10, background: "rgba(255,255,255,0.16)", border: "1px solid rgba(255,255,255,0.25)" }}>
              <Target size={18} />
            </span>
            <span style={{ fontSize: 16, fontWeight: 800, letterSpacing: "0.06em" }}>Cibl</span>
          </div>

          <h1 style={{ margin: "26px 0 0", fontSize: "clamp(30px, 3.4vw, 44px)", lineHeight: 1.12, letterSpacing: "-0.025em", maxWidth: 560 }}>
            Arrête de deviner<br />
            <span style={{ background: "linear-gradient(transparent 68%, rgba(255,255,255,0.32) 68%)" }}>ce qui marche</span> sur LinkedIn.
          </h1>

          <ul style={{ listStyle: "none", padding: 0, margin: "34px 0 0", display: "grid", gap: 15, maxWidth: 580 }}>
            {PROMISES.map((promise) => (
              <li key={promise} style={{ display: "flex", gap: 12, alignItems: "flex-start", fontSize: 15, lineHeight: 1.55 }}>
                <span style={{ display: "grid", placeItems: "center", width: 24, height: 24, borderRadius: "50%", background: "rgba(255,255,255,0.14)", flexShrink: 0, marginTop: 1 }}>
                  <CheckCircle2 size={14} />
                </span>
                <span style={{ opacity: 0.96 }}>{promise}</span>
              </li>
            ))}
          </ul>

          {/* Preuve : tendances réellement mesurées par l'outil */}
          <div
            style={{
              margin: "34px 0 0",
              maxWidth: 460,
              padding: "16px 18px",
              borderRadius: 14,
              background: "rgba(255,255,255,0.09)",
              border: "1px solid rgba(255,255,255,0.18)",
              backdropFilter: "blur(4px)",
            }}
          >
            <p style={{ margin: "0 0 10px", fontSize: 11.5, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", opacity: 0.75 }}>
              Mesuré sur de vraies analyses — pas du feeling
            </p>
            <div style={{ display: "grid", gap: 8 }}>
              {PROOF_STATS.map((stat) => (
                <div key={stat.text} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13.5 }}>
                  {stat.up
                    ? <TrendingUp size={15} style={{ color: "#7ef0c0", flexShrink: 0 }} />
                    : <TrendingDown size={15} style={{ color: "#ffb4a8", flexShrink: 0 }} />}
                  <span style={{ opacity: 0.95 }}>{stat.text}</span>
                </div>
              ))}
            </div>
          </div>

          <div style={{ marginTop: 36, paddingTop: 24, borderTop: "1px solid rgba(255,255,255,0.18)", maxWidth: 460 }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
              <span style={{ fontSize: 40, fontWeight: 800, letterSpacing: "-0.02em" }}>{price}</span>
              <span style={{ fontSize: 15, opacity: 0.85 }}>/ mois</span>
            </div>
            <p style={{ margin: "6px 0 0", fontSize: 14, opacity: 0.85 }}>
              {credits.toLocaleString("fr-FR")} crédits rechargés chaque mois · sans engagement · résiliable en un clic
            </p>
          </div>
        </div>
      </section>

      {/* ── Droite : compte + paiement ── */}
      <section
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 18,
          padding: "48px clamp(20px, 5vw, 64px)",
          background:
            "radial-gradient(circle at 85% 12%, rgba(70,72,212,0.06) 0%, rgba(70,72,212,0) 42%), var(--surface-low)",
        }}
      >
        {/* .auth-card fournit la carte + l'empilement vertical des champs */}
        <form onSubmit={submit} className="auth-card" style={{ maxWidth: 400, padding: 32, gap: 6 }}>
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
            {mode === "signup" ? "Crée ton compte et abonne-toi" : "Connecte-toi pour t'abonner"}
          </h2>
          <p className="auth-sub">
            {mode === "signup"
              ? "30 secondes : ton compte, puis le paiement sécurisé Stripe."
              : "Tu seras redirigé vers le paiement sécurisé Stripe."}
          </p>

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

          <button className="auth-submit" type="submit" disabled={loading} style={{ height: 46, fontSize: 15 }}>
            {loading ? <Loader2 className="spin" size={16} /> : mode === "signup" ? "Créer mon compte et payer" : "Se connecter et payer"}
          </button>

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
      </section>

      {/* Mobile : les deux colonnes s'empilent */}
      <style>{`
        @media (max-width: 860px) {
          .offre-split { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </main>
  );
}
